#!/usr/bin/env python3
"""논문 Table 2(MNIST, K=30)와 재현 결과를 같은 형식의 비교표로 만든다.

지표 정의 (논문 5.1절):
  Accuracy          : 학습 중 최고 test accuracy (%)
  Round-to-accuracy : 목표 정확도(MNIST 95%)에 처음 도달한 라운드
  Time-to-accuracy  : 서버 setup 시작(로그 첫 SERVER 줄)부터 목표 도달까지 경과 시간 (분)
입력: runs/T2_MNIST_{BSA,SASAFL}_C{c}_<mode>_cats<...>/  (가장 최근 실행)
출력: table2_comparison.md, table2_comparison.png
"""

import csv
import json
import re
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

HERE = Path(__file__).resolve().parent
import os
RUNS = Path(os.environ.get("K30_RUNS", HERE / "runs"))
TARGET = 95.0
RATIOS = [0.1, 0.3, 0.5]

# 논문 Table 2, MNIST, K=30
PAPER = {
    0.1: {"BSA": (93.78, None, None), "SASAFL": (98.23, 116, 53.86)},
    0.3: {"BSA": (97.14, 211, 101.44), "SASAFL": (98.07, 132, 66.71)},
    0.5: {"BSA": (98.27, 96, 60.98), "SASAFL": (98.24, 131, 88.77)},
}

TS_RE = re.compile(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\] SERVER >>")


def latest_run(method_tag, ratio):
    cands = sorted(RUNS.glob(f"T2_MNIST_{method_tag}_C{ratio}_*"), key=lambda p: p.stat().st_mtime)
    cands = [c for c in cands if "_old_" not in c.name and (c / "rounds.csv").exists()]
    return cands[-1] if cands else None


def measure(run_dir):
    if run_dir is None:
        return None
    rows = list(csv.DictReader((run_dir / "rounds.csv").open()))
    result = json.loads((run_dir / "result.json").read_text()) if (run_dir / "result.json").exists() else {}
    config = json.loads((run_dir / "config.json").read_text())
    start = None
    for line in (run_dir / "run.log").open(errors="replace"):
        m = TS_RE.search(line)
        if m:
            start = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f")
            break
    accs = [(int(r["round"]), float(r["acc"]), r["ts"]) for r in rows if r["acc"]]
    accs = [a for a in accs if a[0] >= 1]   # 0번째(초기 모델) 평가는 제외
    if not accs:
        return {"acc": None, "rta": None, "tta": None, "rounds": 0, "requested": config.get("rounds"),
                "outcome": result.get("outcome", "running"), "dir": run_dir.name}
    best = max(a[1] for a in accs)
    hit = next((a for a in accs if a[1] >= TARGET), None)
    tta = None
    if hit and start:
        tta = (datetime.strptime(hit[2], "%Y-%m-%d %H:%M:%S.%f") - start).total_seconds() / 60
    return {"acc": best, "rta": hit[0] if hit else None, "tta": tta,
            "rounds": max(a[0] for a in accs), "requested": config.get("rounds"),
            "outcome": result.get("outcome", "running"), "dir": run_dir.name,
            "mode": config.get("mode"), "cats": config.get("cats")}


def fmt(v, digits=2):
    if v is None:
        return "-"
    return f"{v:,.{digits}f}" if isinstance(v, float) else f"{v:,}"


def better(a, b, higher):
    """쌍(BSA, SASAFL) 중 더 좋은 쪽 인덱스. 한쪽만 값이 있으면 그쪽."""
    if a is None and b is None:
        return None
    if a is None:
        return 1
    if b is None:
        return 0
    if a == b:
        return None
    return (0 if a > b else 1) if higher else (0 if a < b else 1)


def build():
    ours = {c: {"BSA": measure(latest_run("BSA", c)), "SASAFL": measure(latest_run("SASAFL", c))} for c in RATIOS}
    metrics = [("Accuracy", 0, True, 2), ("Round-to-accuracy", 1, False, 0), ("Time-to-accuracy", 2, False, 2)]

    # 표 데이터: 행마다 [라벨, 논문BSA, 논문SASAFL, 재현BSA, 재현SASAFL] + 굵게 표시할 칸
    table = []
    notes = []
    for c in RATIOS:
        table.append(("C", f"{c}", None))
        for label, idx, higher, digits in metrics:
            p_b, p_s = PAPER[c]["BSA"][idx], PAPER[c]["SASAFL"][idx]
            o_b = ours[c]["BSA"]
            o_s = ours[c]["SASAFL"]
            key = ["acc", "rta", "tta"][idx]
            r_b = o_b[key] if o_b else None
            r_s = o_s[key] if o_s else None
            if idx == 1:
                r_b = r_b if r_b is None else int(r_b)
                r_s = r_s if r_s is None else int(r_s)
            cells = [fmt(p_b, digits) if idx != 1 else fmt(p_b), fmt(p_s, digits) if idx != 1 else fmt(p_s),
                     fmt(r_b, digits) if idx != 1 else fmt(r_b), fmt(r_s, digits) if idx != 1 else fmt(r_s)]
            bold = set()
            w = better(p_b, p_s, higher)
            if w is not None:
                bold.add(w)
            w = better(r_b, r_s, higher)
            if w is not None:
                bold.add(2 + w)
            table.append((label, cells, bold))
        for tag in ("BSA", "SASAFL"):
            o = ours[c][tag]
            if o is None:
                notes.append(f"C={c} {tag}: 미실행")
            elif o["outcome"] != "completed" or (o["requested"] and o["rounds"] < o["requested"]):
                notes.append(f"C={c} {tag}: {o['rounds']}/{o['requested']}라운드 ({o['outcome']}) — 부분 결과")
    configs = sorted({(o.get("mode"), o.get("cats")) for c in RATIOS for o in ours[c].values() if o})
    setup = {"mode": " / ".join(m for m, _ in configs), "cats": " / ".join(k for _, k in configs)} if configs else None
    if len(configs) > 1:
        notes.append("실행마다 노드·카테고리 구성이 다름: " + ", ".join(f"{m} 노드 {k}" for m, k in configs))
    return table, notes, setup


