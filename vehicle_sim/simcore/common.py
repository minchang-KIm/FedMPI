"""차량 연합학습 장애 시뮬레이터 — 공용 정의 (패턴·유스케이스, 학습 방식, 차량 종류, 설정 기본값, 맵 불러오기, 파일 입출력).

프로세스 구성 (모두 같은 실행 폴더 RUN_DIR을 공유):
  world.py      차량 주행(2차선·신호·보행자·긴급제동)과 셀·터널·음영 등 통신 환경을 0.1초마다 계산 → world.json
  fl_entry.py   실제 FL(torchrun) 실행. 차량(클라이언트)은 world.json을 보고 학습·전송·끊김을 결정
                → client_<id>.json, server.json, events.jsonl
  serve.py      위 파일들을 화면(web/)에 내보내고, 설정 변경·시작/정지·저장/불러오기를 받는다 → config.json
SASAFL 원본 파일(methods/SASAFL/*)은 수정하지 않는다. 동작은 fl/sim_sasafl.py의 서브클래스로 끼워 넣는다.
"""

import json
import math
import os
import random
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # vehicle_sim/
REPO = ROOT.parent                                    # 저장소 루트
MAPS = ROOT / "maps"
SAVES = ROOT / "saves"
RUNS = ROOT / "runs"


# ------------------------------------------------------------------ 파일 입출력
def write_json(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False))
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def emit(run_dir, kind, vid=None, example=None, msg="", **extra):
    """events.jsonl에 사건 한 줄을 추가한다. example은 유스케이스 id(예: '2-5')."""
    ev = {"t": round(time.time(), 3), "kind": kind, "vid": vid, "example": example, "msg": msg}
    if example:
        ev["pattern"] = int(example.split("-")[0])
    ev.update(extra)
    with open(Path(run_dir) / "events.jsonl", "a") as f:   # 작은 한 줄 append는 프로세스 간에도 섞이지 않는다
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


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


# ------------------------------------------------------------------ 8개 패턴 / 34개 유스케이스 (서버가 받은 모습 기준)
PATTERNS = {1: "값을 전달받지 못함", 2: "전송 중 끊김", 3: "해당 라운드 미참여", 4: "늦게 도착(stale)",
            5: "모아서 한꺼번에 전송", 6: "오류 값 지속 전송", 7: "빠른 클라이언트 편중", 8: "서버·글로벌 모델 문제"}
