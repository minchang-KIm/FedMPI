# Fig. 7 (K=30) + SAFA 실험 명령 (wise-175 · wise-176)

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

### F7_MNIST_BSA_C0.1_rep1

- 방법 BSA (`--method=SemiAsync`), MNIST, C=0.1, lr=0.01, τ=9, 시작 2026-10-29T00:08:03, git `c8c5eba`, 상태: completed 500라운드, 35.43분

wise-175 (실행기가 호출한 launcher):

```bash
ROUNDS=500 DATASET=MNIST IID=False SPLIT=gaussian LEARNING_RATE=0.01 BATCH_SIZE=32 LOCAL_EPOCHS=5 TARGET_ACCURACY=1.0 LAG_TOLERANCE=9 K30_SASAFL_SRC= K30_TRACE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 SYNC_SOURCE=0 MASTER_PORT=29901 RUN_ID=F7_MNIST_BSA_C0.1_rep1_1793200083 \
  bash /home/wise-175/Mando/FedMPI/k30_reproduction/launch.sh SemiAsync 0.1 30 two 1,2,3,4,8
```

wise-175 (node_rank 0: 서버 + 클라이언트 15개, cwd /home/wise-175/Mando/FedMPI):

```bash
/home/wise-175/anaconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=16 --node_rank=0 --rdzv_id=F7_MNIST_BSA_C0.1_rep1_1793200083 --rdzv_endpoint=210.107.197.175:29901 --master_addr=210.107.197.175 --master_port=29901 k30_reproduction/harness_entry.py --selection_ratio=0.1 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SemiAsync --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=1883434831241221
```

wise-176 (node_rank 1: 클라이언트 15개, cwd /home/wise-176/Mando/FedMPI, launch.sh가 ssh로 실행):

```bash
/home/wise-176/miniconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=15 --node_rank=1 --rdzv_id=F7_MNIST_BSA_C0.1_rep1_1793200083 --rdzv_endpoint=210.107.197.175:29901 --master_addr=210.107.197.175 --master_port=29901 k30_reproduction/harness_entry.py --selection_ratio=0.1 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SemiAsync --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=382322344148811
```

### F7_MNIST_SASAFL_C0.1_rep1

- 방법 SASAFL (`--method=SASAFL`), MNIST, C=0.1, lr=0.01, τ=9, 시작 2026-10-29T00:43:56, git `c8c5eba`, 상태: completed 500라운드, 70.21분

wise-175 (실행기가 호출한 launcher):

```bash
ROUNDS=500 DATASET=MNIST IID=False SPLIT=gaussian LEARNING_RATE=0.01 BATCH_SIZE=32 LOCAL_EPOCHS=5 TARGET_ACCURACY=1.0 LAG_TOLERANCE=9 K30_SASAFL_SRC= K30_TRACE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 SYNC_SOURCE=0 MASTER_PORT=29902 RUN_ID=F7_MNIST_SASAFL_C0.1_rep1_1793202236 \
  bash /home/wise-175/Mando/FedMPI/k30_reproduction/launch.sh SASAFL 0.1 30 two 1,2,3,4,8
```

wise-175 (node_rank 0: 서버 + 클라이언트 15개, cwd /home/wise-175/Mando/FedMPI):

```bash
/home/wise-175/anaconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=16 --node_rank=0 --rdzv_id=F7_MNIST_SASAFL_C0.1_rep1_1793202236 --rdzv_endpoint=210.107.197.175:29902 --master_addr=210.107.197.175 --master_port=29902 k30_reproduction/harness_entry.py --selection_ratio=0.1 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SASAFL --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=1288434432123181
```

wise-176 (node_rank 1: 클라이언트 15개, cwd /home/wise-176/Mando/FedMPI, launch.sh가 ssh로 실행):

```bash
/home/wise-176/miniconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=15 --node_rank=1 --rdzv_id=F7_MNIST_SASAFL_C0.1_rep1_1793202236 --rdzv_endpoint=210.107.197.175:29902 --master_addr=210.107.197.175 --master_port=29902 k30_reproduction/harness_entry.py --selection_ratio=0.1 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SASAFL --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=284423281133418
```

### F7_MNIST_SAFA_C0.1_rep1

- 방법 SAFA (`--method=SAFA`), MNIST, C=0.1, lr=0.01, τ=5, 시작 2026-10-29T01:54:35, git `c8c5eba`, 상태: completed 500라운드, 249.65분

wise-175 (실행기가 호출한 launcher):

