#!/usr/bin/env python3
"""SASAFL 논문(K=30) 재현 실험 전체를 순서대로 실행하고, 실험마다 논문 형식으로 정리한다.

- 재개 가능: 이미 완료된 실행(result.json outcome=completed, 요청 라운드 도달)은 건너뛴다.
- 실행 하나가 끝날 때마다 해당 실험의 그림/표/SUMMARY.md를 다시 만든다.
- 실패한 실행은 1회 재시도한 뒤 기록을 남기고 다음으로 넘어간다.
- 진행 기록: k30_reproduction/PROGRESS.md

사용법:
  python run_pipeline.py                 # 전체 (E1 → E6)
  python run_pipeline.py --only E2 E3    # 일부
  python run_pipeline.py --report-only   # 실행 없이 정리만 다시
"""

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
K30 = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(K30))

import analysis as A  # noqa: E402
import paper_values as P  # noqa: E402
from run_k30 import Run  # noqa: E402

EXP_ROOT = K30 / "experiments"
PAPER_FIGS = K30 / "paper_figures"
PROGRESS = K30 / "PROGRESS.md"

BASE = {"mode": "single", "cats": "1,2,3,4,8", "K": 30, "batch": 32, "epochs": 5, "target": 1.0, "tau": 9}
SETUP_TEXT = ("K=30, wise-175 단일 노드, CPU 카테고리 1·2·3·4·8코어 × 6명(논문 K=30 구성), "
              "batch 32, local epoch 5, τ=9, ζ=0.9, non-IID(gaussian), 1회 실행")
RUN_MAX_WALL_MIN = 1500   # 실행 하나의 시간 상한 (MNIST SASAFL C=0.5가 561분 걸려 600분 상한에 걸린 적 있음)
MAX_ROUNDS = 500   # 500라운드를 넘는 실험(CIFAR-10, 논문 3000)은 500으로 고정 (2026-10-10 결정)
METHOD_TAG = {"SemiAsync": "BSA", "SASAFL": "SASAFL", "FedAvg": "FedAvg", "FedAsync": "FedAsync"}


def table2_runs(prefix, dataset, lr, rounds, max_wall_min):
    runs = []
    for method in ("SemiAsync", "SASAFL"):
        for c in (0.1, 0.3, 0.5):
            runs.append({**BASE, "name": f"{prefix}_{METHOD_TAG[method]}_C{c}" + ("_single_cats12348" if prefix == "T2_MNIST" else ""),
                         "method": method, "C": c, "dataset": dataset, "lr": lr, "rounds": rounds,
                         "max_wall_min": max_wall_min})
    return runs


EXPERIMENTS = [
    {"id": "E1", "dir": "E1_MNIST_table2", "title": "MNIST — Table 2(MNIST 열), Fig. 7(a), Table 4(MNIST)",
     "runs_root": K30 / "runs",   # 2026-10-10 시작한 Table 2 실행을 그대로 사용
     "runs": table2_runs("T2_MNIST", "MNIST", 0.01, 500, RUN_MAX_WALL_MIN)},
    {"id": "E2", "dir": "E2_FashionMNIST_table2",
     "title": "FashionMNIST — Table 2(FashionMNIST 열), Fig. 7(c), Fig. 11(K=30), Table 4(FashionMNIST)",
     "runs": table2_runs("FMNIST", "FashionMNIST", 0.001, 500, RUN_MAX_WALL_MIN)},
    {"id": "E4", "dir": "E4_CIFAR10_table2",
     "title": "CIFAR-10 — Table 2(CIFAR-10 열), Fig. 8(a), Fig. 9, Table 4(CIFAR-10)",
     "runs": table2_runs("CIFAR10", "CIFAR10", 0.001, MAX_ROUNDS, RUN_MAX_WALL_MIN)},
    {"id": "E5", "dir": "E5_Fig5_lag_tolerance", "title": "Lag tolerance τ=1–10 — Fig. 5 (MNIST, SASAFL, C=0.3, 1회)",
     "runs": [{**BASE, "name": f"LT_tau{t}_rep{r}", "method": "SASAFL", "C": 0.3, "dataset": "MNIST", "lr": 0.01,
               "rounds": 500, "tau": t, "max_wall_min": RUN_MAX_WALL_MIN}
              for r in (1,) for t in range(1, 11)]},
    {"id": "E6", "dir": "E6_final_summary", "title": "최종 종합 — Table 2(3개 데이터셋), Table 4(K=30), 결론 수치 점검",
     "runs": []},
]