# (id, 예시, 근거, 맵·설정에서)
USECASES = [
    ("1-1", "계산 도중 돌발 중단 (업데이트의 약 2%)", "FeLiX(Google 운영 FL)", "차량 설정: 계산 중단 확률"),
    ("1-2", "OTA 설치 및 재부팅 (31–101초)", "Bhattacharjee 외 2023", "서비스센터 OTA"),
    ("1-3", "학습 중 배터리 방전", "FedQoS (예산 1000 J)", "에너지 기준 확인 끈 차량"),
    ("1-4", "우선순위 자원 선점 → FL 종료", "가정", "긴급제동(보행자·신호) + 선점 확률"),
    ("1-5", "시동 꺼짐", "Bonawitz 외 2019 유사 사례", "집·주차장"),
    ("2-1", "기지국 범위 이탈 (체류 5초 미만 28%)", "VEFL", "셀 사이 범위 밖·핸드오버"),
    ("2-2", "고속 주행 도플러 (60–100 km/h)", "VR-VFL", "고속도로 + 도플러 실패 확률"),
    ("2-3", "무선 패킷 오류", "Salehi·Hossain 2021", "조각당 패킷 오류 확률"),
    ("2-4", "지역 간 망 불안정", "NVIDIA FLARE 운영", "권역 경계 통과"),
    ("2-5", "터널 진입 (1 km @80 km/h ≈ 45초)", "계산", "고속도로 터널"),
    ("2-6", "전송 중 배터리 방전", "Bhattacharjee 외 유사 사례", "에너지 0에서 업로드"),
    ("3-1", "잔여 배터리 부족 → 회복 후 복귀", "FedQoS 학습 게이트", "에너지 기준"),
    ("3-2", "새 데이터 없음 (충전 중·시동 켠 채 장시간 정차)", "FedQoS 학습 게이트", "충전소·정비 대기"),
    ("3-3", "비과금망 조건 미충족 (Wi-Fi에서만 참여)", "Bonawitz 외 2019", "차량 설정: Wi-Fi에서만"),
    ("4-1", "하드웨어 성능 차이 (최대 약 2.2배)", "VEFL·FeLiX", "구형 EV"),
    ("4-2", "기지국 혼잡 (동시 전송 시 지연)", "Bhattacharjee 외", "셀 동시 업로드 수"),
    ("4-3", "재전송 대기", "NVIDIA FLARE ReliableMessage", "재전송 제한 시간"),
    ("4-4", "업로드 대역폭 부족 (55.7 / 70.9 Mbps)", "FedQoS", "대역폭·강우 구역"),
    ("4-5", "우선순위 자원 선점 → 지연", "가정", "긴급제동 연산 점유"),
    ("4-6", "데이터 양 차이 (학습 2–120초)", "FeLiX(FedBuff 인용)", "운행이 긴 택시 = 데이터 배수 큼"),
    ("4-7", "송신 순서 대기 (TDMA, G−1라운드)", "Song·Hong 2024", "TDMA 그룹 수"),
    ("4-8", "새 모델 수신 실패 → 이전 버전으로 학습", "Huang 외 2023", "배포 시점에 범위 밖"),
    ("5-1", "수신 영역 밖 학습 후 일괄 송신", "Gilbert 1960 모형", "터널·음영 + 보관 후 전송"),
    ("5-2", "전송 보류 후 일괄 전송 (보류 85.3%)", "FedQoS 전송 게이트", "셀 가장자리 + 보관 후 전송"),
    ("5-3", "서버 복구 후 일괄 전송", "패턴 8과 연결", "서버 장애 버튼"),
    ("6-1", "악의적 조작 (지속·대량)", "Bagdasaryan 외 2020", "차량 설정: 업데이트 증폭"),
    ("6-2", "센서 고장 (특정 데이터 오염)", "Wu 외 2023·Huang 외 2023", "차량 설정: 고장 라벨"),
    ("6-3", "학습 설정 오류 (학습률)", "Huang 외 2023", "차량 설정: 학습률"),
    ("7-1", "최신 EV와 구형 EV 혼재", "SAFA(CFCFM)", "신형 EV 참여 비중 감시"),
    ("7-2", "통신 상태 편중", "Salehi·Hossain 2021", "통신 품질 좋은 차량 비중 감시"),
    ("7-3", "운행 시간대 편중", "FeLiX (최대 5배 변동)", "하루 시계: 통근 차량은 출퇴근 시간에만 운행"),
    ("8-1", "집계 서버 장애 → 복구", "Dispersed FL·FailBench", "버튼: 서버 장애(일시 중단)"),
    ("8-2", "무한 대기 (quota를 못 채움)", "연구실 SASAFL 재현·FedBuff", "보낼 수 있는 차량 < quota"),
    ("8-3", "글로벌 성능 지속 감소 → lag tolerance 강제 갱신", "SAFA·SASAFL", "새 모델 거부가 이어진 차량"),
]
assert len(USECASES) == 34

# ------------------------------------------------------------------ 학습 방식 (같은 하네스에서 기능만 켜고 끈다 → ablation)
METHODS = {
    "SASAFL": {"name": "SASAFL (현재 코드 + optimizer 수정)", "adaptive_quota": True, "decay": True,
               "mid_swap": True, "epoch_reduce": True, "quota": "C"},
    "SASAFL_orig": {"name": "SASAFL 원저자 코드 (quota 고정)", "adaptive_quota": False, "decay": True,
                    "mid_swap": True, "epoch_reduce": True, "quota": "C"},
    "BSA": {"name": "BSA (SemiAsync: 버퍼·감쇄만)", "adaptive_quota": False, "decay": True,
            "mid_swap": False, "epoch_reduce": False, "quota": "C"},
    "FedAsync": {"name": "FedAsync (도착 즉시 반영)", "adaptive_quota": False, "decay": True,
                 "mid_swap": False, "epoch_reduce": False, "quota": "one"},
    "Sync": {"name": "동기식 (K대 모두 기다림)", "adaptive_quota": False, "decay": False,
             "mid_swap": False, "epoch_reduce": False, "quota": "all"},
}

# ------------------------------------------------------------------ 차량 종류 (연산 성능)
VTYPES = {"new": {"name": "신형 EV", "ecu": 1.0, "desc": "고성능 연산 장치"},
          "old": {"name": "구형 EV", "ecu": 2.2, "desc": "저성능 연산 장치 (VEFL 최대 약 2.2배)"}}