```bash
ROUNDS=500 DATASET=MNIST IID=False SPLIT=gaussian LEARNING_RATE=0.01 BATCH_SIZE=32 LOCAL_EPOCHS=5 TARGET_ACCURACY=1.0 LAG_TOLERANCE=5 K30_SASAFL_SRC= K30_TRACE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 SYNC_SOURCE=0 MASTER_PORT=29903 RUN_ID=F7_MNIST_SAFA_C0.1_rep1_1793206475 \
  bash /home/wise-175/Mando/FedMPI/k30_reproduction/launch.sh SAFA 0.1 30 two 1,2,3,4,8
```

wise-175 (node_rank 0: 서버 + 클라이언트 15개, cwd /home/wise-175/Mando/FedMPI):

```bash
/home/wise-175/anaconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=16 --node_rank=0 --rdzv_id=F7_MNIST_SAFA_C0.1_rep1_1793206475 --rdzv_endpoint=210.107.197.175:29903 --master_addr=210.107.197.175 --master_port=29903 k30_reproduction/harness_entry.py --selection_ratio=0.1 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SAFA --lag_tolerance=5 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=1421188243133824
```

wise-176 (node_rank 1: 클라이언트 15개, cwd /home/wise-176/Mando/FedMPI, launch.sh가 ssh로 실행):

```bash
/home/wise-176/miniconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=15 --node_rank=1 --rdzv_id=F7_MNIST_SAFA_C0.1_rep1_1793206475 --rdzv_endpoint=210.107.197.175:29903 --master_addr=210.107.197.175 --master_port=29903 k30_reproduction/harness_entry.py --selection_ratio=0.1 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SAFA --lag_tolerance=5 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=218424433138812
```

### F7_MNIST_BSA_C0.3_rep1

- 방법 BSA (`--method=SemiAsync`), MNIST, C=0.3, lr=0.01, τ=9, 시작 2026-10-29T06:04:41, git `c8c5eba`, 상태: completed 500라운드, 50.52분

wise-175 (실행기가 호출한 launcher):

```bash
ROUNDS=500 DATASET=MNIST IID=False SPLIT=gaussian LEARNING_RATE=0.01 BATCH_SIZE=32 LOCAL_EPOCHS=5 TARGET_ACCURACY=1.0 LAG_TOLERANCE=9 K30_SASAFL_SRC= K30_TRACE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 SYNC_SOURCE=0 MASTER_PORT=29904 RUN_ID=F7_MNIST_BSA_C0.3_rep1_1793221481 \
  bash /home/wise-175/Mando/FedMPI/k30_reproduction/launch.sh SemiAsync 0.3 30 two 1,2,3,4,8
```

wise-175 (node_rank 0: 서버 + 클라이언트 15개, cwd /home/wise-175/Mando/FedMPI):

```bash
/home/wise-175/anaconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=16 --node_rank=0 --rdzv_id=F7_MNIST_BSA_C0.3_rep1_1793221481 --rdzv_endpoint=210.107.197.175:29904 --master_addr=210.107.197.175 --master_port=29904 k30_reproduction/harness_entry.py --selection_ratio=0.3 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SemiAsync --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=1483338114222148
```

wise-176 (node_rank 1: 클라이언트 15개, cwd /home/wise-176/Mando/FedMPI, launch.sh가 ssh로 실행):

```bash
/home/wise-176/miniconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=15 --node_rank=1 --rdzv_id=F7_MNIST_BSA_C0.3_rep1_1793221481 --rdzv_endpoint=210.107.197.175:29904 --master_addr=210.107.197.175 --master_port=29904 k30_reproduction/harness_entry.py --selection_ratio=0.3 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SemiAsync --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=844313138224821
```

### F7_MNIST_SASAFL_C0.3_rep1

- 방법 SASAFL (`--method=SASAFL`), MNIST, C=0.3, lr=0.01, τ=9, 시작 2026-10-29T06:55:39, git `c8c5eba`, 상태: completed 500라운드, 97.31분

wise-175 (실행기가 호출한 launcher):

```bash
ROUNDS=500 DATASET=MNIST IID=False SPLIT=gaussian LEARNING_RATE=0.01 BATCH_SIZE=32 LOCAL_EPOCHS=5 TARGET_ACCURACY=1.0 LAG_TOLERANCE=9 K30_SASAFL_SRC= K30_TRACE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 SYNC_SOURCE=0 MASTER_PORT=29905 RUN_ID=F7_MNIST_SASAFL_C0.3_rep1_1793224539 \
  bash /home/wise-175/Mando/FedMPI/k30_reproduction/launch.sh SASAFL 0.3 30 two 1,2,3,4,8
```

wise-175 (node_rank 0: 서버 + 클라이언트 15개, cwd /home/wise-175/Mando/FedMPI):