def write_md(table, notes, setup):
    lines = ["# Table 2 비교 — MNIST, K=30 (논문 vs 재현)", ""]
    if setup:
        lines.append(f"재현 구성: {setup.get('mode')} 노드, CPU 카테고리 {setup.get('cats')}, 1회 실행 "
                     f"(논문은 10회 평균). 목표 정확도 {TARGET:.0f}%. 굵게 = 각 쌍에서 더 좋은 값.")
    lines += ["", "| | 논문 BSA | 논문 SASAFL | 재현 BSA | 재현 SASAFL |", "|---|---:|---:|---:|---:|"]
    for label, cells, bold in table:
        if label == "C":
            lines.append(f"| **C = {cells}** | | | | |")
            continue
        out = [f"**{v}**" if i in bold else v for i, v in enumerate(cells)]
        lines.append(f"| {label} | " + " | ".join(out) + " |")
    lines += ["", "- Accuracy: 최고 test 정확도(%), Round-to-accuracy: 95% 첫 도달 라운드, "
              "Time-to-accuracy: 서버 setup 시작부터 95% 도달까지(분). `-` = 도달 못 함 또는 미실행."]
    if notes:
        lines += ["", "**주의**"] + [f"- {n}" for n in notes]
    (HERE / "table2_comparison.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def write_png(table, notes, setup):
    font_manager.fontManager.addfont("/usr/share/fonts/truetype/nanum/NanumGothic.ttf")
    font_manager.fontManager.addfont("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf")
    plt.rcParams.update({"font.family": "NanumGothic", "figure.facecolor": "white"})
    n_rows = len(table) + 2
    fig, ax = plt.subplots(figsize=(10.5, 0.42 * n_rows + 2.0))
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, n_rows + 1.5)
    xs = [0.2, 3.9, 5.4, 7.2, 8.7]
    y = n_rows + 0.9
    ax.text(0.2, y + 0.35, "Table 2 비교 — MNIST, K=30 (논문 vs 재현)", fontsize=15, fontweight="bold")
    sub = (f"재현: {setup.get('mode')} 노드, 카테고리 {setup.get('cats')}, 1회 · 논문: 10회 평균 · 목표 정확도 95%"
           if setup else "재현 실행 없음")
    ax.text(0.2, y - 0.25, sub, fontsize=10.5, color="#52514e")
    y -= 0.8
    ax.hlines(y, 0.1, 9.9, color="black", lw=1.4)
    y -= 0.45
    ax.text(0.2, y, "Dataset: MNIST", fontsize=12)
    ax.text((xs[1] + xs[2]) / 2 + 0.5, y, "논문 (Yu et al., 2024)", ha="center", fontsize=12)
    ax.text((xs[3] + xs[4]) / 2 + 0.5, y, "재현 (본 실험)", ha="center", fontsize=12)
    ax.hlines(y - 0.25, xs[1] - 0.2, xs[2] + 1.1, color="black", lw=0.8)
    ax.hlines(y - 0.25, xs[3] - 0.2, xs[4] + 1.1, color="black", lw=0.8)
    y -= 0.6
    ax.text(0.2, y, "Method", fontsize=12)
    for x, head in zip(xs[1:], ["BSA", "SASAFL", "BSA", "SASAFL"]):
        ax.text(x + 1.0, y, head, ha="right", fontsize=12)
    y -= 0.3
    ax.hlines(y, 0.1, 9.9, color="black", lw=0.8)
    for label, cells, bold in table:
        y -= 0.45
        if label == "C":
            ax.text(0.2, y, "C", fontsize=12)
            ax.text(xs[1] + 0.05, y, cells, fontsize=12)
            y -= 0.22
            ax.hlines(y, 0.1, 9.9, color="black", lw=0.6)
            continue
        ax.text(0.2, y, label, fontsize=12)
        for i, v in enumerate(cells):
            ax.text(xs[i + 1] + 1.0, y, v, ha="right", fontsize=12, fontweight="bold" if i in bold else "normal")
        if label == "Time-to-accuracy":
            y -= 0.22
            ax.hlines(y, 0.1, 9.9, color="black", lw=1.4 if (label, cells) == (table[-1][0], table[-1][1]) else 0.8)
    for k, note in enumerate(notes):
        y -= 0.42 if k else 0.6
        ax.text(0.2, y, ("주의: " if k == 0 else "         ") + note, fontsize=9.5, color="#d03b3b")
    ax.set_ylim(y - 0.6, n_rows + 1.5)
    fig.set_size_inches(10.5, 0.52 * (n_rows + 1.5 - (y - 0.6)) + 0.2)
    fig.savefig(HERE / "table2_comparison.png", dpi=200, bbox_inches="tight")
    print(f"[+] {HERE / 'table2_comparison.png'}")


if __name__ == "__main__":
    t, n, s = build()
    write_md(t, n, s)
    write_png(t, n, s)
