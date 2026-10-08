#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SASAFL Paper Reproduction: Figure 6 & Table 1
Isolated Execution Script (Outputs saved in ./exp_fig6_workspace)
"""

import os
import sys
import subprocess
import json
import re
import time
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# ==========================================
# 1. 격리된 출력 디렉토리 및 매개변수 설정
# ==========================================
WORK_DIR = "./exp_fig6_workspace"
LOG_DIR = os.path.join(WORK_DIR, "logs")
RESULTS_JSON = os.path.join(WORK_DIR, "fig6_table1_results.json")
FIG6_PNG_PATH = os.path.join(WORK_DIR, "Figure_6_MNIST.png")
TABLE1_CSV_PATH = os.path.join(WORK_DIR, "Table_1_Wall_Clock_Time.csv")

NPROC_PER_NODE = 101  # Server 1 + Client 100
METHODS = ["SAFA", "SASAFL"]
RATIOS = [0.1, 0.3, 0.5]
MAX_ROUNDS = 50       # Fig 6: 50 라운드 수렴 곡선
TABLE1_TARGET_ROUND = 25  # Table 1: 25 라운드 달성 시 소요 시간(분)

def check_environment():
    """wandb 설치 확인"""
    try:
        import wandb
    except ImportError:
        print("[!] Error: 'wandb' package is missing. Run: pip install wandb")
        sys.exit(1)

def run_experiments():
    """Fig 6 및 Table 1 재현을 위한 전체 실험 세트 순차 실행"""
    os.makedirs(LOG_DIR, exist_ok=True)
    
    env = os.environ.copy()
    if "OMP_NUM_THREADS" in env:
        del env["OMP_NUM_THREADS"]

    all_results = {}

    for method in METHODS:
        # SAFA는 tau=5, SASAFL은 tau=9 설정
        tau_val = 5 if method == "SAFA" else 9
        all_results[method] = {}

        for C in RATIOS:
            run_key = f"C_{C}"
            print(f"\n==========================================")
            print(f" Running Experiment: Method = {method}, C = {C} (tau = {tau_val})")
            print(f"==========================================")

            log_file = os.path.join(LOG_DIR, f"{method}_C_{C}.log")

            # 논문 Fig6 / Table 1 하이퍼파라미터 엄격 반영
            cmd = [
                sys.executable, "-m", "torch.distributed.run",
                "--nnodes=1",
                f"--nproc_per_node={NPROC_PER_NODE}",
                "--standalone",
                "Start.py",
                f"--selection_ratio={C}",
                f"--round={MAX_ROUNDS}",
                "--batch_size=40",          # 논문 명시값: 40
                "--local_epochs=5",
                "--lr=0.001",               # 논문 명시값: 0.001
                "--target_acc=0.98",        # 목표 정확도: 98%
                "--dataset=MNIST",          # 데이터셋: MNIST
                "--iid=True",               # 라벨 분포는 동질(Homogeneous)
                "--split=gaussian",         # 데이터 크기만 가우시안 Non-IID
                f"--method={method}",
                f"--lag_tolerance={tau_val}",
                "--wandb_on=False",
                "--repeat=1",
                "--cluster_type=WISE"
            ]

            start_wall_time = time.time()

            with open(log_file, "w") as f_log:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
                for line in proc.stdout:
                    sys.stdout.write(line)
                    f_log.write(line)
                proc.wait()

            total_elapsed_sec = time.time() - start_wall_time

            # 로그로부터 라운드별 Accuracy 및 소요 시간 수집
            parsed_data = parse_log_data(log_file, total_elapsed_sec)
            all_results[method][run_key] = parsed_data

    with open(RESULTS_JSON, "w") as f:
        json.dump(all_results, f, indent=4)
        
    print(f"\n[+] Experiments complete. Raw results saved to: {RESULTS_JSON}")
    return all_results

def parse_log_data(log_file, total_elapsed_sec):
    """로그 파일에서 라운드별 정확도 및 25 라운드 달성 소요 시간(분) 추출"""
    rounds, accs, timestamps = [], [], []
    time_for_25_rounds = None

    if os.path.exists(log_file):
        start_time_stamp = None
        with open(log_file, "r") as f:
            for line in f:
                # 타임스탬프 파싱 (로그 예시: [2026-10-08 08:38:51.850071])
                time_match = re.search(r'\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[\.\d]*)\]', line)
                curr_ts = None
                if time_match:
                    try:
                        curr_ts = time.mktime(time.strptime(time_match.group(1).split('.')[0], "%Y-%m-%d %H:%M:%S"))
                        if start_time_stamp is None:
                            start_time_stamp = curr_ts
                    except Exception:
                        pass

                # Accuracy 추출 (test_accuracy: XX.XX%)
                acc_match = re.search(r'test_accuracy[^\d]*([\d\.]+)', line, re.IGNORECASE)
                round_match = re.search(r'(\d+)번째\s*글로벌\s*모델', line)

                if acc_match:
                    val = float(acc_match.group(1))
                    if val <= 1.0:
                        val *= 100.0
                    
                    r_num = int(round_match.group(1)) if round_match else len(rounds) + 1
                    rounds.append(r_num)
                    accs.append(val)

                    # 25 라운드 시점의 경과 시간(분) 기록
                    if r_num == TABLE1_TARGET_ROUND and curr_ts and start_time_stamp:
                        time_for_25_rounds = round((curr_ts - start_time_stamp) / 60.0, 2)

    # 타임스탬프 파싱 실패 시 전체 측정 시간 비율로 추정
    if time_for_25_rounds is None:
        if len(rounds) >= TABLE1_TARGET_ROUND:
            time_for_25_rounds = round((total_elapsed_sec / 60.0) * (TABLE1_TARGET_ROUND / max(len(rounds), 1)), 2)
        else:
            time_for_25_rounds = round(total_elapsed_sec / 60.0, 2)

    return {
        "rounds": rounds,
        "accuracies": accs,
        "time_25_rounds_min": time_for_25_rounds
    }

def generate_figure_6(results_data):
    """Figure 6 복원 (SAFA: 파란색, SASAFL: 빨간색 / C=0.1: 실선, C=0.3: 점선, C=0.5: 파선)"""
    fig, ax = plt.subplots(figsize=(8, 5), dpi=300)

    # 선 스타일 매핑 (C=0.1: Solid, C=0.3: Dotted, C=0.5: Dashed)
    style_map = {
        "C_0.1": {"ls": "-", "label_suffix": "C=0.1"},
        "C_0.3": {"ls": ":", "label_suffix": "C=0.3"},
        "C_0.5": {"ls": "--", "label_suffix": "C=0.5"}
    }

    # 색상 매핑 (SAFA: Blue, SASAFL: Red)
    color_map = {
        "SAFA": "blue",
        "SASAFL": "red"
    }

    for method in METHODS:
        for c_key in ["C_0.1", "C_0.3", "C_0.5"]:
            data = results_data.get(method, {}).get(c_key, {})
            rounds = data.get("rounds", [])
            accs = data.get("accuracies", [])

            if rounds and accs:
                label_str = f"{method}, {style_map[c_key]['label_suffix']}"
                ax.plot(
                    rounds, accs,
                    color=color_map[method],
                    linestyle=style_map[c_key]["ls"],
                    linewidth=1.8,
                    label=label_str
                )

    ax.set_xlim(0, MAX_ROUNDS)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Rounds (#)", fontsize=13)
    ax.set_ylabel("Global model accuracy (%)", fontsize=13)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend(loc="lower right", fontsize=10, ncol=2, frameon=True)

    plt.tight_layout()
    plt.savefig(FIG6_PNG_PATH, bbox_inches="tight")
    print(f"[+] Figure 6 saved to: {FIG6_PNG_PATH}")
    plt.close()

def generate_table_1(results_data):
    """Table 1 복원 (25 라운드 달성 Wall-Clock Time 비교 표)"""
    table_rows = []

    for method in METHODS:
        row = {"Method": method}
        for c_key, c_val in [("C_0.1", "C=0.1"), ("C_0.3", "C=0.3"), ("C_0.5", "C=0.5")]:
            time_val = results_data.get(method, {}).get(c_key, {}).get("time_25_rounds_min", "N/A")
            row[c_val] = f"{time_val} min" if isinstance(time_val, (int, float)) else time_val
        table_rows.append(row)

    df = pd.DataFrame(table_rows)

    print("\n========================================================")
    print("      Table 1: Wall Clock Time Comparison on MNIST (K=100) ")
    print("      (Wall clock time in minutes required for 25 rounds)")
    print("========================================================")
    print(df.to_string(index=False))

    df.to_csv(TABLE1_CSV_PATH, index=False)
    print(f"\n[+] Table 1 saved to CSV: {TABLE1_CSV_PATH}")

if __name__ == "__main__":
    check_environment()
    
    # 기존에 저장된 결과가 있으면 그래프/표만 재생성, 없으면 전체 실험 돌림
    if os.path.exists(RESULTS_JSON):
        print(f"[i] Found existing results file: {RESULTS_JSON}. Generating outputs directly...")
        with open(RESULTS_JSON, "r") as f:
            res = json.load(f)
    else:
        res = run_experiments()

    generate_figure_6(res)
    generate_table_1(res)