"""수동 운전: 화면에서 고른 차량을 사람이 직접 운전 (여러 사람이 각자 다른 차량).

RUN_DIR/drive.json {"cars": {vid: {on, throttle, brake, steer, reverse, park, name, t}}}를 매 틱 읽는다.
차량마다 입력이 2초 끊기면 그 차만 자동 운전으로 돌아간다.
  - 자전거 모델(축간 2.8 m)로 이동. 다른 차·건물과는 겹치지 않는다. 도로 밖은 25 km/h 제한.
  - 위치·속도로 셀·터널·음영·Wi-Fi·권역·긴급제동이 자동 주행과 똑같이 계산된다 → 유스케이스가 그대로 일어난다.
  - ADAS 자동 긴급제동(앞차·보행자·건물), 운전자 급제동, 신호 위반은 사건으로 남고 긴급제동은 연산 점유(4-5·1-4)로 이어진다.
  - 주차장 칸 근처에서 정지 후 P → 장소 종류대로 주차(집·직장·차고지 = 시동 꺼짐, 충전소 = 충전, 서비스센터 = 정비 대기).
  - 끄면 자기 경로에서 가장 가까운(방향이 맞는) 차로 지점으로 옮겨 자동 운전을 이어간다. 주차 중이면 30초 뒤 출발.
World가 이 믹스인을 상속한다.
"""

import math
import time

from common import merged_vehicle, read_json
from lanes import ACC, DEC, DEC_EMERG, DT, HW, obb_overlap
from mapgeo import CAR_L, CAR_W, SIDEWALK, road_segments

WHEELBASE, STEER_MAX = 2.8, math.radians(34)            # 축간 거리, 최대 조향각
DRIVE_TIMEOUT = 2.0                                     # 입력이 이만큼 끊기면 자동 운전으로
MANUAL_PARK = {"home": "home", "work": "home", "depot": "home", "gas": "gas", "service": "service"}