# ------------------------------------------------------------------ 공통
def log_progress(msg):
    line = f"- {datetime.now().strftime('%Y-%m-%d %H:%M')} {msg}"
    print(line, flush=True)
    if not PROGRESS.exists():
        PROGRESS.write_text("# K=30 재현 파이프라인 진행 기록\n\n")
    with PROGRESS.open("a") as f:
        f.write(line + "\n")


def runs_root(exp):
    return exp.get("runs_root", EXP_ROOT / exp["dir"] / "runs")


def load_exp_runs(exp):
    root = runs_root(exp)
    return {spec["name"]: A.load_run(root / spec["name"]) for spec in exp["runs"]}


def by_method_c(exp, loaded):
    out = {}
    for spec in exp["runs"]:
        out[(METHOD_TAG[spec["method"]], spec["C"])] = loaded[spec["name"]]
    return out


def status_table(exp, loaded):
    lines = ["| 실행 | 방법 | C | 상태 | 소요(분) |", "|---|---|---:|---|---:|"]
    for spec in exp["runs"]:
        r = loaded[spec["name"]]
        wall = f"{r['wall'][-1]:.1f}" if r is not None and len(r["wall"]) else "-"
        tau = f" (τ={spec['tau']})" if exp["id"] == "E5" else ""
        lines.append(f"| `{spec['name']}` | {METHOD_TAG[spec['method']]}{tau} | {spec['C']} | {A.status_line(r)} | {wall} |")
    return "\n".join(lines)


def partial_notes(exp, loaded):
    return [f"{spec['name']}: {A.status_line(loaded[spec['name']])}" for spec in exp["runs"]
            if loaded[spec["name"]] is None or not loaded[spec["name"]]["complete"]]


def write_summary(exp, sections):
    d = EXP_ROOT / exp["dir"]
    body = [f"# {exp['id']}. {exp['title']}", "",
            f"마지막 갱신: {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
            f"**재현 설정**: {SETUP_TEXT}", ""] + sections
    (d / "SUMMARY.md").write_text("\n".join(body) + "\n")


def compare(exp_dir, paper_name, ours_png, out_name, title):
    paper = PAPER_FIGS / paper_name
    if paper.exists() and ours_png.exists():
        A.compare_with_paper(paper, ours_png, exp_dir / out_name, title)
        return f"![{title}]({out_name})"
    return ""


# ------------------------------------------------------------------ Table 2 계열 공통 정리
def table2_section(exp, d, dataset, loaded, mc):
    ours = {c: {m: A.metrics(mc.get((m, c)), dataset) for m in ("BSA", "SASAFL")} for c in (0.1, 0.3, 0.5)}
    rows = A.table2_rows(dataset, P.TABLE2[dataset], ours)
    notes = partial_notes(exp, loaded)
    A.table2_png(dataset, rows, notes, d / "table2_comparison.png", SETUP_TEXT)
    md = A.table2_markdown(dataset, rows, notes)
    (d / "table2_comparison.md").write_text(md + "\n")
    obs = []
    for c in (0.1, 0.3, 0.5):
        p_b, p_s = P.TABLE2[dataset][c]["BSA"][0], P.TABLE2[dataset][c]["SASAFL"][0]
        o_b, o_s = ours[c]["BSA"][0], ours[c]["SASAFL"][0]
        if o_b is None or o_s is None:
            continue
        paper_dir = "SASAFL" if p_s > p_b else "BSA"
        our_dir = "SASAFL" if o_s > o_b else "BSA"
        obs.append(f"- C={c}: 정확도 차이(SASAFL−BSA) 논문 {p_s - p_b:+.2f}%p, 재현 {o_s - o_b:+.2f}%p → "
                   f"{'논문과 같은 방향' if paper_dir == our_dir else '**논문과 반대 방향**'}")
        rb, rs = ours[c]["BSA"][1], ours[c]["SASAFL"][1]
        if rb and rs:
            pb, ps = P.TABLE2[dataset][c]["BSA"][1], P.TABLE2[dataset][c]["SASAFL"][1]
            paper_ratio = f"{pb / ps:.2f}배" if pb and ps else "BSA 미도달"
            obs.append(f"  - round-to-accuracy BSA/SASAFL = {rb / rs:.2f}배 (논문 {paper_ratio}) "
                       f"→ 1보다 크면 SASAFL이 더 빨리 도달")
    sec = ["## Table 2 비교", "", md, "", "![Table 2 비교](table2_comparison.png)", "",
           "- Accuracy = 최고 test 정확도, Round-to-accuracy = 목표 첫 도달 라운드, "
           "Time-to-accuracy = 서버 setup 시작부터 목표 도달까지(분). `-` = 도달 못 함/미실행",
           "- Time-to-accuracy는 단일 노드 과다 할당(thread 109개 / 논리 CPU 32개) 환경이라 논문과 절대값 비교가 어렵다.",
           ""]
    if obs:
        sec += ["### 관찰", ""] + obs + [""]
    return sec, ours


