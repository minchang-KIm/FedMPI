#!/usr/bin/env bash
# K=30 논문 재현 launcher (단일 노드 / 두 노드, CPU 카테고리 지정 가능)
#
# 사용법: launch.sh METHOD C K MODE CATEGORIES
#   METHOD     : SASAFL | SemiAsync (논문의 BSA)
#   C          : 최소 참여 비율 (0.1 | 0.3 | 0.5)
#   K          : 클라이언트 수
#   MODE       : single (wise-175에 서버+K 클라이언트) | two (175: 서버+K/2, 176: K/2)
#   CATEGORIES : 클라이언트당 thread 수 카테고리, 쉼표 구분 (논문 K=30: 1,2,3,4,8)
#                K는 카테고리 수로 나누어떨어져야 한다. two 모드에서는 카테고리별 인원도 짝수여야 한다.
# 환경변수: ROUNDS DATASET IID SPLIT LEARNING_RATE BATCH_SIZE LOCAL_EPOCHS TARGET_ACCURACY LAG_TOLERANCE
#          MASTER_PORT RUN_ID K30_PID_DIR SYNC_SOURCE K30_SASAFL_SRC·K30_TRACE(두 노드 모두 적용) CMD_FILE(실행 명령 저장)
#          CPU_LIST (single 모드: 이 CPU들에만 고정, 예: 176에서 결함 코어 24(CPU 12,13) 제외 → 0-11,14-31)
#
# ── Fig.7(K=30) SASAFL 실험에서 launch.sh가 최종적으로 Start.py에 넘긴 명령 (two 모드) ──────────────
# launch.sh → torchrun이 노드마다 프로세스를 띄움 → 각 프로세스가 harness_entry.py로 Start.py를 아래 인자 그대로 실행
# (torchrun이 RANK·LOCAL_RANK·WORLD_SIZE=31·MASTER_ADDR=210.107.197.175·MASTER_PORT를 넣고,
#  launch.sh가 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONUNBUFFERED=1을 넣는다.
#  Start.py는 --num_threads의 LOCAL_RANK번째 숫자로 torch.set_num_threads를 정한다)
#
# [F7_MNIST_SASAFL_ON_C0.1_rep1] 제안 기법 적용 (현재 methods/SASAFL/SASAFL.py)
#   wise-175 (cwd /home/wise-175/Mando/FedMPI, 16개 프로세스: LOCAL_RANK 0 = 서버, 1–15 = 클라이언트)
#     python Start.py --selection_ratio=0.1 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SASAFL --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=1412383812423148
#   wise-176 (cwd /home/wise-176/Mando/FedMPI, 15개 프로세스: 모두 클라이언트, rank 16–30)
#     python Start.py --selection_ratio=0.1 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SASAFL --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=821313822348414
#
# [F7_MNIST_SASAFL_OFF_C0.1_rep1] 제안 기법 미적용 (두 노드 모두 K30_SASAFL_SRC=k30_reproduction/original_code/SASAFL_c0b819b.py로 SASAFL.py 교체)
#   wise-175
#     K30_SASAFL_SRC=k30_reproduction/original_code/SASAFL_c0b819b.py python Start.py --selection_ratio=0.1 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SASAFL --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=1324382431848112
#   wise-176
#     K30_SASAFL_SRC=k30_reproduction/original_code/SASAFL_c0b819b.py python Start.py --selection_ratio=0.1 --round=500 --batch_size=32 --local_epochs=5 --lr=0.01 --target_acc=1.0 --dataset=MNIST --iid=False --split=gaussian --method=SASAFL --lag_tolerance=9 --wandb_on=False --repeat=1 --cluster_type=KISTI --num_threads=483248243381211
#
# 나머지 SASAFL 실행은 위 명령에서 아래 값만 바뀐다 (--num_threads는 실행마다 1·2·3·4·8×6을 새로 섞은 값, runs/<이름>/cmd.txt에 기록)
#   --dataset=MNIST        → --lr=0.01        --selection_ratio=0.1 | 0.3 | 0.5
#   --dataset=FashionMNIST → --lr=0.001       --selection_ratio=0.1 | 0.3 | 0.5
# ────────────────────────────────────────────────────────────────────────────────────────────────
set -euo pipefail

METHOD=${1:?usage}
C=${2:?usage}
K=${3:?usage}
MODE=${4:?usage}
CATEGORIES=${5:?usage}

