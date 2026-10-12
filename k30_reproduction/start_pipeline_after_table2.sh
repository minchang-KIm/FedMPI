#!/usr/bin/env bash
# 현재 진행 중인 Table 2(MNIST) 작업이 끝나면 전체 재현 파이프라인(E1→E6)을 이어서 실행한다.
# 세션이 끝나도 계속되도록 분리 실행한다:
#   setsid nohup bash k30_reproduction/start_pipeline_after_table2.sh > k30_reproduction/pipeline_console.log 2>&1 < /dev/null &
# 중단 후 다시 시작할 때도 같은 명령을 쓰면 된다(완료된 실행은 건너뛴다).
cd /home/wise-175/Mando/FedMPI
PY=/home/wise-175/anaconda3/envs/FL/bin/python

echo "[$(date '+%F %T')] Table 2 작업 종료 대기"
while pgrep -f "^/home/wise-175/anaconda3/envs/FL/bin/python k30_reproduction/run_k30.py table2" > /dev/null || pgrep -f "^bash k30_reproduction/run_table2_detached.sh" > /dev/null; do
    sleep 60
done
echo "[$(date '+%F %T')] 파이프라인 시작"
$PY k30_reproduction/pipeline/run_pipeline.py
echo "[$(date '+%F %T')] PIPELINE_DONE"
