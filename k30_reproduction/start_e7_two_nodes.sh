#!/usr/bin/env bash
# E7을 wise-175·wise-176에 나눠 동시에 실행한다. wise-175에서 실행. 이미 돌고 있는 것은 다시 띄우지 않는다.
#   bash k30_reproduction/start_e7_two_nodes.sh
#   tmux attach -t k30   → 창 1 status · 2 log · 3 e7(175 몫) · 4 sync(176 결과 가져오기)
#   176 진행: ssh wise-176@210.107.197.176 tail -f /home/wise-176/Mando/FedMPI/k30_reproduction/e7_console.log
# 재부팅 후 자동 재개: 두 노드 crontab의 @reboot 항목이 이 스크립트 / run_e7_node.sh를 다시 띄운다.
export PATH=$HOME/bin:/home/wise-175/anaconda3/envs/tools/bin:$PATH
REPO=/home/wise-175/Mando/FedMPI
SESSION=k30
W176=wise-176@210.107.197.176
cd "$REPO"

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux new-session -d -s "$SESSION" -n pipeline -c "$REPO"
    tmux new-window -t "$SESSION:1" -n status -c "$REPO" "watch -n 30 bash k30_reproduction/status.sh"
    tmux new-window -t "$SESSION:2" -n log -c "$REPO" \
        "bash -c 'while true; do f=\$(ls -t k30_reproduction/experiments/*/runs/*/run.log 2>/dev/null | head -1); echo \"=== \$f\"; timeout 600 tail -n 400 -f \"\$f\" | grep --line-buffered \"번째 글로벌 모델\"; done'"
fi

if pgrep -f "^bash k30_reproduction/run_e7_queue.sh" > /dev/null; then
    echo "175: 이미 실행 중"
elif pgrep -f "^bash k30_reproduction/run_e7_node.sh" > /dev/null; then
    # 2026-10-19 오전에 띄운 이전 방식(고정 4개)이 돌고 있으면, 끝난 뒤 queue 방식으로 이어간다
    tmux kill-window -t "$SESSION:5" 2>/dev/null
    tmux new-window -t "$SESSION:5" -n queue -c "$REPO" \
        "while pgrep -f '^bash k30_reproduction/run_e7_node.sh' > /dev/null; do sleep 60; done; bash k30_reproduction/run_e7_queue.sh 2>&1 | tee -a k30_reproduction/e7_console.log; exec bash"
    echo "175: 이전 방식 실행이 끝나면 queue로 이어감 (tmux $SESSION:5)"
else
    tmux kill-window -t "$SESSION:3" 2>/dev/null
    tmux new-window -t "$SESSION:3" -n e7 -c "$REPO" \
        "bash k30_reproduction/run_e7_queue.sh 2>&1 | tee -a k30_reproduction/e7_console.log; exec bash"
    echo "175: tmux $SESSION:3 에서 시작"
fi

if ssh -o BatchMode=yes -o ConnectTimeout=10 "$W176" 'pgrep -f "^bash k30_reproduction/run_e7_(node|queue).sh" > /dev/null'; then
    echo "176 몫: 이미 실행 중"
else
    ssh -n -f -o BatchMode=yes -o ConnectTimeout=10 "$W176" \
        'cd /home/wise-176/Mando/FedMPI && setsid nohup bash k30_reproduction/run_e7_queue.sh >> k30_reproduction/e7_console.log 2>&1 < /dev/null &' \
        && echo "176: 시작 요청 (터보가 켜져 있으면 스스로 종료 — 176의 e7_console.log 확인)" || echo "176: 접속 실패 — 176 상태 확인 필요"
fi

if pgrep -f "^bash k30_reproduction/sync_e7_from_176.sh" > /dev/null; then
    echo "동기화: 이미 실행 중"
else
    tmux kill-window -t "$SESSION:4" 2>/dev/null
    tmux new-window -t "$SESSION:4" -n sync -c "$REPO" \
        "bash k30_reproduction/sync_e7_from_176.sh 2>&1 | tee -a k30_reproduction/sync_console.log; exec bash"
    echo "동기화: tmux $SESSION:4 에서 시작"
fi
echo "접속: tmux attach -t $SESSION   (빠져나오기: Ctrl+b 누른 뒤 d)"
