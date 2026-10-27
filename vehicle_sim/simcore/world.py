#!/usr/bin/env python3
"""주행 환경 시뮬레이터: 0.1초마다 차량 주행과 통신 상태를 계산해 RUN_DIR/world.json에 쓴다.

하루 시계
  world.day_minutes(실제 분) = 하루 24시간. start_hour에서 시작. 시간대: 야간·출근·주간·퇴근·저녁.
  통근 차량  집에서 밤을 보내고 출근(07:00–08:30 출발) → 직장 주차(시동 꺼짐) → 퇴근(17:00–18:30 출발) → 귀가
  택시       주간조(06–24시)·야간조(18–10시). 근무가 끝나면 차고지에 주차, 가끔 차고지 휴식
  주민       08–21시에 집과 동네를 오가며 짧게 주차, 밤에는 집
  통과 차량  시간대별 유입량(출퇴근 많음, 밤 적음)으로 진입 게이트에 나타남
  보행자     시간대별 빈도 (학교 앞은 등하교 시간에 많음)
주행 (강체: 차량끼리 겹치지 않는다)
  - 차량은 길이 4.6 m·폭 1.9 m 직사각형. 진행 방향 오른쪽 차로 중심선(모서리는 곡선으로 깎은 경로)을 따라간다.
  - 앞 경로를 1 m 간격으로 훑어 다른 차량(방향 무관: 앞차·교차로를 지나는 차)이 있으면 그 앞에서 멈출 속도로 줄인다.
  - 매 틱 이동 후 차량 직사각형끼리 분리축 검사(SAT). 겹치게 되는 이동은 하지 않는다 (서로 막히면 번호가 큰 차가 양보).
  - 신호(동서·남북 두 현시), 횡단보도 보행자, 곡선 구간·제한 속도에 따라 자연스럽게 가감속.
  - 정차는 도로 밖 주차장 칸으로 들어간다. 나올 때는 차로가 비어 있을 때만 합류.
  - 긴급제동: 보행자 돌발·신호 급정거·교차로 충돌 회피·끼어들기 → ADAS 연산 점유
    = adas_base_s + adas_per_10kmh_s × (속도/10) → 학습 지연(4-5) 또는 FL 종료(1-4).
통신
  cell(서빙 기지국), quality, region, zone 플래그(터널·음영·보호구역·Wi-Fi·강우·혼잡), link_up, server_ok, wifi
수동 운전 → manual.py · 횡단보도 보행자·걷는 사람 → walkers.py · 차로 경로·겹침 검사 → lanes.py
저장
  world.json(현재), world_state.json(2초마다, 불러오기용), world_hist.jsonl(1초마다, 다시 보기용)
사용법: python world.py RUN_DIR      (환경 변수 SIM_RESUME_DIR이 있으면 그 상태에서 이어서 시작)
"""

import json
import math
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DEFAULT_CONFIG, emit, fmt_hour, merged_vehicle, period_of, read_json, write_json  # noqa: E402
from lanes import ACC, DEC, DEC_COMF, DEC_EMERG, DT, GAP_MIN, LanePath, in_rect, obb_overlap  # noqa: E402
from manual import ManualDriveMixin  # noqa: E402
from mapgeo import CAR_L, CAR_W, SIDEWALK, load_map, map_layout, seg_dist  # noqa: E402
from walkers import PedestriansMixin  # noqa: E402


class Vehicle:
    """FL 차량(vid 1..K) 또는 배경 차량(npc, vid 1000+: 학습에는 참여하지 않고 길만 채운다)"""

    def __init__(self, vid, route_id, route, path, npc=False):
        self.vid, self.route_id, self.route, self.path, self.npc = vid, route_id, route, path, npc
        self.kind = route.get("kind", route_id)
        self.accel = float(route.get("accel", ACC))       # 경로별 성능 (레이싱 차는 크게)
        self.brake = float(route.get("brake", DEC_COMF))
        self.mode = "drive"                       # drive · park(주차장 칸) · out(맵 밖)
        self.s = self.odo = self.v = 0.0
        self.x = self.z = 0.0
        self.hx, self.hz = 1.0, 0.0
        self.park = None                          # {place, slot, until, sk, s, odo, why, kind}
        self.plan = None                          # 다가가는 정차 계획
        self.decided = []
        self.gilbert_good, self.cell, self.region, self.in_tunnel = True, None, None, False
        self.emerg_left, self.emerg_id, self.emerg_cause, self.braking = 0.0, 0, "", False
        self.block_t, self.block_by = 0.0, None
        self.cw_at = None
        self.sched = {}
        self.manual, self.aeb, self.hard_brk, self.offroad, self.in_box, self.park_key = False, False, False, False, set(), False
        self.inp, self.driver = {}, ""

    @property
    def present(self):
        return self.mode != "out"

    def put(self, s):
        self.s = self.path.norm(s)
        self.x, self.z, self.hx, self.hz = self.path.at(self.s)

    def box(self):
        return self.x, self.z, self.hx, self.hz

    def state(self):
        return {"mode": self.mode, "s": self.s, "odo": self.odo, "v": self.v, "park": self.park, "sched": self.sched,
                "x": self.x, "z": self.z, "hx": self.hx, "hz": self.hz, "gilbert_good": self.gilbert_good,
                "cell": self.cell, "region": self.region, "in_tunnel": self.in_tunnel, "emerg_id": self.emerg_id}


