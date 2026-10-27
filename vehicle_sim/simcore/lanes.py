"""차로 경로와 차량 기하: 경로(도로 중심선 꼭짓점) → 진행 방향 오른쪽 차로 중심선, 차량 직사각형 겹침 검사."""

import bisect
import math

from mapgeo import CAR_L, CAR_W

DT = 0.1
ACC, DEC, DEC_COMF, DEC_EMERG = 2.2, 4.0, 2.0, 9.0      # m/s²
A_LAT = 2.5                                             # 곡선 구간 횡가속도 한계 (m/s²)
GAP_MIN = 2.5                                           # 정지 시 앞차와 간격 (m)
FILLET_R = 9.0                                          # 모서리 곡선 반경 (m)
HL, HW = CAR_L / 2 + 0.15, CAR_W / 2 + 0.15             # 겹침 검사용 반길이·반폭 (여유 15 cm)


def in_rect(p, r):
    return r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3]


def unit(dx, dz):
    L = math.hypot(dx, dz) or 1.0
    return dx / L, dz / L


def right(h):
    return -h[1], h[0]


def obb_overlap(a, b):
    """a, b = (x, z, hx, hz): 같은 크기 차량 직사각형의 분리축 검사"""
    dx, dz = b[0] - a[0], b[1] - a[1]
    if dx * dx + dz * dz > (2 * (HL + HW)) ** 2:
        return False
    for ux, uz in ((a[2], a[3]), (-a[3], a[2]), (b[2], b[3]), (-b[3], b[2])):
        ra = HL * abs(a[2] * ux + a[3] * uz) + HW * abs(-a[3] * ux + a[2] * uz)
        rb = HL * abs(b[2] * ux + b[3] * uz) + HW * abs(-b[3] * ux + b[2] * uz)
        if abs(dx * ux + dz * uz) > ra + rb:
            return False
    return True


