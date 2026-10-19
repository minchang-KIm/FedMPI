#!/usr/bin/env bash
# E7(적응형 quota 꺼진 원저자 코드) 9개 실행을 두 노드가 '차지(claim)' 방식으로 나눠 돌린다.
# - 각 노드는 9개 전체 목록을 자기 순서대로 훑으며, wise-175의 claims/ 폴더에 먼저 이름을 차지한 실행만 돌린다.
# - 그래서 한쪽이 멈추거나 빠져도 다른 쪽이 남은 실행을 가져간다. 같은 실행을 두 번 돌리지 않는다.
# - 완료된 실행은 건너뛰고, 자기가 차지했던 미완료 실행은 다시 시작한다 (재부팅 후 재개 가능).
#   wise-175: tmux k30 창 3 / wise-176: setsid nohup (start_e7_two_nodes.sh가 띄운다)
set -u
HOST=$(hostname)
CLAIMS=/home/wise-175/Mando/FedMPI/k30_reproduction/experiments/E7_adaptive_off_2023code/claims
L175="ERR_FMNIST_SASAFL_C0.5 ERR_MNIST_SASAFL_C0.3 ERR_CIFAR10_SASAFL_C0.3 ERR_CIFAR10_SASAFL_C0.1"
L176="ERR_MNIST_SASAFL_C0.5 ERR_CIFAR10_SASAFL_C0.5 ERR_FMNIST_SASAFL_C0.3 ERR_MNIST_SASAFL_C0.1 ERR_FMNIST_SASAFL_C0.1"
export K30_CLAIM_DIR=$CLAIMS
case "$HOST" in
    wise-175)
        cd /home/wise-175/Mando/FedMPI
        PY=/home/wise-175/anaconda3/envs/FL/bin/python
        PIPE_PY=$PY
        ORDER="$L175 $L176"
        ;;
    wise-176)
        cd /home/wise-176/Mando/FedMPI
        PY=/home/wise-176/miniconda3/envs/FL/bin/python      # 학습(torchrun)은 FL 환경
        PIPE_PY=/home/wise-176/miniconda3/bin/python         # 파이프라인(그림 생성)은 matplotlib 있는 base 환경
        ORDER="$L176 $L175"
        export K30_CLAIM_SSH=wise-175@210.107.197.175
        export MASTER_ADDR=210.107.197.176 MASTER_REPO=/home/wise-176/Mando/FedMPI MASTER_PY=$PY
        # 176은 P코어가 높은 부스트에서 계산을 틀린다 (2026-10-19 진단). 터보를 끄거나 클럭을 제한한 뒤에만 실행한다.
        if [[ "$(cat /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null)" != "1" && "${K30_ALLOW_TURBO:-0}" != "1" ]]; then
            echo "[$(date '+%F %T')] wise-176: 터보가 켜져 있어 실행하지 않음 (no_turbo=1 설정 후 다시 실행)"; exit 3
        fi
        ;;
    *) echo "unknown host $HOST" >&2; exit 2 ;;
esac
echo "[$(date '+%F %T')] $HOST E7 queue 시작"
# 실행 순서를 노드별로 바꾸기 위해 이름을 하나씩 넘긴다 (run_pipeline은 --names에 든 것만, 정의 순서대로 돈다)
for name in $ORDER; do
    $PIPE_PY k30_reproduction/pipeline/run_pipeline.py --only E7 --names "$name"
done
echo "[$(date '+%F %T')] $HOST E7_NODE_DONE"
