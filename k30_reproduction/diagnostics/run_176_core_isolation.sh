#!/usr/bin/env bash
# 176 core 24(CPU 12·13) 불량 여부 판별. 결과: k30_reproduction/diagnostics/out_176_core/
cd /home/wise-176/Mando/FedMPI
PY=/home/wise-176/miniconda3/envs/FL/bin/python
OUT=k30_reproduction/diagnostics/out_176_core; mkdir -p $OUT
SUSPECT=12,13
OTHERS=0-11,14-31
echo "### A 행렬곱, CPU $SUSPECT 만 $(date +%T)"
taskset -c $SUSPECT $PY k30_reproduction/diagnostics/hw_determinism.py 2 180 > $OUT/A_suspect_only.log 2>&1; tail -4 $OUT/A_suspect_only.log
echo "### B 행렬곱, CPU $OTHERS (30개) $(date +%T)"
taskset -c $OTHERS $PY k30_reproduction/diagnostics/hw_determinism.py 30 300 > $OUT/B_without_suspect.log 2>&1; tail -4 $OUT/B_without_suspect.log
for i in 1 2; do
  echo "### C$i SASAFL 176 단일(S1 구성), CPU $OTHERS $(date +%T)"
  MASTER_ADDR=210.107.197.176 MASTER_REPO=$PWD MASTER_PY=$PY MASTER_PORT=$((29850+i)) RUN_ID=core_c$i \
  ROUNDS=20 LEARNING_RATE=0.01 LOCAL_EPOCHS=5 BATCH_SIZE=32 LAG_TOLERANCE=9 K30_PID_DIR=/tmp/core_c$i \
  timeout 1200 taskset -c $OTHERS bash k30_reproduction/launch.sh SASAFL 0.1 30 single 1,2,3,4,8 > $OUT/C${i}_sasafl_without_suspect.log 2>&1
  echo "C$i exit=$? 마지막라운드=$(grep -oE 'SERVER >> [0-9]+번째' $OUT/C${i}_sasafl_without_suspect.log | tail -1 | grep -oE '[0-9]+') is_set=$(grep -c "is_set'" $OUT/C${i}_sasafl_without_suspect.log) SIGSEGV=$(grep -c SIGSEGV $OUT/C${i}_sasafl_without_suspect.log) SIGABRT=$(grep -c SIGABRT $OUT/C${i}_sasafl_without_suspect.log)"
  sleep 5
done
echo "### kernel segfaults since start"; grep -a "segfault" /var/log/kern.log | awk -v t="$(date +%b' '%e)" '$0 ~ t' | tail -8 | cut -c1-200
echo "### DONE $(date +%T)"