def table4_section(d, dataset, mc):
    paper_rounds = P.TABLE4_K30[dataset]["rounds"]
    rounds = min(paper_rounds, MAX_ROUNDS)
    header = ["", "C=0.1", "C=0.3", "C=0.5"]
    paper_row = [f"논문 K=30 ({paper_rounds}R)"] + [P.TABLE4_K30[dataset][c] for c in (0.1, 0.3, 0.5)]
    ours_row = [f"재현 K=30 ({rounds}R)"]
    for c in (0.1, 0.3, 0.5):
        w = A.wall_at_round(mc.get(("SASAFL", c)), rounds)
        ours_row.append("-" if w is None else f"{w:.0f}")
    A.simple_table_png(f"Table 4 (K=30 행) — SASAFL {dataset} wall clock (분)", header,
                       [paper_row, ours_row], d / "table4_k30.png")
    md = ["| " + " | ".join(header) + " |", "|---|---:|---:|---:|",
          "| " + " | ".join(map(str, paper_row)) + " |", "| " + " | ".join(map(str, ours_row)) + " |"]
    note = ("" if rounds == paper_rounds else
            f" **주의: 논문은 {paper_rounds}라운드 기준, 재현은 {rounds}라운드 기준이라 직접 비교 불가 "
            f"(라운드당 시간 비교용: 논문 {paper_rounds}R 값을 {rounds}/{paper_rounds}배 하면 대략적인 기준이 된다).**")
    return ["## Table 4 (K=30 행)", "", f"SASAFL로 {rounds}라운드를 마치는 데 걸린 시간(분).{note}", ""] + md + \
           ["", "![Table 4](table4_k30.png)", ""]


# ------------------------------------------------------------------ 실험별 정리
def report_E1(exp, loaded):
    d = EXP_ROOT / exp["dir"]
    mc = by_method_c(exp, loaded)
    sec, _ = table2_section(exp, d, "MNIST", loaded, mc)
    A.fig_bsa_vs_sasafl(mc, d / "fig7a_mnist_k30.png", every=5, ylim=(0, 100), xmax=500,
                        inset=((450, 500), (80, 100)))
    sec += ["## Fig. 7(a) — MNIST, K=30 (5라운드 간격)", "", "![Fig7a](fig7a_mnist_k30.png)", "",
            compare(d, "paper_fig7.jpg", d / "fig7a_mnist_k30.png", "compare_fig7.png",
                    "Fig. 7 비교 (재현은 (a) MNIST K=30 패널에 해당)"), "",
            ]
    sec += table4_section(d, "MNIST", mc)
    return sec


