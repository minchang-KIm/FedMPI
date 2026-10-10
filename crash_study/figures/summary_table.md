| 시나리오 | 장애 | 완료 라운드 | 재시작 | 결과 | 마지막 진행 후 정지 시간(초) | 종료 시 서버 위치 |
|---|---|---:|---:|---|---:|---|
| E0 장애 없음 (기준선) | - | 30 | 0 | 정상 종료 | 5.8 | - |
| E1 차량 1대 hard crash (SIGKILL) | KILL rank [3] @round 5 | 5 | 0 | job 전체 비정상 종료 (exit 1) | 0.7 | - |
| E1b hard crash + torchrun 재시작 허용 | KILL rank [3] @round 5 | 24 | 1 | 진행 정지 → 관측 종료 후 강제 종료 | 70.5 | [background] SASAFLServer.py 37 in receive_local_model_from_any_clients / [main] SASAFLServer.py 59 in wait_until_can_update_global_model ← SASAFL.py 60 in runServer |
| E2a 차량 1대 silent drop (SIGSTOP) | STOP rank [3] @round 5 | 6 | 0 | 진행 정지 → 관측 종료 후 강제 종료 | 482.3 | [background] SASAFLServer.py 37 in receive_local_model_from_any_clients / [main] distributed_c10d.py 959 in send ← SASAFLServer.py 112 in send_global_model_to_clients |
| E2b 생존 4대 < P_min 5 (SIGSTOP 6대) | STOP rank [5, 6, 7, 8, 9, 10] @round 5 | 6 | 0 | 진행 정지 → 관측 종료 후 강제 종료 | 477.6 | [background] SASAFLServer.py 37 in receive_local_model_from_any_clients / [main] distributed_c10d.py 959 in send ← SASAFLServer.py 114 in send_global_model_to_clients |
| E2c silent drop + gloo timeout 90초 | STOP rank [3] @round 5 | 6 | 0 | job 전체 비정상 종료 (exit 1) | 123.6 | - |
