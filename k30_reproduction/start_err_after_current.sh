#!/usr/bin/env bash
# 지금 돌고 있는 실행(E5 LT_tau1_rep1)이 끝나면 기존 파이프라인을 멈추고,
# 적응형 quota가 꺼진 원저자 코드(c0b819b)로 E7(SASAFL 9개 실행)을 돌린 뒤 전체 그림을 다시 만든다.
#   tmux 세션 k30의 3번 창(err)에서 실행한다:  bash k30_reproduction/start_in_tmux.sh 가 아니라
#   tmux new-window -t k30:3 -n err "bash k30_reproduction/start_err_after_current.sh 2>&1 | tee -a k30_reproduction/err_console.log"
# 중단 후 다시 시작해도 된다(완료된 실행은 건너뛴다). E5 나머지(τ=2–10)는 나중에 start_in_tmux.sh로 이어서 돌릴 수 있다.
cd /home/wise-175/Mando/FedMPI
PY=/home/wise-175/anaconda3/envs/FL/bin/python
CURRENT=k30_reproduction/experiments/E5_Fig5_lag_tolerance/runs/LT_tau1_rep1/result.json
PIPE_PAT="^/home/wise-175/anaconda3/envs/FL/bin/python k30_reproduction/pipeline/run_pipeline.py$"
WAIT_PAT="^bash k30_reproduction/start_pipeline_after_table2.sh"

note() { echo "- $(date '+%F %H:%M') $*" | tee -a k30_reproduction/PROGRESS.md; }

if pgrep -f "$PIPE_PAT" > /dev/null; then
    echo "[$(date '+%F %T')] 현재 실행 종료 대기: $CURRENT"
    while [[ ! -f "$CURRENT" ]] && pgrep -f "$PIPE_PAT" > /dev/null; do sleep 2; done
    # 결과 저장 후 파이프라인은 15초 쉬고 다음 실행을 시작하므로 그 전에 멈춘다
    pkill -f "$WAIT_PAT"
    pkill -f "$PIPE_PAT"
    sleep 3
    note "사용자 요청으로 기존 파이프라인 중지 (LT_tau1_rep1까지 실행, τ=2–10 보류)"
fi

note "=== E7 시작: 적응형 quota가 꺼진 원저자 코드(c0b819b)로 SASAFL 9개 실행"
$PY k30_reproduction/pipeline/run_pipeline.py --only E7
$PY k30_reproduction/pipeline/run_pipeline.py --report-only
echo "[$(date '+%F %T')] ERR_DONE"