def report_E2(exp, loaded):
    d = EXP_ROOT / exp["dir"]
    mc = by_method_c(exp, loaded)
    sec, _ = table2_section(exp, d, "FashionMNIST", loaded, mc)
    A.fig_bsa_vs_sasafl(mc, d / "fig7c_fmnist_k30.png", every=5, ylim=(0, 100), xmax=500)
    wall = {k: A.wall_at_round(v, 500) for k, v in mc.items()}
    paper_wall = {(m, c): P.FIG11_K30[m][c] for m in ("BSA", "SASAFL") for c in (0.1, 0.3, 0.5)}
    A.fig11(wall, paper_wall, d / "fig11_fmnist_wallclock_k30.png")
    sec += ["## Fig. 7(c) — FashionMNIST, K=30 (5라운드 간격)", "", "![Fig7c](fig7c_fmnist_k30.png)", "",
            compare(d, "paper_fig7.jpg", d / "fig7c_fmnist_k30.png", "compare_fig7.png",
                    "Fig. 7 비교 (재현은 (c) FashionMNIST K=30 패널에 해당)"), "",
            "## Fig. 11 — FashionMNIST 500라운드 wall clock (K=30)", "",
            "논문 BSA 값은 그림에서 읽은 근사값, 논문 SASAFL 값은 Table 4와 같다.", "",
            "![Fig11](fig11_fmnist_wallclock_k30.png)", "",
            compare(d, "paper_fig11.jpg", d / "fig11_fmnist_wallclock_k30.png", "compare_fig11.png", "Fig. 11 비교"), ""]
    sec += table4_section(d, "FashionMNIST", mc)
    return sec


def report_E3(exp, loaded):
    d = EXP_ROOT / exp["dir"]
    e1 = next(e for e in EXPERIMENTS if e["id"] == "E1")
    semi = A.load_run(runs_root(e1) / "T2_MNIST_BSA_C0.1_single_cats12348")
    sync, asyn = loaded["SYNC_FedAvg_C0.1"], loaded["ASYNC_FedAsync"]
    A.fig2(sync, asyn, semi, d / "fig2_sync_async_semi.png")

    def describe(run):
        if run is None or len(run["acc"]) == 0:
            return ("-", "-", "-")
        idx90 = [i for i, a in enumerate(run["acc"]) if a >= 90 and run["rounds"][i] >= 1]
        t90 = f"{run['wall'][idx90[0]]:.1f}" if idx90 else "-"
        return (f"{run['acc'][-1]:.2f}", f"{run['wall'][-1]:.1f}", t90)

    rows = [("Synchronous (FedAvg, C=0.1)", sync), ("Asynchronous (FedAsync)", asyn),
            ("Semi-asynchronous (BSA, C=0.1, E1 재사용)", semi)]
    md = ["| 방식 | 최종 정확도(%) | 500라운드 소요(분) | 90% 도달(분) |", "|---|---:|---:|---:|"]
    md += [f"| {name} | " + " | ".join(describe(r)) + " |" for name, r in rows]
    md += ["", f"논문 본문: semi 최종 {P.FIG2_TEXT['semi_final_acc']}%, sync는 그보다 약 6%p 높음, "
               f"90% 도달 시간 semi 약 {P.FIG2_TEXT['time_to_90_semi_min']}분 / sync 약 {P.FIG2_TEXT['time_to_90_sync_min']}분, "
               "500라운드 wall clock은 sync가 semi·async의 약 3배."]
    return ["## Fig. 2 — 동기·비동기·반비동기 (MNIST, 500라운드)", "",
            "논문은 Fig.2의 K와 C를 밝히지 않았다. K=30, C=0.1로 가정했다. 반비동기는 E1의 BSA C=0.1 실행을 재사용한다.", "",
            "![Fig2](fig2_sync_async_semi.png)", "",
            compare(d, "paper_fig2.jpg", d / "fig2_sync_async_semi.png", "compare_fig2.png", "Fig. 2 비교"), "",
            ] + md + [""]


