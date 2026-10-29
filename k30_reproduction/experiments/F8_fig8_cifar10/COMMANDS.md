# Fig. 8 (CIFAR-10, K=30) 실험 명령 (wise-175 · wise-176)

이 파일은 그림 감시 프로세스가 `runs/*/cmd.txt`와 `config.json`에서 자동으로 다시 만든다.

## 공통 준비

wise-176 코드를 175와 같은 커밋으로 맞춘다 (실행기는 매 실행 전에 두 노드의 git HEAD 일치·코드 무수정·터보 꺼짐을 확인한다):

```bash
# wise-175
cd /home/wise-175/Mando/FedMPI && git push origin main
# wise-176
cd /home/wise-176/Mando/FedMPI && git fetch origin main && git checkout -f -B main origin/main
```

실험 전체 시작/재개 (wise-175에서만 실행. 176 쪽 프로세스는 launch.sh가 ssh로 띄운다):

```bash
# wise-175
bash /home/wise-175/Mando/FedMPI/k30_reproduction/fig7/start_fig7.sh   # tmux 세션 fig7
#   내부: python -u k30_reproduction/fig7/run_fig7.py  → Fig.7 10회 → Fig.8 10회, 실행마다 아래 launch.sh 호출
```

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

## 실행별 명령


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
