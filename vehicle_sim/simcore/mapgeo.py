"""맵: 불러오기·검사, 배치(주차장 칸·교차로·건물·나무·언덕), 34개 유스케이스 조건 검사.

world.py와 화면(serve.py → web/)이 같은 배치를 쓰도록 배치는 맵 이름으로 시드를 고정해 항상 같게 만든다.
"""

import json
import math
import random
import zlib

from common import DEFAULT_CONFIG, MAPS, USECASES


def load_map(name="default"):
    p = MAPS / f"{name}.json"
    if not p.exists():
        p = MAPS / "default.json"
    return json.loads(p.read_text())


def list_maps():
    return sorted(p.stem for p in MAPS.glob("*.json"))


def validate_map(m):
    """불러온 맵이 시뮬레이터가 쓰는 필드를 모두 갖췄는지 확인 (문제 목록 반환)"""
    need = ["size", "roads", "cells", "zones", "places", "routes", "vehicle_routes"]
    errs = [f"'{k}' 없음" for k in need if k not in m]
    for rid in m.get("vehicle_routes", []):
        if rid not in m.get("routes", {}):
            errs.append(f"vehicle_routes의 '{rid}' 경로가 routes에 없음")
    for c in m.get("cells", []):
        if not {"id", "pos", "r"} <= set(c):
            errs.append(f"셀 정의에 id/pos/r 필요: {c}")
    return errs


# ------------------------------------------------------------------ 맵 배치: 주차장·교차로·건물·나무 (world.py와 화면이 같은 값을 쓴다)
CAR_L, CAR_W = 4.6, 1.9          # 차량 크기 (m)
SIDEWALK = 3.0                   # 보도 폭 (m)
LOT_KINDS = ("home", "work", "gas", "service", "depot")
SLOT_W, SLOT_D = 2.8, 5.6        # 주차 칸


def seg_dist(p, a, b):
    ax, az = a[:2]
    bx, bz = b[:2]
    dx, dz = bx - ax, bz - az
    L2 = dx * dx + dz * dz
    t = 0 if L2 == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - az) * dz) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (az + t * dz))


def road_segments(m):
    return [(rd, tuple(a[:2]), tuple(b[:2])) for rd in m["roads"] for a, b in zip(rd["pts"], rd["pts"][1:])]


def road_dist(m, p, segs=None):
    return min(seg_dist(p, a, b) for _, a, b in (segs or road_segments(m)))


def _seg_x(a, b, c, d):
    """두 선분의 교점 (끝점 포함). 평행이면 None"""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if -1e-6 <= t <= 1 + 1e-6 and -1e-6 <= u <= 1 + 1e-6:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def junctions(m):
    """서로 다른 도로가 만나는 점과 갈래 방향들"""
    segs = road_segments(m)
    pts = []
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if segs[i][0] is segs[j][0]:
                continue
            x = _seg_x(segs[i][1], segs[i][2], segs[j][1], segs[j][2])
            if x and not any(math.hypot(x[0] - q[0], x[1] - q[1]) < 5 for q in pts):
                pts.append(x)
    out = []
    for p in pts:
        arms = []
        for _, a, b in segs:
            if seg_dist(p, a, b) > 1:
                continue
            for e in (a, b):
                d = math.hypot(e[0] - p[0], e[1] - p[1])
                if d > 1:
                    u = ((e[0] - p[0]) / d, (e[1] - p[1]) / d)
                    if not any(u[0] * v[0] + u[1] * v[1] > 0.99 for v in arms):
                        arms.append(u)
        out.append({"pos": [round(p[0], 2), round(p[1], 2)], "arms": [[round(u[0], 4), round(u[1], 4)] for u in arms]})
    return out


def _rect_hits(r, rects, pad=0.0):
    return any(r[0] < q[2] + pad and r[2] > q[0] - pad and r[1] < q[3] + pad and r[3] > q[1] - pad for q in rects)