def report_E4(exp, loaded):
    d = EXP_ROOT / exp["dir"]
    mc = by_method_c(exp, loaded)
    sec, _ = table2_section(exp, d, "CIFAR10", loaded, mc)
    A.fig_bsa_vs_sasafl(mc, d / "fig8a_cifar10_k30.png", every=10, ylim=(0, 60), xmax=MAX_ROUNDS)
    A.fig_sasafl_c(mc, d / "fig9_cifar10_sasafl_k30.png", xmax=MAX_ROUNDS)
    A.fig8_grid(mc, d / "fig8_layout_as_paper.png", xmax=MAX_ROUNDS)
    sec += ["**라운드 축소**: 논문은 CIFAR-10을 3000라운드 돌렸지만 여기서는 500라운드로 고정했다. "
            "논문 SASAFL은 목표 55%에 1,490~2,140라운드에 도달하므로, Round/Time-to-accuracy는 대부분 `-`(미도달)로 나올 수 있다. "
            "논문 그림과는 0~500라운드 구간만 비교할 수 있다.", "",
            "## Fig. 8(a) — CIFAR-10, K=30 (10라운드 간격, 0~500라운드)", "", "![Fig8a](fig8a_cifar10_k30.png)", "",
            "논문과 같은 배치:", "", "![Fig8 layout](fig8_layout_as_paper.png)", "",
            compare(d, "paper_fig8.jpg", d / "fig8_layout_as_paper.png", "compare_fig8.png",
                    "Fig. 8 비교 ((b) K=100은 재현 불가)"), "",
            "## Fig. 9 — CIFAR-10 SASAFL, K=30, C별", "", "![Fig9](fig9_cifar10_sasafl_k30.png)", "",
            compare(d, "paper_fig9.jpg", d / "fig9_cifar10_sasafl_k30.png", "compare_fig9.png", "Fig. 9 비교"), ""]
    sec += table4_section(d, "CIFAR10", mc)
    return sec


def report_E5(exp, loaded):
    d = EXP_ROOT / exp["dir"]
    acc_by_tau = {}
    for spec in exp["runs"]:
        run = loaded[spec["name"]]
        if run is not None and run["complete"]:
            acc_by_tau.setdefault(spec["tau"], []).append(A.metrics(run, "MNIST")[0])
    A.fig5(acc_by_tau, d / "fig5_lag_tolerance.png")
    md = ["| τ | 실행 수 | 평균 | 최소 | 최대 |", "|---:|---:|---:|---:|---:|"]
    for t in range(1, 11):
        v = acc_by_tau.get(t, [])
        md.append(f"| {t} | {len(v)} | " + (" | ".join(f"{f(v):.2f}" for f in (lambda x: sum(x) / len(x), min, max))
                                           if v else "- | - | -") + " |")
    best = max(acc_by_tau, key=lambda t: sum(acc_by_tau[t]) / len(acc_by_tau[t])) if acc_by_tau else None
    return ["## Fig. 5 — lag tolerance별 최고 정확도", "",
            "논문은 Fig.5의 데이터셋·C를 밝히지 않았고 설정당 10회 반복했다. "
            "여기서는 MNIST, C=0.3으로 가정하고 τ마다 1회만 실행한다(반복 검증 생략, 완료된 실행만 집계). 그래서 박스 대신 τ별 값 하나가 찍힌다.", "",
            "![Fig5](fig5_lag_tolerance.png)", "",
            compare(d, "paper_fig5.jpg", d / "fig5_lag_tolerance.png", "compare_fig5.png", "Fig. 5 비교"), "",
            ] + md + ["", f"평균이 가장 높은 τ: **{best}** (논문은 τ=9 선택)" if best else "", ""]


