#!/usr/bin/env python3
"""공식 논문 표의 수치로 'SAFA vs 최신 기법'과 '지표 16(동기 FL 대비 상대 정확도)' 근거 그림을 만든다.

수치 출처 (모두 논문 원문 표에서 그대로 옮김):
  - FLUDE (Wang et al., arXiv 2412.19991) Table 1: AsyncFedED, SAFA, FedSEA, Oort, FLUDE
  - FedASMU (Liu et al., AAAI 2024, arXiv 2312.05770) Table 1·2: FedASMU와 FedAvg의 수렴 정확도
  - SASAFL (Yu et al., JPDC 2024) Fig.2 본문: 반비동기 91.6%, 동기보다 6%p 낮음 → 약 94%
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

for f in ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"):
    font_manager.fontManager.addfont(f)
plt.rcParams.update({"font.family": ["NanumGothic"], "axes.spines.top": False, "axes.spines.right": False,
                     "font.size": 11, "axes.unicode_minus": False})
INK2, GRID = "#52514e", "#e1e0d9"
SAFA_C, OTHER, BEST, SAS = "#eb6834", "#c3c2b7", "#2a78d6", "#d03b3b"

METHODS = ["AsyncFedED", "SAFA", "FedSEA", "Oort", "FLUDE"]
ACC = {"CIFAR-10": [82.68, 83.57, 85.67, 86.41, 87.52], "CIFAR-100": [67.61, 67.97, 69.92, 72.02, 73.31],
       "Google Speech": [78.55, 79.19, 82.14, 81.21, 82.44], "Avazu(AUC)": [80.03, 79.57, 81.83, 81.05, 83.38]}
TTA = {"CIFAR-10": [8.12, 7.23, 4.41, 3.57, 2.68], "CIFAR-100": [22.53, 19.29, 18.15, 12.93, 9.39],
       "Google Speech": [5.47, 5.04, 3.07, 2.25, 1.37], "Avazu(AUC)": [3.18, 3.51, 2.57, 3.12, 2.13]}
TASKS = ["LeNet·C10", "CNN·C10", "CNN·C100", "ResNet·C100", "ResNet·Tiny", "AlexNet·C10", "AlexNet·C100", "VGG·C10",
         "TextCNN·IMDb", "LeNet·FMNIST"]
ASMU = [0.486, 0.603, 0.277, 0.358, 0.171, 0.490, 0.246, 0.653, 0.882, 0.829]
FAVG = [0.431, 0.551, 0.243, 0.299, 0.146, 0.432, 0.205, 0.508, 0.874, 0.706]


def main():
    fig, axes = plt.subplots(1, 3, figsize=(20, 6.6), gridspec_kw={"width_ratios": [1.2, 1.2, 1.6]})
    w = 0.16
    for ax, data, ylabel in ((axes[0], ACC, "최종 정확도 / AUC (%)"), (axes[1], TTA, "목표 도달 시간 (FLUDE = 1, 낮을수록 좋음)")):
        for i, m in enumerate(METHODS):
            col = SAFA_C if m == "SAFA" else (BEST if m == "FLUDE" else OTHER)
            xs = [k + (i - 2) * w for k in range(4)]
            if data is ACC:
                ax.bar(xs, [data[d][i] - 60 for d in data], w * 0.9, bottom=60, color=col, label=m, edgecolor="white", linewidth=1.5)
            else:
                ax.bar(xs, [data[d][i] / data[d][4] for d in data], w * 0.9, color=col, label=m, edgecolor="white", linewidth=1.5)
        ax.set_xticks(range(4))
        ax.set_xticklabels(list(data))
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", color=GRID)
        ax.legend(ncol=5, fontsize=9, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.08))
    axes[0].set_ylim(60, 90)
    gaps = [ACC[d][1] - ACC[d][4] for d in ACC]
    for k, (d, g) in enumerate(zip(ACC, gaps)):
        axes[0].text(k - w, ACC[d][1] + 0.4, f"{g:+.1f}", ha="center", fontsize=9, color=SAFA_C)
    axes[1].axhline(1, color=INK2, lw=1, ls="--")
    slow = [TTA[d][1] / TTA[d][4] for d in TTA]
    for k, s in enumerate(slow):
        axes[1].text(k - w, s + 0.05, f"{s:.1f}×", ha="center", fontsize=9, color=SAFA_C)
    axes[0].set_title(f"(a) 최종 정확도 — SAFA는 최신 기법(FLUDE)보다 {-max(gaps):.1f}~{-min(gaps):.1f}%p 낮음\n"
                      "출처: FLUDE (arXiv 2412.19991) Table 1, 같은 testbed(Jetson 80대+폰 40대)", loc="left", fontsize=11.5)
    axes[1].set_title(f"(b) 목표 정확도 도달 시간 — SAFA는 {min(slow):.1f}~{max(slow):.1f}배 느림\n출처: 같은 표",
                      loc="left", fontsize=11.5)

    ax = axes[2]
    ratio = [100 * a / f for a, f in zip(ASMU, FAVG)]
    xs = list(range(len(TASKS)))
    ax.bar(xs, ratio, 0.6, color=BEST, edgecolor="white", label="FedASMU ÷ FedAvg (FedASMU 논문 Table 1·2)")
    ax.bar([len(TASKS) + 0.6], [94.0], 0.6, color=SAS, edgecolor="white",
           label="SASAFL 논문 Fig.2: 반비동기(BSA) ÷ 동기, 같은 500라운드")
    for x, r in zip(xs + [len(TASKS) + 0.6], ratio + [94.0]):
        ax.text(x, r + 1, f"{r:.1f}", ha="center", fontsize=8.5)
    for y, lab in ((100, "2차 100%"), (110, "3차 110%"), (120, "4차 120%")):
        ax.axhline(y, color=INK2, lw=1, ls=":")
        ax.text(len(TASKS) + 1.15, y + 1.2, lab, va="bottom", fontsize=9, color=INK2)
    ax.set_xticks(xs + [len(TASKS) + 0.6])
    ax.set_xticklabels(TASKS + ["SASAFL 측"], rotation=35, ha="right", fontsize=9)
    ax.set_xlim(-0.6, len(TASKS) + 1.9)
    ax.set_ylim(80, 135)
    ax.set_ylabel("동기 FL(FedAvg) 대비 상대 정확도 (%)")
    ax.grid(axis="y", color=GRID)
    ax.legend(fontsize=9, frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.22), ncol=1)
    ax.set_title("(c) 지표 16 기준 — 표의 SOTA 117.4% = FedASMU LeNet·FMNIST (0.829÷0.706)\n"
                 "출처: FedASMU (AAAI 2024) Table 1·2 (VGG·C100은 270%로 축 밖이라 생략)", loc="left", fontsize=11.5)
    fig.tight_layout()
    fig.savefig("sota_vs_safa_evidence.png", dpi=200)
    print("[+] sota_vs_safa_evidence.png")


if __name__ == "__main__":
    main()
