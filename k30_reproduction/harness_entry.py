#!/usr/bin/env python3
"""Start.py를 수정 없이 실행하는 진입점 (관측 장치만 추가).

- rank별 PID를 K30_PID_DIR에 기록 (멈춘 서버의 스택을 받기 위함)
- SIGUSR1 수신 시 모든 스레드의 Python 스택을 stderr로 덤프
"""

import faulthandler
import json
import os
import runpy
import signal
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.chdir(REPO)

pid_dir = os.environ.get("K30_PID_DIR")
if pid_dir:
    Path(pid_dir).mkdir(parents=True, exist_ok=True)
    rank = int(os.environ["RANK"])
    (Path(pid_dir) / f"rank_{rank}.json").write_text(json.dumps({"rank": rank, "pid": os.getpid()}))

faulthandler.register(signal.SIGUSR1, all_threads=True)

sys.argv = [str(REPO / "Start.py")] + sys.argv[1:]
runpy.run_path(str(REPO / "Start.py"), run_name="__main__")