def report_E6(exp, loaded_all):
    d = EXP_ROOT / exp["dir"]
    d.mkdir(parents=True, exist_ok=True)
    exps = {e["id"]: e for e in EXPERIMENTS}
    mcs = {eid: by_method_c(exps[eid], loaded_all.get(eid, {})) for eid in ("E1", "E2", "E4")}
    ours = {ds: {c: {m: A.metrics(mcs[eid].get((m, c)), ds) for m in ("BSA", "SASAFL")} for c in (0.1, 0.3, 0.5)}
            for eid, ds in (("E1", "MNIST"), ("E2", "FashionMNIST"), ("E4", "CIFAR10"))}
    A.table2_full_png(P.TABLE2, "Table 2 — 논문 (Yu et al., 2024), K=30", d / "table2_paper.png",
                      note="논문 값 그대로 (설정당 10회 평균)")
    A.table2_full_png(ours, "Table 2 — 재현 (본 실험), K=30", d / "table2_reproduced.png",
                      note=f"{SETUP_TEXT}. CIFAR-10은 500라운드(논문 3000)")
    A.stack_vertical([d / "table2_paper.png", d / "table2_reproduced.png"], d / "compare_table2.png")
    t4_paper = [("논문 K=30 (MNIST 300R / FMNIST 500R / CIFAR-10 1000R)",
                 {ds: {c: P.TABLE4_K30[ds][c] for c in (0.1, 0.3, 0.5)} for ds in P.TABLE4_K30})]
    t4_ours = [("재현 K=30 (MNIST 300R / FMNIST 500R / CIFAR-10 500R)",
                {ds: {c: A.wall_at_round(mcs[eid].get(("SASAFL", c)), min(P.TABLE4_K30[ds]["rounds"], MAX_ROUNDS))
                      for c in (0.1, 0.3, 0.5)}
                 for eid, ds in (("E1", "MNIST"), ("E2", "FashionMNIST"), ("E4", "CIFAR10"))})]
    A.table4_full_png(t4_paper, t4_ours, d / "compare_table4.png",
                      note="CIFAR-10은 라운드 기준이 달라(1000R vs 500R) 직접 비교 불가")
    A.fig7_grid(mcs["E1"], mcs["E2"], d / "fig7_layout_as_paper.png")
    sec = ["## 논문과 같은 배치의 표·그림", "",
           "### Table 2 (위: 논문, 아래: 재현)", "", "![Table 2](compare_table2.png)", "",
           "### Table 4 (K=30 행)", "", "![Table 4](compare_table4.png)", "",
           "### Fig. 7 ((b)(d) K=100은 재현 불가)", "", "![Fig7 layout](fig7_layout_as_paper.png)", "",
           compare(d, "paper_fig7.jpg", d / "fig7_layout_as_paper.png", "compare_fig7.png", "Fig. 7 비교"), "",
           "## Table 2 전체 (K=30)", ""]
    for eid, dataset in (("E1", "MNIST"), ("E2", "FashionMNIST"), ("E4", "CIFAR10")):
        md = EXP_ROOT / next(e for e in EXPERIMENTS if e["id"] == eid)["dir"] / "table2_comparison.md"
        sec += [md.read_text() if md.exists() else f"{dataset}: 아직 결과 없음", ""]
    sec += ["## Table 4 (K=30 행)", ""]
    for eid in ("E1", "E2", "E4"):
        sm = EXP_ROOT / next(e for e in EXPERIMENTS if e["id"] == eid)["dir"] / "SUMMARY.md"
        if sm.exists():
            text = sm.read_text()
            if "## Table 4" in text:
                sec += [text.split("## Table 4 (K=30 행)")[1].split("![Table 4]")[0].strip(), ""]
    sec += ["## 결론 수치 점검", "",
            "| 결론의 주장 | 논문 출처 | 이 장비에서 재현 |", "|---|---|---|"]
    for claim, src in P.CONCLUSION_CLAIMS:
        sec.append(f"| {claim} | {src} | 불가 (K=100) |")
    sec += ["", "K=30에서 같은 지표(재현값, 논문 K=30 값):", ""]
    for eid, dataset in (("E1", "MNIST"), ("E2", "FashionMNIST"), ("E4", "CIFAR10")):
        exp_i = next(e for e in EXPERIMENTS if e["id"] == eid)
        mc = by_method_c(exp_i, loaded_all.get(eid, {}))
        for c in (0.1, 0.3, 0.5):
            o_b, o_s = A.metrics(mc.get(("BSA", c)), dataset), A.metrics(mc.get(("SASAFL", c)), dataset)
            p_b, p_s = P.TABLE2[dataset][c]["BSA"], P.TABLE2[dataset][c]["SASAFL"]
            gap = f"{o_s[0] - o_b[0]:+.2f}" if o_b[0] is not None and o_s[0] is not None else "-"
            rr = f"{o_b[1] / o_s[1]:.2f}" if o_b[1] and o_s[1] else "-"
            tr = f"{o_b[2] / o_s[2]:.2f}" if o_b[2] and o_s[2] else "-"
            prr = f"{p_b[1] / p_s[1]:.2f}" if p_b[1] and p_s[1] else "-"
            ptr = f"{p_b[2] / p_s[2]:.2f}" if p_b[2] and p_s[2] else "-"
            sec.append(f"- {dataset} C={c}: 정확도 차이 재현 {gap}%p (논문 {p_s[0] - p_b[0]:+.2f}%p), "
                       f"RTA 배수 재현 {rr} (논문 {prr}), TTA 배수 재현 {tr} (논문 {ptr})")
    sec += ["", "## 이 장비로 재현하지 못한 항목", "",
            "- K=100: Table 3, Fig. 6, Table 1, Fig. 7(b)(d), Fig. 8(b), Fig. 10, Table 4의 K≥100 행",
            "- 이유: 논문 K=100 카테고리(1·2·3·5·8코어 × 20명)는 노드당 190 thread가 필요하다. "
            "두 노드(각 논리 32)로 시도한 실행은 실패했다(../../crash_study, ../README.md 참고).", ""]
    return sec


