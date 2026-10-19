#!/usr/bin/env bash
# E7(원저자 코드, K=30) → E8(K=10)을 wise-175·wise-176에 claim 방식으로 나눠 실행한다. wise-175에서 실행.
# 이미 돌고 있는 것은 다시 띄우지 않는다. 재부팅 후에는 두 노드 crontab @reboot이 다시 띄운다.
#   bash k30_reproduction/start_two_nodes.sh
#   tmux attach -t k30 → 1 status · 2 log · 3/5 E7(175) · 6 E8(175) · 4 sync(176 결과 가져오기)
#   176 진행: ssh wise-176@210.107.197.176 tail -f /home/wise-176/Mando/FedMPI/k30_reproduction/e7_console.log
export PATH=$HOME/bin:/home/wise-175/anaconda3/envs/tools/bin:$PATH
REPO=/home/wise-175/Mando/FedMPI
SESSION=k30
W176=wise-176@210.107.197.176
cd "$REPO"
SSH176=(ssh -o BatchMode=yes -o ConnectTimeout=10 "$W176")

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux new-session -d -s "$SESSION" -n pipeline -c "$REPO"
    tmux new-window -t "$SESSION:1" -n status -c "$REPO" "watch -n 30 bash k30_reproduction/status.sh"
    tmux new-window -t "$SESSION:2" -n log -c "$REPO" \
        "bash -c 'while true; do f=\$(ls -t k30_reproduction/experiments/*/runs/*/run.log 2>/dev/null | head -1); echo \"=== \$f\"; timeout 600 tail -n 400 -f \"\$f\" | grep --line-buffered \"번째 글로벌 모델\"; done'"
fi

# 175: E7 → E8
if pgrep -f "^bash .*run_e7_(node|queue)\.sh" > /dev/null; then
    echo "175 E7: 실행 중"
else
    tmux kill-window -t "$SESSION:3" 2>/dev/null
    tmux new-window -t "$SESSION:3" -n e7 -c "$REPO" \
        "bash k30_reproduction/run_e7_queue.sh 2>&1 | tee -a k30_reproduction/e7_console.log; exec bash"
    echo "175 E7: tmux $SESSION:3 에서 시작"
fi
if pgrep -f "^bash k30_reproduction/run_e8_queue.sh" > /dev/null; then
    echo "175 E8: 실행/대기 중"
else
    tmux kill-window -t "$SESSION:6" 2>/dev/null
    tmux new-window -t "$SESSION:6" -n e8 -c "$REPO" \
        "sleep 5; bash k30_reproduction/run_e8_queue.sh 2>&1 | tee -a k30_reproduction/e8_console.log; exec bash"
    echo "175 E8: tmux $SESSION:6 에서 대기 (175의 E7이 끝나면 시작)"
fi

# 176: E7 → E8 (터보가 켜져 있으면 스크립트가 스스로 종료)
if "${SSH176[@]}" 'pgrep -f "^bash k30_reproduction/run_e[78]_queue.sh" > /dev/null'; then
    echo "176: 실행/대기 중"
else
    ssh -n -f -o BatchMode=yes -o ConnectTimeout=10 "$W176" \
        'cd /home/wise-176/Mando/FedMPI && setsid nohup bash -c "bash k30_reproduction/run_e7_queue.sh; bash k30_reproduction/run_e8_queue.sh" >> k30_reproduction/e7_console.log 2>&1 < /dev/null &' \
        && echo "176: 시작 요청 (터보가 켜져 있으면 스스로 종료 — 176의 e7_console.log 확인)" || echo "176: 접속 실패"
fi

if pgrep -f "^bash k30_reproduction/sync_from_176.sh" > /dev/null; then
    echo "동기화: 실행 중"
else
    tmux kill-window -t "$SESSION:4" 2>/dev/null
    tmux new-window -t "$SESSION:4" -n sync -c "$REPO" \
        "bash k30_reproduction/sync_from_176.sh 2>&1 | tee -a k30_reproduction/sync_console.log; exec bash"
    echo "동기화: tmux $SESSION:4 에서 시작"
fi
echo "접속: tmux attach -t $SESSION   (빠져나오기: Ctrl+b 누른 뒤 d)"
