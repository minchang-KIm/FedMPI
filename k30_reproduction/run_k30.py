#!/usr/bin/env python3
"""K=30 논문 재현 실험 실행기.

launch.sh를 실행하고 서버 로그로 라운드 진행을 추적한다.
  - 정상 완료 / 비정상 종료 / 진행 정지(stall)를 판정한다.
  - 정지하면 서버에 SIGUSR1을 보내 스택을 받은 뒤, 양쪽 노드의 프로세스를 정리한다.
결과: runs/<name>/{run.log, result.json, rounds.csv}

사용법: python run_k30.py <stage> [--only NAME ...]
  stage: smoke | fallback | table2 (아래 STAGES 참고)
"""

import argparse
import csv
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WORKER_HOST = "wise-176@210.107.197.176"

PAPER_CATS = "1,2,3,4,8"   # 논문 K=30 CPU 카테고리 (카테고리당 6명)
SMALL_CATS = "1,2,3"       # 대체안: 1·2·3 코어 카테고리 (카테고리당 10명)

SMOKE_ROUNDS = 20
COMMON = {"K": 30, "dataset": "MNIST", "lr": 0.01, "batch": 32, "epochs": 5, "tau": 9}

STAGES = {
    # 1단계: 논문 그대로의 K=30 구성이 '돌아가는지' (20라운드)
    "smoke": [
        {"name": "S1_single_paperCats_SASAFL", "method": "SASAFL", "C": 0.1, "mode": "single", "cats": PAPER_CATS},
        {"name": "S2_two_paperCats_SASAFL", "method": "SASAFL", "C": 0.1, "mode": "two", "cats": PAPER_CATS},
        {"name": "S3_two_paperCats_BSA", "method": "SemiAsync", "C": 0.1, "mode": "two", "cats": PAPER_CATS},
    ],
    # 2단계(대체안): 1·2·3 카테고리, 카테고리당 10명
    "fallback": [
        {"name": "F1_two_cats123_SASAFL", "method": "SASAFL", "C": 0.1, "mode": "two", "cats": SMALL_CATS},
        {"name": "F2_two_cats123_BSA", "method": "SemiAsync", "C": 0.1, "mode": "two", "cats": SMALL_CATS},
        {"name": "F3_single_cats123_SASAFL", "method": "SASAFL", "C": 0.1, "mode": "single", "cats": SMALL_CATS},
    ],
}
# git 동기화(176 → 175와 같은 커밋 31288d0) 후 S2 구성 재테스트 3회
STAGES["resync"] = [
    {"name": f"R{i}_two_paperCats_SASAFL_after_gitsync", "method": "SASAFL", "C": 0.1, "mode": "two", "cats": PAPER_CATS}
    for i in (1, 2, 3)
]
# 3단계: 논문 Table 2 MNIST 열 (BSA vs SASAFL × C) — 노드/카테고리는 --mode/--cats로 지정
for method, tag in (("SemiAsync", "BSA"), ("SASAFL", "SASAFL")):
    for c in (0.1, 0.3, 0.5):
        STAGES.setdefault("table2", []).append(
            {"name": f"T2_MNIST_{tag}_C{c}", "method": method, "C": c, "rounds": 500, "target": 1.0})

TS_RE = re.compile(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\] SERVER >> (\d+)번째 글로벌 모델(.*)$")
ACC_RE = re.compile(r"test_accuracy: ([\d.]+)%")
LOSS_RE = re.compile(r"test_loss: ([\d.]+)")
QUOTA_RE = re.compile(r"이번 라운드에서 (\d+)개의 로컬 모델")
ERROR_SIGNS = {
    "is_set_corruption": "object has no attribute 'is_set'",
    "segfault": "SIGSEGV",
    "abort": "SIGABRT",
    "connection_closed": "Connection closed by peer",
    "gloo_timeout": "Timed out waiting",
    "traceback": "Traceback (most recent call last)",
    "child_failed": "ChildFailedError",
}


