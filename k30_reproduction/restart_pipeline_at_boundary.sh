#!/usr/bin/env bash
# 지금 실행 중인 run이 끝나는 순간(다음 run 시작 전) 파이프라인을 재시작해 수정된 설정을 적용한다.
cd /home/wise-175/Mando/FedMPI
RUN_DIR=k30_reproduction/experiments/E2_FashionMNIST_table2/runs/FMNIST_BSA_C0.1
PIPE=$(pgrep -f "^/home/wise-175/anaconda3/envs/FL/bin/python k30_reproduction/pipeline/run_pipeline.py")
WAITER=$(pgrep -f "^bash k30_reproduction/start_pipeline_after_table2.sh")
echo "[$(date '+%F %T')] 대기: $RUN_DIR 완료 후 파이프라인($PIPE) 재시작"
kill $WAITER 2>/dev/null   # 옛 대기 스크립트가 PIPELINE_DONE을 잘못 찍지 않게 먼저 종료
until [ -f "$RUN_DIR/result.json" ]; do sleep 1; done
kill $PIPE; sleep 3
echo "[$(date '+%F %T')] 옛 파이프라인 종료. 남은 학습 프로세스: $(pgrep -fc '^/home/wise-175/anaconda3/envs/FL/bin/python.*harness_entry.py')"
echo "- $(date '+%Y-%m-%d %H:%M') 설정 변경(실행 시간 상한 600→1500분) 적용을 위해 파이프라인 재시작" >> k30_reproduction/PROGRESS.md
setsid nohup bash k30_reproduction/start_pipeline_after_table2.sh >> k30_reproduction/pipeline_console.log 2>&1 < /dev/null &
echo "[$(date '+%F %T')] 새 파이프라인 시작"
