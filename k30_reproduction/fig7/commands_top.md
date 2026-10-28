## `--cluster_type`: WISE와 KISTI의 차이, 그리고 이 실험이 KISTI를 쓴 이유

`Start.py`의 `--cluster_type`은 **클라이언트마다 CPU 스레드 수를 정하는 방식**만 바꾼다. 데이터 분할, 모델, 학습, 통신 코드 경로는 두 값에서 똑같다.

| 구분 | `--cluster_type=KISTI` (이 실험) | `--cluster_type=WISE` |
|---|---|---|
| 스레드 수를 정하는 곳 | 실행 인자 `--num_threads` (숫자 하나 = 프로세스 하나) | 서버가 실행 중에 정해서 클라이언트에 보냄 |
| 코드 경로 | `Start.py` 41–44행: `torch.set_num_threads(int(args.num_threads[LOCAL_RANK]))`<br>`FedAvgServer.setup`·`FedAvgClient.setup`의 `if cluster_type == "WISE"` 분기를 건너뜀 | `FedAvgServer.setup` 63–64행 → `send_omp_num_threads_to_clients()`<br>`FedAvgClient.setup` 51–52행 → `receive_omp_num_threads_from_server()` → `torch.set_num_threads(...)` |
| 스레드 배치 | 실행 스크립트가 정한 그대로. 이 실험은 논문 5.1절대로 **1·2·3·4·8코어 × 각 6명**을 섞어 두 노드에 나눔 | `utils/utils.py omp_num_threads_per_clients()`: **[1, 2, 5]를 차례로 반복한 뒤 섞음** → 카테고리 3개, 1·2·5코어 × 10명 |
| 논문 조건과 맞는가 | 맞음 (K=30: 5개 카테고리 1, 2, 3, 4, 8코어 × 6명) | 맞지 않음 (카테고리 수·코어 수가 다름) |
| 원저자가 쓴 곳 | `KISTI_jobscript/server.sh`, `client.sh`: Nurion(KISTI) 논문 실험 스크립트가 `--cluster_type=KISTI --num_threads=...`로 실행 | 연구실 WISE 서버용 |

**이 실험은 `--cluster_type=KISTI`를 쓴다.** 논문 실험을 돌린 KISTI Nurion 환경과 같은 코드 경로·같은 클라이언트 스레드 배치를 쓰기 위해서다.

원저자 KISTI 스크립트와 이 실험의 실행 방식은 다음처럼 같다.

| 항목 | 원저자 KISTI 스크립트 (`KISTI_jobscript/*.sh`) | 이 실험 (`k30_reproduction/launch.sh two`) |
|---|---|---|
| 노드 수 | 2 (`#PBS -l select=2`) | 2 (wise-175, wise-176) |
| 실행 방식 | 노드마다 `torchrun --nnodes=2 --node_rank=…`, 서버 노드는 `nproc_per_node+1` | 같음 |
| 통신 | gloo (`GLOO_SOCKET_IFNAME` 지정) | 같음 |
| 스레드 목록 | `num_threads_list=(1×6, 2×6, 3×6, 4×6, 8×6)`을 `shuf`로 섞음, 서버는 맨 앞 `1` | 같은 목록을 `shuf`로 섞음, 서버는 맨 앞 `1` |
| 고정 인자 | `--batch_size=32 --local_epochs=5 --cluster_type=KISTI` | 같음 |
| 노드별 클라이언트 수 | 노드 코어(68) 한도까지 앞 노드부터 채움 | 카테고리마다 3명씩 두 노드에 반씩 (175: 서버 + 15, 176: 15) |
| lag tolerance | 인자를 넘기지 않아 `Start.py` 기본값 2 | 논문 5.2절대로 `--lag_tolerance=9` (SAFA는 5) |

마지막 두 줄이 원저자 스크립트와 다르다.
- 노드별 배치는 장비(노드당 논리 CPU 32개)에 맞춰 반씩 나눈 것이다. 학습 파라미터에는 영향이 없다.
- lag tolerance는 논문 본문 값을 따랐다.
