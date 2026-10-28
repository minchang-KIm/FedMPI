## 논문 파라미터 vs 이 실험 파라미터 (Fig. 8, CIFAR-10, K=30)

논문: Yu et al., *Staleness aware semi-asynchronous federated learning*, JPDC 193 (2024) 104950.
코드와 실행 환경은 Fig. 7과 같다 (`F7_fig7_safa/COMMANDS.md`의 공통 표 참고). 아래는 Fig. 8에서 정해지는 값이다.

| 인자 | 값 | 근거 |
| --- | --- | --- |
| `--dataset` | CIFAR10 | Fig.8 캡션, §5.1 |
| `--method` | `SemiAsync` (BSA) / `SASAFL` | Fig.8 캡션, §5.1 Benchmarks |
| `--selection_ratio` | 0.1 / 0.3 / 0.5 | Fig.8 캡션, §5.1 |
| `--round` | 3000 | §5.1 |
| `--lr` | 0.001 | §5.1 |
| `--batch_size` | 32 | §5.1, 원저자 KISTI 스크립트 |
| `--local_epochs` | 5 | §5.1, 원저자 KISTI 스크립트 |
| `--lag_tolerance` | 9 | §5.2 |
| `--iid` / `--split` | False / gaussian (표준편차 300, 원저자 `utils/data_utils.py`) | §5.1 |
| `--target_acc` | 1.0 (55%는 사후 지표) | 원저자 KISTI 스크립트, §5.2 |
| `--cluster_type` | KISTI | `KISTI_jobscript/cifar10_jobscript.sh` |
| `--num_threads` | 서버 `1` + 1·2·3·4·8 × 6 셔플 | §5.1, `cifar10_jobscript.sh:22` |
| 프로세스 수 | 클라이언트 30 + 서버 1 | Fig.8 캡션 (a) K=30, §5.1 |
| 반복 | 설정당 10회, 그림은 회차 평균 | §5.1 |
| 그래프 표시 간격 | 10라운드마다 | Fig.8 캡션 |
| `--comm_hetero` | False | 논문 언급 없음, 원저자 기본값 |
| 모델 | `model_controller/CNN_Cifar10` (원저자 코드) | §5.1 |

Fig. 8의 K=100 열은 돌리지 않는다 (이 장비 두 노드에 101개 프로세스를 올리면 과다할당이 더 커진다).
