## 논문 파라미터 vs 이 실험 파라미터 (Fig. 7, K=30)

출처 표기:
- `§5.1`: 논문 5.1절 Experiment setup
- `§5.2`: 5.2절 Experiment results
- `Alg.2`, `Eq.(2)`: 논문 알고리즘·식 번호
- `Fig.7`: 그림 캡션

논문: Yu et al., *Staleness aware semi-asynchronous federated learning*, JPDC 193 (2024) 104950.

### 1) 데이터셋에 따라 달라지는 파라미터

| 파라미터 | 논문 MNIST | 이 실험 MNIST | 논문 FashionMNIST | 이 실험 FashionMNIST | 일치 |
|---|---|---|---|---|---|
| 학습률 (lr) | 0.01 (§5.1) | `--lr=0.01` | 0.001 (§5.1) | `--lr=0.001` | ✅ |
| 라운드 수 | 500 (§5.1) | `--round=500` | 500 (§5.1) | `--round=500` | ✅ |
| 모델 | [2](McMahan et al.)의 CNN, MNIST·FashionMNIST 동일 모델 (§5.1) | `model_controller/CNN_Mnist` | 같은 모델 (§5.1) | `CNN_Mnist` (`FedAvgServer.setup`: FashionMNIST → CNN_Mnist) | ✅ |
| 목표 정확도 (Table 2 지표용) | 95% (§5.2) | 학습은 500R까지 모두 돌고(`--target_acc=1.0`, 원저자 KISTI 스크립트와 같음) 95%는 사후 계산 | 70% (§5.2) | 같은 방식, 70% | ✅ |
| 데이터 분할 | non-IID, 크기 가우시안, 레이블 순 정렬 후 순차 배정, 클라이언트당 1–2개 레이블 (§5.1) | `--iid=False --split=gaussian` | 같음 | 같음 | ✅ |
| 가우시안 표준편차 | 논문 미기재 | 400 (원저자 `utils/data_utils.py`) | 논문 미기재 | 400 (같은 파일) | — (원저자 코드값) |

### 2) 데이터셋과 무관한 공통 파라미터

| 파라미터 | 논문 | 이 실험 | 일치 |
|---|---|---|---|
| 전체 클라이언트 수 K | 30 (§5.1, Fig.7 왼쪽 열) | 30 (`nproc` 16 + 15, 서버 제외 30) | ✅ |
| CPU 카테고리 | 1·2·3·4·8코어, 카테고리당 6명 (§5.1) | `--num_threads` = `1·2·3·4·8 × 6`을 섞은 값, `--cluster_type=KISTI` | ✅ |
| 참여 비율 C | 0.1, 0.3, 0.5 (§5.1) | `--selection_ratio=0.1/0.3/0.5` | ✅ |
| 최소 참여 수 P_min | C·K (Alg.2) = 3, 9, 15 | `int(C·K)` = 3, 9, 15 (원저자 코드) | ✅ |
| 배치 크기 | 32 (§5.1) | `--batch_size=32` | ✅ |
| local epoch E | 5 (§5.1) | `--local_epochs=5` | ✅ |
| 최소 local epoch | E/2 (§5.1) | 2 (원저자 `SASAFLClient.train`: `current_local_epoch < 2`이면 2) | ✅ (E/2=2.5를 정수 epoch으로) |
| lag tolerance τ (SASAFL) | 9 (§5.2) | `--lag_tolerance=9` | ✅ |
| lag tolerance τ (SAFA) | 5 (§5.2, SAFA 원 논문 권장값) | `--lag_tolerance=5` | ✅ |
| lag tolerance τ (BSA) | BSA에는 수신 정책이 없음 (§5.1 Benchmarks) | 인자 9를 넘기지만 `SemiAsync`는 사용하지 않음 | ✅ |
| decay coefficient ζ | 0.9 (Eq.(2), §5.1) | 0.9 (원저자 `SASAFLServer`/`SemiAsyncServer.refine_received_local_model`) | ✅ |
| staleness 보정 | Eq.(2), SASAFL·BSA 공통 (§5.1) | 원저자 코드 그대로 | ✅ |
| 반복 횟수 | 설정당 10회 평균 (§5.1) | 설정당 10회, 그림은 회차 평균 | ✅ |
| 그래프 표시 간격 | 5라운드마다 (Fig.7 캡션) | 5라운드마다 | ✅ |
| 통신 백엔드 | PyTorch distributed, gloo (§5.1) | gloo | ✅ |
| PyTorch 버전 | 1.12 (§5.1) | 1.12.1 | ✅ |
| 노드 수 | 원저자 KISTI 스크립트: 2 노드 | 2 노드 (wise-175 + wise-176) | ✅ |
| 통신 지연 주입 | 언급 없음 | 없음 (`--comm_hetero` 기본값 False, 원저자 코드) | ✅ |
| 옵티마이저 | 논문 미기재 | SGD, momentum 0.9 (원저자 `*Client.train`) | — (원저자 코드값) |
| 가중치 초기화 | 논문 미기재 | Xavier normal (원저자 `utils/model_utils.init_weight`) | — (원저자 코드값) |
| 테스트 배치 | 논문 미기재 | `--batch_size`와 같은 32 (원저자 `FedAvgServer.evaluate`) | — (원저자 코드값) |
| 하드웨어 | Nurion KNL, 노드당 68코어 (§5.1) | Intel i9-14900KF, 노드당 논리 CPU 32개 | ❌ 장비 차이 (대체 불가) |

### 3) SAFA 파라미터

