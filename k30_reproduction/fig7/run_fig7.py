#!/usr/bin/env python3
"""Fig. 7 (K=30) + SAFA 실험 실행기. 모든 실행은 wise-175(서버 + 15 클라이언트) + wise-176(15 클라이언트) 두 노드로 돈다.

- 실행 순서: spec.queue() (회차 단위). 완료된 실행은 건너뛰므로 중단 후 같은 명령으로 이어서 돈다.
- 실행 전 검사(하나라도 실패하면 실행하지 않고 5분마다 다시 검사):
    두 노드의 git HEAD가 같고 코드(추적 파일)에 수정이 없음 / 두 노드 터보 꺼짐 / 다른 FL 프로세스 없음
- 실행마다 runs/<이름>/에 cmd.txt(두 노드의 실제 명령), config.json, run.log, rounds.csv(라운드마다 갱신), result.json
"""
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_k30  # noqa: E402
import spec  # noqa: E402

WORKER = "wise-176@210.107.197.176"
WORKER_REPO = "/home/wise-176/Mando/FedMPI"
CODE_PATHS = ["Start.py", "methods", "utils", "model_controller", "k30_reproduction/harness_entry.py",
              "k30_reproduction/launch.sh", "k30_reproduction/original_code", "k30_reproduction/fig7", "k30_reproduction/run_k30.py"]
PROGRESS = spec.OUT / "PROGRESS.md"


def log(msg):
    line = f"- {datetime.now():%Y-%m-%d %H:%M} {msg}"
    print(line, flush=True)
    with PROGRESS.open("a") as f:
        f.write(line + "\n")