class World(PedestriansMixin, ManualDriveMixin):
    def __init__(self, run_dir):
        self.run_dir = Path(run_dir)
        self.cfg = read_json(self.run_dir / "config.json", DEFAULT_CONFIG)
        self.rng = random.Random(int(self.cfg["fl"].get("seed", 42)))
        self.map = load_map(self.cfg["world"].get("map", "default"))
        self.layout = map_layout(self.map)
        self.lane_w = float(self.map.get("lane_width", 3.5))
        self.lots = {pid: [None] * len(l["slots"]) for pid, l in self.layout["lots"].items()}
        self.clock = 0.0                          # 시뮬레이션 경과 시간 (실제 초)
        self.cfg_mtime = 0
        self.box_occ = {s["id"]: {} for s in self.map.get("signals", [])}   # 교차로 안(예약 포함) 차량: {vid: 진입 방향}
        self.solid = [tuple(b[:4]) for b in self.layout["buildings"]] + [
            (b["x"] - b["w"] / 2, b["z"] - b["d"] / 2, b["x"] + b["w"] / 2, b["z"] + b["d"] / 2)
            for b in self.layout["place_buildings"] if b["kind"] != "canopy"]
        self.init_manual()
        self.init_pedestrians()
        self.paths = {rid: LanePath(r, self.lane_w / 2, self) for rid, r in self.map["routes"].items()}
        vr = self.map["vehicle_routes"]
        self.n_city = 0
        self.fl = [self.make_vehicle(i, vr[(i - 1) % len(vr)]) for i in range(1, int(self.cfg["fl"]["K"]) + 1)]
        nr = self.map.get("npc_routes") or list(self.map["routes"])
        self.npcs = [self.make_vehicle(1000 + i, nr[i % len(nr)], npc=True)
                     for i in range(int(self.cfg["world"].get("npc_cars", 16)))]
        self.vehicles = self.fl + self.npcs
        resume = os.environ.get("SIM_RESUME_DIR")
        if resume and (Path(resume) / "world_state.json").exists():
            st = read_json(Path(resume) / "world_state.json", {})
            self.clock = st.get("clock", 0.0)
            for v in self.fl:
                d = st.get("vehicles", {}).get(str(v.vid))
                if d:
                    for k in ("mode", "s", "odo", "v", "park", "sched", "x", "z", "hx", "hz", "gilbert_good",
                              "cell", "region", "in_tunnel", "emerg_id"):
                        if k in d:
                            setattr(v, k, d[k])
                    if v.park and v.park["place"] in self.lots:
                        self.lots[v.park["place"]][v.park["slot"]] = v.vid
            emit(self.run_dir, "world", msg=f"저장된 주행 상태에서 이어서 시작 ({resume})")
        else:
            self.initial_placement()
        self.hist = open(self.run_dir / "world_hist.jsonl", "a")

    def make_vehicle(self, vid, rid, npc=False):
        """차량 하나 + 하루 일정 (경로 종류: 통근·택시(상시 운행 경로 포함)·주민·통과)"""
        v = Vehicle(vid, rid, self.map["routes"][rid], self.paths[rid], npc)
        r = self.rng
        if npc:
            return v
        if v.kind == "commute":
            v.sched = {"am": 7.0 + r.uniform(0, 1.5), "pm": 17.0 + r.uniform(0, 1.5)}
        elif v.kind == "city" and v.route.get("always"):
            v.sched = {"on": 0.0, "off": 24.0, "shift": "상시"}
        elif v.kind == "city":
            self.n_city += 1
            v.sched = {"on": 5.5 + r.uniform(0, 1), "off": (23.5 + r.uniform(0, 1)) % 24, "shift": "주간"} \
                if self.n_city % 2 == 1 else {"on": 17.5 + r.uniform(0, 1), "off": 9 + r.uniform(0, 1), "shift": "야간"}
        elif v.kind == "resident":
            v.sched = {"wake": 8 + r.uniform(0, 1), "sleep": 20.5 + r.uniform(0, 1)}
        return v

    # ---------------------------------------------------------------- 하루 시계
    def sec_per_hour(self):
        return max(1.0, float(self.cfg["world"].get("day_minutes", 30))) * 60 / 24

    def hours(self):
        return float(self.cfg["world"].get("start_hour", 6.8)) + self.clock / self.sec_per_hour()

    def tod(self):
        return self.hours() % 24

    def until(self, h):
        """다음 h시까지 실제 초"""
        return ((h - self.tod()) % 24) * self.sec_per_hour()

    @staticmethod
    def between(t, a, b):
        return a <= t < b if a <= b else (t >= a or t < b)

    def on_duty(self, v, t=None):
        t = self.tod() if t is None else t
        return self.between(t, v.sched["on"], v.sched["off"])

    def sched_text(self, v):
        s = v.sched
        if v.npc:
            return "배경 차량 (학습 참여 안 함)"
        if v.kind == "commute":
            return f"출근 {fmt_hour(s['am'])} · 퇴근 {fmt_hour(s['pm'])}"
        if v.kind == "city" and s["shift"] == "상시":
            return f"{v.route.get('label', '택시')} 상시 운행"
        if v.kind == "city":
            return f"택시 {s['shift']}조 {fmt_hour(s['on'])}–{fmt_hour(s['off'])}"
        if v.kind == "resident":
            return f"주민 활동 {fmt_hour(s['wake'])}–{fmt_hour(s['sleep'])}"
        return "통과 차량 (시간대별 유입)"

    def hour_mult(self, kind):
        t = self.tod()
        p, _ = period_of(t)
        if kind == "visitor":
            return {"night": 0.15, "am": 2.2, "day": 1.0, "pm": 2.2, "evening": 0.7}[p]
        if kind == "school":
            if 7.5 <= t < 9:
                return 3.0
            if 12.5 <= t < 16:
                return 2.2
            return 0.05 if p == "night" else 0.6
        return {"night": 0.1, "am": 1.6, "day": 1.0, "pm": 1.6, "evening": 0.9}[p]

    # ---------------------------------------------------------------- 지도 질의
    def road_axis(self, p):
        """그 지점 도로가 가로(x)인지 세로(z)인지 → 보행자는 반대 방향으로 건넌다"""
        best, axis = 1e9, "x"
        for rd in self.map["roads"]:
            for a, b in zip(rd["pts"], rd["pts"][1:]):
                d = seg_dist(p, a, b)
                if d < best:
                    best, axis = d, ("x" if abs(b[0] - a[0]) > abs(b[1] - a[1]) else "z")
        return axis

    def zone_flags(self, p):
        f = {}
        for z in self.map["zones"]:
            hit = in_rect(p, z["rect"]) if "rect" in z else \
                math.hypot(p[0] - z["circle"][0], p[1] - z["circle"][1]) <= z["circle"][2]
            f[z["kind"]] = f.get(z["kind"], False) or hit
        return f

    def speed_at(self, p):
        for z in self.map["zones"]:
            if "speed" in z and "rect" in z and in_rect(p, z["rect"]):
                return z["speed"]
        best, spd = 1e9, 45
        for rd in self.map["roads"]:
            for a, b in zip(rd["pts"], rd["pts"][1:]):
                d = seg_dist(p, a, b)
                if d < best:
                    best, spd = d, rd["speed"]
        return spd

    def signal_state(self, sig, axis):
        """axis 'x'(동서) / 'z'(남북)의 신호: green / yellow / red"""
        sc = float(self.cfg["world"].get("signal_scale", 1.0))
        g, y = sig["green"] * sc, sig["yellow"] * sc
        t = (self.clock + sig.get("offset", 0) * sc) % (2 * (g + y))
        ew = "green" if t < g else ("yellow" if t < g + y else "red")
        if axis == "x":
            return ew
        t2 = t - (g + y)
        if t2 < 0:
            return "red"
        return "green" if t2 < g else "yellow"

    def place_for(self, kind, node):
        best, bd = None, 1e9
        for p in self.map["places"]:
            if p["kind"] == kind:
                d = math.hypot(p["pos"][0] - node[0], p["pos"][1] - node[1])
                if d < bd:
                    best, bd = p, d
        return best["id"] if best else None

    def place_name(self, pid):
        return next((p["name"] for p in self.map["places"] if p["id"] == pid), pid)

    # ---------------------------------------------------------------- 설정·사건
    def reload_cfg(self):
        p = self.run_dir / "config.json"
        try:
            m = p.stat().st_mtime
        except FileNotFoundError:
            return
        if m != self.cfg_mtime:
            self.cfg = read_json(p, self.cfg)
            self.cfg_mtime = m

    def ev(self, v, msg, **kw):
        if v is not None and v.npc:                       # 배경 차량은 사건 기록에 남기지 않는다
            return
        emit(self.run_dir, "world", vid=v.vid if v else None, msg=msg, **kw)

    def emergency(self, v, cause):
        vc = merged_vehicle(self.cfg, v.vid)
        kmh = v.v * 3.6
        occ = float(vc.get("adas_base_s", 2.0)) + float(vc.get("adas_per_10kmh_s", 1.0)) * kmh / 10
        v.emerg_left = max(v.emerg_left, occ)
        v.emerg_id += 1
        v.emerg_cause = cause
        v.braking = True
        self.ev(v, f"긴급제동({cause}) {kmh:.0f} km/h → ADAS 연산 점유 {occ:.1f}초", emergency=v.emerg_id,
                cause=cause, kmh=round(kmh), occupy_s=round(occ, 1))

    # ---------------------------------------------------------------- 주차장 (도로 밖 칸)
    def park_in(self, v, stop, dur_s, why, sk):
        s_stop, kind, node = stop
        pid = self.place_for(kind, node)
        slots = self.lots.get(pid)
        if not slots or None not in slots:
            return False
        k = slots.index(None)
        slots[k] = v.vid
        sl = self.layout["lots"][pid]["slots"][k]
        v.mode, v.v, v.plan = "park", 0.0, None
        self.release_boxes(v)
        v.park = {"place": pid, "slot": k, "until": self.clock + dur_s, "sk": sk, "s": s_stop, "odo": v.odo,
                  "why": why, "kind": kind}
        v.x, v.z, v.hx, v.hz = sl[0], sl[1], math.cos(sl[2]), math.sin(sl[2])
        return True

    def entry_clear(self, v, s, margin=6.0):
        """주차장·게이트에서 차로로 들어갈 자리가 비었는지 (뒤에서 다가오는 차 포함)"""
        x, z, hx, hz = v.path.at(s)
        for o in self.vehicles:
            if o is v or o.mode != "drive":
                continue
            dx, dz = o.x - x, o.z - z
            d = math.hypot(dx, dz)
            if d < CAR_L + margin:
                return False
            if d < 25 and o.hx * hx + o.hz * hz > 0.7 and dx * hx + dz * hz < 0 and abs(-dx * hz + dz * hx) < 2.5:
                return False
        return True

    def leave_park(self, v):
        p = v.park
        if not self.entry_clear(v, p["s"]):
            return False
        self.lots[p["place"]][p["slot"]] = None
        v.mode, v.v, v.odo = "drive", 0.0, p["odo"]
        v.put(p["s"])
        msg = {"home": "시동 켬, 출발", "gas": "충전 끝, 출발", "service": "정비 대기 끝, 출발",
               "ota": "OTA 설치·재부팅 완료, 출발"}.get(p["sk"], "출발")
        self.ev(v, f"{msg} ({self.place_name(p['place'])})", stop=p["sk"], phase="end")
        v.park = None
        return True

    def initial_placement(self):
        """시작 시각에 맞춰 주차할 차량은 주차장에, 나머지는 경로 위에 겹치지 않게"""
        t = self.tod()
        for v in self.vehicles:
            want = None
            if v.npc:
                v.mode = "drive"
                continue
            if v.kind == "commute":
                if self.between(t, v.sched["am"] + 0.5, v.sched["pm"]):
                    want = ("work", v.sched["pm"], "근무 중 주차")
                elif not (self.between(t, v.sched["am"], v.sched["am"] + 0.5) or
                          self.between(t, v.sched["pm"], v.sched["pm"] + 2)):
                    want = ("home", v.sched["am"], f"밤샘 주차 — 출근 {fmt_hour(v.sched['am'])}")
            elif v.kind == "city" and not self.on_duty(v, t):
                want = ("depot", v.sched["on"], f"근무 전 — {fmt_hour(v.sched['on'])}까지 차고지")
            elif v.kind == "resident" and not self.between(t, v.sched["wake"], v.sched["sleep"]):
                want = ("home", v.sched["wake"], f"밤샘 주차 — {fmt_hour(v.sched['wake'])}")
            elif v.kind == "visitor":
                v.mode = "out"
                continue
            if want:
                st = next((s for s in v.path.stops if s[1] == want[0]), None)
                if st:
                    v.odo = st[0]
                    if self.park_in(v, st, self.until(want[1]), want[2], "home"):
                        continue
            v.mode = "drive"
        drivers = [v for v in self.vehicles if v.mode == "drive"]
        for k, v in enumerate(drivers):
            same = [o for o in drivers if o.route_id == v.route_id]
            s = v.path.L * (same.index(v) + 0.3) / len(same)
            for _ in range(200):
                v.put(s)
                if all(not obb_overlap(v.box(), o.box()) and math.hypot(v.x - o.x, v.z - o.z) > 12 for o in drivers[:k]):
                    break
                s += 9.0
            v.odo = s

    # ---------------------------------------------------------------- 정차 계획 (하루 시계)
    def decide_stop(self, v, kind, node):
        """(실제 초, 이유, 정차 종류) 또는 None. 정차 종류: home(시동 꺼짐) · gas · ota · service"""
        t, w, r = self.tod(), self.cfg["world"], self.rng
        sph = self.sec_per_hour()
        if kind == "home":
            if v.kind == "commute" and not self.between(t, v.sched["am"], v.sched["pm"]):
                return self.until(v.sched["am"]), f"퇴근 후 귀가 — 다음 출근 {fmt_hour(v.sched['am'])}까지 주차", "home"
            if v.kind == "resident":
                if self.between(t, v.sched["wake"], v.sched["sleep"]):
                    m = r.uniform(*w.get("home_park_min", [20, 90]))
                    return m * sph / 60, f"집에 들러 {m:.0f}분 주차", "home"
                return self.until(v.sched["wake"]), f"귀가 — {fmt_hour(v.sched['wake'])}까지 주차", "home"
            return None
        if kind == "work":
            if v.kind == "commute" and self.between(t, v.sched["am"], v.sched["pm"]):
                return self.until(v.sched["pm"]), f"출근 — 퇴근 {fmt_hour(v.sched['pm'])}까지 주차", "home"
            return None
        if kind == "depot":
            if v.kind == "city":
                if not self.on_duty(v):
                    return (self.until(v.sched["on"]), f"{v.sched['shift']}조 근무 끝 — {fmt_hour(v.sched['on'])}까지 "
                                                       f"차고지 주차", "home")
                if r.random() < 0.15:
                    m = r.uniform(10, 25)
                    return m * sph / 60, f"차고지 휴식 {m:.0f}분", "home"
            return None
        if kind == "gas":
            c = read_json(self.run_dir / f"client_{v.vid}.json", {}) or {}
            if float(c.get("energy_frac", 1.0)) < 0.5 or r.random() < 0.3:
                return r.uniform(*w["charge_s"]), "충전소 정차 (시동 켠 채 충전, 새 데이터 없음)", "gas"
            return None
        if kind == "service":
            x = r.random()
            if x < float(w["ota_prob"]):
                return r.uniform(*w["ota_s"]), "서비스센터 OTA 설치 (재부팅)", "ota"
            if x < float(w["ota_prob"]) + (1 - float(w["ota_prob"])) * 0.5:
                return r.uniform(*w["service_wait_s"]), "서비스센터 정비 대기 (시동 켠 채 정차)", "service"
        return None

    # ---------------------------------------------------------------- 주행
    def release_boxes(self, v):
        for occ in self.box_occ.values():
            for k in [k for k in occ if k[0] == v.vid]:
                occ.pop(k)

    def exit_clear(self, v, s_x):
        """교차로 출구 너머 차 한 대 길이에 서 있는(느린) 차가 없는지 — 교차로 안에 갇히지 않게"""
        near = [o for o in self.vehicles if o is not v and o.mode == "drive" and o.v < 2.0
                and abs(o.x - v.x) + abs(o.z - v.z) < 80]
        d = 0.0
        while d <= CAR_L + GAP_MIN + 1:
            x, z, _, _ = v.path.at(s_x + d)
            for o in near:
                dx, dz = x - o.x, z - o.z
                if abs(dx * o.hx + dz * o.hz) <= CAR_L / 2 + 0.5 and abs(-dx * o.hz + dz * o.hx) <= CAR_W + 0.15:
                    return False
            d += 1.0
        return True

    def path_hit(self, v, look):
        """내 앞 경로(차로 중심선)를 훑어 처음 닿는 다른 차량까지 앞 범퍼 기준 거리"""
        near = [o for o in self.vehicles if o is not v and o.mode == "drive"
                and abs(o.x - v.x) + abs(o.z - v.z) < look + 12
                and not (o.block_by == v.vid and v.vid < o.vid and v.block_t > 3)]   # 서로 막힘: 번호 작은 차 우선
        if not near:
            return None, None
        d = CAR_L / 2
        while d <= look:
            x, z, _, _ = v.path.at(v.s + d)
            for o in near:
                dx, dz = x - o.x, z - o.z
                if abs(dx * o.hx + dz * o.hz) <= CAR_L / 2 + 0.2 and abs(-dx * o.hz + dz * o.hx) <= CAR_W + 0.15:
                    return d - CAR_L / 2, o
            d += 1.0 if d < 25 else 2.0
        return None, None

    def step_vehicle(self, v):
        wcfg = self.cfg["world"]
        vcfg = merged_vehicle(self.cfg, v.vid)
        if v.emerg_left > 0:
            v.emerg_left = max(0.0, v.emerg_left - DT)
        if vcfg.get("leave") and v.mode != "out":
            if v.park:
                self.lots[v.park["place"]][v.park["slot"]] = None
                v.park = None
            v.mode, v.plan = "out", None
            self.ev(v, "맵에서 이탈 (차량 설정)")
            return
        if v.mode == "out":
            if vcfg.get("leave"):
                return
            due = self.rng.random() < self.hour_mult("visitor") / max(1.0, float(wcfg["visitor_gap_mean_s"])) * DT \
                if v.kind == "visitor" else True
            if due and self.entry_clear(v, 0.0, 10):
                v.mode, v.v, v.odo, v.plan = "drive", 0.0, 0.0, None
                v.put(0.0)
                self.ev(v, "진입 게이트로 새로 합류" if v.kind == "visitor" else "맵으로 돌아옴")
            return
        if v.mode == "park":
            if self.clock >= v.park["until"]:
                if v.kind == "city" and v.park["kind"] == "depot" and not self.on_duty(v):
                    v.park["until"] = self.clock + self.until(v.sched["on"])
                else:
                    self.leave_park(v)
            return
        P = v.path
        scale = float(wcfg.get("speed_scale", 1.0))
        look = max(45.0, v.v * v.v / (2 * DEC) + 35)
        look_c = max(look, v.v * v.v / (2 * v.brake) + 20)   # 앞 곡선을 미리 보고 감속할 거리
        i = P.index(v.s)
        target = P.lim[i] * scale
        j, dist = i + 1, P.S[i + 1] - P.norm(v.s)            # 앞 구간 제한 속도·곡선: 편안한 감속으로 맞출 수 있는 속도
        while dist < look_c:
            if j >= len(P.lim):
                if not P.loop:
                    break
                j = 0
            target = min(target, math.sqrt((P.lim[j] * scale) ** 2 + 2 * v.brake * max(0.0, dist)))
            dist += P.S[j + 1] - P.S[j]
            j += 1
        stops = []                                           # (앞 범퍼에서 멈출 지점까지 거리, 이유)
        gap, other = self.path_hit(v, look)
        if gap is not None:
            stops.append((gap - GAP_MIN, "car"))
        pg = self.walker_hit(v, look)
        if pg is not None:
            stops.append((pg - 1.5, "보행자 차로"))
        for s_e, sig, axis, dk, s_x in P.signals:
            occ = self.box_occ[sig["id"]]
            key = (v.vid, round(s_e))
            a = P.ahead_signed(s_e, v.s) - CAR_L / 2 - 0.8
            if key in occ:                                   # 교차로에 들어간(예약한) 차: 뒤 범퍼가 출구를 지나면 해제
                past = ((v.s - s_x - CAR_L / 2 - 1) % P.L < P.L / 2) if P.loop else v.s > s_x + CAR_L / 2 + 1
                if past or a > 40:
                    occ.pop(key, None)
                continue
            if not -0.5 < a < 110:
                continue
            st = self.signal_state(sig, axis)
            if st == "red" or (st == "yellow" and a > v.v ** 2 / (2 * DEC)):
                stops.append((a, "신호 " + sig["id"]))
            elif a < max(3.0, v.v * 1.2):
                # 진입 직전: 다른 방향에서 들어온 차가 안에 있거나, 빠져나갈 자리가 막혀 있으면 정지선에서 대기
                clash = any(d != dk for (o, _), d in occ.items() if o != v.vid)
                if clash or not self.exit_clear(v, s_x):
                    stops.append((a, "교차로 대기 " + sig["id"]))
                else:
                    occ[key] = dk
        width = 2 * self.lane_w + 2 * SIDEWALK
        for s_c, cw, c in P.cross:                           # 내 차로를 아직 다 건너지 않은 보행자가 있으면 정지선에서 대기
            a = P.ahead(s_c, v.s) - CAR_L / 2 - 3.5
            if not -0.5 < a < 70:
                continue
            busy = False
            for t0, d, _ in self.peds[cw["id"]]:
                o = ((self.clock - t0) * 1.3 - width / 2) * d
                if (d > 0 and o < c + self.lane_w / 2 + 1) or (d < 0 and o > c - self.lane_w / 2 - 1):
                    busy = True
                    break
            if busy:
                stops.append((a, "보행자 " + cw["id"]))
        for s_stop, kind, node in ([] if v.npc else P.stops):   # 정차 계획: 정차 지점 80 m 앞에서 한 번 정한다
            a = P.ahead(s_stop, v.s)
            key = round(v.odo + a)
            if 0 < a < 80 and key not in v.decided:
                v.decided = (v.decided + [key])[-8:]
                d = self.decide_stop(v, kind, node)
                if d:
                    v.plan = {"odo": v.odo + a, "stop": (s_stop, kind, node), "dur": d[0], "why": d[1], "sk": d[2]}
        if v.plan:
            a = v.plan["odo"] - v.odo
            if a < -2:
                v.plan = None
            else:
                stops.append((a, "정차"))
        why_stop = ""
        for a, why in stops:
            vs = math.sqrt(2 * DEC * max(0.0, a))
            if vs < target:
                target, why_stop = vs, why
        need = max([v.v ** 2 / (2 * max(0.3, a)) for a, _ in stops if a < 60] or [0])
        if v.v > target:
            dec = DEC_EMERG if (v.braking or need > 6.5) else DEC
            if need > 6.5 and not v.braking and v.v * 3.6 > 15:
                if why_stop.startswith("신호"):
                    self.emergency(v, "신호 급정거")
                elif why_stop == "car" and v.v * 3.6 > 20:
                    self.emergency(v, "교차로·앞차 충돌 회피")
                elif why_stop == "보행자 차로":
                    self.emergency(v, "차로에 들어온 보행자")
            v.v = max(target, v.v - dec * DT)
        else:
            v.v = min(target, v.v + v.accel * DT)
            v.braking = False
        if v.v * 3.6 > 40 and self.rng.random() < 0.0008 * float(vcfg.get("emergency_rate", 1.0)):
            self.emergency(v, "끼어들기")
        # 이동 + 강체 검사: 다른 차와 겹치게 되는 이동은 하지 않는다
        ns = v.s + v.v * DT
        if not P.loop and ns >= P.L - 0.5:
            v.mode, v.plan = "out", None
            self.release_boxes(v)
            self.ev(v, "이탈 게이트로 맵을 떠남")
            return
        x, z, hx, hz = P.at(ns)
        blocker = next((o for o in self.vehicles if o is not v and o.mode == "drive"
                        and obb_overlap((x, z, hx, hz), o.box())), None)
        if blocker is None:
            v.odo += v.v * DT
            v.s, v.x, v.z, v.hx, v.hz = P.norm(ns), x, z, hx, hz
        else:
            v.v = 0.0
        stuck = blocker or (other if why_stop == "car" and v.v < 0.1 else None)
        if stuck is not None:
            v.block_by = stuck.vid
            v.block_t += DT
            if blocker and v.block_t > 6 and blocker.block_by == v.vid and v.vid > blocker.vid:
                back = P.at(v.s - 1.5)                       # 서로 막힘: 번호 큰 차가 1.5 m 물러남
                if all(not obb_overlap(back, o.box()) for o in self.vehicles if o is not v and o.mode == "drive"):
                    v.put(v.s - 1.5)
                    v.odo -= 1.5
                    v.block_t = 0.0
        else:
            v.block_t, v.block_by = 0.0, None
        if why_stop.startswith("보행자") and v.v < 0.5:
            self.cw_wait.setdefault(why_stop.split()[1], self.clock)
        elif v.cw_at:
            self.cw_wait.pop(v.cw_at, None)
        v.cw_at = why_stop.split()[1] if why_stop.startswith("보행자") and v.v < 0.5 else None
        if v.plan and abs(v.plan["odo"] - v.odo) < 1.0 and v.v < 0.6:
            pl = v.plan
            if self.park_in(v, pl["stop"], pl["dur"], pl["why"], pl["sk"]):
                self.ev(v, f"{pl['why']} ({self.place_name(v.park['place'])})", stop=pl["sk"], phase="start")
            else:
                self.ev(v, f"{self.place_name(self.place_for(pl['stop'][1], pl['stop'][2]))} 만차 — 지나감")
                v.plan = None

    # ---------------------------------------------------------------- 통신
    def serving_cell(self, v, tunnel):
        if tunnel:
            return None, 0.0
        best, q = None, 0.0
        for c in self.map["cells"]:
            d = math.hypot(v.x - c["pos"][0], v.z - c["pos"][1])
            if d <= c["r"] and 1 - d / c["r"] > q:
                best, q = c, 1 - d / c["r"]
        return best, q

    def link(self, v):
        ncfg = self.cfg["net"]
        z = self.zone_flags((v.x, v.z))
        if not self.cfg["world"].get("weather_on", True):
            z["weather"] = False
        tunnel = z.get("tunnel", False)
        cell, q = self.serving_cell(v, tunnel) if v.present else (None, 0.0)
        if tunnel != v.in_tunnel:
            self.ev(v, "터널 진입" if tunnel else "터널 통과", zone="tunnel")
            v.in_tunnel = tunnel
        if z.get("shadow"):
            p_stay = ncfg["gilbert_p"] if v.gilbert_good else ncfg["gilbert_q"]
            if self.rng.random() > p_stay ** DT:
                v.gilbert_good = not v.gilbert_good
        else:
            v.gilbert_good = True
        cid = cell["id"] if cell else None
        if cid != v.cell and v.present:
            if v.cell and cid:
                self.ev(v, f"핸드오버 {v.cell} → {cid}", handover=[v.cell, cid])
            elif v.cell and not cid and not tunnel:
                self.ev(v, f"기지국 {v.cell} 범위 이탈")
            v.cell = cid
        region = "W" if v.x < self.map.get("region_border_x", 1e9) else "E"
        if v.region and region != v.region and v.present:
            self.ev(v, f"권역 경계 통과 {v.region} → {region}", region_cross=[v.region, region])
        v.region = region
        sk = v.park["sk"] if v.park else None
        link_up = bool(v.present and cid and not tunnel and v.gilbert_good and sk not in ("home", "ota"))
        at_wifi = (v.park and any(p["id"] == v.park["place"] and p.get("wifi") for p in self.map["places"])) or any(
            p.get("wifi") and math.hypot(v.x - p["pos"][0], v.z - p["pos"][1]) < 60 for p in self.map["places"])
        return {
            "pos": [round(v.x, 2), round(v.z, 2)], "heading": round(math.atan2(v.hz, v.hx), 3),
            "speed_kmh": round(abs(v.v) * 3.6, 1), "manual": v.manual, "driver": v.driver if v.manual else "", "reverse": v.v < -0.05, "offroad": v.offroad, "route": v.route_id, "kind": v.kind, "present": v.present,
            "mode": v.mode, "parked": v.park["place"] if v.park else None, "park_why": v.park["why"] if v.park else "",
            "cell": cid, "quality": round(q, 3), "region": region, "zones": z, "gilbert_good": v.gilbert_good,
            "link_up": link_up, "server_ok": link_up, "wifi": bool(link_up and (z.get("wifi") or at_wifi)),
            "engine_off": sk == "home" or not v.present, "charging": sk == "gas", "ota": sk == "ota",
            "idle_parked": sk in ("gas", "service"), "home_charging": bool(v.park and v.park["kind"] == "home"),
            "stop_left": round(max(0.0, v.park["until"] - self.clock), 1) if v.park else 0.0, "available": True,
            "moving": abs(v.v) > 1, "emergency": round(v.emerg_left, 1), "emergency_id": v.emerg_id,
            "emergency_cause": v.emerg_cause, "braking": v.braking or (v.mode == "drive" and v.v < 0.5),
            "sched": self.sched_text(v),
        }

    # ---------------------------------------------------------------- 루프
    def run(self):
        last_state = last_hist = -1e9
        last_period = None
        while True:
            now = time.time()
            self.reload_cfg()
            self.clock += DT
            tod = self.tod()
            pkey, pname = period_of(tod)
            if pkey != last_period:
                if last_period is not None:
                    self.ev(None, f"{fmt_hour(tod)} — {pname} 시간대 시작", period=pkey)
                last_period = pkey
            self.step_peds()
            self.reload_drive()
            self.update_manual()
            peds = self.ped_positions()
            self.step_walkers()
            for v in self.vehicles:
                if v.manual:
                    self.step_manual(v, peds)
                else:
                    self.step_vehicle(v)
            self.collide_walkers()
            walkers = self.walker_states()
            state = {str(v.vid): self.link(v) for v in self.fl}
            npc = [[v.vid, round(v.x, 2), round(v.z, 2), round(math.atan2(v.hz, v.hx), 3), round(v.v * 3.6),
                    int(v.braking or v.v < 0.5), v.route_id] for v in self.npcs if v.present]
            sigs = {s["id"]: [self.signal_state(s, "x"), self.signal_state(s, "z")] for s in self.map.get("signals", [])}
            write_json(self.run_dir / "world.json", {"t": now, "elapsed": self.clock, "tod": round(tod, 4),
                                                     "day": int(self.hours() // 24) + 1, "period": pkey,
                                                     "period_name": pname, "sec_per_hour": self.sec_per_hour(),
                                                     "vehicles": state, "signals": sigs, "peds": peds,
                                                     "npc": npc, "walkers": walkers, "ped_hits": self.ped_hits})
            if self.clock - last_state >= 2:            # 불러오기용 전체 상태
                write_json(self.run_dir / "world_state.json",
                           {"clock": self.clock, "vehicles": {str(v.vid): v.state() for v in self.fl}})
                last_state = self.clock
            if self.clock - last_hist >= 1:             # 다시 보기용 기록 (1초 간격, 짧게)
                rec = {"t": round(now, 2), "c": round(self.clock, 1), "h": round(tod, 3),
                       "v": {k: [s["pos"][0], s["pos"][1], s["heading"], int(s["speed_kmh"]),
                                 int(s["present"]) | int(s["engine_off"]) << 1 | int(s["charging"]) << 2
                                 | int(s["ota"]) << 3 | int(s["emergency"] > 0) << 4 | int(s["link_up"]) << 5
                                 | int(s["braking"]) << 6]
                             for k, s in state.items()},
                       "s": {k: v[0][0] + v[1][0] for k, v in sigs.items()}, "p": peds, "w": [x[:7] for x in walkers],
                       "n": [x[:4] for x in npc]}
                self.hist.write(json.dumps(rec, separators=(",", ":")) + "\n")
                self.hist.flush()
                last_hist = self.clock
            time.sleep(max(0.0, DT - (time.time() - now)))


if __name__ == "__main__":
    World(sys.argv[1]).run()