```bash
/home/wise-175/anaconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=16 --node_rank=0 --rdzv_id=F7_MNIST_SASAFL_C0.3_rep1_1793224539 --rdzv_endpoint=210.107.197.175:29905 --master_addr=210.107.197.175 --master_port=29905 k30_reproduction/harness_entry.py --selection_ratio=0.3 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SASAFL --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=1144823331241882
```

wise-176 (node_rank 1: 클라이언트 15개, cwd /home/wise-176/Mando/FedMPI, launch.sh가 ssh로 실행):

```bash
/home/wise-176/miniconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=15 --node_rank=1 --rdzv_id=F7_MNIST_SASAFL_C0.3_rep1_1793224539 --rdzv_endpoint=210.107.197.175:29905 --master_addr=210.107.197.175 --master_port=29905 k30_reproduction/harness_entry.py --selection_ratio=0.3 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SASAFL --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=284814832432311
```

### F7_MNIST_SAFA_C0.3_rep1

- 방법 SAFA (`--method=SAFA`), MNIST, C=0.3, lr=0.01, τ=5, 시작 2026-10-29T08:33:24, git `c8c5eba`, 상태: completed 500라운드, 266.67분

wise-175 (실행기가 호출한 launcher):

```bash
ROUNDS=500 DATASET=MNIST IID=False SPLIT=gaussian LEARNING_RATE=0.01 BATCH_SIZE=32 LOCAL_EPOCHS=5 TARGET_ACCURACY=1.0 LAG_TOLERANCE=5 K30_SASAFL_SRC= K30_TRACE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 SYNC_SOURCE=0 MASTER_PORT=29906 RUN_ID=F7_MNIST_SAFA_C0.3_rep1_1793230404 \
  bash /home/wise-175/Mando/FedMPI/k30_reproduction/launch.sh SAFA 0.3 30 two 1,2,3,4,8
```

wise-175 (node_rank 0: 서버 + 클라이언트 15개, cwd /home/wise-175/Mando/FedMPI):

```bash
/home/wise-175/anaconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=16 --node_rank=0 --rdzv_id=F7_MNIST_SAFA_C0.3_rep1_1793230404 --rdzv_endpoint=210.107.197.175:29906 --master_addr=210.107.197.175 --master_port=29906 k30_reproduction/harness_entry.py --selection_ratio=0.3 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SAFA --lag_tolerance=5 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=1242431381183482
```

wise-176 (node_rank 1: 클라이언트 15개, cwd /home/wise-176/Mando/FedMPI, launch.sh가 ssh로 실행):

```bash
/home/wise-176/miniconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=15 --node_rank=1 --rdzv_id=F7_MNIST_SAFA_C0.3_rep1_1793230404 --rdzv_endpoint=210.107.197.175:29906 --master_addr=210.107.197.175 --master_port=29906 k30_reproduction/harness_entry.py --selection_ratio=0.3 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SAFA --lag_tolerance=5 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=832844311248123
```

### F7_MNIST_BSA_C0.5_rep1

- 방법 BSA (`--method=SemiAsync`), MNIST, C=0.5, lr=0.01, τ=9, 시작 2026-10-29T13:00:31, git `fbeb19a`, 상태: 진행 중

wise-175 (실행기가 호출한 launcher):

```bash
ROUNDS=500 DATASET=MNIST IID=False SPLIT=gaussian LEARNING_RATE=0.01 BATCH_SIZE=32 LOCAL_EPOCHS=5 TARGET_ACCURACY=1.0 LAG_TOLERANCE=9 K30_SASAFL_SRC= K30_TRACE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 SYNC_SOURCE=0 MASTER_PORT=29907 RUN_ID=F7_MNIST_BSA_C0.5_rep1_1793246431 \
  bash /home/wise-175/Mando/FedMPI/k30_reproduction/launch.sh SemiAsync 0.5 30 two 1,2,3,4,8
```

wise-175 (node_rank 0: 서버 + 클라이언트 15개, cwd /home/wise-175/Mando/FedMPI):

```bash
/home/wise-175/anaconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=16 --node_rank=0 --rdzv_id=F7_MNIST_BSA_C0.5_rep1_1793246431 --rdzv_endpoint=210.107.197.175:29907 --master_addr=210.107.197.175 --master_port=29907 k30_reproduction/harness_entry.py --selection_ratio=0.5 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SemiAsync --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=1134883141234228
```

wise-176 (node_rank 1: 클라이언트 15개, cwd /home/wise-176/Mando/FedMPI, launch.sh가 ssh로 실행):