# ------------------------------------------------------------------ 설정 (화면에서 바꿈)
DEFAULT_CONFIG = {
    "fl": {"K": 8, "dataset": "MNIST", "C": 0.3, "tau": 9, "epochs": 1, "lr": 0.01, "batch": 32,
           "split": "gaussian", "alpha": 0.1, "rejoin": True, "method": "SASAFL", "seed": 42},
    "net": {"bandwidth_mbps": 55.7, "payload_mb": 30, "fragments": 10, "frag_fail": 0.01, "doppler_kmh": 60, "doppler_fail": 0.15,
            "cell_capacity": 2, "tdma_groups": 1, "tdma_slot_s": 2.0, "retx_timeout_s": 5.0, "retx_total_s": 20.0,
            "gilbert_p": 0.85, "gilbert_q": 0.7, "region_instability": 0.3, "handover_drops": True,
            "weather_bw_mult": 0.5, "edge_quality": 0.15},
    "energy": {"budget_j": 1000, "round_j_min": 20, "round_j_max": 30, "min_energy_j": 100,
               "charge_rate_jps": 40, "upload_j": 10},
    "world": {"map": "default", "day_minutes": 30, "start_hour": 6.8, "weather_on": True, "visitor_gap_mean_s": 60,
              "home_park_min": [20, 90], "ota_prob": 0.4, "ota_s": [31, 101], "service_wait_s": [30, 60],
              "charge_s": [30, 60], "speed_scale": 1.0, "signal_scale": 1.0, "pedestrian_scale": 1.0},
    "server": {"pause_s": 60, "p7_window": 12, "p7_ratio": 1.4},
    "vehicle_default": {"vtype": None, "ecu_factor": None, "crash_prob": 0.02,
                        "emergency_rate": 1.0, "adas_base_s": 2.0, "adas_per_10kmh_s": 1.0, "adas_slowdown": 1.5,
                        "safety_preempt_prob": 0.3,
                        "store_forward": False, "retransmit": True, "wifi_only": False, "energy_gate": True,
                        "battery_scale": 1.0, "min_data": 32, "data_rate_per_s": 5, "data_mult": None,
                        "lr_override": None, "backdoor_boost": 0.0, "sensor_fault_classes": "", "sensor_fault_level": 0.0,
                        "leave": False},
    "vehicles": {},
}


def merged_vehicle(cfg, vid):
    v = dict(cfg.get("vehicle_default", {}))
    v.update(cfg.get("vehicles", {}).get(str(vid), {}))
    if not v.get("vtype"):
        v["vtype"] = "new" if int(vid) % 2 == 1 else "old"       # 기본: 홀수 신형 · 짝수 구형
    if not v.get("ecu_factor"):
        v["ecu_factor"] = VTYPES[v["vtype"]]["ecu"]
    return v


def method_of(cfg):
    m = cfg.get("fl", {}).get("method", "SASAFL")
    return m, METHODS.get(m, METHODS["SASAFL"])


def new_run_dir(tag=""):
    d = RUNS / (time.strftime("%Y%m%d_%H%M%S") + (f"_{tag}" if tag else ""))
    d.mkdir(parents=True, exist_ok=True)
    (d / "events.jsonl").touch()
    cur = RUNS / "current"
    if cur.is_symlink() or cur.exists():
        cur.unlink()
    cur.symlink_to(d.name)
    return d


# ------------------------------------------------------------------ 하루 시계 (7-3 운행 시간대)
PERIODS = [("night", "야간", 0, 7), ("am", "출근", 7, 9.5), ("day", "주간", 9.5, 17), ("pm", "퇴근", 17, 19.5),
           ("evening", "저녁", 19.5, 23), ("night", "야간", 23, 24)]
PERIOD_NAMES = {"am": "출근", "day": "주간", "pm": "퇴근", "evening": "저녁", "night": "야간"}


def period_of(h):
    h %= 24
    for key, name, a, b in PERIODS:
        if a <= h < b:
            return key, name
    return "night", "야간"


def fmt_hour(h):
    h %= 24
    return f"{int(h):02d}:{int(round((h % 1) * 60)) % 60:02d}"


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
    for _, a, b in road_segments(m):
        out.append((min(a[0], b[0]) - h, min(a[1], b[1]) - h, max(a[0], b[0]) + h, max(a[1], b[1]) + h))
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
    block = [tuple(l["rect"]) for l in lots.values()]
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
            "trees": trees[:2600], "hills": hills}


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
