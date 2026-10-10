#!/usr/bin/env python3
"""E3: SASAFL 서버 코드를 그대로 호출해 crash 비고려를 결정적으로 증명한다.

분산 통신 없이 SASAFLServer 인스턴스의 메서드만 사용한다 (원본 코드 수정 없음).
  T1. 버퍼에 쌓인 로컬 모델 < P_r 이면 wait_until_can_update_global_model()은 반환하지 않는다
      (timeout·생존 확인 없음, busy-wait로 CPU 소모).
  T2. get_next_round_minimum_local_model()의 입력에는 '현재 연결된 클라이언트 수'가 없다.
      loss가 오르면 P_r은 연결 상태와 무관하게 K까지 증가한다.
  T3. send_global_model_to_clients()는 매 라운드 전체 클라이언트에게 blocking send를 한다.
"""

import inspect
import json
import sys
import threading
import time
from pathlib import Path

STUDY = Path(__file__).resolve().parents[1]
REPO = STUDY.parent
sys.path.insert(0, str(REPO))

from methods.SASAFL.SASAFLServer import SASAFLServer  # noqa: E402


def make_server(num_clients, ratio):
    # FLgroup은 이 테스트에서 사용되지 않는다 (생성자는 통신을 하지 않음)
    return SASAFLServer(num_clients, ratio, 32, 500, 1.0, "False", None)


def t1_wait_never_returns(observe_sec=15.0):
    server = make_server(10, 0.3)            # K=10, C=0.3 -> P_min=3
    p_r = int(server.num_clients * server.selection_ratio)
    # 차량 2대만 업로드에 성공하고 나머지는 연결이 끊긴 상황
    server.cached_client_idx = [1, 2]
    server.num_cached_local_model = 2

    result = {}

    def target():
        result["picked"] = server.wait_until_can_update_global_model(p_r)

    cpu_before = time.process_time()
    wall_before = time.time()
    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(observe_sec)
    wall = time.time() - wall_before
    cpu = time.process_time() - cpu_before
    return {
        "K": server.num_clients,
        "P_r": p_r,
        "buffered_local_models": 2,
        "connected_clients": 2,
        "observe_sec": round(wall, 2),
        "returned": not worker.is_alive(),
        "cpu_sec_consumed": round(cpu, 2),
        "cpu_utilisation_pct": round(100 * cpu / wall, 1),
    }


def t2_quota_ignores_connectivity():
    signature = str(inspect.signature(SASAFLServer.get_next_round_minimum_local_model))
    server = make_server(100, 0.1)           # K=100, C=0.1 -> P_min=10
    p_min = int(server.num_clients * server.selection_ratio)
    # 차량 이탈로 연결된 클라이언트 수가 라운드마다 4대씩 줄어드는 시나리오 (가정)
    connected = [100 - 4 * r for r in range(12)]
    # 가정: stale 업데이트로 global loss가 라운드마다 30%씩 상승하는 발산 구간
    losses = [round(2.40 * 1.3 ** (r + 1), 3) for r in range(12)]
    server.last_global_loss = 2.40
    p_r = p_min
    trace = []
    for r, (loss, alive) in enumerate(zip(losses, connected)):
        p_next = server.get_next_round_minimum_local_model(loss, p_r, p_min)
        trace.append({
            "round": r + 1,
            "global_loss": loss,
            "P_r": p_r,
            "P_next": p_next,
            "connected": alive,
            "deadlock_if_no_buffer": p_next > alive,
        })
        p_r = p_next
    return {"signature": signature, "K": 100, "P_min": p_min, "trace": trace}


def t3_send_to_all_source():
    source = inspect.getsource(SASAFLServer.send_global_model_to_clients)
    wait_source = inspect.getsource(SASAFLServer.wait_until_can_update_global_model)
    quota_source = inspect.getsource(SASAFLServer.get_next_round_minimum_local_model)
    return {"send_global_model_to_clients": source,
            "wait_until_can_update_global_model": wait_source,
            "get_next_round_minimum_local_model": quota_source}


def main():
    out = STUDY / "results" / "E3_code_level"
    out.mkdir(parents=True, exist_ok=True)
    t1 = t1_wait_never_returns()
    print("[T1]", json.dumps(t1, ensure_ascii=False))
    t2 = t2_quota_ignores_connectivity()
    print("[T2] signature:", t2["signature"])
    for row in t2["trace"]:
        print("     ", row)
    t3 = t3_send_to_all_source()
    (out / "T1_wait_never_returns.json").write_text(json.dumps(t1, indent=2, ensure_ascii=False))
    (out / "T2_quota_trace.json").write_text(json.dumps(t2, indent=2, ensure_ascii=False))
    for name, src in t3.items():
        (out / f"T3_source_{name}.py.txt").write_text(src)
    print(f"[+] saved to {out}")


if __name__ == "__main__":
    main()
