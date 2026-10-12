#!/usr/bin/env python3
"""진단 ①: CPU 계산 결정성 검사 (SASAFL·FL 코드와 무관).

모든 코어에 프로세스를 하나씩 띄워 '같은 입력 → 같은 행렬곱'을 반복하고 결과 해시를 비교한다.
프로세스당 thread 1개로 고정하므로 정상 CPU라면 결과는 비트 단위로 항상 같다.
한 번이라도 다르면 CPU(또는 메모리)가 계산을 틀린 것이다.

사용법: python hw_determinism.py [프로세스 수=코어 수] [초=300]
"""

import hashlib
import multiprocessing as mp
import os
import sys
import time


def worker(idx, seconds, queue):
    os.environ["OMP_NUM_THREADS"] = "1"
    import torch
    torch.set_num_threads(1)
    g = torch.Generator().manual_seed(1234)
    a = torch.randn(512, 512, generator=g, dtype=torch.float64)
    b = torch.randn(512, 512, generator=g, dtype=torch.float32)
    ref64 = hashlib.sha256((a @ a).numpy().tobytes()).hexdigest()
    ref32 = hashlib.sha256((b @ b).numpy().tobytes()).hexdigest()
    iters = mismatches = 0
    end = time.time() + seconds
    while time.time() < end:
        h64 = hashlib.sha256((a @ a).numpy().tobytes()).hexdigest()
        h32 = hashlib.sha256((b @ b).numpy().tobytes()).hexdigest()
        iters += 1
        if h64 != ref64 or h32 != ref32:
            mismatches += 1
    queue.put((idx, iters, mismatches, ref64[:16], ref32[:16]))


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else os.cpu_count()
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 300
    queue = mp.Queue()
    procs = [mp.Process(target=worker, args=(i, seconds, queue)) for i in range(n)]
    for p in procs:
        p.start()
    results = []
    deadline = time.time() + seconds + 120
    while len(results) < n and time.time() < deadline:
        try:
            results.append(queue.get(timeout=5))
        except Exception:  # noqa: BLE001
            if all(not p.is_alive() for p in procs):
                break
    for p in procs:
        p.join(timeout=10)
    total_iter = sum(r[1] for r in results)
    total_bad = sum(r[2] for r in results)
    refs = {(r[3], r[4]) for r in results}
    crashed = [(i, p.exitcode) for i, p in enumerate(procs) if p.exitcode != 0]
    print(f"host={os.uname().nodename} procs={n} seconds={seconds}")
    print(f"total_iterations={total_iter} mismatches={total_bad} distinct_reference_hashes={len(refs)} "
          f"crashed_workers={crashed}")
    print(f"reported_workers={len(results)}/{n} (exitcode -11 = SIGSEGV)")
    print("RESULT:", "PASS (모든 계산 결과 동일)" if total_bad == 0 and len(refs) <= 1 and not crashed and len(results) == n
          else "FAIL (같은 계산의 결과가 달라짐 또는 프로세스 비정상 종료)")


if __name__ == "__main__":
    main()