def sh(cmd, remote=False, timeout=60):
    argv = ["ssh", "-n", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", WORKER, cmd] if remote else ["bash", "-c", cmd]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip()
    except subprocess.TimeoutExpired:
        return 255, ""


def preflight():
    """문제 목록을 돌려준다 (비어 있으면 통과)."""
    problems = []
    paths = " ".join(CODE_PATHS)
    rc1, head1 = sh(f"cd {spec.REPO} && git rev-parse HEAD")
    rc2, head2 = sh(f"cd {WORKER_REPO} && git rev-parse HEAD", remote=True)
    if rc1 or rc2 or head1 != head2:
        problems.append(f"git HEAD 불일치 175={head1} 176={head2}")
    _, dirty1 = sh(f"cd {spec.REPO} && git status --porcelain -- {paths}")
    _, dirty2 = sh(f"cd {WORKER_REPO} && git status --porcelain -- {paths}", remote=True)
    if dirty1:
        problems.append(f"175 코드 수정됨: {dirty1.splitlines()[:5]}")
    if dirty2:
        problems.append(f"176 코드 수정됨: {dirty2.splitlines()[:5]}")
    _, t1 = sh("cat /sys/devices/system/cpu/intel_pstate/no_turbo")
    _, t2 = sh("cat /sys/devices/system/cpu/intel_pstate/no_turbo", remote=True)
    if t1 != "1" or t2 != "1":
        problems.append(f"터보 켜짐 175={t1} 176={t2}")
    _, p1 = sh("pgrep -fc '[h]arness_entry.py|[v]ehicle_sim/fl/fl_entry' || true")
    _, p2 = sh("pgrep -fc '[h]arness_entry.py' || true", remote=True)
    if p1 not in ("", "0") or p2 not in ("", "0"):
        problems.append(f"다른 FL 프로세스 실행 중 175={p1} 176={p2}")
    return problems, head1


class LiveRun(run_k30.Run):
    """라운드가 끝날 때마다 run.log를 flush하고 rounds.csv를 다시 쓴다 (그림 갱신용)."""

    def reader(self, proc, logf):
        fields = ["round", "ts", "acc", "loss", "next_quota"]
        live = self.out / "rounds.csv"
        written = 0
        for line in proc.stdout:
            logf.write(line)
            if "SERVER >> FL 프로세스를 종료합니다" in line:
                # 서버가 끝났다. 저장소 SAFA는 클라이언트가 broadcast에서 멈춰 프로세스가 끝나지 않으므로 2분 뒤 정리한다
                self.server_finished = True
                self.last_progress = time.time()
                self.stall_sec = 120
            m = run_k30.TS_RE.search(line)
            with self.lock:
                if m:
                    ts, rnd, rest = m.groups()
                    self.pending = {"round": int(rnd), "ts": ts}
                    self.rounds.append(self.pending)
                    self.last_progress = time.time()
                    a = run_k30.ACC_RE.search(rest)
                    if a:
                        self.pending["acc"] = float(a.group(1))
                    lo = run_k30.LOSS_RE.search(rest)
                    if lo:
                        self.pending["loss"] = float(lo.group(1))
                elif self.pending is not None:
                    a, lo = run_k30.ACC_RE.search(line), run_k30.LOSS_RE.search(line)
                    if a and "acc" not in self.pending:
                        self.pending["acc"] = float(a.group(1))
                    if lo and "loss" not in self.pending:
                        self.pending["loss"] = float(lo.group(1))
                q = run_k30.QUOTA_RE.search(line)
                if q and self.pending is not None:
                    self.pending["next_quota"] = int(q.group(1))
                done = sum(1 for r in self.rounds if "acc" in r and "loss" in r)
                if done != written:
                    written = done
                    logf.flush()
                    tmp = live.with_suffix(".tmp")
                    with tmp.open("w", newline="") as f:
                        w = csv.DictWriter(f, fieldnames=fields)
                        w.writeheader()
                        for r in self.rounds:
                            w.writerow({k: r.get(k, "") for k in fields})
                    os.replace(tmp, live)
        logf.flush()


def cleanup_orphans():
    """이전 실행기가 죽으며 남긴 Fig.7 실험 프로세스를 두 노드에서 정리한다 (실행 시작 직전에만 부른다)."""
    sh("pkill -9 -f '[r]dzv_id=F7_' ; true")
    sh("pkill -9 -f '[r]dzv_id=F7_' ; true", remote=True)
    time.sleep(3)


def is_done(name):
    res = spec.RUNS / name / "result.json"
    if not res.exists():
        return False
    r = json.loads(res.read_text())
    finished = r.get("outcome") == "completed" or r.get("server_finished", False)
    return finished and r.get("rounds_done", 0) >= spec.ROUNDS


def main():
    spec.RUNS.mkdir(parents=True, exist_ok=True)
    os.environ["SYNC_SOURCE"] = "0"   # 코드는 git으로 동기화한다 (launch.sh가 tar로 덮어쓰지 않게)
    q = spec.queue()
    log(f"실행기 시작: 전체 {len(q)}개, 완료 {sum(is_done(s['name']) for s in q)}개")
    port = 29900
    for s in q:
        if is_done(s["name"]):
            continue
        for attempt in (1, 2):
            cleanup_orphans()
            while True:
                problems, head = preflight()
                if not problems:
                    break
                log(f"실행 전 검사 실패 → 5분 뒤 다시 검사: {'; '.join(problems)}")
                time.sleep(300)
            port = 29900 + (port - 29900 + 1) % 90
            cmd_file = spec.RUNS / s["name"] / "cmd.txt"
            os.environ["CMD_FILE"] = str(cmd_file)
            cfg = dict(s)
            cfg["git_head"] = head
            if cfg["sasafl_src"] is None:
                cfg.pop("sasafl_src")
            log(f"실행 시작: {s['name']} (시도 {attempt}/2, git {head[:7]})")
            run = LiveRun(cfg, spec.RUNS, 20 * 60, 2400 * 60, port)
            result = run.run()
            if getattr(run, "server_finished", False):
                # 서버가 정상 종료 메시지를 남긴 실행: 클라이언트 정리로 끝났어도 결과는 완료로 본다
                result["server_finished"] = True
                (run.out / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
            log(f"실행 종료: {s['name']} → {result['outcome']}, {result['rounds_done']}/{spec.ROUNDS}라운드, "
                f"최고 {result['best_acc']}%, {result['wall_min']}분")
            time.sleep(20)
            if is_done(s["name"]):
                break
    log("FIG7_DONE: 전체 실행 완료")


if __name__ == "__main__":
    main()
