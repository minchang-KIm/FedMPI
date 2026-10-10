# 실험 결과 요약 — SASAFL과 차량 crash

- 실행: 2026-10-10, wise-175 단일 노드
- 환경: PyTorch 1.12.1, gloo, torchrun
- 원본 로그: `results/`
- 그림: `figures/`

## 1. 핵심 결론

| # | 주장 | 증거 | 판정 |
|---|---|---|---|
| 1 | 프로세스가 죽으면(hard crash) job 전체가 종료된다 | E1: SIGKILL 1.4초 후 11개 프로세스 전체 종료(exit 1). 서버가 먼저 `send_global_model_to_clients`에서 `Connection closed by peer` 예외로 죽었고, 이어서 torchrun이 나머지에 SIGTERM을 보냈다 | **확인** |
| 2 | torchrun 재시작은 복구가 아니다 | E1b: `--max_restarts=3`으로 재시작했더니 라운드가 0부터 다시 시작했다(글로벌 모델과 버퍼 유실). 실제 차량은 서버가 재기동할 수 없으므로, 이 재시작은 현실의 장애 모델과도 맞지 않는다 | **확인** |
| 3 | 프로세스는 살아 있는데 응답이 없으면(silent drop) 서버가 정지한다 | E2a: 차량 1대 SIGSTOP → 6라운드 이후 482초 동안 진행 0. 서버 메인 스레드는 `dist.send`(SASAFLServer.py 112행)에서 블록, CPU 0%. 나머지 9대도 새 모델을 받지 못했다 | **확인** |
| 4 | gloo timeout은 복구 수단이 아니다 | E2c: timeout을 90초로 줄였더니, 장애 100초 후 서버 send가 `Timed out waiting 90000ms for send operation` 예외로 죽었고 torchrun이 전체를 종료했다. 기본값(30분)이면 30분 정지 후 같은 결과가 된다 | **확인** |
| 5 | Pᵣ는 장애가 없어도 K에 도달하며, 그때 1대만 업로드하지 못해도 영구 대기한다 | E0: 30라운드 중 3회(19, 25, 29라운드) Pᵣ=K=10. E1b: 재시작 후 24라운드에서 Pᵣ=K=10인데 클라이언트 5·8이 업로드하지 못해 70초 이상 정지. 서버 스택은 `wait_until_can_update_global_model`(59행)이었고 CPU 100%(busy-wait) | **확인** (E1b의 클라이언트 5·8 미진행 원인은 미확인) |
| 6 | 대기 함수에 timeout, 생존 확인, 하한 조정이 없다 | E3-T1: 버퍼 2개, Pᵣ=3에서 15초 동안 반환하지 않았고 CPU 100%를 사용했다 | **확인** |
| 7 | quota 함수의 입력에 연결 상태가 없다 | E3-T2: 시그니처가 `(current_global_loss, current_num_picked_client, miminum_num_picked_client)`이다. loss가 오르면 연결 차량 수와 무관하게 K까지 증가한다 | **확인** |
| 8 | 끊김률이 오르면 SASAFL 규칙이 정지한다 | E4: K=100, 재접속 불가 조건에서 p_drop=2%면 C=0.5의 99.8%, C=0.3의 10%가 50라운드를 끝내지 못했다. 재접속 가능 조건에서는 정상상태 연결 비율 `p_back/(p_back+p_drop)`이 C 아래로 내려갈 때 급격히 정지했다. crash-aware 규칙 `min(Pᵣ, 연결 차량)`은 연결 차량이 0대가 되는 경우 말고는 정지하지 않았다 | **시뮬레이션** |

## 2. 실측 결과표

`figures/summary_table.md`와 같다. "정지 시간"은 마지막 라운드 이후 관측이 끝날 때까지의 시간이다.

| 시나리오 | 장애 | 완료 라운드 | 결과 | 정지 시간(초) | 종료 시 서버 위치 |
|---|---|---:|---|---:|---|
| E0 장애 없음 | - | 30 | 정상 종료 | - | - |
| E1 hard crash 1대 | SIGKILL rank 3 @5R | 5 | job 전체 종료 (exit 1) | - | `send_global_model_to_clients`에서 예외 |
| E1b hard crash + 재시작 | SIGKILL rank 3 @5R | 24 (재시작 후) | 정지 → 관측 종료 | 70.5 | `wait_until_can_update_global_model` 59행 (busy-wait) |
| E2a silent drop 1대 | SIGSTOP rank 3 @5R | 6 | 정지 → 관측 종료 | 482.3 | `dist.send` ← `send_global_model_to_clients` 112행 |
| E2b 생존 4 < P_min 5 | SIGSTOP 6대 @5R | 6 | 정지 → 관측 종료 | 477.6 | `dist.send` ← `send_global_model_to_clients` 114행 |
| E2c silent drop + timeout 90초 | SIGSTOP rank 3 @5R | 6 | job 전체 종료 (exit 1) | - | send timeout 예외 |

## 3. 해석

- **두 층의 문제가 겹쳐 있다.**
  1. 통신과 런처 층: torchrun의 gang 실패 semantics, gloo의 재접속 불가와 30분 timeout, 서버의 전체 대상 blocking send
  2. 알고리즘 층: P_min과 Pᵣ에 대응하는 "살아있는 차량 수" 개념이 없음
- 통신 층을 고쳐도(예외 처리, 비동기 send, timeout) 알고리즘 층의 문제(Pᵣ > 생존 차량 → 영구 대기)는 그대로 남는다. 반대로 알고리즘에 `min(Pᵣ, alive)`를 넣어도, torch.distributed는 죽은 rank를 다시 붙일 수 없으므로 실제 차량 환경을 재현할 수 없다.
  - **그래서 코드 수정은 임시방편이다.**
- E2b는 "생존 < P_min" 상황을 의도했다. 하지만 이 testbed에서는 서버가 정지한 차량에게 보내는 send에서 **먼저** 블록되기 때문에, P_min 대기가 따로 드러나지 않았다. 알고리즘 측 결함은 E3(코드 직접 호출)과 E1b(실측 스택: `wait_until_can_update_global_model`)로 입증된다.

## 4. 한계

- 실측은 K=10 단일 노드에서 했다. 다만 실패 경로는 규모와 무관한 코드 경로다.
- SIGSTOP은 네트워크 단절의 근사다. 실제 무선 단절에서는 커널 TCP keepalive와 재전송 동작이 다를 수 있다. 다만 gloo는 재접속을 지원하지 않으므로 결론은 바뀌지 않는다.
- E4는 sweep 변수 기반 모델이다. 실제 차량 연결 통계는 아니다.
- E1b에서 재시작 후 클라이언트 5·8이 학습을 진행하지 못한 원인은 확인하지 않았다(클라이언트 스택 미수집).
