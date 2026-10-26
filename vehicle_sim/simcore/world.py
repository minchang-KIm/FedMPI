#!/usr/bin/env python3
"""주행 환경 시뮬레이터: 0.1초마다 차량 주행과 통신 상태를 계산해 RUN_DIR/world.json에 쓴다.

주행
  - 2차선(우측 통행): 차량은 진행 방향 오른쪽 차로를 달린다. 같은 차로 앞차와 간격을 유지한다(차간 거리 제어).
  - 신호등: 교차로마다 동서·남북 두 현시(초록→노랑→빨강). 빨간불·노란불(멈출 수 있을 때)에는 정지선에 선다.
  - 횡단보도: 보행자가 건너는 동안 차량이 선다. 보행자가 갑자기 뛰어들면(돌발) 긴급제동.
  - 긴급제동: 보행자 돌발·신호 급정거·끼어들기 → 9 m/s² 감속, ADAS가 연산을 점유하는 시간
    = adas_base_s + adas_per_10kmh_s × (속도/10). 차량(FL 클라이언트)은 이 시간 동안 학습이 느려지거나(4-5)
    확률적으로 FL 프로세스가 종료된다(1-4).
  - 정차: 집(시동 꺼짐) · 충전소(충전, 시동 켬, 새 데이터 없음) · 서비스센터(OTA 재부팅 또는 정비 대기).
통신
  cell(서빙 기지국), quality, region, zone 플래그(터널·음영·보호구역·Wi-Fi·강우·혼잡), link_up, server_ok, wifi
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
from common import DEFAULT_CONFIG, emit, load_map, merged_vehicle, read_json, write_json  # noqa: E402

DT = 0.1
ACC, DEC, DEC_EMERG = 2.5, 4.0, 9.0          # m/s²
CAR_GAP = 12.0                               # 앞차·정지선과 띄우는 거리 (m)


def in_rect(p, r):
    return r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3]


class Vehicle:
    def __init__(self, vid, route_id, route, phase, lane_w):
        self.vid, self.route_id, self.route = vid, route_id, route
        self.pts = route["pts"]
        self.lane_w = lane_w
        self.seg, self.s = 0, 0.0
        self.v = 0.0                               # m/s
        self.stop_left, self.stop_kind = 0.0, None
        self.present, self.respawn_at = True, None
        self.gilbert_good, self.cell, self.region, self.in_tunnel = True, None, None, False
        self.available = True
        self.emerg_left, self.emerg_id, self.emerg_cause = 0.0, 0, ""
        self.braking = False
        total = sum(self.seg_len(i) for i in range(len(self.pts) - 1))
        d = phase * total
        while d > self.seg_len(self.seg) and self.seg < len(self.pts) - 2:
            d -= self.seg_len(self.seg)
            self.seg += 1
        self.s = d
        self.update_pos()

    def seg_len(self, i):
        a, b = self.pts[i], self.pts[i + 1]
        return math.hypot(b[0] - a[0], b[1] - a[1])

    def update_pos(self):
        a, b = self.pts[self.seg], self.pts[self.seg + 1]
        L = self.seg_len(self.seg) or 1.0
        t = min(1.0, self.s / L)
        hx, hz = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        self.h = (hx, hz)
        self.n = (-hz, hx)                         # 진행 방향 오른쪽
        self.center = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
        off = self.lane_w / 2 if self.stop_left <= 0 else self.lane_w * 1.6     # 정차 중이면 갓길
        self.pos = [self.center[0] + self.n[0] * off, self.center[1] + self.n[1] * off]
        self.heading = math.atan2(hz, hx)

    def state(self):
        return {k: getattr(self, k) for k in ("seg", "s", "v", "stop_left", "stop_kind", "present", "gilbert_good",
                                               "cell", "region", "in_tunnel", "available", "emerg_left", "emerg_id",
                                               "emerg_cause")}

    def restore(self, st):
        for k, val in st.items():
            setattr(self, k, val)
        self.update_pos()


class World:
    def __init__(self, run_dir):
        self.run_dir = Path(run_dir)
        self.cfg = read_json(self.run_dir / "config.json", DEFAULT_CONFIG)
        self.rng = random.Random(int(self.cfg["fl"].get("seed", 42)))
        self.map = load_map(self.cfg["world"].get("map", "default"))
        self.lane_w = float(self.map.get("lane_width", 7))
        K = int(self.cfg["fl"]["K"])
        vr = self.map["vehicle_routes"]
        routes = [vr[(i - 1) % len(vr)] for i in range(1, K + 1)]
        count = {}
        self.vehicles = []
        for i, r in enumerate(routes, start=1):
            n, k = routes.count(r), count.get(r, 0)
            count[r] = k + 1
            self.vehicles.append(Vehicle(i, r, self.map["routes"][r], (k + 0.5) / n, self.lane_w))
        self.t0 = time.time()
        self.clock = 0.0                          # 시뮬레이션 경과 시간 (신호 주기 기준)
        self.cfg_mtime = 0
        self.peds = {x["id"]: [] for x in self.map.get("crosswalks", [])}   # 보행자: [시작 시각, 방향]
        self.cw_axis = {x["id"]: self.road_axis(x["pos"]) for x in self.map.get("crosswalks", [])}
        resume = os.environ.get("SIM_RESUME_DIR")
        if resume and (Path(resume) / "world_state.json").exists():
            st = read_json(Path(resume) / "world_state.json", {})
            self.clock = st.get("clock", 0.0)
            for v in self.vehicles:
                if str(v.vid) in st.get("vehicles", {}):
                    v.restore(st["vehicles"][str(v.vid)])
            emit(self.run_dir, "world", msg=f"저장된 주행 상태에서 이어서 시작 ({resume})")
        self.hist = open(self.run_dir / "world_hist.jsonl", "a")

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

    def road_speed(self, p):
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
        if t < g:
            ew = "green"
        elif t < g + y:
            ew = "yellow"
        else:
            ew = "red"
        if axis == "x":
            return ew
        t2 = t - (g + y)
        if t2 < 0:
            return "red"
        return "green" if t2 < g else "yellow"

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

    # ---------------------------------------------------------------- 보행자
    def step_peds(self):
        scale = float(self.cfg["world"].get("pedestrian_scale", 1.0))
        width = 2 * self.lane_w + 8
        for x in self.map.get("crosswalks", []):
            lst = self.peds[x["id"]]
            lst[:] = [p for p in lst if (self.clock - p[0]) * 1.3 < width]          # 다 건넌 보행자 제거
            if self.rng.random() < x.get("rate_per_min", 3) * scale / 600:
                darting = self.rng.random() < x.get("dart_prob", 0.05)
                lst.append([self.clock, self.rng.choice([-1, 1]), darting])
                if darting:                                                  # 돌발: 다가오던 차 긴급제동
                    for v in self.vehicles:
                        if not v.present or v.stop_left > 0:
                            continue
                        proj, lat = self.rel(v, x["pos"])
                        stop_need = v.v ** 2 / (2 * DEC) + 4
                        rate = float(merged_vehicle(self.cfg, v.vid).get("emergency_rate", 1.0))
                        if 3 < proj < stop_need + 15 and abs(lat) < 20 and v.v > 4 and self.rng.random() < min(1, rate):
                            self.emergency(v, f"{x['name']} 보행자 돌발")

    def ped_positions(self):
        width = 2 * self.lane_w + 8
        out = []
        for x in self.map.get("crosswalks", []):
            ax = self.cw_axis[x["id"]]
            for t0, d, dart in self.peds[x["id"]]:
                p = (self.clock - t0) * 1.3 - width / 2
                off = p * d
                pos = [x["pos"][0], x["pos"][1] + off] if ax == "x" else [x["pos"][0] + off, x["pos"][1]]
                out.append([round(pos[0], 1), round(pos[1], 1), 1 if dart else 0])
        return out

    @staticmethod
    def rel(v, p):
        dx, dz = p[0] - v.pos[0], p[1] - v.pos[1]
        return dx * v.h[0] + dz * v.h[1], dx * v.n[0] + dz * v.n[1]

    # ---------------------------------------------------------------- 주행
    def obstacle_dist(self, v):
        """앞에 있는 가장 가까운 장애물(앞차·정지선·보행자)까지 거리와 원인"""
        best, why = 1e9, ""
        for o in self.vehicles:
            if o is v or not o.present or o.stop_left > 0:
                continue
            proj, lat = self.rel(v, o.pos)
            if 0 < proj < 80 and abs(lat) < self.lane_w * 0.7 and o.h[0] * v.h[0] + o.h[1] * v.h[1] > 0.5:
                if proj - CAR_GAP < best:
                    best, why = proj - CAR_GAP, "앞차"
        axis = "x" if abs(v.h[0]) > abs(v.h[1]) else "z"
        for sig in self.map.get("signals", []):
            proj, lat = self.rel(v, sig["pos"])
            if 0 < proj < 90 and abs(lat) < 22:
                st = self.signal_state(sig, axis)
                line = proj - 14
                if st == "red" or (st == "yellow" and line > v.v ** 2 / (2 * DEC)):
                    if line < best:
                        best, why = line, f"신호 {sig['id']}"
        for x in self.map.get("crosswalks", []):
            if not self.peds[x["id"]]:
                continue
            proj, lat = self.rel(v, x["pos"])
            if 0 < proj < 70 and abs(lat) < 22 and proj - 10 < best:
                best, why = proj - 10, "보행자"
        return best, why

    def step_vehicle(self, v, now):
        wcfg = self.cfg["world"]
        vcfg = merged_vehicle(self.cfg, v.vid)
        if vcfg.get("leave") and v.present:
            v.present, v.respawn_at = False, None
            self.ev(v, "맵에서 이탈 (차량 설정)")
        if not v.present:
            if vcfg.get("leave"):
                return
            if v.respawn_at is None:
                v.respawn_at = self.clock + self.rng.expovariate(1.0 / max(1, wcfg["visitor_gap_mean_s"]))
            if self.clock >= v.respawn_at:
                v.present, v.seg, v.s, v.v = True, 0, 0.0, 0.0
                v.update_pos()
                self.ev(v, "진입 게이트로 새로 합류")
            return
        if v.emerg_left > 0:
            v.emerg_left = max(0.0, v.emerg_left - DT)
        if v.stop_left > 0:
            v.stop_left -= DT
            v.v = 0.0
            if v.stop_left <= 0:
                self.ev(v, {"home": "시동 켬, 출발", "gas": "충전 끝, 출발", "service": "서비스센터 출발",
                            "ota": "OTA 설치·재부팅 완료"}.get(v.stop_kind, "출발"), stop=v.stop_kind, phase="end")
                v.stop_kind = None
                v.update_pos()
            return
        # 속도 제어: 제한 속도 → 장애물 앞에서 멈출 수 있는 속도 → 가감속
        limit = self.road_speed(v.pos) / 3.6 * float(wcfg.get("speed_scale", 1.0))
        d, why = self.obstacle_dist(v)
        target = limit if d > 900 else min(limit, math.sqrt(max(0.0, 2 * DEC * max(0.0, d))))
        need = v.v ** 2 / (2 * max(0.5, d)) if d < 900 else 0
        if v.v > target:
            dec = DEC_EMERG if (v.braking or need > 6.5) else DEC
            if need > 6.5 and not v.braking and v.v * 3.6 > 15 and why.startswith("신호"):
                self.emergency(v, "신호 급정거")
            v.v = max(target, v.v - dec * DT)
        else:
            v.v = min(target, v.v + ACC * DT)
            v.braking = False
        # 끼어들기 등 무작위 긴급 상황 (고속일수록 잦음, 차량 설정 emergency_rate 배수)
        if v.v * 3.6 > 40 and self.rng.random() < 0.0008 * float(vcfg.get("emergency_rate", 1.0)):
            self.emergency(v, "끼어들기")
        v.s += v.v * DT
        while v.s >= v.seg_len(v.seg):
            v.s -= v.seg_len(v.seg)
            v.seg += 1
            if v.seg >= len(v.pts) - 1:
                if v.route["loop"]:
                    v.seg = 0
                else:
                    v.present, v.respawn_at, v.seg, v.s = False, None, 0, 0.0
                    self.ev(v, "이탈 게이트로 맵을 떠남")
                    return
            node = v.pts[v.seg]
            if len(node) > 2:
                self.maybe_stop(v, node[2], wcfg)
                if v.stop_left > 0:
                    v.s, v.v = 0.0, 0.0
                    break
        v.update_pos()

    def maybe_stop(self, v, kind, wcfg):
        if kind == "home":
            v.stop_left, v.stop_kind = self.rng.uniform(*wcfg["home_park_s"]), "home"
            self.ev(v, "집 도착, 시동 끔 (주차)", stop="home", phase="start")
        elif kind == "gas":
            energy = (read_json(self.run_dir / f"client_{v.vid}.json", {}) or {}).get("energy", 1000)
            if energy < 0.5 * self.cfg["energy"]["budget_j"] or self.rng.random() < 0.35:
                v.stop_left, v.stop_kind = self.rng.uniform(*wcfg["charge_s"]), "gas"
                self.ev(v, "충전소 정차 (시동 켠 채 충전, 새 데이터 없음)", stop="gas", phase="start")
        elif kind == "service":
            if self.rng.random() < wcfg["ota_prob"]:
                v.stop_left, v.stop_kind = self.rng.uniform(*wcfg["ota_s"]), "ota"
                self.ev(v, "서비스센터 OTA 설치 시작 (재부팅)", stop="ota", phase="start")
            else:
                v.stop_left, v.stop_kind = self.rng.uniform(*wcfg["service_wait_s"]), "service"
                self.ev(v, "서비스센터 정비 대기 (시동 켠 채 정차)", stop="service", phase="start")

    # ---------------------------------------------------------------- 통신
    def serving_cell(self, v, tunnel):
        if tunnel:
            return None, 0.0
        best, q = None, 0.0
        for c in self.map["cells"]:
            d = math.hypot(v.pos[0] - c["pos"][0], v.pos[1] - c["pos"][1])
            if d <= c["r"] and 1 - d / c["r"] > q:
                best, q = c, 1 - d / c["r"]
        return best, q

    def link(self, v):
        ncfg = self.cfg["net"]
        z = self.zone_flags(v.pos)
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
        region = "W" if v.pos[0] < self.map.get("region_border_x", 1e9) else "E"
        if v.region and region != v.region and v.present:
            self.ev(v, f"권역 경계 통과 {v.region} → {region}", region_cross=[v.region, region])
        v.region = region
        off = v.stop_kind in ("home", "ota")
        link_up = bool(v.present and cid and not tunnel and v.gilbert_good and not off)
        at_wifi_place = v.stop_kind in ("gas", "service") or any(
            p.get("wifi") and math.hypot(v.pos[0] - p["pos"][0], v.pos[1] - p["pos"][1]) < 60 for p in self.map["places"])
        return {
            "pos": [round(v.pos[0], 1), round(v.pos[1], 1)], "heading": round(v.heading, 3),
            "speed_kmh": round(v.v * 3.6, 1), "route": v.route_id, "present": v.present,
            "cell": cid, "quality": round(q, 3), "region": region, "zones": z, "gilbert_good": v.gilbert_good,
            "link_up": link_up, "server_ok": link_up, "wifi": bool(link_up and (z.get("wifi") or at_wifi_place)),
            "engine_off": v.stop_kind == "home" or not v.present, "charging": v.stop_kind == "gas",
            "ota": v.stop_kind == "ota", "idle_parked": v.stop_kind in ("gas", "service"),
            "stop_left": round(max(0, v.stop_left), 1), "available": v.available, "moving": v.v > 1,
            "emergency": round(v.emerg_left, 1), "emergency_id": v.emerg_id, "emergency_cause": v.emerg_cause,
            "braking": v.braking,
        }

    def availability_target(self):
        w = self.cfg["world"]
        if w.get("availability_mode") != "cycle":
            return 1.0
        lo, hi, per = w["availability_min"], w["availability_max"], max(30, w["availability_period_s"])
        return lo + (hi - lo) * 0.5 * (1 - math.cos(2 * math.pi * self.clock / per))

    # ---------------------------------------------------------------- 루프
    def run(self):
        last_avail = last_state = last_hist = -1e9
        while True:
            now = time.time()
            self.reload_cfg()
            self.clock += DT
            if self.clock - last_avail > 10:
                # 7-3 운행 시간대: 가용률 주기. 통근(commute) 차량은 출퇴근 구간에 더 많이 가용
                tgt = self.availability_target()
                cyc = self.cfg["world"].get("availability_mode") == "cycle"
                for v in self.vehicles:
                    was = v.available
                    bias = 1.0
                    if cyc:
                        phase = math.sin(2 * math.pi * self.clock / max(30, self.cfg["world"]["availability_period_s"]))
                        bias = 1.3 if (v.route_id == "commute") == (phase > 0) else 0.7
                    v.available = self.rng.random() < min(1.0, tgt * bias)
                    if was != v.available and cyc:
                        self.ev(v, f"가용 상태 {'켜짐' if v.available else '꺼짐'} (목표 가용률 {tgt:.0%})")
                last_avail = self.clock
            self.step_peds()
            state = {}
            for v in self.vehicles:
                self.step_vehicle(v, now)
                state[str(v.vid)] = self.link(v)
            sigs = {}
            for s in self.map.get("signals", []):
                sigs[s["id"]] = [self.signal_state(s, "x"), self.signal_state(s, "z")]
            peds = self.ped_positions()
            write_json(self.run_dir / "world.json", {"t": now, "elapsed": self.clock,
                                                     "availability_target": self.availability_target(),
                                                     "vehicles": state, "signals": sigs, "peds": peds})
            if self.clock - last_state >= 2:            # 불러오기용 전체 상태
                write_json(self.run_dir / "world_state.json",
                           {"clock": self.clock, "vehicles": {str(v.vid): v.state() for v in self.vehicles}})
                last_state = self.clock
            if self.clock - last_hist >= 1:             # 다시 보기용 기록 (1초 간격, 짧게)
                rec = {"t": round(now, 2), "c": round(self.clock, 1),
                       "v": {k: [s["pos"][0], s["pos"][1], s["heading"], int(s["speed_kmh"]),
                                 int(s["present"]) | int(s["engine_off"]) << 1 | int(s["charging"]) << 2
                                 | int(s["ota"]) << 3 | int(s["emergency"] > 0) << 4 | int(s["link_up"]) << 5]
                             for k, s in state.items()},
                       "s": {k: v[0][0] + v[1][0] for k, v in sigs.items()}, "p": peds}
                self.hist.write(json.dumps(rec, separators=(",", ":")) + "\n")
                self.hist.flush()
                last_hist = self.clock
            time.sleep(max(0.0, DT - (time.time() - now)))


def seg_dist(p, a, b):
    ax, az = a[:2]
    bx, bz = b[:2]
    dx, dz = bx - ax, bz - az
    L2 = dx * dx + dz * dz
    t = 0 if L2 == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - az) * dz) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (az + t * dz))


if __name__ == "__main__":
    World(sys.argv[1]).run()