REPORTS = {"E1": report_E1, "E2": report_E2, "E4": report_E4, "E5": report_E5}


def build_report(exp, loaded_all):
    d = EXP_ROOT / exp["dir"]
    d.mkdir(parents=True, exist_ok=True)
    try:
        if exp["id"] == "E6":
            sections = report_E6(exp, loaded_all)
        else:
            loaded = loaded_all[exp["id"]]
            sections = ["## 실행 상태", "", status_table(exp, loaded), ""] + REPORTS[exp["id"]](exp, loaded)
        write_summary(exp, sections)
    except Exception:
        (d / "report_error.log").write_text(traceback.format_exc())
        log_progress(f"{exp['id']} 정리 중 오류 → {d / 'report_error.log'}")


# ------------------------------------------------------------------ 실행
def run_experiment(exp, port_counter, stall_min, attempts):
    root = runs_root(exp)
    root.mkdir(parents=True, exist_ok=True)
    if exp["id"] == "E1":
        link = EXP_ROOT / exp["dir"] / "runs"
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.exists():
            link.symlink_to(Path("../../runs"))
    for spec in exp["runs"]:
        existing = A.load_run(root / spec["name"])
        if existing is not None and existing["complete"]:
            continue
        for attempt in range(1, attempts + 1):
            log_progress(f"{exp['id']} 실행 시작: {spec['name']} (시도 {attempt}/{attempts})")
            port_counter[0] += 1
            port = 29700 + (port_counter[0] % 250)
            result = Run(dict(spec), root, stall_min * 60, spec.get("max_wall_min", 600) * 60, port).run()
            done = result["outcome"] == "completed" and result["rounds_done"] >= spec["rounds"]
            log_progress(f"{exp['id']} 실행 종료: {spec['name']} → {result['outcome']}, "
                         f"{result['rounds_done']}/{spec['rounds']}라운드, 최고 {result['best_acc']}%, "
                         f"{result['wall_min']}분")
            time.sleep(15)
            if done:
                break
        yield spec["name"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--stall-min", type=float, default=20)
    parser.add_argument("--attempts", type=int, default=2)
    args = parser.parse_args()
    exps = [e for e in EXPERIMENTS if not args.only or e["id"] in args.only]
    EXP_ROOT.mkdir(exist_ok=True)
    port_counter = [int(time.time()) % 100]
    log_progress(f"파이프라인 시작 ({', '.join(e['id'] for e in exps)}, report_only={args.report_only})")
    loaded_all = {}
    for exp in EXPERIMENTS:   # E6 정리를 위해 전체 로딩
        if exp["runs"]:
            loaded_all[exp["id"]] = load_exp_runs(exp)
    for exp in exps:
        if not args.report_only and exp["runs"]:
            log_progress(f"=== {exp['id']} 시작: {exp['title']}")
            for _ in run_experiment(exp, port_counter, args.stall_min, args.attempts):
                loaded_all[exp["id"]] = load_exp_runs(exp)
                build_report(exp, loaded_all)
        if exp["runs"]:
            loaded_all[exp["id"]] = load_exp_runs(exp)
        build_report(exp, loaded_all)
        log_progress(f"=== {exp['id']} 정리 완료 → experiments/{exp['dir']}/SUMMARY.md")
    log_progress("파이프라인 종료")


if __name__ == "__main__":
    main()