def _road_rects(m, extra):
    """도로(+보도) 띠를 축 정렬 사각형으로 (맵 도로는 모두 가로·세로)"""
    lw = float(m.get("lane_width", 3.5))
    h = lw + SIDEWALK + extra
    out = []
    for rd, a, b in road_segments(m):
        e = h + (16 if rd.get("track") else 0)           # 서킷은 양옆 모래 완충지대까지 비워 둔다
        out.append((min(a[0], b[0]) - e, min(a[1], b[1]) - e, max(a[0], b[0]) + e, max(a[1], b[1]) + e))
    return out


def _lots(m, segs):
    lw = float(m.get("lane_width", 3.5))
    lots, taken = {}, []
    roads = _road_rects(m, 0.5)
    for p in m["places"]:
        if p["kind"] not in LOT_KINDS:
            continue
        pos = p["pos"]
        _, a, b = min(segs, key=lambda s: seg_dist(pos, s[1], s[2]))
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        n0 = (-u[1], u[0])
        k = int(p.get("slots", 6))
        best = None
        for side in (1, -1):
            n = (n0[0] * side, n0[1] * side)
            dc = lw + SIDEWALK + 1.0 + SLOT_D / 2
            c = (pos[0] + n[0] * dc, pos[1] + n[1] * dc)
            hw = k * SLOT_W / 2
            xs = [c[0] + u[0] * sx * hw + n[0] * sz * SLOT_D / 2 for sx in (-1, 1) for sz in (-1, 1)]
            zs = [c[1] + u[1] * sx * hw + n[1] * sz * SLOT_D / 2 for sx in (-1, 1) for sz in (-1, 1)]
            rect = (min(xs), min(zs), max(xs), max(zs))
            room = road_dist(m, (pos[0] + n[0] * 45, pos[1] + n[1] * 45), segs)
            ok = not _rect_hits(rect, roads) and not _rect_hits(rect, taken, 2)
            score = (ok, room)
            if best is None or score > best[0]:
                best = (score, n, c, rect)
        _, n, c, rect = best
        taken.append(rect)
        head = math.atan2(n[1], n[0])
        slots = [[round(c[0] + u[0] * (j - (k - 1) / 2) * SLOT_W, 2), round(c[1] + u[1] * (j - (k - 1) / 2) * SLOT_W, 2),
                  round(head, 4)] for j in range(k)]
        lots[p["id"]] = {"place": p["id"], "kind": p["kind"], "center": [round(c[0], 2), round(c[1], 2)],
                         "u": [round(u[0], 4), round(u[1], 4)], "n": [round(n[0], 4), round(n[1], 4)],
                         "w": k * SLOT_W, "d": SLOT_D, "rect": [round(v, 2) for v in rect], "slots": slots}
    return lots


PLACE_BLDG = {"home": (46, 18, 24, "apartment"), "work": (40, 26, 48, "office"), "gas": (22, 12, 6, "canopy"),
              "service": (36, 20, 9, "garage"), "depot": (34, 18, 7, "shed"), "server": (40, 26, 14, "datacenter")}


