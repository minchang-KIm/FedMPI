#!/usr/bin/env python3
"""E4: 차량 연결 끊김 하에서 SASAFL 집계 quota(P_r) 규칙의 교착 확률 시뮬레이션.

- P_r 갱신은 실제 SASAFL 코드(SASAFLServer.get_next_round_minimum_local_model)를 호출한다.
- global loss는 실측값을 재생한다: 커밋된 K=100, C=0.1 SASAFL 실행 로그(50라운드).
- 차량 연결은 라운드마다 2-상태 마르코프 체인으로 모델링한다(sweep 변수, 실측값 아님).
    연결 -> 끊김: p_drop,  끊김 -> 재연결: p_back
- SASAFL에 유리한(낙관적) 가정: 연결된 차량은 매 라운드 반드시 업로드한다.
  즉 라운드 r은 '연결된 차량 수 >= P_r'일 때만 진행된다. 그렇지 않으면 서버는 대기한다.
- crash-aware 비교 규칙: P_eff = min(P_r, 연결된 차량 수, ...) (논문에 없는 가상 규칙)
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

STUDY = Path(__file__).resolve().parents[1]
REPO = STUDY.parent
sys.path.insert(0, str(REPO))

from methods.SASAFL.SASAFLServer import SASAFLServer  # noqa: E402

K = 100
RATIOS = [0.1, 0.3, 0.5]
P_DROPS = [0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10]
P_BACKS = [0.0, 0.02, 0.05, 0.2]  # 0.0 = 재접속 불가(현재 testbed), 0.02 = 평균 50라운드(장시간 주차 등), 0.2 = 평균 5라운드(터널 등)
TRIALS = 2000
MAX_STEPS_FACTOR = 10          # 50라운드에 500 step 넘게 걸리면 '교착'으로 간주
SEED = 20261010


def real_losses():
    log = subprocess.run(
        ["git", "show", "HEAD:exp_fig6_workspace/logs/SASAFL_C_0.1.log"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    losses = []
    for idx, line in enumerate(log):
        if "번째 글로벌 모델" in line:
            for follow in log[idx + 1: idx + 3]:
                if "test_loss" in follow:
                    losses.append(float(follow.split("test_loss:")[1].strip()))
                    break
    return losses


def quota_trajectory(losses, ratio):
    server = SASAFLServer(K, ratio, 32, 500, 1.0, "False", None)
    p_min = int(K * ratio)
    server.last_global_loss = losses[0]
    p_r = p_min
    traj = [p_r]
    for loss in losses[1:]:
        p_r = server.get_next_round_minimum_local_model(loss, p_r, p_min)
        traj.append(p_r)
    return traj  # traj[r] = round r+1 집계에 필요한 quota


def simulate(traj, p_drop, p_back, rng, crash_aware=False):
    rounds = len(traj)
    max_steps = rounds * MAX_STEPS_FACTOR
    connected = np.ones(K, dtype=bool)
    r = 0
    step = 0
    stalled_steps = 0
    while r < rounds and step < max_steps:
        drop = rng.random(K) < p_drop
        back = rng.random(K) < p_back
        connected = np.where(connected, ~drop, back)
        alive = int(connected.sum())
        need = traj[r]
        if crash_aware:
            need = max(1, min(need, alive))
        if alive >= need and alive > 0:
            r += 1
        else:
            stalled_steps += 1
        step += 1
    return {"finished": r >= rounds, "steps": step, "stalled": stalled_steps}


def main():
    out = STUDY / "results" / "E4_simulation"
    out.mkdir(parents=True, exist_ok=True)
    losses = real_losses()
    rng = np.random.default_rng(SEED)
    result = {"K": K, "trials": TRIALS, "losses_source": "HEAD:exp_fig6_workspace/logs/SASAFL_C_0.1.log",
              "losses": losses, "trajectories": {}, "sweep": []}
    for ratio in RATIOS:
        traj = quota_trajectory(losses, ratio)
        result["trajectories"][str(ratio)] = traj
        print(f"C={ratio}: P_r 궤적 = {traj}")
        for p_back in P_BACKS:
            for p_drop in P_DROPS:
                for crash_aware in (False, True):
                    runs = [simulate(traj, p_drop, p_back, rng, crash_aware) for _ in range(TRIALS)]
                    deadlock = 1 - np.mean([x["finished"] for x in runs])
                    finished_steps = [x["steps"] for x in runs if x["finished"]]
                    slowdown = (np.mean(finished_steps) / len(traj)) if finished_steps else None
                    row = {"C": ratio, "p_drop": p_drop, "p_back": p_back, "crash_aware": crash_aware,
                           "deadlock_prob": round(float(deadlock), 4),
                           "slowdown_if_finished": None if slowdown is None else round(float(slowdown), 3)}
                    result["sweep"].append(row)
                    print(row)
    (out / "simulation_results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"[+] saved {out / 'simulation_results.json'}")


if __name__ == "__main__":
    main()
