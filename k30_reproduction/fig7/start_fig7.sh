#!/usr/bin/env bash
# Fig.7(K=30)+SAFA 실험을 tmux 세션 'fig7'에서 시작/재개한다 (wise-175에서 실행. 176은 launch.sh가 ssh로 띄운다)
#   창 0 runner : run_fig7.py (죽으면 1분 뒤 다시 시작, 완료된 실행은 건너뜀)
#   창 1 plot   : plot_fig7.py --watch (라운드가 끝날 때마다 그림 갱신, 죽으면 5초 뒤 다시 시작)
#   창 2 log    : 진행 기록
# 이미 돌고 있으면 새로 띄우지 않는다. crontab @reboot에서도 이 스크립트를 부른다.
set -u
TMUX_BIN=$(command -v tmux || echo /home/wise-175/anaconda3/envs/tools/bin/tmux)
REPO=/home/wise-175/Mando/FedMPI
PY=/home/wise-175/anaconda3/envs/FL/bin/python
OUT=$REPO/k30_reproduction/experiments/F7_fig7_safa
SESSION=fig7
mkdir -p "$OUT"
if "$TMUX_BIN" has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux 세션 '$SESSION'이 이미 있음 → 새로 시작하지 않음 (tmux attach -t $SESSION)"
    exit 0
fi
"$TMUX_BIN" new-session -d -s "$SESSION" -n runner -c "$REPO" \
    "bash -c 'set -o pipefail; until $PY -u k30_reproduction/fig7/run_fig7.py 2>&1 | tee -a $OUT/runner_console.log; do echo restart; sleep 60; done; exec bash'"
"$TMUX_BIN" new-window -t "$SESSION:1" -n plot -c "$REPO" \
    "bash -c 'while true; do nice -n 10 $PY -u k30_reproduction/fig7/plot_fig7.py --watch >> $OUT/plot_console.log 2>&1; sleep 5; done'"
"$TMUX_BIN" new-window -t "$SESSION:2" -n log -c "$REPO" "bash -c 'touch $OUT/PROGRESS.md; tail -f $OUT/PROGRESS.md'"
echo "시작함: tmux attach -t $SESSION"