| 파라미터 | 논문 (SASAFL 논문 §5.2, Fig.6 조건) | SAFA (저장소 구현) | SAFAfix (수정판) |
|---|---|---|---|
| lag tolerance | 5 | 5 | 5 |
| 학습률 / 배치 | Fig.6(SAFA 비교)에서는 lr 0.001, batch 40. Fig.7에는 SAFA가 없음 | 0.001 / 40 (클라이언트에 고정, 원저자 코드) | Fig.7 조건 그대로 (MNIST 0.01, FMNIST 0.001 / 32) |
| quota | C·K | `int(K·C)` | `int(K·C)` |
| 충돌 확률 | 논문 미기재 | 클라이언트별 매 라운드 0.1 (원저자 `generate_crash_trace`) | 같음 |
| 라운드 마감 T_lim | 논문 미기재 | 5000초 (원저자 `SAFAServer`) | 같음 |

## 임의로 정한 파라미터가 없음을 보여주는 표

학습 결과에 영향을 주는 값을 모두 적고, 각 값의 출처를 분류했다.
- **A**: 논문 본문에 명시
- **B**: 논문에 없어서 원저자 코드(`c0b819b`)·원저자 KISTI 스크립트의 값을 그대로 씀
- **C**: 이 실험에서 정한 값

| 값 | 쓰인 값 | 출처 | 분류 |
|---|---|---|---|
| K | 30 | §5.1 | A |
| CPU 카테고리 | 1·2·3·4·8 × 6 | §5.1 | A |
| C | 0.1 / 0.3 / 0.5 | §5.1 | A |
| P_min | C·K | Alg.2 | A |
| lr | MNIST 0.01, FashionMNIST 0.001 | §5.1 | A |
| batch | 32 | §5.1 | A |
| E | 5 | §5.1 | A |
| 최소 local epoch | E/2 → 2 | §5.1, 원저자 `SASAFLClient` | A |
| τ (SASAFL) | 9 | §5.2 | A |
| τ (SAFA) | 5 | §5.2 | A |
| ζ | 0.9 | Eq.(2), §5.1 | A |
| 라운드 | 500 | §5.1 | A |
| 반복 | 10 | §5.1 | A |
| 데이터 분할 | non-IID, gaussian | §5.1 | A |
| 목표 정확도(지표) | 95% / 70% | §5.2 | A |
| 표시 간격 | 5라운드 | Fig.7 캡션 | A |
| 가우시안 표준편차 | 400 | 원저자 `utils/data_utils.py` | B |
| 옵티마이저 | SGD, momentum 0.9 | 원저자 클라이언트 코드 | B |
| 가중치 초기화 | Xavier normal | 원저자 `init_weight` | B |
| `--target_acc` | 1.0 (끝까지 학습) | 원저자 KISTI 스크립트 | B |
| `--cluster_type` | KISTI | 원저자 KISTI 스크립트 | B |
| `--comm_hetero` | False | 원저자 기본값 | B |
| SAFA 충돌 확률 / T_lim | 0.1 / 5000초 | 원저자 SAFA 코드 | B |
| SAFA(저장소) lr·batch | 0.001 / 40 | 원저자 SAFA 코드 (= 논문 Fig.6 조건) | B |
| SAFAfix lr·batch | Fig.7 조건과 같음 | §5.1 (Fig.7 조건 적용) | A |
| **임의 설정 값 (C)** | **없음** | — | — |

### 이 실험에서 정한 실행 환경 값 (논문에 없음)

아래 네 값은 논문에 없고, 이 장비에서 돌리기 위해 정한 값이다. 학습 하이퍼파라미터는 아니지만, **노드별 배치는 결과에 영향을 줄 수 있다.**

| 항목 | 값 | 왜 이렇게 했나 | 원저자 KISTI 스크립트 | 결과에 영향 |
|---|---|---|---|---|
| 노드별 클라이언트 배치 | 175: 서버 + 15, 176: 15 (카테고리당 3명씩) | 이 장비는 노드당 논리 CPU가 32개(176은 30개)라 스레드 109개를 어떻게 나눠도 과다할당이 된다. 반씩 나누면 노드당 스레드가 55·54개로 가장 고르게 낮아진다 | 섞은 스레드 목록을 앞 노드부터 노드 코어(68) 한도까지 채움. KNL 노드에서는 과다할당이 없음 | **있음.** 노드의 CPU 경합이 클라이언트 학습 속도를 바꾸고, 속도가 도착 순서와 집계 참여 구성을 바꾼다(단일 노드 109스레드 → 두 노드 반반으로 바꿨을 때 SASAFL 결과가 달라진 것이 이 효과) |
| 포트·실행 ID | 29900번대, 실행마다 다른 ID | 같은 장비에서 실행을 연달아 띄울 때 포트·rendezvous가 겹치지 않게 | 포트는 무작위(`RANDOM%55535+10000`), `rdzv_id=0` | 없음 (통신 주소일 뿐) |
| `OMP_NUM_THREADS` 등 | 1 | 프로세스가 기본 스레드 수를 시작값으로 갖지 않게. 실제 스레드 수는 `Start.py`가 `--num_threads`의 숫자로 `torch.set_num_threads`를 호출해 정한다 | 지정 안 함. `torchrun`은 노드당 프로세스가 여럿이면 기본으로 `OMP_NUM_THREADS=1`을 넣음 | 없음 (원저자 실행과 같은 결과값) |
| `SYNC_SOURCE` | 0 | `launch.sh`가 실행마다 코드를 tar로 176에 복사하지 않게. 코드는 git으로 같은 커밋을 맞추고 실행 전에 검사한다 | 두 노드가 같은 `/scratch` 공유 디렉터리의 코드를 씀 | 없음 (두 노드가 같은 코드를 쓴다는 점은 같음) |
