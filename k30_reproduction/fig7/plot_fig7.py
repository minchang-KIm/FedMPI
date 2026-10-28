#!/usr/bin/env python3
"""논문 Fig. 7 (K=30)과 같은 형식의 그림에 SAFA를 더해 그린다.

그림 4장 (SASAFL 제안 기법 ON/OFF × SAFA 저장소 구현/수정판):
  fig7_SASAFL-ON_SAFA-repo.png, fig7_SASAFL-ON_SAFA-fixed.png, fig7_SASAFL-OFF_SAFA-repo.png, fig7_SASAFL-OFF_SAFA-fixed.png
각 그림: (a) MNIST with K=30, (c) FashionMNIST with K=30. BSA 초록, SASAFL 빨강, SAFA 파랑, C=0.1/0.3/0.5 = 실선/점선/파선.
곡선은 완료·진행 중 회차의 라운드별 평균이고, 논문처럼 5라운드마다 표시한다.

--watch: 결과(rounds.csv)가 바뀔 때마다(=라운드가 끝날 때마다) 다시 그린다. 그림은 임시 파일에 그린 뒤 교체한다.
"""
import argparse
import csv
import json
import os
import sys
import time
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec  # noqa: E402

plt.rcParams.update({
    "font.family": ["Liberation Serif"], "axes.unicode_minus": False, "font.size": 15, "legend.fontsize": 10.5,
    "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "white", "savefig.facecolor": "white",
})
GREEN, RED, BLUE = "#00a650", "#ff0000", "#0070c0"
C_STYLE = {0.1: "-", 0.3: ":", 0.5: "--"}
EVERY = 5
FIGS = (
    ("fig7_SASAFL-ON_SAFA-repo.png", "SASAFL_ON", "SAFA"),
    ("fig7_SASAFL-ON_SAFA-fixed.png", "SASAFL_ON", "SAFAfix"),
    ("fig7_SASAFL-OFF_SAFA-repo.png", "SASAFL_OFF", "SAFA"),
    ("fig7_SASAFL-OFF_SAFA-fixed.png", "SASAFL_OFF", "SAFAfix"),
)


def read_curve(run_dir):
    f = run_dir / "rounds.csv"
    if not f.exists():
        return {}
    out = {}
    try:
        for r in csv.DictReader(f.open()):
            if r.get("acc"):
                out[int(r["round"])] = float(r["acc"])
    except (OSError, ValueError, csv.Error):
        return {}
    return out


def mean_curves():
    """(variant, dataset, C) -> (rounds, mean acc, 회차 수). 시도가 여러 번이면 가장 최근 폴더(이름 그대로)만 쓴다."""
    groups = {}
    for s in spec.queue():
        curve = read_curve(spec.RUNS / s["name"])
        if curve:
            groups.setdefault((s["variant"], s["dataset"], s["C"]), []).append(curve)
    out = {}
    for key, curves in groups.items():
        rounds = sorted(set().union(*curves))
        acc = np.array([np.mean([c[r] for c in curves if r in c]) for r in rounds])
        out[key] = (np.array(rounds), acc, len(curves))
    return out


def draw(ax, curves, ds, sasafl, safa, inset):
    for label, variant, color in (("BSA", "BSA", GREEN), ("SASAFL", sasafl, RED), ("SAFA", safa, BLUE)):
        for c in spec.CS:
            item = curves.get((variant, ds, c))
            if item is None:
                ax.plot([], [], color=color, ls=C_STYLE[c], lw=1.6, label=f"{label}, C={c}")
                continue
            x, y, _ = item
            keep = x % EVERY == 0
            ax.plot(x[keep], y[keep], color=color, ls=C_STYLE[c], lw=1.6, label=f"{label}, C={c}")
    ax.set_xlim(0, spec.ROUNDS)
    ax.set_ylim(0, 100)
    ax.set_xticks(range(0, spec.ROUNDS + 1, 100))
    ax.set_yticks(range(0, 101, 20))
    ax.set_xlabel("Rounds (#)")
    ax.set_ylabel("Global model accuracy (%)")
    ax.grid(color="#dddddd")
    handles, labels = ax.get_legend_handles_labels()
    order = [r * 3 + c for c in range(3) for r in range(3)]   # 행 우선(논문처럼 방법별 한 줄)
    ax.legend([handles[i] for i in order], [labels[i] for i in order], loc="lower center", bbox_to_anchor=(0.5, 1.0),
              ncol=3, frameon=False, handlelength=2.5, columnspacing=1.0, handletextpad=0.5)
    if inset:
        ins = ax.inset_axes([0.55, 0.12, 0.4, 0.38])
        for variant, color in (("BSA", GREEN), (sasafl, RED), (safa, BLUE)):
            for c in spec.CS:
                item = curves.get((variant, ds, c))
                if item is None:
                    continue
                x, y, _ = item
                keep = (x % EVERY == 0) & (x >= 450)
                ins.plot(x[keep], y[keep], color=color, ls=C_STYLE[c], lw=1.2)
        ins.set_xlim(450, 500)
        ins.set_ylim(80, 100)
        ins.set_xticks([450, 500])
        ins.set_yticks([80, 100])
        ins.tick_params(labelsize=9)
        ax.indicate_inset_zoom(ins, edgecolor="black")


def render(curves):
    for fname, sasafl, safa in FIGS:
        fig, axes = plt.subplots(1, 2, figsize=(15, 5.6))
        draw(axes[0], curves, "MNIST", sasafl, safa, inset=True)
        draw(axes[1], curves, "FashionMNIST", sasafl, safa, inset=False)
        for ax, cap in zip(axes, ("(a) MNIST with K=30", "(c) FashionMNIST with K=30")):
            ax.text(0.5, -0.24, cap, transform=ax.transAxes, ha="center", fontsize=18)
        fig.tight_layout()
        out = spec.OUT / fname
        tmp = out.with_name(out.stem + ".tmp.png")
        fig.savefig(tmp, dpi=200)
        plt.close(fig)
        os.replace(tmp, out)
    status = {f"{v} {d} C={c}": n for (v, d, c), (_, _, n) in sorted(curves.items())}
    (spec.OUT / "figure_status.json").write_text(json.dumps(
        {"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "reps_per_curve": status}, indent=1, ensure_ascii=False))


def signature():
    sig = []
    for s in spec.queue():
        f = spec.RUNS / s["name"] / "rounds.csv"
        if f.exists():
            st = f.stat()
            sig.append((s["name"], st.st_mtime_ns, st.st_size))
    return tuple(sig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--watch", action="store_true")
    args = p.parse_args()
    spec.OUT.mkdir(parents=True, exist_ok=True)
    if not args.watch:
        render(mean_curves())
        return
    last = None
    while True:
        try:
            sig = signature()
            if sig != last:
                render(mean_curves())
                last = sig
        except Exception:   # 그림 하나 실패로 감시가 멈추지 않게 한다
            traceback.print_exc()
        time.sleep(3)


if __name__ == "__main__":
    main()