def map_layout(m):
    """주차장 칸·교차로·건물·나무·언덕. 같은 맵이면 항상 같은 결과 (맵 이름으로 시드)"""
    rng = random.Random(zlib.crc32(m.get("name", "map").encode()))
    W, H = m["size"]
    segs = road_segments(m)
    lots = _lots(m, segs)
    roads = _road_rects(m, 2.0)
    block = [tuple(l["rect"]) for l in lots.values()] + [tuple(d["rect"]) for d in m.get("decor", [])]
    pb = []
    for p in m["places"]:
        spec = PLACE_BLDG.get(p["kind"])
        if not spec:
            continue
        w, d, h, kind = spec
        if p["id"] in lots:
            lot = lots[p["id"]]
            n, u, c = lot["n"], lot["u"], lot["center"]
            off = SLOT_D / 2 + 5 + d / 2
            cx, cz = c[0] + n[0] * off, c[1] + n[1] * off
            if kind == "canopy":
                cx, cz = c
            ww, dd = (w, d) if abs(u[0]) > abs(u[1]) else (d, w)
        else:
            cx, cz = p["pos"]
            ww, dd = w, d
        r = (cx - ww / 2, cz - dd / 2, cx + ww / 2, cz + dd / 2)
        pb.append({"x": round(cx, 1), "z": round(cz, 1), "w": ww, "d": dd, "h": h, "kind": kind, "place": p["id"]})
        if kind != "canopy":
            block.append(r)
    water = [tuple(w["rect"]) for w in m.get("water", [])]
    hills = [dict(h) for h in m.get("hills", [])]
    tunnels = [tuple(z["rect"]) for z in m["zones"] if z["kind"] == "tunnel"]
    cells = [(c["pos"][0] - 10, c["pos"][1] - 10, c["pos"][0] + 10, c["pos"][1] + 10) for c in m["cells"]]
    avoid = block + water + cells + [tuple(h["rect"]) for h in hills] + [(t[0] - 30, t[1] - 60, t[2] + 30, t[3] + 60) for t in tunnels]
    shadow = [tuple(z["rect"]) for z in m["zones"] if z["kind"] == "shadow"]

    blds = []

    def try_bld(x0, z0, x1, z1, h, kind):
        r = (x0, z0, x1, z1)
        if x0 < 0 or z0 < 0 or x1 > W or z1 > H:
            return False
        if _rect_hits(r, roads) or _rect_hits(r, avoid, 3) or _rect_hits(r, [b["r"] for b in blds], 4):
            return False
        blds.append({"r": r, "h": h, "kind": kind})
        return True

    for z in shadow:                                         # 빌딩 숲: 음영 구역 양쪽에 고층 건물
        for x in range(int(z[0]), int(z[2]) - 20, 34):
            for zz in range(int(z[1]) - 20, int(z[3]) + 10, 30):
                w, d = rng.uniform(20, 28), rng.uniform(18, 24)
                try_bld(x, zz, x + w, zz + d, rng.uniform(45, 95), "tower")
    SPEC = {"downtown": (36, (16, 28), (14, 26), (16, 55), "office"),
            "residential": (26, (10, 18), (9, 14), (6, 14), "house"),
            "industrial": (48, (24, 40), (18, 30), (8, 15), "warehouse")}
    trees = []
    for lu in m.get("landuse", []):
        x0, z0, x1, z1 = lu["rect"]
        dens = float(lu.get("density", 0.5))
        if lu["kind"] == "park":
            n = int((x1 - x0) * (z1 - z0) / 900 * dens)
            for _ in range(min(n, 900)):
                p = (rng.uniform(x0, x1), rng.uniform(z0, z1))
                if not _rect_hits((p[0] - 2, p[1] - 2, p[0] + 2, p[1] + 2), roads + avoid + [b["r"] for b in blds]):
                    trees.append([round(p[0], 1), round(p[1], 1), round(rng.uniform(0.8, 1.4), 2)])
            continue
        cell, wr, dr, hr, kind = SPEC.get(lu["kind"], SPEC["residential"])
        x = x0
        while x < x1 - cell * 0.5:
            zz = z0
            while zz < z1 - cell * 0.5:
                if rng.random() < dens:
                    w, d = rng.uniform(*wr), rng.uniform(*dr)
                    h = rng.uniform(*hr)
                    k = kind
                    if lu["kind"] == "residential" and rng.random() < 0.25:
                        w, d, h, k = min(cell * 1.6, w * 2.2), d, rng.uniform(22, 42), "apartment"
                    ox, oz = rng.uniform(0, max(0, cell - w)), rng.uniform(0, max(0, cell - d))
                    try_bld(x + ox, zz + oz, x + ox + w, zz + oz + d, h, k)
                elif lu["kind"] == "residential" and rng.random() < 0.5:
                    trees.append([round(x + cell / 2, 1), round(zz + cell / 2, 1), round(rng.uniform(0.7, 1.2), 2)])
                zz += cell
            x += cell
    # 가로수: 보도 바깥쪽, 교차로·주차장·횡단보도 근처 제외
    lw = float(m.get("lane_width", 3.5))
    jpos = [j["pos"] for j in junctions(m)] + [c["pos"] for c in m.get("crosswalks", [])] + \
        [s["pos"] for s in m.get("signals", [])]
    for _, a, b in segs:
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 1:
            continue
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
        n = (-u[1], u[0])
        s = 12.0
        while s < L - 12:
            for side in (1, -1):
                p = (a[0] + u[0] * s + n[0] * side * (lw + SIDEWALK - 0.6), a[1] + u[1] * s + n[1] * side * (lw + SIDEWALK - 0.6))
                if any(math.hypot(p[0] - q[0], p[1] - q[1]) < 22 for q in jpos):
                    continue
                if _rect_hits((p[0] - 1, p[1] - 1, p[0] + 1, p[1] + 1), avoid + tunnels, 2):
                    continue
                if road_dist(m, p, segs) < lw + SIDEWALK - 1.0:
                    continue
                trees.append([round(p[0], 1), round(p[1], 1), round(rng.uniform(0.7, 1.0), 2)])
            s += 20.0
    rng.shuffle(trees)
    return {"lots": lots, "junctions": junctions(m), "place_buildings": pb,
            "buildings": [[round(b["r"][0], 1), round(b["r"][1], 1), round(b["r"][2], 1), round(b["r"][3], 1),
                           round(b["h"], 1), b["kind"]] for b in blds],
            "trees": trees[:3200], "hills": hills, "decor": m.get("decor", [])}