class Run:
    def __init__(self, cfg, out_root, stall_sec, max_wall_sec, port):
        self.cfg = cfg
        self.out = Path(out_root) / cfg["name"]
        if self.out.exists():
            self.out.rename(self.out.with_name(cfg["name"] + "_old_" + time.strftime("%Y%m%d_%H%M%S")))
        self.out.mkdir(parents=True)
        self.stall_sec = stall_sec
        self.max_wall_sec = max_wall_sec
        self.port = port
        self.rounds = []
        self.pending = None
        self.last_progress = time.time()
        self.lock = threading.Lock()

    def reader(self, proc, log):
        for line in proc.stdout:
            log.write(line)
            m = TS_RE.search(line)
            with self.lock:
                if m:
                    ts, rnd, rest = m.groups()
                    self.pending = {"round": int(rnd), "ts": ts}
                    self.rounds.append(self.pending)
                    self.last_progress = time.time()
                    a = ACC_RE.search(rest)
                    if a:
                        self.pending["acc"] = float(a.group(1))
                elif self.pending is not None:
                    a, l = ACC_RE.search(line), LOSS_RE.search(line)
                    if a and "acc" not in self.pending:
                        self.pending["acc"] = float(a.group(1))
                    if l and "loss" not in self.pending:
                        self.pending["loss"] = float(l.group(1))
                q = QUOTA_RE.search(line)
                if q and self.pending is not None:
                    self.pending["next_quota"] = int(q.group(1))
        log.flush()

    def cleanup(self, proc, run_id):
        # 정지한 서버의 스택을 받고 양쪽 노드 프로세스를 정리한다
        pid_file = self.out / "pids" / "rank_0.json"
        if pid_file.exists():
            pid = json.loads(pid_file.read_text())["pid"]
            try:
                os.kill(pid, signal.SIGUSR1)
                time.sleep(5)
            except ProcessLookupError:
                pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if self.cfg["mode"] == "two":
            subprocess.run(["ssh", WORKER_HOST, f"pkill -9 -f 'rdzv_id={run_id}' ; pkill -9 -f k30_reproduction/harness_entry.py ; true"],
                           capture_output=True, timeout=30)
        subprocess.run(["pkill", "-9", "-f", f"rdzv_id={run_id}"], capture_output=True)
        proc.wait()

    def run(self):
        cfg = self.cfg
        run_id = f"{cfg['name']}_{int(time.time())}"
        env = os.environ.copy()
        # 실험별 설정(cfg)이 COMMON 기본값보다 우선한다
        settings = {**COMMON, **{k: cfg[k] for k in ("K", "dataset", "lr", "batch", "epochs", "tau") if k in cfg}}
        env.update({
            "ROUNDS": str(cfg.get("rounds", SMOKE_ROUNDS)),
            "TARGET_ACCURACY": str(cfg.get("target", 1.0)),
            "DATASET": settings["dataset"], "LEARNING_RATE": str(settings["lr"]),
            "BATCH_SIZE": str(settings["batch"]), "LOCAL_EPOCHS": str(settings["epochs"]),
            "LAG_TOLERANCE": str(settings["tau"]), "IID": "False", "SPLIT": "gaussian",
            "MASTER_PORT": str(self.port), "RUN_ID": run_id,
            "K30_PID_DIR": str(self.out / "pids"),
        })
        if cfg.get("sasafl_src"):
            env["K30_SASAFL_SRC"] = str(cfg["sasafl_src"])
        cmd = ["bash", str(HERE / "launch.sh"), cfg["method"], str(cfg["C"]), str(settings["K"]), cfg["mode"], cfg["cats"]]
        meta = {**cfg, **settings, "rounds": int(env["ROUNDS"]), "cmd": " ".join(cmd), "run_id": run_id,
                "start": datetime.now().isoformat(timespec="seconds")}
        (self.out / "config.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        print(f"\n===== {cfg['name']} : {meta['cmd']}", flush=True)

        start = time.time()
        log = (self.out / "run.log").open("w")
        proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", start_new_session=True)
        reader = threading.Thread(target=self.reader, args=(proc, log), daemon=True)
        reader.start()
        outcome = None
        while outcome is None:
            code = proc.poll()
            now = time.time()
            if code is not None:
                outcome = "completed" if code == 0 else "crashed"
            elif now - self.last_progress > self.stall_sec:
                outcome = "stalled"
            elif now - start > self.max_wall_sec:
                outcome = "max_wall"
            else:
                time.sleep(2)
        if outcome in ("stalled", "max_wall"):
            self.cleanup(proc, run_id)
        reader.join(timeout=20)
        log.close()

        text = (self.out / "run.log").read_text(errors="replace")
        errors = {k: text.count(v) for k, v in ERROR_SIGNS.items()}
        with (self.out / "rounds.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["round", "ts", "acc", "loss", "next_quota"])
            w.writeheader()
            for r in self.rounds:
                w.writerow({k: r.get(k, "") for k in w.fieldnames})
        accs = [r["acc"] for r in self.rounds if "acc" in r]
        result = {
            "name": cfg["name"], "outcome": outcome, "returncode": proc.returncode,
            "wall_min": round((time.time() - start) / 60, 2),
            "rounds_done": max((r["round"] for r in self.rounds), default=0),
            "rounds_requested": meta["rounds"],
            "best_acc": max(accs) if accs else None, "last_acc": accs[-1] if accs else None,
            "errors": errors,
        }
        (self.out / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"===== {cfg['name']} -> {json.dumps(result, ensure_ascii=False)}", flush=True)
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=list(STAGES))
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--mode", choices=["single", "two"], help="table2 단계의 노드 구성")
    parser.add_argument("--cats", help="table2 단계의 CPU 카테고리 (예: 1,2,3,4,8)")
    parser.add_argument("--stall-min", type=float, default=10)
    parser.add_argument("--max-wall-min", type=float, default=40)
    parser.add_argument("--out", default=str(HERE / "runs"))
    args = parser.parse_args()
    runs = STAGES[args.stage]
    if args.only:
        runs = [r for r in runs if r["name"] in args.only]
    port = 29640
    for cfg in runs:
        cfg = dict(cfg)
        if args.stage == "table2":
            if not (args.mode and args.cats):
                sys.exit("table2 단계는 --mode와 --cats가 필요합니다")
            cfg.update(mode=args.mode, cats=args.cats)
            cfg["name"] += f"_{args.mode}_cats{args.cats.replace(',', '')}"
        Run(cfg, args.out, args.stall_min * 60, args.max_wall_min * 60, port).run()
        port += 1
        time.sleep(10)


if __name__ == "__main__":
    main()
