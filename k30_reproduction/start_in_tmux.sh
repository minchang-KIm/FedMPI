#!/usr/bin/env bash
# K=30 재현 실험을 tmux 세션 'k30' 안에서 실행/관찰한다. (세션이 끊겨도 tmux 서버가 계속 돌린다)
#
#   bash k30_reproduction/start_in_tmux.sh          # 실험 시작(이미 돌고 있으면 관찰 창만 만든다)
#   tmux attach -t k30                               # 접속
#
# 창 구성: 0 pipeline(실험 본체) · 1 status(30초마다 상태) · 2 log(지금 실행의 라운드별 정확도)
TMUX_BIN=$(command -v tmux || echo /home/wise-175/anaconda3/envs/tools/bin/tmux)
REPO=/home/wise-175/Mando/FedMPI
SESSION=k30

running() {
    pgrep -f "^/home/wise-175/anaconda3/envs/FL/bin/python k30_reproduction/pipeline/run_pipeline.py" > /dev/null \
        || pgrep -f "^bash k30_reproduction/start_pipeline_after_table2.sh" > /dev/null \
        || pgrep -f "^bash k30_reproduction/start_err_after_current.sh" > /dev/null
}

LOG_CMD='while true; do f=$(ls -t k30_reproduction/runs/*/run.log k30_reproduction/experiments/*/runs/*/run.log 2>/dev/null | head -1); echo "=== $f"; timeout 600 tail -n 400 -f "$f" | grep --line-buffered "번째 글로벌 모델"; done'

if ! "$TMUX_BIN" has-session -t "$SESSION" 2>/dev/null; then
    "$TMUX_BIN" new-session -d -s "$SESSION" -n pipeline -c "$REPO"
    "$TMUX_BIN" new-window -t "$SESSION:1" -n status -c "$REPO" "watch -n 30 bash k30_reproduction/status.sh"
    "$TMUX_BIN" new-window -t "$SESSION:2" -n log -c "$REPO" "bash -c '$LOG_CMD'"
fi

if running; then
    "$TMUX_BIN" send-keys -t "$SESSION:0" \
        "echo '실험이 이미 다른 곳(setsid)에서 실행 중이라 새로 시작하지 않음. 상태는 1번 창.'" Enter
    echo "실험이 이미 실행 중 → 관찰용 tmux 세션 '$SESSION'만 준비함"
else
    "$TMUX_BIN" send-keys -t "$SESSION:0" "bash k30_reproduction/start_pipeline_after_table2.sh 2>&1 | tee -a k30_reproduction/pipeline_console.log" Enter
    echo "tmux 세션 '$SESSION'의 0번 창에서 실험 시작"
fi
echo "접속: tmux attach -t $SESSION   (빠져나오기: Ctrl+b 누른 뒤 d)"
