#!/usr/bin/env bash
# E7(적응형 quota 꺼진 원저자 코드) 실행을 두 노드에 나눠 돌린다. 각 노드는 자기 몫만 독립적으로 실행한다
# (한 노드가 멈춰도 다른 노드는 계속 간다). 완료된 실행은 건너뛰므로 다시 실행해도 된다.
#   wise-175: tmux 세션 k30 창 3 (start_e7_two_nodes.sh가 띄운다)
#   wise-176: setsid nohup (tmux 없음), 로그 k30_reproduction/e7_console.log
set -u
HOST=$(hostname)
case "$HOST" in
    wise-175)
        cd /home/wise-175/Mando/FedMPI
        PY=/home/wise-175/anaconda3/envs/FL/bin/python
        PIPE_PY=$PY
        NAMES="ERR_FMNIST_SASAFL_C0.5 ERR_MNIST_SASAFL_C0.3 ERR_CIFAR10_SASAFL_C0.3 ERR_CIFAR10_SASAFL_C0.1"
        ;;
    wise-176)
        cd /home/wise-176/Mando/FedMPI
        PY=/home/wise-176/miniconda3/envs/FL/bin/python      # 학습(torchrun)은 FL 환경
        PIPE_PY=/home/wise-176/miniconda3/bin/python         # 파이프라인(그림 생성)은 matplotlib 있는 base 환경
        NAMES="ERR_MNIST_SASAFL_C0.5 ERR_CIFAR10_SASAFL_C0.5 ERR_FMNIST_SASAFL_C0.3 ERR_MNIST_SASAFL_C0.1 ERR_FMNIST_SASAFL_C0.1"
        # 176은 코어 24(CPU 12,13)가 행렬곱을 틀리게 계산한다 (diagnostics, 2026-10-10) → 그 코어를 뺀다
        export CPU_LIST=0-11,14-31
        export MASTER_ADDR=210.107.197.176 MASTER_REPO=/home/wise-176/Mando/FedMPI MASTER_PY=$PY
        ;;
    *) echo "unknown host $HOST" >&2; exit 2 ;;
esac
echo "[$(date '+%F %T')] $HOST E7 시작: $NAMES"
$PIPE_PY k30_reproduction/pipeline/run_pipeline.py --only E7 --names $NAMES
echo "[$(date '+%F %T')] $HOST E7_NODE_DONE"