class ManualDriveMixin:
    def init_manual(self):
        h = self.lane_w + SIDEWALK                # 수동 운전: 달릴 수 있는 곳(도로·보도·주차장)과 부딪히는 곳(건물)
        self.drivable = [(min(a[0], b[0]) - h, min(a[1], b[1]) - h, max(a[0], b[0]) + h, max(a[1], b[1]) + h)
                         for _, a, b in road_segments(self.map)]
        self.drivable += [(l["rect"][0] - 6, l["rect"][1] - 6, l["rect"][2] + 6, l["rect"][3] + 6)
                          for l in self.layout["lots"].values()]
        self.drive, self.drive_mtime, self.drive_refused = {}, 0, {}

    # ---------------------------------------------------------------- 수동 운전
    def reload_drive(self):
        p = self.run_dir / "drive.json"
        try:
            m = p.stat().st_mtime_ns
        except FileNotFoundError:
            self.drive = {}
            return
        if m != self.drive_mtime:
            self.drive = read_json(p, self.drive) or {}
            self.drive_mtime = m

    def update_manual(self):
        cars, now = self.drive.get("cars") or {}, time.time()
        want = {int(k): d for k, d in cars.items() if d.get("on") and now - float(d.get("t", 0)) < DRIVE_TIMEOUT}
        for v in self.vehicles:
            if v.manual and v.vid not in want:
                d = cars.get(str(v.vid)) or {}
                self.end_manual(v, "입력 끊김" if d.get("on") else "운전 끄기")
        for vid in list(self.drive_refused):
            if vid not in want:
                del self.drive_refused[vid]
        for vid, d in want.items():
            v = next((o for o in self.vehicles if o.vid == vid), None)
            if v is None:
                continue
            v.inp, v.driver = d, d.get("name") or ""
            if v.manual:
                continue
            if v.mode == "out":
                if vid not in self.drive_refused:
                    self.ev(v, "맵 밖에 있는 차량이라 운전할 수 없음", manual="refused")
                    self.drive_refused[vid] = True
                continue
            self.begin_manual(v)

    def begin_manual(self, v):
        where = ""
        if v.mode == "park":                      # 주차 중: 차로가 비었으면 차로로 나와서, 아니면 칸에서 도로 쪽을 보고 출발
            p = v.park
            self.lots[p["place"]][p["slot"]] = None
            where = f" — {self.place_name(p['place'])}에서 출발"
            v.park = None
            v.mode = "drive"
            if self.entry_clear(v, p["s"]):
                v.put(p["s"])
            else:
                v.hx, v.hz = -v.hx, -v.hz
        self.release_boxes(v)
        v.manual, v.plan, v.aeb, v.hard_brk, v.in_box, v.park_key, v.offroad = True, None, False, False, set(), False, False
        v.block_t, v.block_by = 0.0, None
        self.ev(v, f"{v.driver or '누군가'} 수동 운전 시작{where} (셀·구역·긴급제동은 위치·속도대로 계산)", manual="on")

    def end_manual(self, v, why):
        v.manual, v.aeb, v.offroad, v.driver = False, False, False, ""
        if v.mode == "park":                      # 수동으로 주차해 둔 차: 30초 뒤 자동으로 출발
            v.park["until"] = self.clock + 30
            self.ev(v, f"자동 운전으로 전환 ({why}) — 30초 뒤 {self.place_name(v.park['place'])}에서 출발", manual="off")
            return
        s = self.nearest_s(v, (v.x, v.z), (v.hx, v.hz))
        x0, z0 = v.x, v.z
        for k in range(40):                       # 차로 위 빈 자리 (앞쪽으로 6 m씩)
            v.put(s + 6 * k)
            if all(not obb_overlap(v.box(), o.box()) for o in self.vehicles if o is not v and o.mode == "drive"):
                break
        v.v = min(abs(v.v), 5.0)
        v.decided, v.block_t, v.block_by = [], 0.0, None
        d = math.hypot(v.x - x0, v.z - z0)
        self.ev(v, f"자동 운전으로 전환 ({why})" + (f" — 경로 차로로 {d:.0f} m 이동" if d > 1 else ""), manual="off")

    def nearest_s(self, v, p, h):
        """내 경로에서 p에 가장 가깝고 진행 방향이 h와 맞는 지점"""
        P, best, bs, s = v.path, 1e18, 0.0, 0.0
        while s < P.L:
            x, z, hx, hz = P.at(s)
            c = math.hypot(x - p[0], z - p[1]) + 15 * (1 - (hx * h[0] + hz * h[1]))
            if c < best:
                best, bs = c, s
            s += 1.0
        return bs

    def blocked_at(self, v, box):
        x, z = box[0], box[1]
        W, H = self.map["size"]
        if not (2 < x < W - 2 and 2 < z < H - 2):
            return "맵 경계"
        for r in self.solid:
            if r[0] - HW < x < r[2] + HW and r[1] - HW < z < r[3] + HW:
                return "건물"
        o = next((o for o in self.vehicles if o is not v and o.mode == "drive" and obb_overlap(box, o.box())), None)
        return f"V{o.vid}" if o else None

    def aeb_target(self, v, peds):
        """진행 방향 정지 거리 안에 다른 차·보행자·건물이 있으면 그 이름 (ADAS 자동 긴급제동)"""
        sg = 1 if v.v >= 0 else -1
        look = v.v * v.v / (2 * DEC_EMERG) + 3.0
        peds = list(peds) + [(w.x, w.z, 0) for w in self.walkers if w.state != "off" and abs(w.x - v.x) + abs(w.z - v.z) < look + 8]
        near = [o for o in self.vehicles if o is not v and o.mode == "drive" and abs(o.x - v.x) + abs(o.z - v.z) < look + 12]
        d = CAR_L / 2
        while d <= look + CAR_L / 2:
            x, z = v.x + sg * v.hx * d, v.z + sg * v.hz * d
            for o in near:
                dx, dz = x - o.x, z - o.z
                if abs(dx * o.hx + dz * o.hz) <= CAR_L / 2 + 0.2 and abs(-dx * o.hz + dz * o.hx) <= CAR_W / 2 + 0.6:
                    return "앞차" if sg > 0 else "뒤차"
            for px, pz, *_ in peds:
                if math.hypot(px - x, pz - z) < 1.6:
                    return "보행자"
            for r in self.solid:
                if r[0] < x < r[2] and r[1] < z < r[3]:
                    return "건물"
            d += 1.0
        return None

    def step_manual(self, v, peds):
        d = getattr(v, "inp", {}) or {}
        num = lambda k, lo: min(1.0, max(lo, float(d.get(k) or 0)))      # noqa: E731
        thr, brk, steer = num("throttle", 0.0), num("brake", 0.0), num("steer", -1.0)
        rev = bool(d.get("reverse"))
        if v.emerg_left > 0:
            v.emerg_left = max(0.0, v.emerg_left - DT)
        if d.get("park") and not v.park_key:      # P: 정지 상태로 주차장 근처면 그 칸에 주차, 주차 중이면 출발
            self.manual_park(v)
        v.park_key = bool(d.get("park"))
        if v.mode == "park":
            if thr > 0.2:
                self.manual_unpark(v)
            return
        # 운전자 급제동 → 긴급제동 (ADAS 연산 점유)
        if brk > 0.85 and v.v * 3.6 > 30 and not v.hard_brk:
            self.emergency(v, "운전자 급제동")
        v.hard_brk = brk > 0.3 and (v.hard_brk or (brk > 0.85 and v.v * 3.6 > 30))
        # ADAS 자동 긴급제동: 정지 거리 안에 장애물이 있으면 운전자 입력보다 우선해 멈춘다
        use_aeb = merged_vehicle(self.cfg, v.vid).get("aeb", True)
        hit = self.aeb_target(v, peds) if use_aeb and (abs(v.v) * 3.6 > 12 or v.aeb) else None
        if hit and not v.aeb and abs(v.v) * 3.6 > 12:
            v.aeb = True
            self.emergency(v, f"ADAS 자동 긴급제동({hit})")
        if v.aeb:
            thr, brk = 0.0, 1.0
            if abs(v.v) < 0.2:
                v.aeb = False
        # 앞뒤 방향: 가속·제동·구름 저항, 후진은 정지 후 R
        on_road = any(r[0] <= v.x <= r[2] and r[1] <= v.z <= r[3] for r in self.drivable)
        if on_road != (not v.offroad):
            v.offroad = not on_road
            self.ev(v, "도로 밖으로 나감 (25 km/h 제한)" if v.offroad else "도로로 돌아옴", manual="road")
        vmax = (25 if v.offroad else 130) / 3.6
        a = (-ACC * 0.8 if rev else ACC * 1.4) * thr
        if brk > 0:
            dv = (DEC_EMERG if v.aeb else DEC * 1.6) * brk * DT
            v.v = max(0.0, v.v - dv) if v.v > 0 else min(0.0, v.v + dv)
        if a:
            v.v += a * DT
        elif not brk:
            v.v -= math.copysign(min(abs(v.v), (0.25 + 0.0006 * v.v * v.v) * DT), v.v)
        v.v = max(-15 / 3.6, v.v)
        if v.v > vmax:
            v.v = max(vmax, v.v - DEC * DT)
        v.braking = v.aeb or brk > 0.1
        # 자전거 모델 (속도가 높을수록 조향각 줄임)
        st = steer * STEER_MAX / (1 + v.v * v.v / 60)
        yaw = v.v / WHEELBASE * math.tan(st) * DT
        h = math.atan2(v.hz, v.hx) + yaw
        hx, hz = math.cos(h), math.sin(h)
        nx, nz = v.x + hx * v.v * DT, v.z + hz * v.v * DT
        why = self.blocked_at(v, (nx, nz, hx, hz))
        if why is None:
            v.odo += abs(v.v) * DT
            v.x, v.z, v.hx, v.hz = nx, nz, hx, hz
        else:
            if abs(v.v) * 3.6 > 8:
                self.ev(v, f"수동 운전 충돌 직전 정지 ({why}) {abs(v.v) * 3.6:.0f} km/h", manual="crash")
            v.v = 0.0
        # 신호 교차로에 적색으로 들어가면 신호 위반
        B = self.lane_w + 3.0
        for sig in self.map.get("signals", []):
            inside = abs(v.x - sig["pos"][0]) <= B and abs(v.z - sig["pos"][1]) <= B
            if inside and sig["id"] not in v.in_box:
                v.in_box.add(sig["id"])
                axis = "x" if abs(v.hx) > abs(v.hz) else "z"
                if self.signal_state(sig, axis) == "red" and v.v > 1:
                    self.ev(v, f"신호 위반 — 교차로 {sig['id']} 적색 진입", manual="red_light")
            elif not inside:
                v.in_box.discard(sig["id"])

    def manual_park(self, v):
        if v.mode == "park":
            self.manual_unpark(v)
            return
        if abs(v.v) > 1.0:
            self.ev(v, "주차하려면 먼저 멈추세요", manual="park")
            return
        best, bd = None, 1e9
        for pid, l in self.layout["lots"].items():
            r = l["rect"]
            dd = math.hypot(max(r[0] - v.x, 0, v.x - r[2]), max(r[1] - v.z, 0, v.z - r[3]))
            if dd < bd:
                best, bd = pid, dd
        if best is None or bd > 12:
            self.ev(v, "주차장 칸 근처가 아님 (집·직장·차고지·충전소·서비스센터 주차장으로 가세요)", manual="park")
            return
        slots = self.lots[best]
        free = [k for k, o in enumerate(slots) if o is None]
        if not free:
            self.ev(v, f"{self.place_name(best)} 만차", manual="park")
            return
        sls = self.layout["lots"][best]["slots"]
        k = min(free, key=lambda i: math.hypot(sls[i][0] - v.x, sls[i][1] - v.z))
        kind = self.layout["lots"][best]["kind"]
        sk = MANUAL_PARK.get(kind, "home")
        slots[k] = v.vid
        sl = sls[k]
        v.mode, v.v, v.aeb = "park", 0.0, False
        v.park = {"place": best, "slot": k, "until": 1e18, "sk": sk, "s": self.nearest_s(v, (v.x, v.z), (v.hx, v.hz)),
                  "odo": v.odo, "kind": kind,
                  "why": {"home": "수동 주차 (시동 꺼짐)", "gas": "수동 주차 — 충전 중", "service": "수동 주차 — 정비 대기"}[sk]}
        v.x, v.z, v.hx, v.hz = sl[0], sl[1], math.cos(sl[2]), math.sin(sl[2])
        self.ev(v, f"{v.park['why']} ({self.place_name(best)})", stop=sk, phase="start", manual="park")

    def manual_unpark(self, v):
        p = v.park
        self.lots[p["place"]][p["slot"]] = None
        v.mode, v.v, v.park = "drive", 0.0, None
        v.hx, v.hz = -v.hx, -v.hz                 # 칸에서 도로 쪽을 보고 나온다
        self.ev(v, f"수동 운전 출발 ({self.place_name(p['place'])})", stop=p["sk"], phase="end", manual="unpark")
