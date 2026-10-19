#!/usr/bin/env bash
# E8(K=10) 27개 실행을 두 노드가 claim 방식으로 나눠 돌린다 (run_e7_queue.sh와 같은 방식).
# 두 노드 모두 같은 순서(MNIST → FashionMNIST → CIFAR-10)로 훑으며 아직 아무도 차지하지 않은 실행을 가져간다.
# 이 노드의 E7 queue가 끝난 뒤 시작한다 (start_e7_two_nodes.sh / crontab이 이어서 띄운다).
set -u
HOST=$(hostname)
export K30_CLAIM_DIR=/home/wise-175/Mando/FedMPI/k30_reproduction/experiments/E8_K10/claims
case "$HOST" in
    wise-175)
        cd /home/wise-175/Mando/FedMPI
        PIPE_PY=/home/wise-175/anaconda3/envs/FL/bin/python
        ;;
    wise-176)
        cd /home/wise-176/Mando/FedMPI
        PIPE_PY=/home/wise-176/miniconda3/bin/python
        export K30_CLAIM_SSH=wise-175@210.107.197.175
        export MASTER_ADDR=210.107.197.176 MASTER_REPO=/home/wise-176/Mando/FedMPI MASTER_PY=/home/wise-176/miniconda3/envs/FL/bin/python
        if [[ "$(cat /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null)" != "1" && "${K30_ALLOW_TURBO:-0}" != "1" ]]; then
            echo "[$(date '+%F %T')] wise-176: 터보가 켜져 있어 실행하지 않음 (no_turbo=1 설정 후 다시 실행)"; exit 3
        fi
        ;;
    *) echo "unknown host $HOST" >&2; exit 2 ;;
esac
# E7 실행·대기 중인 것이 하나라도 있으면 (tmux 대기 창 포함) 기다린다
while pgrep -f "^bash .*run_e7_(node|queue)\.sh" > /dev/null; do sleep 60; done
echo "[$(date '+%F %T')] $HOST E8(K=10) queue 시작"
for ds in MNIST FMNIST CIFAR10; do
    for c in 0.1 0.3 0.5; do
        for v in BSA SASAFL SASAFLorig; do
            $PIPE_PY k30_reproduction/pipeline/run_pipeline.py --only E8 --names "K10_${ds}_${v}_C${c}"
        done
    done
done
echo "[$(date '+%F %T')] $HOST E8_NODE_DONE"
