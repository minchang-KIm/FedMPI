#!/usr/bin/env python3
"""crash_study 결과를 PPT용 그림(PNG)과 요약표(CSV/MD)로 만든다.

입력: results/<scenario>/{run.log, events.json, samples.csv, config.json}
      results/E3_code_level/*.json, results/E4_simulation/simulation_results.json
출력: figures/*.png, figures/summary_table.{csv,md}
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
from matplotlib.patches import FancyBboxPatch  # noqa: E402

STUDY = Path(__file__).resolve().parents[1]
RESULTS = STUDY / "results"
FIGS = STUDY / "figures"
FIGS.mkdir(exist_ok=True)

for font in ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
             "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"):
    font_manager.fontManager.addfont(font)

# 참조 팔레트 (dataviz skill, light mode)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
CRITICAL = "#d03b3b"
WARNING = "#fab219"
GOOD = "#0ca30c"

plt.rcParams.update({
    "font.family": "NanumGothic",
    "axes.unicode_minus": False,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK_2,
    "xtick.color": INK_2,
    "ytick.color": INK_2,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.titleweight": "bold",
    "axes.titlesize": 13,
    "axes.titlecolor": INK,
    "font.size": 11,
    "lines.linewidth": 2,
})

TS_RE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\] (.*)$")
ROUND_RE = re.compile(r"SERVER >> (\d+)번째 글로벌 모델")
QUOTA_RE = re.compile(r"SERVER >> 이번 라운드에서 (\d+)개의 로컬 모델을 사용합니다")
ACC_RE = re.compile(r"test_accuracy: ([\d.]+)%")
LOSS_RE = re.compile(r"test_loss: ([\d.]+)")

SCENARIO_LABEL = {
    "E0_baseline": "E0 장애 없음 (기준선)",
    "E1_hardcrash_1client": "E1 차량 1대 hard crash (SIGKILL)",
    "E1b_hardcrash_restart": "E1b hard crash + torchrun 재시작 허용",
    "E2a_silentdrop_1client": "E2a 차량 1대 silent drop (SIGSTOP)",
    "E2b_silentdrop_below_pmin": "E2b 생존 4대 < P_min 5 (SIGSTOP 6대)",
    "E2c_silentdrop_timeout90s": "E2c silent drop + gloo timeout 90초",
}


# 그림 1 패널별 해설 (로그에서 확인한 사실)
FIG1_NOTES = {
    "E1_hardcrash_1client": "서버가 dist.send 중 'Connection closed by peer'로\n먼저 사망 → torchrun이 나머지 10개 프로세스 SIGTERM",
    "E1b_hardcrash_restart": "재시작 후 라운드 0부터 다시 학습(상태 유실).\n24라운드 이후 정지: P_r=K=10인데 클라이언트 5·8이\n재시작 후 업로드하지 못함 (장애 주입과 무관한 정지)",
    "E2a_silentdrop_1client": "서버 메인 스레드가 멈춘 차량 1대에 대한\ndist.send(112행)에서 블록 → 나머지 9대도 정지",
    "E2b_silentdrop_below_pmin": "서버가 dist.send(114행)에서 먼저 블록.\n(이 testbed에선 통신 블록이 P_min 대기보다 먼저 발생)",
    "E2c_silentdrop_timeout90s": "장애 100초 후 서버 send가 timeout 예외로 사망\n→ torchrun이 전체 종료. timeout은 복구가 아님",
}


def save(fig, name):
    path = FIGS / name
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"[+] {path}")


def load_run(name):
    d = RESULTS / name
    if not (d / "run.log").exists() or not (d / "events.json").exists():
        return None
    events = json.loads((d / "events.json").read_text()) if (d / "events.json").exists() else []
    cfg = json.loads((d / "config.json").read_text())
    lines = (d / "run.log").read_text(errors="replace").splitlines()

    first_ts = None
    rounds, quotas = [], []
    pending_round = None
    for line in lines:
        m = TS_RE.match(line)
        if m:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f").timestamp()
            first_ts = first_ts or ts
            msg = m.group(2)
            rm = ROUND_RE.search(msg)
            if rm:
                pending_round = {"t_abs": ts, "round": int(rm.group(1))}
                rounds.append(pending_round)
                continue
            qm = QUOTA_RE.search(msg)
            if qm:
                quotas.append({"t_abs": ts, "quota": int(qm.group(1))})
        elif pending_round is not None:
            am, lm = ACC_RE.search(line), LOSS_RE.search(line)
            if am:
                pending_round["acc"] = float(am.group(1))
            if lm:
                pending_round["loss"] = float(lm.group(1))

    # 오케스트레이터 시작 시각(초 단위)을 로그 날짜에 붙여 절대시각으로 변환
    start_wall = next(e["wall"] for e in events if e["event"] == "start")
    day = datetime.fromtimestamp(first_ts).strftime("%Y-%m-%d")
    t0 = datetime.strptime(f"{day} {start_wall}", "%Y-%m-%d %H:%M:%S").timestamp()
    for r in rounds:
        r["t"] = r["t_abs"] - t0
    for q in quotas:
        q["t"] = q["t_abs"] - t0

    samples = []
    if (d / "samples.csv").exists():
        with (d / "samples.csv").open() as f:
            for row in csv.DictReader(f):
                samples.append({
                    "t": float(row["t"]),
                    "cpu": float(row["server_cpu_pct"]) if row["server_cpu_pct"] else None,
                    "state": row["server_state"],
                    "stopped": int(row["stopped_workers"]),
                    "restart": int(row["restart_count"]),
                    "round": int(row["last_round"]),
                })
    fault = next((e for e in events if e["event"] == "fault_injected"), None)
    end = next((e for e in events if e["event"] == "end"), None)
    return {"name": name, "cfg": cfg, "rounds": rounds, "quotas": quotas, "samples": samples,
            "fault": fault, "end": end, "lines": lines}


def stack_dump(run):
    """SIGUSR1로 받은 서버 스택에서 SASAFL 관련 프레임만 뽑는다."""
    lines = run["lines"]
    idx = [i for i, l in enumerate(lines) if l.startswith("Thread 0x") or l.startswith("Current thread 0x")]
    frames = []
    for i in idx:
        header = "main" if lines[i].startswith("Current") else "background"
        picked = []
        for l in lines[i + 1: i + 14]:
            if not l.startswith("  File"):
                break
            if "/methods/SASAFL/" in l or "distributed_c10d" in l:
                fname = l.split('"')[1].rsplit("/", 1)[-1]
                where = l.split('"')[-1].replace(", line", "").strip()
                picked.append(f"{fname} {where}")
            if len(picked) == 2:
                break
        if picked:
            frames.append((header, " ← ".join(picked)))
    return frames


def outcome_text(run):
    end = run["end"] or {}
    if end.get("type") == "exited":
        return "정상 종료" if end.get("returncode") == 0 else f"job 전체 비정상 종료 (exit {end.get('returncode')})"
    return "진행 정지 → 관측 종료 후 강제 종료"


# ---------------------------------------------------------------- 그림 1: 타임라인
def fig_timeline(runs):
    names = [n for n in SCENARIO_LABEL if runs.get(n)]
    fig, axes = plt.subplots(2, 3, figsize=(17, 9), sharey=True)
    for ax, name in zip(axes.flat, names):
        run = runs[name]
        rs = run["rounds"]
        # 재시작(E1b)으로 라운드가 0으로 돌아가는 지점에서 선을 끊는다
        segs, cur = [], []
        for r in rs:
            if cur and r["round"] < cur[-1]["round"]:
                segs.append(cur)
                cur = []
            cur.append(r)
        if cur:
            segs.append(cur)
        for k, seg in enumerate(segs):
            ax.step([r["t"] for r in seg], [r["round"] for r in seg], where="post",
                    color=SERIES[0] if k == 0 else SERIES[1], linewidth=2,
                    label="최초 실행" if k == 0 else f"재시작 {k}회차 (라운드 0부터)")
        if run["fault"]:
            ft = run["fault"]["t"]
            ax.axvline(ft, color=CRITICAL, linewidth=1.5, linestyle="--")
            sig = run["fault"]["signal"]
            ax.text(ft, 31.5, f" 장애 주입\n {'SIGKILL' if sig == 'KILL' else 'SIGSTOP'} "
                    f"rank {run['fault']['ranks'] if len(run['fault']['ranks']) < 3 else str(len(run['fault']['ranks'])) + '대'}",
                    color=CRITICAL, fontsize=9.5, va="top")
        end_t = run["end"]["t"] if run["end"] else (rs[-1]["t"] if rs else 0)
        ax.axvline(end_t, color=INK_2, linewidth=1, linestyle=":")
        last = rs[-1]["round"] if rs else 0
        if run["fault"] and run["end"] and run["end"].get("type") != "exited" and rs:
            ax.hlines(last, rs[-1]["t"], end_t, color=CRITICAL, linewidth=2, linestyle=(0, (2, 2)))
            ax.text((rs[-1]["t"] + end_t) / 2, last + 0.8, f"{end_t - rs[-1]['t']:.0f}초간 라운드 진행 0",
                    ha="center", color=CRITICAL, fontsize=10, fontweight="bold")
        ax.set_title(SCENARIO_LABEL[name], fontsize=12, loc="left", pad=24)
        ax.text(0.0, 1.02, "결과: " + outcome_text(run), transform=ax.transAxes, fontsize=10.5, va="bottom",
                color=GOOD if "정상 종료" == outcome_text(run) else CRITICAL, fontweight="bold")
        note = FIG1_NOTES.get(name)
        if note:
            ax.text(0.98, 0.04, note, transform=ax.transAxes, ha="right", va="bottom", fontsize=9, color=INK,
                    bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=AXIS))
        ax.set_xlabel("실험 시작 후 경과 시간 (초)")
        ax.set_ylim(-1, 32)
        if len(segs) > 1:
            ax.legend(loc="center right", fontsize=9, frameon=False)
    for ax in axes[:, 0]:
        ax.set_ylabel("완료된 글로벌 라운드")
    for ax in list(axes.flat)[len(names):]:
        ax.axis("off")
    fig.suptitle("SASAFL (torchrun + gloo, K=10) — 차량 연결 장애 주입 시 학습 진행", fontsize=16,
                 fontweight="bold", x=0.01, ha="left", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    save(fig, "fig1_fault_timeline.png")


# ---------------------------------------------------------------- 그림 2: 정지 중 서버 상태
def fig_server_state(runs):
    names = [n for n in ("E2a_silentdrop_1client", "E2b_silentdrop_below_pmin", "E2c_silentdrop_timeout90s",
                         "E1b_hardcrash_restart") if runs.get(n)]
    if not names:
        return
    fig, axes = plt.subplots(3, len(names), figsize=(5.4 * len(names), 9.5),
                             gridspec_kw={"height_ratios": [1, 1, 0.55]})
    for col, name in enumerate(names):
        run = runs[name]
        s = [x for x in run["samples"] if x["round"] >= 0]
        ax_r, ax_c, ax_t = axes[0][col], axes[1][col], axes[2][col]
        ax_r.step([x["t"] for x in s], [x["round"] for x in s], where="post", color=SERIES[0])
        ax_r.set_title(SCENARIO_LABEL[name], fontsize=11, loc="left")
        ax_r.set_ylabel("서버 라운드")
        cpu = [(x["t"], x["cpu"]) for x in s if x["cpu"] is not None]
        ax_c.plot([t for t, _ in cpu], [c for _, c in cpu], color=SERIES[1], linewidth=1.5)
        ax_c.set_ylabel("서버 프로세스 CPU (%)\n(100% = 코어 1개)")
        ax_c.set_xlabel("경과 시간 (초)")
        ax_c.set_ylim(-5, max(c for _, c in cpu) * 1.1 if cpu else 110)
        ax_c.set_xlim(ax_r.get_xlim())
        for ax in (ax_r, ax_c):
            if run["fault"]:
                ax.axvline(run["fault"]["t"], color=CRITICAL, linestyle="--", linewidth=1.3)
        ax_t.axis("off")
        dump = stack_dump(run)
        if dump:
            txt = "\n".join(f"[{h}] " + f.replace(" ← ", "\n      ← ") for h, f in dump)
            ax_t.text(0.0, 1.0, "관측 종료 시 서버 스택 (SIGUSR1 덤프)\n" + txt, transform=ax_t.transAxes,
                      va="top", fontsize=9, color=INK)
        elif run["end"] and run["end"].get("type") == "exited":
            ax_t.text(0.0, 1.0, "서버 프로세스 예외로 종료 → 스택 덤프 없음\n(run.log의 traceback 참고)",
                      transform=ax_t.transAxes, va="top", fontsize=9, color=INK)
    fig.suptitle("정지 구간의 서버 상태 — silent drop: send에서 블록(CPU 0%) / P_r 대기: busy-wait(CPU ≥100%)",
                 fontsize=14, fontweight="bold", x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    save(fig, "fig2_server_state_during_stall.png")


# ---------------------------------------------------------------- 그림 3: E0 실측 P_r
def fig_e0_quota(runs):
    run = runs.get("E0_baseline")
    if not run:
        return
    K = run["cfg"]["clients"]
    p_min = int(K * run["cfg"]["ratio"])
    quotas = [q["quota"] for q in run["quotas"]]
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(12, 7.5), sharex=True, gridspec_kw={"height_ratios": [1.3, 1]})
    xs = list(range(1, len(quotas) + 1))
    colors = [CRITICAL if q >= K else SERIES[0] for q in quotas]
    ax.bar(xs, quotas, color=colors, width=0.7, edgecolor=SURFACE, linewidth=2)
    ax.axhline(K, color=INK_2, linewidth=1.2, linestyle="--")
    ax.text(0.5, K + 0.15, f"K = {K} (전체 차량)", va="bottom", fontsize=10, color=INK_2)
    ax.axhline(p_min, color=INK_2, linewidth=1, linestyle=":")
    ax.text(0.5, p_min + 0.15, f"P_min = C·K = {p_min}", va="bottom", fontsize=10, color=INK_2)
    hits = [x for x, q in zip(xs, quotas) if q >= K]
    ax.set_ylabel("집계 quota P_r (필요 업로드 수)")
    ax.set_title(f"E0 실측: 장애가 없어도 P_r이 K에 도달 ({len(hits)}회, 라운드 {hits}) — "
                 "이 라운드에 차량 1대만 끊겨도 영구 대기", loc="left", fontsize=12)
    ax.set_ylim(0, K + 1.5)
    losses = [r.get("loss") for r in run["rounds"][1:len(quotas) + 1]]
    prev = [r.get("loss") for r in run["rounds"][:len(quotas)]]
    ax2.plot(xs, prev, color=SERIES[1], marker="o", markersize=5)
    ax2.set_ylabel("직전 global loss (P_r 결정 입력)")
    ax2.set_xlabel("라운드 (P_r이 적용되는 라운드)")
    ax2.set_title("global loss가 오르면 Eq.(1)에 따라 P_r 증가 — 연결 상태는 입력에 없음", loc="left", fontsize=12)
    fig.tight_layout()
    save(fig, "fig3_e0_measured_quota.png")
    return {"hits": hits, "quotas": quotas, "losses": losses}


# ---------------------------------------------------------------- 그림 4: 코드 수준 증명
def fig_code_level():
    t1 = json.loads((RESULTS / "E3_code_level" / "T1_wait_never_returns.json").read_text())
    t2 = json.loads((RESULTS / "E3_code_level" / "T2_quota_trace.json").read_text())
    trace = t2["trace"]
    fig, (ax, axt) = plt.subplots(1, 2, figsize=(16, 6), gridspec_kw={"width_ratios": [1.6, 1]})
    rs = [r["round"] for r in trace]
    ax.plot(rs, [r["P_next"] for r in trace], color=SERIES[1], marker="o", markersize=7,
            label="다음 라운드 P_r (SASAFL 코드가 계산)")
    ax.plot(rs, [r["connected"] for r in trace], color=SERIES[0], marker="s", markersize=7,
            label="연결된 차량 수 (가정: 라운드당 4대 이탈)")
    dead = [r for r in trace if r["P_next"] > r["connected"]]
    if dead:
        ax.axvspan(dead[0]["round"] - 0.5, rs[-1] + 0.5, color=CRITICAL, alpha=0.08)
        ax.text(dead[0]["round"] - 0.3, 104, "P_r > 연결 차량 → 버퍼가 영원히 안 참 (교착)", color=CRITICAL,
                fontsize=11, fontweight="bold")
    ax.axhline(100, color=INK_2, linestyle="--", linewidth=1)
    ax.set_ylim(0, 112)
    ax.set_xlabel("라운드")
    ax.set_ylabel("차량 수")
    ax.set_title("T2. get_next_round_minimum_local_model(): 연결 상태를 입력받지 않음\n"
                 f"signature = {t2['signature']}", loc="left", fontsize=11.5)
    ax.legend(loc="center left", frameon=False)
    axt.axis("off")
    lines = [
        ("T1. wait_until_can_update_global_model()", True),
        (f"K = {t1['K']},  P_r = {t1['P_r']}", False),
        (f"버퍼의 로컬 모델 = {t1['buffered_local_models']}  (나머지 차량 연결 끊김)", False),
        (f"관측 시간 = {t1['observe_sec']}초", False),
        (f"반환 여부 = {'반환함' if t1['returned'] else '반환하지 않음'}", False),
        (f"소모 CPU = {t1['cpu_sec_consumed']}초  ({t1['cpu_utilisation_pct']}%)", False),
        ("", False),
        ("→ timeout, 생존 확인, 하한 조정 로직이 없음", True),
        ("→ 대기하는 동안 코어 1개를 100% 소모 (busy-wait)", True),
    ]
    y = 0.92
    for text, bold in lines:
        axt.text(0.02, y, text, fontsize=12.5 if bold else 12, fontweight="bold" if bold else "normal",
                 color=CRITICAL if text.startswith("→") else INK, transform=axt.transAxes)
        y -= 0.095
    axt.add_patch(FancyBboxPatch((0.0, 0.08), 0.98, 0.9, boxstyle="round,pad=0.01", fc="white", ec=AXIS,
                                 transform=axt.transAxes, zorder=-1))
    fig.suptitle("E3 코드 수준 증명 — 실제 SASAFLServer 메서드를 직접 호출 (원본 코드 무수정)", fontsize=15,
                 fontweight="bold", x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    save(fig, "fig4_code_level_proof.png")


# ---------------------------------------------------------------- 그림 5: 시뮬레이션
def fig_simulation():
    sim = json.loads((RESULTS / "E4_simulation" / "simulation_results.json").read_text())
    rows = [r for r in sim["sweep"] if not r["crash_aware"]]
    aware = [r for r in sim["sweep"] if r["crash_aware"]]
    p_backs = sorted({r["p_back"] for r in rows})
    titles = {0.0: "재접속 불가 (현재 torch.distributed testbed)", 0.02: "평균 50라운드 후 복귀 (장시간 주차 등)",
              0.05: "평균 20라운드 후 복귀", 0.2: "평균 5라운드 후 복귀 (터널 등 단기 음영)"}
    fig, axes = plt.subplots(1, len(p_backs), figsize=(5 * len(p_backs), 5.2), sharey=True)
    for ax, pb in zip(axes, p_backs):
        for k, c in enumerate([0.1, 0.3, 0.5]):
            sel = sorted([r for r in rows if r["p_back"] == pb and r["C"] == c], key=lambda r: r["p_drop"])
            ax.plot([100 * r["p_drop"] for r in sel], [100 * r["deadlock_prob"] for r in sel], color=SERIES[k],
                    marker="o", markersize=7, label=f"SASAFL C={c}")
            if pb > 0:
                # 정상상태 연결 비율 a = p_back/(p_back+p_drop) 이 C 와 같아지는 p_drop
                thr = pb * (1 - c) / c
                if thr <= 0.1:
                    ax.axvline(100 * thr, color=SERIES[k], linestyle=":", linewidth=1.3)
        # crash-aware 규칙은 need=min(P_r, alive)라 C와 무관하다 -> 한 줄로 표시
        sel = sorted([r for r in aware if r["p_back"] == pb and r["C"] == 0.1], key=lambda r: r["p_drop"])
        ax.plot([100 * r["p_drop"] for r in sel], [100 * r["deadlock_prob"] for r in sel], color=INK_2,
                linestyle="--", linewidth=1.5, label="crash-aware 규칙 P=min(P_r, 연결 차량)\n(실패 = 연결 차량이 0대가 된 경우)")
        ax.set_title(titles.get(pb, f"p_back={pb}"), fontsize=11.5, loc="left")
        ax.set_xlabel("라운드당 차량 연결 끊김 확률 p_drop (%)")
        ax.set_ylim(-3, 103)
    axes[0].set_ylabel("50라운드를 끝내지 못할 확률 (%)\n(교착 또는 10배 이상 지연)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False, fontsize=10.5)
    fig.suptitle("E4 시뮬레이션 — K=100, P_r은 실제 SASAFL 코드 + 실측 K=100 loss로 계산, "
                 f"설정당 {sim['trials']}회 (점선: 정상상태 연결 비율 = C 가 되는 지점)",
                 fontsize=13.5, fontweight="bold", x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.1, 1, 0.92))
    save(fig, "fig5_simulation_deadlock_probability.png")


# ---------------------------------------------------------------- 그림 6: 실패 전파 다이어그램
def fig_failure_flow():
    fig, ax = plt.subplots(figsize=(16, 7.5))
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 7.5)
    ax.axis("off")

    def box(x, y, w, h, text, color, bold=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08", fc="white", ec=color, lw=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=11,
                fontweight="bold" if bold else "normal", color=INK, wrap=True)

    def arrow(x1, y1, x2, y2):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=INK_2, lw=1.6, mutation_scale=16))

    ax.text(0.1, 7.1, "차량 연결 장애가 SASAFL testbed 전체로 전파되는 경로", fontsize=16, fontweight="bold")
    # hard crash
    box(0.2, 4.6, 2.8, 1.4, "Hard crash\n전원 차단 · 앱 종료\n(SIGKILL, TCP 종료)", CRITICAL, True)
    box(3.8, 4.6, 3.4, 1.4, "서버 send_global_model_to_clients()\ndist.send → 'Connection closed\nby peer' 예외 (처리 코드 없음)", SERIES[1])
    box(8.0, 4.6, 3.4, 1.4, "torchrun elastic agent:\n'k≤n개 실패 시 모든 worker 중지'\nmax_restarts=0 → 즉시 종료", SERIES[1])
    box(12.2, 4.6, 3.6, 1.4, "결과: job 전체 종료\n(E1: 장애 후 1.4초)\n재시작해도 라운드 0부터 (E1b)", CRITICAL, True)
    arrow(3.0, 5.3, 3.8, 5.3)
    arrow(7.2, 5.3, 8.0, 5.3)
    arrow(11.4, 5.3, 12.2, 5.3)
    # silent drop
    box(0.2, 1.6, 2.8, 1.4, "Silent drop\n터널 · 음영 지역\n(SIGSTOP, TCP 유지)", WARNING, True)
    box(3.8, 2.4, 3.4, 1.35, "서버가 매 라운드 '전체' 차량에\nblocking dist.send\n→ 멈춘 차량에서 블록 (E2a 스택 확인)", SERIES[1])
    box(3.8, 0.7, 3.4, 1.2, "버퍼 업로드 수 < P_r\nwait_until...() busy-wait\n(timeout·생존 확인 없음, E3)", SERIES[1])
    box(8.0, 1.6, 3.4, 1.4, "gloo timeout 기본 30분\n만료 시 send 예외 → 서버 사망\n(E2c: 90초 설정 → 100초 후 종료)", SERIES[1])
    box(12.2, 1.6, 3.6, 1.4, "결과: timeout까지 정지 후\njob 전체 종료\n(E2a/E2b: 8분 정지, E2c)", CRITICAL, True)
    arrow(3.0, 2.5, 3.8, 3.0)
    arrow(3.0, 2.1, 3.8, 1.3)
    arrow(7.2, 3.1, 8.0, 2.5)
    arrow(7.2, 1.3, 8.0, 2.0)
    arrow(11.4, 2.3, 12.2, 2.3)
    ax.text(0.2, 0.15, "근거: PyTorch 1.12 공식 문서(docs_screenshots/01–05), results/E1·E2 로그와 서버 스택 덤프",
            fontsize=10, color=INK_2)
    save(fig, "fig6_failure_propagation.png")


# ---------------------------------------------------------------- 요약표
def summary_table(runs):
    rows = []
    for name in SCENARIO_LABEL:
        run = runs.get(name)
        if not run:
            continue
        rs = run["rounds"]
        fault = run["fault"]
        end = run["end"] or {}
        last_round_t = rs[-1]["t"] if rs else None
        rows.append({
            "scenario": name,
            "description": SCENARIO_LABEL[name],
            "K": run["cfg"]["clients"],
            "C": run["cfg"]["ratio"],
            "P_min": int(run["cfg"]["clients"] * run["cfg"]["ratio"]),
            "fault": f"{fault['signal']} rank {fault['ranks']} @round {fault['at_round']}" if fault else "-",
            "fault_t_sec": round(fault["t"], 1) if fault else "",
            "rounds_completed": rs[-1]["round"] if rs else 0,
            "restarts": max((s["restart"] for s in run["samples"]), default=0),
            "outcome": outcome_text(run),
            "end_t_sec": round(end.get("t", 0), 1),
            "sec_without_progress_at_end": round(end.get("t", 0) - last_round_t, 1) if last_round_t else "",
            "server_stack_at_end": " / ".join(f"[{h}] {f}" for h, f in stack_dump(run)),
        })
    with (FIGS / "summary_table.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    md = ["| 시나리오 | 장애 | 완료 라운드 | 재시작 | 결과 | 마지막 진행 후 정지 시간(초) | 종료 시 서버 위치 |",
          "|---|---|---:|---:|---|---:|---|"]
    for r in rows:
        md.append(f"| {r['description']} | {r['fault']} | {r['rounds_completed']} | {r['restarts']} | {r['outcome']} | "
                  f"{r['sec_without_progress_at_end']} | {r['server_stack_at_end'] or '-'} |")
    (FIGS / "summary_table.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


def main():
    runs = {name: load_run(name) for name in SCENARIO_LABEL}
    fig_timeline(runs)
    fig_server_state(runs)
    fig_e0_quota(runs)
    fig_code_level()
    fig_simulation()
    fig_failure_flow()
    summary_table(runs)


if __name__ == "__main__":
    main()