class LanePath:
    """경로(도로 중심선 꼭짓점) → 진행 방향 오른쪽 차로 중심선. 모서리는 곡선(2차 베지어), U턴은 반원"""

    def __init__(self, route, off, world):
        a_lat = float(route.get("a_lat", A_LAT))          # 경로별 횡가속도 한계 (레이싱 차는 크게)
        pts = [tuple(p[:2]) for p in route["pts"]]
        kinds = [p[2] if len(p) > 2 else None for p in route["pts"]]
        self.loop = bool(route.get("loop"))
        if self.loop and pts[0] == pts[-1]:
            if kinds[-1] and not kinds[0]:
                kinds[0] = kinds[-1]
            pts, kinds = pts[:-1], kinds[:-1]
        n = len(pts)
        xs, zs, vmax, cid, stop_idx = [], [], [], [], []      # cid: 곡선(모서리) 번호, 직선 점은 None

        def add(x, z, vm, c=None):
            if xs and math.hypot(x - xs[-1], z - zs[-1]) < 0.05:
                vmax[-1] = min(vmax[-1], vm)
                cid[-1] = cid[-1] if cid[-1] is not None else c
                return
            xs.append(x)
            zs.append(z)
            vmax.append(vm)
            cid.append(c)
        for i in range(n):
            p = pts[i]
            start = len(xs)
            if not self.loop and i in (0, n - 1):
                d = unit(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]) if i == 0 else \
                    unit(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
                r = right(d)
                add(p[0] + r[0] * off, p[1] + r[1] * off, 99.0)
            else:
                a, b = pts[i - 1], pts[(i + 1) % n]
                d1, d2 = unit(p[0] - a[0], p[1] - a[1]), unit(b[0] - p[0], b[1] - p[1])
                r1, r2 = right(d1), right(d2)
                dot = d1[0] * d2[0] + d1[1] * d2[1]
                if dot > 0.999:
                    add(p[0] + r1[0] * off, p[1] + r1[1] * off, 99.0)
                elif dot < -0.98:                                     # U턴: 반원
                    for k in range(9):
                        ang = math.pi * k / 8
                        vx = r1[0] * math.cos(ang) + d1[0] * math.sin(ang)
                        vz = r1[1] * math.cos(ang) + d1[1] * math.sin(ang)
                        add(p[0] + vx * off * 1.4, p[1] + vz * off * 1.4, math.sqrt(a_lat * off), i)
                else:                                                 # 모서리: 두 차로선의 교점을 곡선으로 깎음
                    q1 = (p[0] + r1[0] * off, p[1] + r1[1] * off)
                    q2 = (p[0] + r2[0] * off, p[1] + r2[1] * off)
                    den = d1[0] * d2[1] - d1[1] * d2[0]
                    t = ((q2[0] - q1[0]) * d2[1] - (q2[1] - q1[1]) * d2[0]) / den
                    c = (q1[0] + d1[0] * t, q1[1] + d1[1] * t)
                    th = math.acos(max(-1.0, min(1.0, dot)))
                    cut = min(FILLET_R * math.tan(th / 2), 0.45 * math.dist(a, p), 0.45 * math.dist(p, b))
                    R = cut / math.tan(th / 2)
                    # 짧은 꼭짓점이 이어진 큰 곡선(원을 여러 마디로 나눈 길)은 실제 반경 = 마디 길이 / 꺾인 각
                    if th < 0.35:
                        R = max(R, min(math.dist(a, p), math.dist(p, b)) / th)
                    A = (c[0] - d1[0] * cut, c[1] - d1[1] * cut)
                    B = (c[0] + d2[0] * cut, c[1] + d2[1] * cut)
                    for k in range(9):
                        t = k / 8
                        add((1 - t) ** 2 * A[0] + 2 * (1 - t) * t * c[0] + t * t * B[0],
                            (1 - t) ** 2 * A[1] + 2 * (1 - t) * t * c[1] + t * t * B[1], math.sqrt(a_lat * R), i)
            if kinds[i]:
                stop_idx.append(((start + len(xs) - 1) // 2, kinds[i], p))
        if self.loop:
            xs.append(xs[0])
            zs.append(zs[0])
            vmax.append(vmax[0])
            cid.append(cid[0])
        self.x, self.z, self.vmax = xs, zs, vmax
        S = [0.0]
        for i in range(1, len(xs)):
            S.append(S[-1] + math.hypot(xs[i] - xs[i - 1], zs[i] - zs[i - 1]))
        self.S, self.L = S, S[-1]
        self.stops = [(S[i], kind, p) for i, kind, p in stop_idx]
        self.lim = []                                   # 구간 i (점 i→i+1) 제한 속도 m/s: 도로·구역·곡선
        for i in range(len(xs) - 1):
            mid = ((xs[i] + xs[i + 1]) / 2, (zs[i] + zs[i + 1]) / 2)
            curve = cid[i] is not None and cid[i] == cid[i + 1]
            self.lim.append(min(world.speed_at(mid) / 3.6, vmax[i] if curve else 99.0))
        # 신호 교차로 진입점·횡단보도 통과점 (1 m 간격으로 미리 계산).
        # 순환 경로는 교차로 한가운데서 시작할 수 있으므로 교차로·횡단보도 밖의 점에서부터 한 바퀴 훑는다
        B = world.lane_w + 3.0
        sigs, cws = world.map.get("signals", []), world.map.get("crosswalks", [])

        def in_box(x, z, sig):
            return abs(x - sig["pos"][0]) <= B and abs(z - sig["pos"][1]) <= B

        def near_cw(x, z, cw):
            return math.hypot(x - cw["pos"][0], z - cw["pos"][1]) < world.lane_w + 1

        s0 = 0.0
        if self.loop:
            while s0 < self.L:
                x, z, _, _ = self.at(s0)
                if not any(in_box(x, z, g) for g in sigs) and not any(near_cw(x, z, c) for c in cws):
                    break
                s0 += 1.0
        end = s0 + self.L + 1
        self.signals, self.cross = [], []
        for sig in sigs:
            inside, entry = None, None
            s = s0
            while s < end:
                x, z, hx, hz = self.at(s)
                ins = in_box(x, z, sig)
                if ins and inside is False:
                    dirkey = ("E" if hx > 0 else "W") if abs(hx) > abs(hz) else ("S" if hz > 0 else "N")
                    entry = (self.norm(s), sig, "x" if abs(hx) > abs(hz) else "z", dirkey)
                elif not ins and inside and entry:
                    self.signals.append(entry + (self.norm(s),))   # (진입 s, 신호, 축, 진입 방향, 빠져나가는 s)
                    entry = None
                inside = ins
                s += 1.0
        for cw in cws:
            best, bs = None, 0.0
            s = s0
            while s < end:
                x, z, _, _ = self.at(s)
                d = math.hypot(x - cw["pos"][0], z - cw["pos"][1])
                if d < world.lane_w + 1:
                    if best is None or d < best:
                        best, bs = d, self.norm(s)
                elif best is not None:
                    self.cross.append(self._cross(bs, cw, world))
                    best = None
                s += 1.0
            if best is not None:
                self.cross.append(self._cross(bs, cw, world))

    def _cross(self, s, cw, world):
        """(통과 지점 s, 횡단보도, 보행자 이동축에서 내 차로 중심의 위치)"""
        x, z, _, _ = self.at(s)
        return s, cw, (z - cw["pos"][1]) if world.cw_axis[cw["id"]] == "x" else (x - cw["pos"][0])

    def norm(self, s):
        return s % self.L if self.loop else min(max(s, 0.0), self.L)

    def index(self, s):
        i = bisect.bisect_right(self.S, self.norm(s)) - 1
        return min(max(i, 0), len(self.S) - 2)

    def at(self, s):
        s = self.norm(s)
        i = self.index(s)
        seg = self.S[i + 1] - self.S[i]
        t = (s - self.S[i]) / seg if seg > 1e-9 else 0.0
        hx, hz = unit(self.x[i + 1] - self.x[i], self.z[i + 1] - self.z[i])
        return self.x[i] + (self.x[i + 1] - self.x[i]) * t, self.z[i] + (self.z[i + 1] - self.z[i]) * t, hx, hz

    def ahead(self, target, s):
        """현재 s에서 target까지 앞쪽 거리"""
        return (target - self.norm(s)) % self.L if self.loop else target - s

    def ahead_signed(self, target, s):
        """ahead와 같지만 순환 경로에서 이미 지나친 지점은 음수 (반 바퀴 기준)"""
        d = self.ahead(target, s)
        return d - self.L if self.loop and d > self.L / 2 else d
