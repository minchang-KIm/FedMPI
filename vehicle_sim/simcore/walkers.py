"""사람: 횡단보도를 건너는 보행자(신호처럼 차를 세움)와 보도·공원을 걷는 사람(차에 치이면 날아갔다 일어남).

World가 이 믹스인을 상속한다. self.map·self.rng·self.vehicles·self.solid·self.lane_w·self.clock 등을 쓴다.
"""

import math

from common import merged_vehicle
from lanes import DEC, DT, right, unit
from mapgeo import CAR_L, CAR_W, SIDEWALK, road_segments

PED_R, GRAV = 0.35, 9.8                                 # 걷는 사람 반경 (m), 중력
WSTATE = {"walk": 0, "cross": 1, "fly": 2, "slide": 3, "down": 4, "getup": 5}


class Walker:
    """보도·공원을 걷는 사람. walk(보도 선 위) · cross(목표점으로 직진: 길 건너기·복귀) · fly · slide · down · getup · off"""

    def __init__(self, wid, rank, rng):
        self.wid, self.rank = wid, rank
        self.state = "off"
        self.x = self.z = self.y = 0.0
        self.vx = self.vz = self.vy = 0.0
        self.yaw, self.tilt, self.spin = 0.0, 0.0, 0.0
        self.line, self.t, self.dir = 0, 0.0, 1
        self.speed = rng.uniform(1.0, 1.6)
        self.goal, self.after, self.timer = None, None, 0.0
        self.park = None                          # 공원을 걷는 사람: 공원 사각형
        self.jay, self.lie = False, math.pi / 2