# ------------------------------------------------------------------ 맵 조건 검사: 34개 유스케이스를 이 맵에서 일으킬 수 있는가
def _route_samples(m, step=8.0):
    """경로를 따라 (x, z, 도로 제한 속도, 경로 id) 표본"""
    segs = road_segments(m)
    out = []
    for rid, r in m["routes"].items():
        pts = r["pts"]
        for a, b in zip(pts, pts[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            for k in range(max(1, int(L / step))):
                t = k * step / max(L, 1e-9)
                p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                rd = min(segs, key=lambda s: seg_dist(p, s[1], s[2]))[0]
                out.append((p[0], p[1], rd["speed"], rid))
    return out


def _in_zone(z, p):
    if "rect" in z:
        r = z["rect"]
        return r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3]
    c = z["circle"]
    return math.hypot(p[0] - c[0], p[1] - c[1]) <= c[2]


def map_coverage(m, cfg=None):
    """[{id, ok, how}] — 맵에서 각 유스케이스를 일으킬 장소·구역이 경로 위에 있는지. 설정으로 일으키는 것은 '설정'"""
    cfg = cfg or DEFAULT_CONFIG
    S = _route_samples(m)
    zones = lambda kind: [z for z in m["zones"] if z["kind"] == kind]
    on = lambda kind: [p for p in S if any(_in_zone(z, p) for z in zones(kind))]
    stops = {}
    for rid, r in m["routes"].items():
        for p in r["pts"]:
            if len(p) > 2:
                stops.setdefault(p[2], set()).add(rid)

    def q(p):
        best = 0.0
        for c in m["cells"]:
            d = math.hypot(p[0] - c["pos"][0], p[1] - c["pos"][1])
            if d <= c["r"]:
                best = max(best, 1 - d / c["r"])
        return best
    tun = on("tunnel")
    open_s = [p for p in S if p not in tun]
    qual = [q(p) for p in open_s]
    out_cov = sum(1 for v in qual if v == 0)
    edge = sum(1 for v in qual if 0 < v < float(cfg["net"]["edge_quality"]))
    cells_seen = {max(m["cells"], key=lambda c: (1 - math.hypot(p[0] - c["pos"][0], p[1] - c["pos"][1]) / c["r"]))["id"]
                  for p in open_s if q(p) > 0}
    fast = [p for p in S if p[2] >= float(cfg["net"]["doppler_kmh"])]
    bx = m.get("region_border_x")
    cross = 0
    if bx is not None:
        for r in m["routes"].values():
            for a, b in zip(r["pts"], r["pts"][1:]):
                if (a[0] - bx) * (b[0] - bx) < 0 and not any(_in_zone(z, (bx, a[1])) for z in zones("tunnel")):
                    cross += 1
    near = lambda pts, d: [p for p in S if any(math.hypot(p[0] - c[0], p[1] - c[1]) < d for c in pts)]
    cw = near([c["pos"] for c in m.get("crosswalks", [])], 20)
    sig = near([s["pos"] for s in m.get("signals", [])], 20)
    wifi_place = near([p["pos"] for p in m["places"] if p.get("wifi")], 60)
    com = [r for r in m["routes"].values() if r.get("kind") == "commute"]
    com_ok = any({p[2] for p in r["pts"] if len(p) > 2} >= {"home", "work"} for r in com)
    res = {
        "1-2": ("service" in stops, "서비스센터 정차 (OTA)"),
        "1-4": (bool(cw or sig), f"경로 위 횡단보도·신호 표본 {len(cw) + len(sig)}"),
        "1-5": (bool({"home", "work", "depot"} & set(stops)), "집·직장·차고지 주차 (시동 꺼짐)"),
        "2-1": (out_cov > 0 or len(cells_seen) >= 2, f"셀 밖 표본 {out_cov}, 지나는 셀 {len(cells_seen)}개(핸드오버)"),
        "2-2": (bool(fast), f"{cfg['net']['doppler_kmh']} km/h 이상 도로 표본 {len(fast)}"),
        "2-4": (cross > 0, f"권역 경계(x={bx}) 통과 {cross}곳"),
        "2-5": (bool(tun), f"터널 표본 {len(tun)}"),
        "3-2": (bool({"gas", "service"} & set(stops)), "충전소·정비 대기 정차"),
        "3-3": (bool(on("wifi") or wifi_place), "Wi-Fi 구역·장소"),
        "4-2": (len(m["cells"]) >= 1, f"기지국 {len(m['cells'])}개"),
        "4-4": (bool(on("weather")), f"강우 구역 표본 {len(on('weather'))}"),
        "4-5": (bool(cw or sig), "긴급제동(보행자·신호·끼어들기)"),
        "4-8": (out_cov > 0 or bool(tun), "배포 시점에 범위 밖·터널"),
        "5-1": (bool(tun or on("shadow")), f"터널·음영 표본 {len(tun) + len(on('shadow'))}"),
        "5-2": (edge > 0, f"셀 가장자리(품질<{cfg['net']['edge_quality']}) 표본 {edge}"),
        "7-2": (out_cov + edge > 0, "통신 품질이 다른 구간"),
        "7-3": (com_ok, "통근 경로에 집·직장 정차 (하루 시계)"),
        "1-3": ("gas" in stops, "충전소 (방전 후 회복)"),
        "2-6": ("gas" in stops, "충전소 (방전 후 회복)"),
        "3-1": ("gas" in stops, "충전소 (에너지 회복)"),
    }
    out = []
    for uid, *_ in USECASES:
        ok, how = res.get(uid, (True, "설정·버튼으로 발생 (맵과 무관)"))
        out.append({"id": uid, "ok": bool(ok), "how": how})
    return out


def map_problems(m):
    """경로가 도로 위에 있는지, 정차 지점에 장소가 있는지, 3갈래 이상 교차로에 신호가 있는지"""
    errs = validate_map(m)
    if errs:
        return errs
    segs = road_segments(m)
    for rid, r in m["routes"].items():
        for a, b in zip(r["pts"], r["pts"][1:]):
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if road_dist(m, a, segs) > 1 or road_dist(m, b, segs) > 1 or road_dist(m, mid, segs) > 1:
                errs.append(f"경로 {rid}의 {a[:2]}→{b[:2]} 구간이 도로 위에 없음")
        for p in r["pts"]:
            if len(p) > 2 and not any(pl["kind"] == p[2] and math.hypot(pl["pos"][0] - p[0], pl["pos"][1] - p[1]) < 5
                                      for pl in m["places"]):
                errs.append(f"경로 {rid}의 정차 {p} 위치에 '{p[2]}' 장소가 없음")
    for j in junctions(m):
        if len(j["arms"]) >= 3 and not any(math.hypot(s["pos"][0] - j["pos"][0], s["pos"][1] - j["pos"][1]) < 8
                                           for s in m.get("signals", [])):
            errs.append(f"{len(j['arms'])}갈래 교차로 {j['pos']}에 신호 없음")
    return errs
