#!/usr/bin/env python3
"""논문 Fig. 7 (K=30)과 같은 형식의 그림에 SAFA를 더해 그린다.

그림 2장 (SASAFL 제안 기법 ON / OFF) + 논문 원본(왼쪽)과 나란히 붙인 compare_*.png:
  fig7_SASAFL-ON.png, fig7_SASAFL-OFF.png
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
FIGS = (   # 그림마다 BSA, SASAFL(ON 또는 OFF), SAFA를 함께 그린다
    ("fig7_SASAFL-ON.png", "SASAFL_ON"),
    ("fig7_SASAFL-OFF.png", "SASAFL_OFF"),
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


def lines_for(sasafl):
    return (("BSA", "BSA", GREEN), ("SASAFL", sasafl, RED), ("SAFA", "SAFA", BLUE))


def draw(ax, curves, ds, sasafl, inset):
    for label, variant, color in lines_for(sasafl):
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
    rows = len(handles) // 3
    order = [r * 3 + c for c in range(3) for r in range(rows)]   # 행 우선(논문처럼 방법별 한 줄)
    ax.legend([handles[i] for i in order], [labels[i] for i in order], loc="lower center", bbox_to_anchor=(0.5, 1.0),
              ncol=3, frameon=False, handlelength=2.5, columnspacing=1.0, handletextpad=0.5)
    if inset:
        ins = ax.inset_axes([0.55, 0.12, 0.4, 0.38])
        for _, variant, color in lines_for(sasafl):
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
    for fname, sasafl in FIGS:
        fig, axes = plt.subplots(1, 2, figsize=(15, 5.6))
        draw(axes[0], curves, "MNIST", sasafl, inset=True)
        draw(axes[1], curves, "FashionMNIST", sasafl, inset=False)
        for ax, cap in zip(axes, ("(a) MNIST with K=30", "(c) FashionMNIST with K=30")):
            ax.text(0.5, -0.27, cap, transform=ax.transAxes, ha="center", fontsize=18)
        fig.tight_layout()
        out = spec.OUT / fname
        tmp = out.with_name(out.stem + ".tmp.png")
        fig.savefig(tmp, dpi=200)
        plt.close(fig)
        os.replace(tmp, out)
    render_compare(curves)
    build_commands_md()
    status = {f"{v} {d} C={c}": n for (v, d, c), (_, _, n) in sorted(curves.items())}
    (spec.OUT / "figure_status.json").write_text(json.dumps(
        {"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "reps_per_curve": status}, indent=1, ensure_ascii=False))


PAPER_FIG7 = spec.K30 / "paper_figures" / "paper_fig7.jpg"


def render_compare(curves):
    """왼쪽: 논문 Fig. 7의 K=30 열((a), (c)), 오른쪽: 재현을 같은 세로 배치로. compare_fig7_*.png"""
    from PIL import Image
    paper = Image.open(PAPER_FIG7).convert("RGB")
    paper = paper.crop((0, 0, paper.width // 2 + 3, paper.height))   # 왼쪽 열 = K=30
    for fname, sasafl in FIGS:
        fig, axes = plt.subplots(2, 1, figsize=(7.6, 11.4))
        draw(axes[0], curves, "MNIST", sasafl, inset=True)
        draw(axes[1], curves, "FashionMNIST", sasafl, inset=False)
        for ax, cap in zip(axes, ("(a) MNIST with K=30", "(c) FashionMNIST with K=30")):
            ax.text(0.5, -0.32, cap, transform=ax.transAxes, ha="center", fontsize=18)
        fig.tight_layout(h_pad=3)
        tmp = spec.OUT / ("_ours_" + fname)
        fig.savefig(tmp, dpi=200)
        plt.close(fig)
        ours = Image.open(tmp).convert("RGB")
        tmp.unlink()
        h = ours.height
        left = paper.resize((int(paper.width * h / paper.height), h))
        canvas = Image.new("RGB", (left.width + ours.width + 60, h + 40), "white")
        canvas.paste(left, (20, 20))
        canvas.paste(ours, (left.width + 40, 20))
        out = spec.OUT / ("compare_" + fname)
        tmp2 = out.with_name(out.stem + ".tmp.png")
        canvas.save(tmp2)
        os.replace(tmp2, out)


def build_commands_md():
    """실행마다 두 노드(175, 176)에서 실제로 실행한 명령을 COMMANDS.md로 정리한다 (cmd.txt·config.json 기준)."""
    lines = [
        "# Fig. 7 (K=30) + SAFA 실험 명령 (wise-175 · wise-176)", "",
        "이 파일은 그림 감시 프로세스가 `runs/*/cmd.txt`와 `config.json`에서 자동으로 다시 만든다.", "",
        "## 공통 준비", "",
        "wise-176 코드를 175와 같은 커밋으로 맞춘다 (실행기는 매 실행 전에 두 노드의 git HEAD 일치·코드 무수정·터보 꺼짐을 확인한다):", "",
        "```bash", "# wise-175", "cd /home/wise-175/Mando/FedMPI && git push origin main",
        "# wise-176", "cd /home/wise-176/Mando/FedMPI && git fetch origin main && git checkout -f -B main origin/main", "```", "",
        "실험 전체 시작/재개 (wise-175에서만 실행. 176 쪽 프로세스는 launch.sh가 ssh로 띄운다):", "",
        "```bash", "# wise-175", "bash /home/wise-175/Mando/FedMPI/k30_reproduction/fig7/start_fig7.sh   # tmux 세션 fig7",
        "#   내부: python -u k30_reproduction/fig7/run_fig7.py  → 실행마다 아래 launch.sh 호출", "```", "",
    ]
    lines += (spec.HERE / "commands_top.md").read_text().splitlines() + ["", "## 실행별 명령", ""]
    for s in spec.queue():
        d = spec.RUNS / s["name"]
        cmd = d / "cmd.txt"
        if not cmd.exists():
            continue
        try:
            cfg = json.loads((d / "config.json").read_text())
        except (OSError, ValueError):
            cfg = {}
        res = {}
        if (d / "result.json").exists():
            try:
                res = json.loads((d / "result.json").read_text())
            except ValueError:
                pass
        state = (f"{res.get('outcome')} {res.get('rounds_done')}라운드, {res.get('wall_min')}분" if res else "진행 중")
        text = cmd.read_text().splitlines()
        launch = next((l[len("# launch: "):] for l in text if l.startswith("# launch: ")), "")
        env = next((l[len("# env: "):] for l in text if l.startswith("# env: ")), "")
        cmds = [l for l in text if l and not l.startswith("#")]
        if cmds:
            import re
            port = re.search(r"--master_port=(\d+)", cmds[0])
            rid = re.search(r"--rdzv_id=(\S+)", cmds[0])
            env += f" SYNC_SOURCE=0 MASTER_PORT={port.group(1) if port else ''} RUN_ID={rid.group(1) if rid else ''}"
        lines += [f"### {s['name']}", "",
                  f"- 방법 {s['variant']} (`--method={s['method']}`), {s['dataset']}, C={s['C']}, lr={s['lr']}, τ={s['tau']}, "
                  f"시작 {cfg.get('start', '-')}, git `{str(cfg.get('git_head', '-'))[:7]}`, 상태: {state}", "",
                  "wise-175 (실행기가 호출한 launcher):", "", "```bash", f"{env} \\", f"  bash {launch}", "```", ""]
        if len(cmds) >= 2:
            lines += ["wise-175 (node_rank 0: 서버 + 클라이언트 15개, cwd /home/wise-175/Mando/FedMPI):", "",
                      "```bash", cmds[0], "```", "",
                      "wise-176 (node_rank 1: 클라이언트 15개, cwd /home/wise-176/Mando/FedMPI, launch.sh가 ssh로 실행):", "",
                      "```bash", cmds[1], "```", ""]
    lines += [""] + (spec.HERE / "commands_bottom.md").read_text().splitlines()
    out = spec.OUT / "COMMANDS.md"
    tmp = out.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, out)


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
