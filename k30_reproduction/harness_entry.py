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
    rank = int(os.environ.get("RANK", os.environ.get("OMPI_COMM_WORLD_RANK", "0")))
    (Path(pid_dir) / f"rank_{rank}.json").write_text(json.dumps({"rank": rank, "pid": os.getpid()}))

faulthandler.register(signal.SIGUSR1, all_threads=True)

# K30_SASAFL_SRC가 있으면 methods/SASAFL/SASAFL.py 대신 그 파일을 쓴다 (저장소 코드는 그대로 둔다)
# 예: original_code/SASAFL_c0b819b.py = 원저자 마지막 커밋(2023-12-14)의 SASAFL.py
sasafl_src = os.environ.get("K30_SASAFL_SRC")
if sasafl_src:
    import hashlib
    import importlib.util

    import methods.SASAFL as sasafl_pkg
    spec = importlib.util.spec_from_file_location("methods.SASAFL.SASAFL", sasafl_src)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    sasafl_pkg.SASAFL = module
    if os.environ.get("RANK", os.environ.get("OMPI_COMM_WORLD_RANK")) == "0" or os.environ.get("LOCAL_RANK") == "0":
        digest = hashlib.sha256(Path(sasafl_src).read_bytes()).hexdigest()
        print(f"[k30] SASAFL.py 교체: {sasafl_src} sha256={digest}", flush=True)

sys.argv = [str(REPO / "Start.py")] + sys.argv[1:]
runpy.run_path(str(REPO / "Start.py"), run_name="__main__")
