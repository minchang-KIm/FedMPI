#!/usr/bin/env bash
# 두 노드 MPI 백엔드 launcher (launch.sh two 모드의 mpirun 판)
# 175: 서버 + K/2 클라이언트, 176: K/2 클라이언트. rank 0(서버)은 175.
#
# 사용법: launch_mpi.sh METHOD C K CATEGORIES
# 필요: 두 노드 모두 USE_MPI=1로 빌드한 PyTorch가 든 env (기본 FLmpi), Open MPI 4.1, 175→176 비밀번호 없는 ssh
# -H에는 IP를 쓴다 (ssh 별칭 node1/node2를 쓰면 Open MPI가 hostname 불일치로 죽는다)
# 환경변수: MASTER_PY WORKER_PY MASTER_REPO WORKER_REPO ROUNDS DATASET LEARNING_RATE ... (launch.sh와 같음)
set -euo pipefail

METHOD=${1:?usage}
C=${2:?usage}
K=${3:?usage}
CATEGORIES=${4:?usage}

MASTER_NODE=${MASTER_NODE:-210.107.197.175}
WORKER_NODE=${WORKER_NODE:-210.107.197.176}
WORKER_USER=${WORKER_USER:-wise-176}
MASTER_REPO=${MASTER_REPO:-/home/wise-175/Mando/FedMPI}
WORKER_REPO=${WORKER_REPO:-/home/wise-176/Mando/FedMPI}
MASTER_PY=${MASTER_PY:-/home/wise-175/anaconda3/envs/FLmpi/bin/python}
WORKER_PY=${WORKER_PY:-/home/wise-176/miniconda3/envs/FLmpi/bin/python}
IFACE=${IFACE:-$(ip -o -4 addr show | awk '$4 ~ "^210\\.107\\.197\\." {print $2; exit}')}

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
if (( PER_CAT % 2 != 0 )); then echo "two-node mode needs an even number of clients per category" >&2; exit 2; fi
HALF_CAT=$(( PER_CAT / 2 ))
PER_HOST=$(( K / 2 ))

make_digits() {
    local count=$1 out=() v i
    for v in "${CATS[@]}"; do
        for ((i = 0; i < count; i++)); do out+=("$v"); done
    done
    printf '%s\n' "${out[@]}" | shuf | tr -d '\n'
}
# Start.py는 num_threads[LOCAL_RANK]를 쓴다. 175는 local rank 0이 서버, 176은 local rank 0부터 클라이언트
MASTER_THREADS="1$(make_digits "$HALF_CAT")"
WORKER_THREADS="$(make_digits "$HALF_CAT")"

ENTRY=k30_reproduction/harness_entry.py
# MPMD에서는 -x가 첫 app context에만 붙으므로 env로 양쪽에 똑같이 넣는다
RUN_ENV=(env FL_BACKEND=mpi OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONUNBUFFERED=1)
COMMON_ARGS=(
    "--selection_ratio=$C" "--round=$ROUNDS" "--batch_size=$BATCH_SIZE" "--local_epochs=$LOCAL_EPOCHS"
    "--lr=$LEARNING_RATE" "--target_acc=$TARGET_ACCURACY" "--dataset=$DATASET" "--iid=$IID"
    "--split=$SPLIT" "--method=$METHOD" "--lag_tolerance=$LAG_TOLERANCE" "--wandb_on=False"
    "--repeat=1" "--cluster_type=KISTI"
)

echo "[mpi] method=$METHOD C=$C K=$K categories=$CATEGORIES iface=$IFACE"
echo "[mpi] $MASTER_NODE threads=$MASTER_THREADS (server + $PER_HOST clients) $WORKER_NODE threads=$WORKER_THREADS"

cd "$MASTER_REPO"
unset DISPLAY
exec mpirun --tag-output --bind-to none --oversubscribe --mca plm_rsh_args "-l $WORKER_USER" \
    --mca btl tcp,self --mca btl_tcp_if_include "$IFACE" --mca oob_tcp_if_include "$IFACE" \
    -np $((PER_HOST + 1)) -H "$MASTER_NODE:$((PER_HOST + 1))" --wdir "$MASTER_REPO" \
        "${RUN_ENV[@]}" "$MASTER_PY" -u "$ENTRY" "${COMMON_ARGS[@]}" "--num_threads=$MASTER_THREADS" \
    : -np "$PER_HOST" -H "$WORKER_NODE:$PER_HOST" --wdir "$WORKER_REPO" \
        "${RUN_ENV[@]}" "$WORKER_PY" -u "$ENTRY" "${COMMON_ARGS[@]}" "--num_threads=$WORKER_THREADS"