MASTER_ADDR=${MASTER_ADDR:-210.107.197.175}
WORKER_ADDR=${WORKER_ADDR:-210.107.197.176}
WORKER_HOST=${WORKER_HOST:-wise-176@210.107.197.176}
MASTER_REPO=${MASTER_REPO:-/home/wise-175/Mando/FedMPI}
WORKER_REPO=${WORKER_REPO:-/home/wise-176/Mando/FedMPI}
MASTER_PY=${MASTER_PY:-/home/wise-175/anaconda3/envs/FL/bin/python}
WORKER_PY=${WORKER_PY:-/home/wise-176/miniconda3/envs/FL/bin/python}
MASTER_PORT=${MASTER_PORT:-29640}
RUN_ID=${RUN_ID:-k30_${METHOD}_${C//./}}
SYNC_SOURCE=${SYNC_SOURCE:-1}

ROUNDS=${ROUNDS:-500}
DATASET=${DATASET:-MNIST}
IID=${IID:-False}
SPLIT=${SPLIT:-gaussian}
LEARNING_RATE=${LEARNING_RATE:-0.01}
BATCH_SIZE=${BATCH_SIZE:-32}
LOCAL_EPOCHS=${LOCAL_EPOCHS:-5}
TARGET_ACCURACY=${TARGET_ACCURACY:-1.0}
LAG_TOLERANCE=${LAG_TOLERANCE:-9}

IFS=',' read -r -a CATS <<< "$CATEGORIES"
NCAT=${#CATS[@]}
if (( K % NCAT != 0 )); then echo "K=$K is not divisible by ${NCAT} categories" >&2; exit 2; fi
PER_CAT=$(( K / NCAT ))

# 카테고리 값을 클라이언트별 digit 문자열로 만든다 (shuf로 무작위 배치)
make_digits() {
    local count=$1 out=() v i
    for v in "${CATS[@]}"; do
        for ((i = 0; i < count; i++)); do out+=("$v"); done
    done
    printf '%s\n' "${out[@]}" | shuf | tr -d '\n'
}

ENTRY=k30_reproduction/harness_entry.py
COMMON_ARGS=(
    "--selection_ratio=$C" "--round=$ROUNDS" "--batch_size=$BATCH_SIZE" "--local_epochs=$LOCAL_EPOCHS"
    "--lr=$LEARNING_RATE" "--target_acc=$TARGET_ACCURACY" "--dataset=$DATASET" "--iid=$IID"
    "--split=$SPLIT" "--method=$METHOD" "--lag_tolerance=$LAG_TOLERANCE" "--wandb_on=False"
    "--repeat=1" "--cluster_type=KISTI"
)

MASTER_IFACE=$(ip -o -4 addr show | awk -v a="$MASTER_ADDR" '$4 ~ "^" a "/" {print $2; exit}')
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONUNBUFFERED=1
export GLOO_SOCKET_IFNAME="$MASTER_IFACE"
cd "$MASTER_REPO"

if [[ "$MODE" == "single" ]]; then
    THREADS="1$(make_digits "$PER_CAT")"
    echo "[k30] mode=single method=$METHOD C=$C K=$K categories=$CATEGORIES threads=$THREADS"
    PIN=()
    if [[ -n "${CPU_LIST:-}" ]]; then PIN=(taskset -c "$CPU_LIST"); echo "[k30] cpu_list=$CPU_LIST"; fi
    exec "${PIN[@]}" "$MASTER_PY" -m torch.distributed.run --nnodes=1 --nproc_per_node=$((K + 1)) \
        --rdzv_id="$RUN_ID" --master_addr="$MASTER_ADDR" --master_port="$MASTER_PORT" \
        --rdzv_endpoint="$MASTER_ADDR:$MASTER_PORT" --node_rank=0 \
        "$ENTRY" "${COMMON_ARGS[@]}" "--num_threads=$THREADS"
fi

if [[ "$MODE" != "two" ]]; then echo "unknown mode $MODE" >&2; exit 2; fi
if (( PER_CAT % 2 != 0 )); then echo "two mode needs an even number of clients per category" >&2; exit 2; fi
HALF_CAT=$(( PER_CAT / 2 ))
PER_HOST=$(( K / 2 ))
MASTER_THREADS="1$(make_digits "$HALF_CAT")"
WORKER_THREADS="$(make_digits "$HALF_CAT")"
WORKER_IFACE=$(ssh "$WORKER_HOST" "ip -o -4 addr show | awk -v a='$WORKER_ADDR' '\$4 ~ \"^\" a \"/\" {print \$2; exit}'")

if [[ "$SYNC_SOURCE" == "1" ]]; then
    tar -czf - Start.py methods utils model_controller k30_reproduction/harness_entry.py k30_reproduction/trace_hooks.py | \
        ssh "$WORKER_HOST" "mkdir -p '$WORKER_REPO/k30_reproduction' && tar -xzf - -C '$WORKER_REPO'"
fi

echo "[k30] mode=two method=$METHOD C=$C K=$K categories=$CATEGORIES"
# CMD_FILE이 있으면 두 노드에서 실제로 실행하는 명령을 그대로 저장한다
if [[ -n "${CMD_FILE:-}" ]]; then
    {
        echo "# launch: $0 $*"
        echo "# env: ROUNDS=$ROUNDS DATASET=$DATASET IID=$IID SPLIT=$SPLIT LEARNING_RATE=$LEARNING_RATE BATCH_SIZE=$BATCH_SIZE LOCAL_EPOCHS=$LOCAL_EPOCHS TARGET_ACCURACY=$TARGET_ACCURACY LAG_TOLERANCE=$LAG_TOLERANCE K30_SASAFL_SRC=${K30_SASAFL_SRC:-} K30_TRACE=${K30_TRACE:-} OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1"
        echo "# [wise-175, node_rank 0: 서버 + $PER_HOST 클라이언트] cwd=$MASTER_REPO"
        echo "$MASTER_PY -m torch.distributed.run --nnodes=2 --nproc_per_node=$((PER_HOST + 1)) --node_rank=0 --rdzv_id=$RUN_ID --rdzv_endpoint=$MASTER_ADDR:$MASTER_PORT --master_addr=$MASTER_ADDR --master_port=$MASTER_PORT $ENTRY ${COMMON_ARGS[*]} --num_threads=$MASTER_THREADS"
        echo "# [wise-176, node_rank 1: $PER_HOST 클라이언트] cwd=$WORKER_REPO"
        echo "$WORKER_PY -m torch.distributed.run --nnodes=2 --nproc_per_node=$PER_HOST --node_rank=1 --rdzv_id=$RUN_ID --rdzv_endpoint=$MASTER_ADDR:$MASTER_PORT --master_addr=$MASTER_ADDR --master_port=$MASTER_PORT $ENTRY ${COMMON_ARGS[*]} --num_threads=$WORKER_THREADS"
    } > "$CMD_FILE"
fi
echo "[k30] master threads=$MASTER_THREADS (server + $PER_HOST clients) worker threads=$WORKER_THREADS"

ssh "$WORKER_HOST" "
    set -euo pipefail
    cd '$WORKER_REPO'
    export GLOO_SOCKET_IFNAME='$WORKER_IFACE' OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONUNBUFFERED=1
    export K30_PID_DIR='/tmp/k30_pids_$RUN_ID'
    ${K30_SASAFL_SRC:+export K30_SASAFL_SRC='$K30_SASAFL_SRC'}
    ${K30_TRACE:+export K30_TRACE='$K30_TRACE'}
    exec '$WORKER_PY' -m torch.distributed.run --nnodes=2 --nproc_per_node=$PER_HOST --node_rank=1 \
        --rdzv_id='$RUN_ID' --rdzv_endpoint='$MASTER_ADDR:$MASTER_PORT' \
        --master_addr='$MASTER_ADDR' --master_port='$MASTER_PORT' \
        $ENTRY ${COMMON_ARGS[*]} --num_threads='$WORKER_THREADS'
" 2>&1 | sed -u 's/^/[176] /' &
WORKER_PID=$!

set +e
"$MASTER_PY" -m torch.distributed.run --nnodes=2 --nproc_per_node=$((PER_HOST + 1)) --node_rank=0 \
    --rdzv_id="$RUN_ID" --rdzv_endpoint="$MASTER_ADDR:$MASTER_PORT" \
    --master_addr="$MASTER_ADDR" --master_port="$MASTER_PORT" \
    "$ENTRY" "${COMMON_ARGS[@]}" "--num_threads=$MASTER_THREADS"
MASTER_STATUS=$?
wait "$WORKER_PID"
WORKER_STATUS=$?
set -e
echo "[k30] master_status=$MASTER_STATUS worker_status=$WORKER_STATUS"
if (( MASTER_STATUS != 0 || WORKER_STATUS != 0 )); then exit 1; fi