class PedestriansMixin:
    def init_pedestrians(self):
        self.peds = {x["id"]: [] for x in self.map.get("crosswalks", [])}   # 횡단보도 보행자: [시작 시각, 방향, 돌발]
        self.cw_wait = {}                         # 횡단보도 앞에서 차가 기다리기 시작한 시각 (오래 기다리면 보행자 멈춤)
        self.cw_axis = {x["id"]: self.road_axis(x["pos"]) for x in self.map.get("crosswalks", [])}
        # 걷는 사람: 보도 선(도로마다 양쪽, 짝수·홀수 번호가 서로 맞은편) · 공원
        off, self.walk_lines = self.lane_w + SIDEWALK / 2, []
        for rd, a, b in road_segments(self.map):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            cut = self.lane_w + SIDEWALK + 1
            if rd["speed"] >= 80 or L < 2 * cut + 10:
                continue
            u = unit(b[0] - a[0], b[1] - a[1])
            n = right(u)
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if self.zone_flags(mid).get("tunnel"):
                continue
            for side in (1, -1):
                p0 = (a[0] + u[0] * cut + n[0] * off * side, a[1] + u[1] * cut + n[1] * off * side)
                p1 = (b[0] - u[0] * cut + n[0] * off * side, b[1] - u[1] * cut + n[1] * off * side)
                self.walk_lines.append((p0, p1, L - 2 * cut, (n[0] * side, n[1] * side)))
        self.parks = [tuple(lu["rect"]) for lu in self.map.get("landuse", []) if lu["kind"] == "park"]
        self.walkers = [Walker(i, i, self.rng) for i in range(int(self.cfg["world"].get("walkers", 40)))]
        self.ped_hits = 0

    # ---------------------------------------------------------------- 보행자
    def step_peds(self):
        scale = float(self.cfg["world"].get("pedestrian_scale", 1.0))
        width = 2 * self.lane_w + 2 * SIDEWALK
        for x in self.map.get("crosswalks", []):
            lst = self.peds[x["id"]]
            lst[:] = [p for p in lst if (self.clock - p[0]) * 1.3 < width]          # 다 건넌 보행자 제거
            rate = x.get("rate_per_min", 3) * scale * self.hour_mult("school" if x.get("school") else "ped")
            held = self.clock - self.cw_wait.get(x["id"], self.clock) > 8      # 차가 8초 넘게 기다리면 새 보행자는 대기
            if not held and self.rng.random() < rate / 600:
                darting = self.rng.random() < x.get("dart_prob", 0.05)
                lst.append([self.clock, self.rng.choice([-1, 1]), darting])
                if darting:                                                  # 돌발: 다가오던 차 긴급제동
                    for v in self.vehicles:
                        if v.mode != "drive" or v.v < 4:
                            continue
                        rate_v = float(merged_vehicle(self.cfg, v.vid).get("emergency_rate", 1.0))
                        for s_cw, cw, _ in v.path.cross:
                            a = v.path.ahead(s_cw, v.s)
                            if cw["id"] == x["id"] and 3 < a < v.v ** 2 / (2 * DEC) + 19 and self.rng.random() < min(1.0, rate_v):
                                self.emergency(v, f"{x['name']} 보행자 돌발")

    def ped_positions(self):
        width = 2 * self.lane_w + 2 * SIDEWALK
        out = []
        for x in self.map.get("crosswalks", []):
            ax = self.cw_axis[x["id"]]
            for t0, d, dart in self.peds[x["id"]]:
                off = ((self.clock - t0) * 1.3 - width / 2) * d
                pos = [x["pos"][0], x["pos"][1] + off] if ax == "x" else [x["pos"][0] + off, x["pos"][1]]
                out.append([round(pos[0], 1), round(pos[1], 1), 1 if dart else 0])
        return out

    # ---------------------------------------------------------------- 걷는 사람
    def walker_hit(self, v, look):
        """내 앞 차로에 있는(보도가 아닌) 사람까지 앞 범퍼 기준 거리"""
        near = [w for w in self.walkers if w.state not in ("walk", "off") and abs(w.x - v.x) + abs(w.z - v.z) < look + 10]
        if not near:
            return None
        d = CAR_L / 2
        while d <= look:
            x, z, _, _ = v.path.at(v.s + d)
            for w in near:
                if math.hypot(w.x - x, w.z - z) < CAR_W / 2 + 0.9:
                    return d - CAR_L / 2
            d += 1.0 if d < 25 else 2.0
        return None

    def wl_point(self, k, t):
        p0, p1, L, _ = self.walk_lines[k]
        f = t / L if L else 0.0
        return p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f

    def nearest_line(self, x, z):
        best, bk, bt = 1e18, 0, 0.0
        for k, (p0, p1, L, _) in enumerate(self.walk_lines):
            ux, uz = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
            t = min(L, max(0.0, (x - p0[0]) * ux + (z - p0[1]) * uz))
            d = math.hypot(p0[0] + ux * t - x, p0[1] + uz * t - z)
            if d < best:
                best, bk, bt = d, k, t
        return bk, bt

    def walker_go(self, w, gx, gz, after):
        w.state, w.goal, w.after = "cross", (gx, gz), after
        w.yaw = math.atan2(gz - w.z, gx - w.x)

    def spawn_walker(self, w):
        r = self.rng
        if self.parks and r.random() < 0.25:
            w.park = r.choice(self.parks)
            w.x, w.z = r.uniform(w.park[0], w.park[2]), r.uniform(w.park[1], w.park[3])
            w.state = "walk"
            return
        w.park = None
        w.line = r.randrange(len(self.walk_lines))
        w.t = r.uniform(0, self.walk_lines[w.line][2])
        w.dir = r.choice([1, -1])
        w.x, w.z = self.wl_point(w.line, w.t)
        w.state = "walk"

    def step_walkers(self):
        if not self.walk_lines:
            return
        r, wcfg = self.rng, self.cfg["world"]
        n_on = round(len(self.walkers) * min(1.0, max(0.15, self.hour_mult("ped") / 1.6)) * min(1.0, float(wcfg.get("pedestrian_scale", 1.0))))
        jay = float(wcfg.get("jaywalk_per_min", 0.3)) / 60 * DT
        for w in self.walkers:
            if w.state == "off":
                if w.rank < n_on:
                    self.spawn_walker(w)
                continue
            if w.state == "walk" and w.rank >= n_on and not w.park:
                w.state = "off"                       # 집으로 (시간대)
                continue
            if w.state == "walk":
                if w.park:                            # 공원: 아무 곳이나 목표로 걷기
                    if w.goal is None or math.hypot(w.goal[0] - w.x, w.goal[1] - w.z) < 1:
                        w.goal = (r.uniform(w.park[0], w.park[2]), r.uniform(w.park[1], w.park[3]))
                    w.yaw = math.atan2(w.goal[1] - w.z, w.goal[0] - w.x)
                    w.x += math.cos(w.yaw) * w.speed * 0.7 * DT
                    w.z += math.sin(w.yaw) * w.speed * 0.7 * DT
                    continue
                p0, p1, L, n = self.walk_lines[w.line]
                w.t += w.dir * w.speed * DT
                if w.t <= 0 or w.t >= L:               # 보도 끝: 근처 다른 보도로 건너거나 되돌아감
                    w.t = min(L, max(0.0, w.t))
                    w.x, w.z = self.wl_point(w.line, w.t)
                    cand = []
                    for k, (q0, q1, _, _) in enumerate(self.walk_lines):
                        if k == w.line:
                            continue
                        for end, q in ((0, q0), (1, q1)):
                            if math.hypot(q[0] - w.x, q[1] - w.z) < 30:
                                cand.append((k, end, q))
                    if cand and r.random() < 0.85:
                        k, end, q = r.choice(cand)
                        self.walker_go(w, q[0], q[1], (k, end))
                    else:
                        w.dir = -w.dir
                    continue
                w.x, w.z = self.wl_point(w.line, w.t)
                w.yaw = math.atan2((p1[1] - p0[1]) * w.dir, (p1[0] - p0[0]) * w.dir)
                if r.random() < jay and 15 < w.t < L - 15:     # 무단횡단: 맞은편 보도로 곧장
                    o = w.line ^ 1                    # 맞은편 보도 (같은 도로, 같은 위치 t)
                    ox, oz = self.wl_point(o, w.t)
                    self.walker_go(w, ox, oz, (o, w.t))
                    w.jay = True
                continue
            if w.state == "cross":
                gx, gz = w.goal
                d = math.hypot(gx - w.x, gz - w.z)
                step = w.speed * (1.25 if w.jay else 1.0) * DT
                if d <= step:
                    k, e = w.after                    # 교차로 건너기: (보도, 끝 0/1) · 그 외: (보도, 위치 t)
                    w.line = k
                    L = self.walk_lines[k][2]
                    if w.jay:
                        w.t, w.dir = min(L, max(0.0, e)), r.choice([1, -1])
                    else:
                        w.t, w.dir = (0.0, 1) if e == 0 else (L, -1)
                    w.state, w.goal, w.jay = "walk", None, False
                    w.x, w.z = self.wl_point(k, w.t)
                else:
                    w.yaw = math.atan2(gz - w.z, gx - w.x)
                    w.x += (gx - w.x) / d * step
                    w.z += (gz - w.z) / d * step
                continue
            if w.state in ("fly", "slide"):
                self.step_flight(w)
                continue
            if w.state == "down":
                w.timer -= DT
                if w.timer <= 0:
                    w.state, w.timer = "getup", 1.4
                continue
            if w.state == "getup":
                w.timer -= DT
                f = max(0.0, w.timer / 1.4)
                w.tilt = (math.pi / 2) * f if w.lie < math.pi else 2 * math.pi - (math.pi / 2) * f
                if w.timer <= 0:
                    w.tilt = 0.0
                    k, t = self.nearest_line(w.x, w.z)          # 보도로 돌아가 다시 걷기
                    gx, gz = self.wl_point(k, t)
                    w.park = None
                    self.walker_go(w, gx, gz, (k, t))
                    w.jay = True                                # 도착 지점에서 그 자리부터 걷는다

    def step_flight(self, w):
        """차에 치인 사람: 포물선 비행·회전 → 땅에 튕김 → 미끄러짐 → 쓰러짐"""
        nx, nz = w.x + w.vx * DT, w.z + w.vz * DT
        if any(rc[0] < nx < rc[2] and rc[1] < nz < rc[3] for rc in self.solid):   # 건물 벽에 막힘
            w.vx, w.vz = -w.vx * 0.2, -w.vz * 0.2
        else:
            W, H = self.map["size"]
            w.x, w.z = min(W - 1, max(1.0, nx)), min(H - 1, max(1.0, nz))
        if w.state == "fly":
            w.y += w.vy * DT
            w.vy -= GRAV * DT
            w.tilt += w.spin * DT
            if w.y <= 0:
                w.y = 0.0
                if w.vy < -2.5:                       # 튕김
                    w.vy = -w.vy * 0.3
                    w.vx, w.vz, w.spin = w.vx * 0.6, w.vz * 0.6, w.spin * 0.5
                else:
                    w.tilt %= 2 * math.pi
                    w.state, w.vy, w.lie = "slide", 0.0, math.pi / 2 if w.tilt < math.pi else 3 * math.pi / 2
            return
        sp = math.hypot(w.vx, w.vz)
        w.tilt += (w.lie - w.tilt) * min(1.0, DT * 6)    # 등·배를 대고 눕는다
        if sp < 0.15:
            w.state, w.vx, w.vz, w.tilt = "down", 0.0, 0.0, w.lie
            w.timer = self.rng.uniform(3, 6)
        else:
            k = max(0.0, sp - 7.0 * DT) / sp          # 바닥 마찰
            w.vx, w.vz = w.vx * k, w.vz * k

    def collide_walkers(self):
        for w in self.walkers:
            if w.state in ("off", "fly"):
                continue
            for v in self.vehicles:
                if v.mode != "drive":
                    continue
                dx, dz = w.x - v.x, w.z - v.z
                if abs(dx) + abs(dz) > 6:
                    continue
                lx, lz = dx * v.hx + dz * v.hz, -dx * v.hz + dz * v.hx
                if abs(lx) > CAR_L / 2 + PED_R or abs(lz) > CAR_W / 2 + PED_R:
                    continue
                spd = abs(v.v)
                sg = 1 if v.v >= 0 else -1
                front = lx * sg > 0
                if spd > 2.0 and w.state not in ("slide", "down", "getup"):
                    kmh = spd * 3.6
                    side = (1 if lz > 0 else -1) * (0.1 if front else 0.5)
                    w.vx = v.hx * sg * spd * 1.1 + (-v.hz) * side * spd
                    w.vz = v.hz * sg * spd * 1.1 + v.hx * side * spd
                    w.vy = 1.2 + 0.3 * spd
                    w.y, w.spin, w.state, w.goal, w.park = 0.2, 3 + spd * 0.7, "fly", None, None
                    w.yaw = math.atan2(-v.hz * sg, -v.hx * sg)     # 차 쪽을 보다가 뒤로 넘어간다
                    self.ped_hits += 1
                    est = (w.vx ** 2 + w.vz ** 2) ** 0.5 * (2 * w.vy / GRAV)
                    self.ev(v, f"보행자 충돌 {kmh:.0f} km/h → 약 {est:.0f} m 날아감 (쓰러졌다가 일어남)",
                            ped_hit=w.wid, kmh=round(kmh))
                    self.emergency(v, f"보행자 충돌 {kmh:.0f} km/h")
                    v.v *= 0.85
                elif w.state in ("walk", "cross") and spd <= 0.5:
                    # 멈춘 차에 막힌 사람: 차 앞뒤 가까운 쪽 범퍼 밖으로 돌아간다 (옆으로만 밀면 차와 서로 기다리며 멈춤)
                    out = (CAR_L / 2 + PED_R + 0.1) * (1 if lx >= 0 else -1) - lx
                    w.x += v.hx * out
                    w.z += v.hz * out
                else:                                  # 느린 접촉·쓰러진 사람: 차 옆으로 밀어냄
                    push = (CAR_W / 2 + PED_R + 0.05 - abs(lz)) * (1 if lz >= 0 else -1)
                    w.x += -v.hz * push
                    w.z += v.hx * push
                    if w.state in ("walk", "cross") and spd > 0.5:
                        w.state, w.vx, w.vz, w.vy, w.y, w.spin, w.goal = "slide", v.hx * sg * spd, v.hz * sg * spd, 0, 0, 0, None
                        w.park, w.lie = None, math.pi / 2
                break

    def walker_states(self):
        return [[w.wid, round(w.x, 2), round(w.z, 2), round(w.y, 2), round(w.yaw, 2), round(w.tilt, 2), WSTATE[w.state],
                 round(w.vx if w.state in ("fly", "slide") else math.cos(w.yaw) * w.speed * (0 if w.state in ("down", "getup") else 1), 2),
                 round(w.vz if w.state in ("fly", "slide") else math.sin(w.yaw) * w.speed * (0 if w.state in ("down", "getup") else 1), 2),
                 round(w.vy, 2), round(w.spin if w.state == "fly" else 0, 2)]
                for w in self.walkers if w.state != "off"]
