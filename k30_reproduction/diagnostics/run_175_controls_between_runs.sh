#!/usr/bin/env bash
# 175 대조군: Table 2 실행 사이에 실행기를 일시정지하고 진단 1·2를 돌린 뒤 재개한다.
cd /home/wise-175/Mando/FedMPI
PY=/home/wise-175/anaconda3/envs/FL/bin/python
OUT=k30_reproduction/diagnostics/out_175; mkdir -p $OUT
ORCH=$(pgrep -f "^/home/wise-175/anaconda3/envs/FL/bin/python k30_reproduction/run_k30.py table2")
N0=$(grep -c " -> " k30_reproduction/table2_console.log)
echo "대기: 현재 완료 실행 $N0개, orchestrator=$ORCH ($(date +%T))"
until [ "$(grep -c ' -> ' k30_reproduction/table2_console.log)" -gt "$N0" ]; do sleep 0.5; done
kill -STOP $ORCH; echo "실행기 일시정지 $(date +%T)"
export FEDMPI_REPO=$PWD
$PY k30_reproduction/diagnostics/hw_determinism.py 32 300 > $OUT/1_hw_determinism.log 2>&1; tail -3 $OUT/1_hw_determinism.log
$PY k30_reproduction/diagnostics/thread_pattern_repro.py 300 30 > $OUT/2_thread_pattern.log 2>&1; tail -4 $OUT/2_thread_pattern.log
kill -CONT $ORCH; echo "실행기 재개 $(date +%T)"
