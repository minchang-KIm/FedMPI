"""Fig. 7 (K=30, + SAFA)과 Fig. 8 (CIFAR-10, K=30) 실험 목록. 실행기(run_fig7.py)와 그림(plot_fig7.py)이 함께 쓴다.

논문 5.1절 조건: K=30, CPU 카테고리 1·2·3·4·8코어 × 6명, C ∈ {0.1, 0.3, 0.5}, lr MNIST 0.01 / FashionMNIST 0.001,
batch 32, local epoch 5 (최소 E/2), lag tolerance τ=9 (SAFA는 논문대로 5), ζ=0.9, non-IID(gaussian), 500라운드, 10회 반복.
Fig.8: CIFAR-10, lr 0.001, 3000라운드, BSA·SASAFL, 나머지는 같음.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
K30 = HERE.parent
REPO = K30.parent

K = 30
CATS = "1,2,3,4,8"
REPS = 10
CS = (0.1, 0.3, 0.5)
ROUNDS = 500   # Fig.7 라운드 수 (Fig.8은 FIG8_ROUNDS)

# 이름, Start.py --method, lag tolerance
# SASAFL은 원저자 마지막 커밋(c0b819b) 코드 그대로다 (2026-10-28 사용자 지시: 제안 기법 수정 f8fd198 제거, optimizer 수정 없음).
# BSA는 BSA에만 있던 통신 지연 sleep만 뺐다 (SemiAsyncClient 주석). SAFA는 저자 구현에 맞춘 methods/SAFA.
FIG7_METHODS = (
    ("BSA", "SemiAsync", 9),
    ("SASAFL", "SASAFL", 9),
    ("SAFA", "SAFA", 5),
)
FIG8_METHODS = (   # 논문 Fig.8은 BSA와 SASAFL만 비교한다
    ("BSA", "SemiAsync", 9),
    ("SASAFL", "SASAFL", 9),
)
FIG7_DATASETS = (("MNIST", 0.01), ("FashionMNIST", 0.001))
FIG8_DATASET, FIG8_LR, FIG8_ROUNDS = "CIFAR10", 0.001, 3000

OUT = K30 / "experiments" / "F7_fig7_safa"
RUNS = OUT / "runs"
OUT8 = K30 / "experiments" / "F8_fig8_cifar10"
RUNS8 = OUT8 / "runs"
PROGRESS = OUT / "PROGRESS.md"   # Fig.7·Fig.8 실행기 공통 진행 기록


def run_name(ds, method, c, rep):
    short = {"MNIST": "MNIST", "FashionMNIST": "FMNIST", "CIFAR10": "CIFAR10"}[ds]
    fig = "F8" if ds == "CIFAR10" else "F7"
    return f"{fig}_{short}_{method}_C{c}_rep{rep}"


def _entry(fig, ds, lr, rounds, method, start_method, tau, c, rep):
    return {"name": run_name(ds, method, c, rep), "fig": fig, "runs_dir": str(RUNS if fig == 7 else RUNS8),
            "rep": rep, "variant": method, "method": start_method, "C": c, "K": K, "dataset": ds, "lr": lr,
            "batch": 32, "epochs": 5, "tau": tau, "rounds": rounds, "target": 1.0, "mode": "two", "cats": CATS}


def queue_fig7():
    """회차 단위 순서: 1회차(2 데이터셋 × 3 C × 3 방법 = 18개) → 2회차 → …"""
    return [_entry(7, ds, lr, ROUNDS, m, sm, tau, c, rep)
            for rep in range(1, REPS + 1) for ds, lr in FIG7_DATASETS for c in CS for m, sm, tau in FIG7_METHODS]


def queue_fig8():
    """회차 단위 순서: 1회차(3 C × 2 방법 = 6개) → 2회차 → …"""
    return [_entry(8, FIG8_DATASET, FIG8_LR, FIG8_ROUNDS, m, sm, tau, c, rep)
            for rep in range(1, REPS + 1) for c in CS for m, sm, tau in FIG8_METHODS]


def queue():
    """Fig.7 10회 전부 → Fig.8 10회 (사용자 지시 2026-10-28: Fig.7, Fig.8 순서로 반복 실험)"""
    return queue_fig7() + queue_fig8()