```bash
/home/wise-176/miniconda3/envs/FL/bin/python -m torch.distributed.run --nnodes=2 --nproc_per_node=15 --node_rank=1 --rdzv_id=F7_MNIST_BSA_C0.5_rep1_1793246431 --rdzv_endpoint=210.107.197.175:29907 --master_addr=210.107.197.175 --master_port=29907 k30_reproduction/harness_entry.py --selection_ratio=0.5 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SemiAsync --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=312411884433822
```


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

### 3) 방법별 코드 (2026-10-28 공정 재시작 기준)

| 방법 | 코드 | 원저자 코드와 다른 점 |
|---|---|---|
| SASAFL | `methods/SASAFL` = 원저자 마지막 커밋 `c0b819b`와 바이트 단위로 같음 | 없음 (제안 기법 수정 f8fd198 제거, optimizer 수정 없음) |
| BSA | `methods/SemiAsyncFL` | 통신 지연 sleep 제거. 원저자 커밋 393fef1이 BSA 클라이언트에만 넣고 SASAFL에는 넣지 않은 코드라 공정성을 위해 뺐다 (comm_hetero=False면 0초라 원래도 결과 영향 없음) |
| SAFA | `methods/SAFA` | SAFA 저자 구현(wingter562/SAFA `semiAysnc_FedAvg.py`)에 맞춰 버그 수정: 글로벌 모델 적용, 클라이언트별 수신 칸, 집계 가중치 합 1, 전체 K개 캐시 집계, CFCFM 추정치·정렬, cross-rounder, 0라운드 처리, 학습 전 동기 수신 |

### 4) SAFA 파라미터

| 파라미터 | 논문 (SASAFL 논문 §5.2, Fig.6 조건) | 이 실험의 SAFA (`methods/SAFA`) |
|---|---|---|
| lag tolerance | 5 | 5 |
| 학습률 / 배치 | Fig.6(SAFA 비교)에서는 lr 0.001, batch 40. Fig.7에는 SAFA가 없음 | 0.001 / 40 (원저자 클라이언트 코드에 고정, 실행 인자와 무관) |
| quota | C·K | `int(K·C)` |
| 충돌 확률 | 논문 미기재 | 클라이언트별 매 라운드 0.1 (원저자 `generate_crash_trace`) |
| 라운드 마감 T_lim | 논문 미기재 | 5000초 (원저자 `SAFAServer`) |

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
| **임의 설정 값 (C)** | **없음** | — | — |

### 이 실험에서 정한 실행 환경 값 (논문에 없음)

아래 네 값은 논문에 없고, 이 장비에서 돌리기 위해 정한 값이다. 학습 하이퍼파라미터는 아니지만, **노드별 배치는 결과에 영향을 줄 수 있다.**

| 항목 | 값 | 왜 이렇게 했나 | 원저자 KISTI 스크립트 | 결과에 영향 |
|---|---|---|---|---|
| 노드별 클라이언트 배치 | 175: 서버 + 15, 176: 15 (카테고리당 3명씩) | 이 장비는 노드당 논리 CPU가 32개(176은 30개)라 스레드 109개를 어떻게 나눠도 과다할당이 된다. 반씩 나누면 노드당 스레드가 55·54개로 가장 고르게 낮아진다 | 섞은 스레드 목록을 앞 노드부터 노드 코어(68) 한도까지 채움. KNL 노드에서는 과다할당이 없음 | **있음.** 노드의 CPU 경합이 클라이언트 학습 속도를 바꾸고, 속도가 도착 순서와 집계 참여 구성을 바꾼다(단일 노드 109스레드 → 두 노드 반반으로 바꿨을 때 SASAFL 결과가 달라진 것이 이 효과) |
| 포트·실행 ID | 29900번대, 실행마다 다른 ID | 같은 장비에서 실행을 연달아 띄울 때 포트·rendezvous가 겹치지 않게 | 포트는 무작위(`RANDOM%55535+10000`), `rdzv_id=0` | 없음 (통신 주소일 뿐) |
| `OMP_NUM_THREADS` 등 | 1 | 프로세스가 기본 스레드 수를 시작값으로 갖지 않게. 실제 스레드 수는 `Start.py`가 `--num_threads`의 숫자로 `torch.set_num_threads`를 호출해 정한다 | 지정 안 함. `torchrun`은 노드당 프로세스가 여럿이면 기본으로 `OMP_NUM_THREADS=1`을 넣음 | 없음 (원저자 실행과 같은 결과값) |
| `SYNC_SOURCE` | 0 | `launch.sh`가 실행마다 코드를 tar로 176에 복사하지 않게. 코드는 git으로 같은 커밋을 맞추고 실행 전에 검사한다 | 두 노드가 같은 `/scratch` 공유 디렉터리의 코드를 씀 | 없음 (두 노드가 같은 코드를 쓴다는 점은 같음) |
