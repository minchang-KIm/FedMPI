#!/usr/bin/env python3
"""진단 ②(b): SASAFL 클라이언트의 '스레드 사용 패턴'만 흉내 낸 최소 재현 (SASAFL·gloo 코드 미사용).

SASAFL 클라이언트와 같은 구조:
  - 메인 스레드: threading.Event를 대기 없이 계속 확인 (SASAFL.py 20–29행의 busy-wait)
                 Event가 켜지면 CNN_Mnist 학습 몇 스텝 수행
  - 수신 스레드: 버퍼 텐서를 채우고(dist.recv 대신 copy_), 잘라서 state_dict에 unpack,
                 load_state_dict 후 Event를 켬 (SASAFLClient.py 42–77행)
  - 프로세스별 torch.set_num_threads를 논문 카테고리(1,2,3,4,8)로 지정, 30개 동시 실행

각 프로세스는 Event 객체가 다른 타입으로 바뀌면(SASAFL에서 본 증상) 즉시 보고한다.
사용법: python thread_pattern_repro.py [초=300] [프로세스 수=30]
"""

import multiprocessing as mp
import os
import random
import sys
import threading
import time


def client(idx, threads, seconds, queue):
    sys.path.insert(0, os.environ.get("FEDMPI_REPO", "."))
    import torch
    from model_controller import CNN_Mnist
    from utils.model_utils import TensorBuffer

    torch.set_num_threads(threads)
    model = CNN_Mnist.Model()
    received = CNN_Mnist.Model()
    sd = model.state_dict()
    flat = TensorBuffer(list(sd.values()))
    info = torch.zeros(len(flat.buffer) + 3)
    source = torch.randn(len(flat.buffer) + 3)
    ongoing = threading.Event()
    stop = threading.Event()
    counters = {"recv": 0, "train": 0}

    def receiver():
        while not stop.is_set():
            info.copy_(source)                       # dist.recv 대신
            flat.buffer = info[:-3]
            flat.unpack(sd.values())
            if ongoing.is_set():
                received.load_state_dict(sd)          # 학습 중 교체 경로
            else:
                model.load_state_dict(sd)
                ongoing.set()
            counters["recv"] += 1
            time.sleep(random.uniform(0.0, 0.05))

    t = threading.Thread(target=receiver, daemon=True)
    t.start()
    opt = torch.optim.SGD(model.parameters(), lr=0.01, momentum=0.9)
    loss_fn = torch.nn.CrossEntropyLoss()
    x = torch.randn(32, 1, 28, 28)
    y = torch.randint(0, 10, (32,))
    end = time.time() + seconds
    status = "ok"
    try:
        while time.time() < end:                       # SASAFL.py 20–29행과 같은 busy-wait
            if not isinstance(ongoing, threading.Event):
                status = f"CORRUPTED: Event가 {type(ongoing).__name__}로 바뀜"
                break
            if ongoing.is_set():
                for _ in range(3):
                    opt.zero_grad()
                    loss_fn(model(x), y).backward()
                    opt.step()
                counters["train"] += 1
                ongoing.clear()
    except Exception as exc:  # noqa: BLE001
        status = f"EXCEPTION: {type(exc).__name__}: {exc}"
    stop.set()
    queue.put((idx, threads, status, counters["recv"], counters["train"]))


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 300
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    cats = [1, 2, 3, 4, 8] * (n // 5)
    random.shuffle(cats)
    queue = mp.Queue()
    procs = [mp.Process(target=client, args=(i, cats[i], seconds, queue)) for i in range(n)]
    for p in procs:
        p.start()
    deadline = time.time() + seconds + 120
    results = []
    while len(results) < n and time.time() < deadline:
        try:
            results.append(queue.get(timeout=5))
        except Exception:  # noqa: BLE001
            if all(not p.is_alive() for p in procs):
                break
    for p in procs:
        p.join(timeout=10)
    bad = [r for r in results if r[2] != "ok"]
    died = [(i, p.exitcode) for i, p in enumerate(procs) if p.exitcode not in (0, None)]
    print(f"host={os.uname().nodename} procs={n} seconds={seconds} total_threads={sum(cats)}")
    print(f"reported={len(results)} abnormal_reports={len(bad)} died={died}")
    for r in bad[:10]:
        print("  ", r)
    print(f"total_recv={sum(r[3] for r in results)} total_train={sum(r[4] for r in results)}")
    print("RESULT:", "PASS" if not bad and not died and len(results) == n else "FAIL")


if __name__ == "__main__":
    main()
