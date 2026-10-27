"""차량 연합학습 장애 시뮬레이터 — 공용 정의 (패턴·유스케이스, 학습 방식, 차량 종류, 설정 기본값, 맵 불러오기, 파일 입출력).

프로세스 구성 (모두 같은 실행 폴더 RUN_DIR을 공유):
  world.py      차량 주행(2차선·신호·보행자·긴급제동)과 셀·터널·음영 등 통신 환경을 0.1초마다 계산 → world.json
  fl_entry.py   실제 FL(torchrun) 실행. 차량(클라이언트)은 world.json을 보고 학습·전송·끊김을 결정
                → client_<id>.json, server.json, events.jsonl
  serve.py      위 파일들을 화면(web/)에 내보내고, 설정 변경·시작/정지·저장/불러오기를 받는다 → config.json
맵 형식·배치·유스케이스 조건 검사는 mapgeo.py.
SASAFL 원본 파일(methods/SASAFL/*)은 수정하지 않는다. 동작은 fl/sim_sasafl.py의 서브클래스로 끼워 넣는다.
"""

import json
import os
import time
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
              "charge_s": [30, 60], "speed_scale": 1.0, "signal_scale": 1.0, "pedestrian_scale": 1.0,
              "walkers": 40, "jaywalk_per_min": 0.3, "npc_cars": 16},
    "server": {"pause_s": 60, "p7_window": 12, "p7_ratio": 1.4},
    "vehicle_default": {"vtype": None, "ecu_factor": None, "crash_prob": 0.02,
                        "emergency_rate": 1.0, "adas_base_s": 2.0, "adas_per_10kmh_s": 1.0, "adas_slowdown": 1.5,
                        "safety_preempt_prob": 0.3,
                        "store_forward": False, "retransmit": True, "wifi_only": False, "energy_gate": True,
                        "battery_scale": 1.0, "min_data": 32, "data_rate_per_s": 5, "data_mult": None,
                        "lr_override": None, "backdoor_boost": 0.0, "sensor_fault_classes": "", "sensor_fault_level": 0.0,
                        "leave": False, "aeb": True},
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
