"""Fig. 7 (K=30) + SAFA 실험 목록. 실행기(run_fig7.py)와 그림(plot_fig7.py)이 함께 쓴다.

논문 5.1절 조건: K=30, CPU 카테고리 1·2·3·4·8코어 × 6명, C ∈ {0.1, 0.3, 0.5}, lr MNIST 0.01 / FashionMNIST 0.001,
batch 32, local epoch 5 (최소 E/2), lag tolerance τ=9 (SAFA는 논문대로 5), ζ=0.9, non-IID(gaussian), 500라운드, 10회 반복.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
K30 = HERE.parent
REPO = K30.parent
OUT = K30 / "experiments" / "F7_fig7_safa"
RUNS = OUT / "runs"

K = 30
CATS = "1,2,3,4,8"
ROUNDS = 500
REPS = 10
CS = (0.1, 0.3, 0.5)
DATASETS = (("MNIST", 0.01), ("FashionMNIST", 0.001))
SASAFL_OFF_SRC = "k30_reproduction/original_code/SASAFL_c0b819b.py"   # 저장소 기준 상대 경로 (두 노드 공통)

# 이름, Start.py --method, lag tolerance, SASAFL.py 교체 파일
METHODS = (
    ("BSA", "SemiAsync", 9, None),
    ("SASAFL_ON", "SASAFL", 9, None),             # 제안 기법(참여 수 조정) 동작: 현재 SASAFL.py (f8fd198)
    ("SASAFL_OFF", "SASAFL", 9, SASAFL_OFF_SRC),  # 제안 기법 꺼짐: 원저자 마지막 SASAFL.py (c0b819b, quota=C·K 고정)
    ("SAFA", "SAFA", 5, None),                    # 저장소 구현 (집계 가중치 정규화 버그만 수정, methods/SAFA/SAFAServer.py)
)


def run_name(ds, method, c, rep):
    short = {"MNIST": "MNIST", "FashionMNIST": "FMNIST"}[ds]
    return f"F7_{short}_{method}_C{c}_rep{rep}"


def queue():
    """회차 단위 순서: 1회차 24개 전부 → 2회차 → …"""
    out = []
    for rep in range(1, REPS + 1):
        for ds, lr in DATASETS:
            for c in CS:
                for method, start_method, tau, src in METHODS:
                    out.append({
                        "name": run_name(ds, method, c, rep), "rep": rep, "variant": method,
                        "method": start_method, "C": c, "K": K, "dataset": ds, "lr": lr, "batch": 32, "epochs": 5,
                        "tau": tau, "sasafl_src": src, "rounds": ROUNDS, "target": 1.0, "mode": "two", "cats": CATS,
                    })
    return out
