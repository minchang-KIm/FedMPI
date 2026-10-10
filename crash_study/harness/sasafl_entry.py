#!/usr/bin/env python3
"""Start.py를 수정 없이 실행하는 계측용 진입점.

추가하는 것은 관측 장치뿐이며 학습/통신 로직은 원본 그대로다.
  - rank별 PID 파일 기록 (외부에서 특정 클라이언트에 장애를 주입하기 위함)
  - SIGUSR1 수신 시 모든 스레드의 Python 스택을 stderr로 덤프 (멈춘 위치 증명)
  - CRASH_PG_TIMEOUT_SEC가 설정되면 init_process_group에 timeout을 주입
    (기본값 30분을 기다리지 않고 timeout 이후의 동작을 관찰하기 위함)
"""

import datetime
import faulthandler
import json
import os
import runpy
import signal
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.chdir(REPO)

pid_dir = os.environ.get("CRASH_PID_DIR")
if pid_dir:
    Path(pid_dir).mkdir(parents=True, exist_ok=True)
    record = {
        "rank": int(os.environ["RANK"]),
        "local_rank": int(os.environ["LOCAL_RANK"]),
        "pid": os.getpid(),
        "restart_count": int(os.environ.get("TORCHELASTIC_RESTART_COUNT", "0")),
    }
    (Path(pid_dir) / f"rank_{record['rank']}.json").write_text(json.dumps(record))

faulthandler.register(signal.SIGUSR1, all_threads=True)

timeout_sec = os.environ.get("CRASH_PG_TIMEOUT_SEC")
if timeout_sec:
    import torch.distributed as dist

    original_init = dist.init_process_group

    def init_with_timeout(*args, **kwargs):
        kwargs.setdefault("timeout", datetime.timedelta(seconds=float(timeout_sec)))
        return original_init(*args, **kwargs)

    dist.init_process_group = init_with_timeout

sys.argv = [str(REPO / "Start.py")] + sys.argv[1:]
runpy.run_path(str(REPO / "Start.py"), run_name="__main__")
