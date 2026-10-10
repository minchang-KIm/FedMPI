#!/usr/bin/env python3
"""SASAFL crash 실험 오케스트레이터 (단일 노드, torchrun + gloo).

차량 연결 장애를 두 가지로 모델링한다.
  - hard crash   : SIGKILL  -> 프로세스 사망 (차량 전원 차단, 앱 강제 종료). TCP 연결이 닫힌다.
  - silent drop  : SIGSTOP  -> 프로세스는 살아 있으나 응답 없음 (터널/음영 지역 진입 등
                   네트워크 단절). TCP 연결은 열린 채로 상대가 침묵한다.

사용법: python run_experiment.py <scenario> [--out results]
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
REPO = STUDY.parent
ENTRY = STUDY / "harness" / "sasafl_entry.py"
PYTHON = os.environ.get("FL_PYTHON", "/home/wise-175/anaconda3/envs/FL/bin/python")

ROUND_RE = re.compile(r"SERVER >> (\d+)번째 글로벌 모델")

BASE = {
    "clients": 10,
    "ratio": 0.3,
    "rounds": 30,
    "lag_tolerance": 9,
    "threads": 2,
    "max_restarts": 0,
    "pg_timeout_sec": None,
    "fault": None,           # {"signal": "KILL"|"STOP", "ranks": [...], "at_round": N}
    "observe_after_fault_sec": 0,
    "max_wall_sec": 900,
}

SCENARIOS = {
    # 장애 없음: 기준선 (라운드 진행 속도, P_r 변화, 정확도)
    "E0_baseline": {},
    # 차량 1대 hard crash -> torchrun gang semantics로 전체 job 종료되는지
    "E1_hardcrash_1client": {
        "fault": {"signal": "KILL", "ranks": [3], "at_round": 5},
        "observe_after_fault_sec": 120,
    },
    # torchrun 재시작 허용 시 -> 모든 worker가 처음부터 다시 시작되는지 (상태 유실)
    "E1b_hardcrash_restart": {
        "max_restarts": 3,
        "fault": {"signal": "KILL", "ranks": [3], "at_round": 5},
        "observe_after_fault_sec": 240,
    },
    # 차량 1대 silent drop (gloo 기본 timeout 30분) -> 서버가 멈추는지
    "E2a_silentdrop_1client": {
        "fault": {"signal": "STOP", "ranks": [3], "at_round": 5},
        "observe_after_fault_sec": 480,
    },
    # 살아있는 클라이언트 < P_min (K=10, C=0.5 -> P_min=5, 6대 drop -> 4대 생존)
    "E2b_silentdrop_below_pmin": {
        "ratio": 0.5,
        "fault": {"signal": "STOP", "ranks": [5, 6, 7, 8, 9, 10], "at_round": 5},
        "observe_after_fault_sec": 480,
    },
    # silent drop + 짧은 gloo timeout(90초) -> timeout 이후에도 복구되는지
    "E2c_silentdrop_timeout90s": {
        "pg_timeout_sec": 90,
        "fault": {"signal": "STOP", "ranks": [3], "at_round": 5},
        "observe_after_fault_sec": 360,
    },
}


def read_cpu_ticks(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[11]) + int(fields[12]), fields[0]
    except (FileNotFoundError, ProcessLookupError, IndexError):
        return None, "gone"


class Experiment:
    def __init__(self, name, cfg, out_root):
        self.name = name
        self.cfg = cfg
        self.out = Path(out_root) / name
        if self.out.exists():
            stamp = time.strftime("%Y%m%d_%H%M%S")
            self.out.rename(self.out.with_name(f"{name}_old_{stamp}"))
        self.out.mkdir(parents=True)
        self.pid_dir = self.out / "pids"
        self.events = []
        self.t0 = None
        self.last_round = -1
        self.fault_done = threading.Event()
        self.fault_time = None
        self.lock = threading.Lock()

    def event(self, kind, **data):
        record = {"t": round(time.time() - self.t0, 3), "wall": time.strftime("%H:%M:%S"), "event": kind, **data}
        with self.lock:
            self.events.append(record)
        print(f"[orchestrator] {record}", flush=True)

    def rank_pids(self):
        pids = {}
        for path in self.pid_dir.glob("rank_*.json"):
            try:
                info = json.loads(path.read_text())
                pids[info["rank"]] = info
            except (json.JSONDecodeError, KeyError):
                pass
        return pids

    def command(self):
        c = self.cfg
        world = c["clients"] + 1
        args = [
            PYTHON, "-m", "torch.distributed.run",
            "--standalone", "--nnodes=1", f"--nproc_per_node={world}",
            f"--max_restarts={c['max_restarts']}",
            str(ENTRY),
            f"--selection_ratio={c['ratio']}", f"--round={c['rounds']}",
            "--batch_size=32", "--local_epochs=2", "--lr=0.01", "--target_acc=1.0",
            "--dataset=MNIST", "--iid=False", "--split=gaussian",
            "--method=SASAFL", f"--lag_tolerance={c['lag_tolerance']}",
            "--wandb_on=False", "--repeat=1", "--cluster_type=KISTI",
            f"--num_threads={str(c['threads']) * world}",
        ]
        return args

    def inject(self):
        fault = self.cfg["fault"]
        sig = {"KILL": signal.SIGKILL, "STOP": signal.SIGSTOP}[fault["signal"]]
        pids = self.rank_pids()
        targets = {r: pids[r]["pid"] for r in fault["ranks"] if r in pids}
        for rank, pid in targets.items():
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        self.fault_time = time.time()
        self.event("fault_injected", signal=fault["signal"], ranks=list(targets), pids=list(targets.values()),
                   at_round=self.last_round)
        self.fault_done.set()

    def reader(self, proc, log_file):
        fault = self.cfg["fault"]
        for line in proc.stdout:
            log_file.write(line)
            match = ROUND_RE.search(line)
            if match:
                self.last_round = int(match.group(1))
                if fault and not self.fault_done.is_set() and self.last_round >= fault["at_round"]:
                    self.inject()
        log_file.flush()

    def sampler(self, proc, stop):
        with (self.out / "samples.csv").open("w") as f:
            f.write("t,last_round,server_cpu_pct,server_state,alive_workers,stopped_workers,restart_count\n")
            prev = {}
            hz = os.sysconf("SC_CLK_TCK")
            while not stop.is_set():
                pids = self.rank_pids()
                server = pids.get(0)
                cpu_pct, state = "", "none"
                if server:
                    ticks, state = read_cpu_ticks(server["pid"])
                    now = time.time()
                    if ticks is not None and server["pid"] in prev:
                        p_ticks, p_time = prev[server["pid"]]
                        cpu_pct = round(100.0 * (ticks - p_ticks) / hz / (now - p_time), 1)
                    if ticks is not None:
                        prev = {server["pid"]: (ticks, now)}
                alive = stopped = 0
                for info in pids.values():
                    _, st = read_cpu_ticks(info["pid"])
                    if st in ("gone", "Z"):
                        continue
                    alive += 1
                    if st == "T":
                        stopped += 1
                restart = max((i["restart_count"] for i in pids.values()), default=0)
                f.write(f"{time.time() - self.t0:.2f},{self.last_round},{cpu_pct},{state},{alive},{stopped},{restart}\n")
                f.flush()
                stop.wait(2.0)

    def run(self):
        cfg = self.cfg
        (self.out / "config.json").write_text(json.dumps({"name": self.name, **cfg}, indent=2))
        env = os.environ.copy()
        env.update({
            "PYTHONUNBUFFERED": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "CRASH_PID_DIR": str(self.pid_dir),
        })
        if cfg["pg_timeout_sec"]:
            env["CRASH_PG_TIMEOUT_SEC"] = str(cfg["pg_timeout_sec"])
        else:
            env.pop("CRASH_PG_TIMEOUT_SEC", None)

        cmd = self.command()
        (self.out / "command.txt").write_text(" ".join(cmd) + "\n")
        self.t0 = time.time()
        self.event("start", cmd=" ".join(cmd[3:7]))
        log_file = (self.out / "run.log").open("w")
        proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", start_new_session=True)
        stop = threading.Event()
        threading.Thread(target=self.reader, args=(proc, log_file), daemon=True).start()
        threading.Thread(target=self.sampler, args=(proc, stop), daemon=True).start()

        outcome = None
        while True:
            code = proc.poll()
            now = time.time()
            if code is not None:
                outcome = {"type": "exited", "returncode": code}
                break
            if self.fault_time and now - self.fault_time > cfg["observe_after_fault_sec"]:
                outcome = {"type": "stalled_killed_by_orchestrator", "rounds_at_end": self.last_round}
                break
            if now - self.t0 > cfg["max_wall_sec"]:
                outcome = {"type": "max_wall_reached", "rounds_at_end": self.last_round}
                break
            time.sleep(1)

        if outcome["type"] != "exited":
            server = self.rank_pids().get(0)
            if server:
                self.event("stack_dump_requested", pid=server["pid"])
                try:
                    os.kill(server["pid"], signal.SIGUSR1)
                except ProcessLookupError:
                    pass
                time.sleep(5)
            for info in self.rank_pids().values():
                try:
                    os.kill(info["pid"], signal.SIGCONT)
                except ProcessLookupError:
                    pass
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()

        self.event("end", **outcome, last_round=self.last_round)
        stop.set()
        time.sleep(2.5)
        log_file.close()
        (self.out / "events.json").write_text(json.dumps(self.events, indent=2, ensure_ascii=False))
        return outcome


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="+", choices=list(SCENARIOS) + ["all"])
    parser.add_argument("--out", default=str(STUDY / "results"))
    args = parser.parse_args()
    names = list(SCENARIOS) if "all" in args.scenarios else args.scenarios
    for name in names:
        cfg = {**BASE, **SCENARIOS[name]}
        print(f"\n===== {name} =====", flush=True)
        outcome = Experiment(name, cfg, args.out).run()
        print(f"===== {name} -> {outcome} =====", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
