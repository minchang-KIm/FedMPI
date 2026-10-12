#!/usr/bin/env bash
# 176에서만 실행하는 진단 묶음. 결과: k30_reproduction/diagnostics/out_176/
cd /home/wise-176/Mando/FedMPI
PY=/home/wise-176/miniconda3/envs/FL/bin/python
OUT=k30_reproduction/diagnostics/out_176; mkdir -p $OUT
export FEDMPI_REPO=$PWD
echo "### 1 hw_determinism $(date +%T)"; $PY k30_reproduction/diagnostics/hw_determinism.py 32 300 > $OUT/1_hw_determinism.log 2>&1; tail -3 $OUT/1_hw_determinism.log
echo "### 2 thread_pattern_repro $(date +%T)"; $PY k30_reproduction/diagnostics/thread_pattern_repro.py 300 30 > $OUT/2_thread_pattern.log 2>&1; tail -4 $OUT/2_thread_pattern.log
run_fl() {  # method cats tag i
  MASTER_ADDR=210.107.197.176 MASTER_REPO=$PWD MASTER_PY=$PY MASTER_PORT=$((29800+RANDOM%100)) RUN_ID=diag_$3_$4 \
  ROUNDS=20 LEARNING_RATE=0.01 LOCAL_EPOCHS=5 BATCH_SIZE=32 LAG_TOLERANCE=9 K30_PID_DIR=/tmp/diag_$3_$4 \
  timeout 900 bash k30_reproduction/launch.sh $1 0.1 30 single $2 > $OUT/$3_$4.log 2>&1
  echo "$3 #$4 exit=$? 마지막라운드=$(grep -oE 'SERVER >> [0-9]+번째' $OUT/$3_$4.log | tail -1 | grep -oE '[0-9]+') is_set=$(grep -c "is_set'" $OUT/$3_$4.log) SIGSEGV=$(grep -c SIGSEGV $OUT/$3_$4.log) SIGABRT=$(grep -c SIGABRT $OUT/$3_$4.log)"
  sleep 5
}
echo "### 3 BSA single paperCats $(date +%T)"; for i in 1 2; do run_fl SemiAsync 1,2,3,4,8 3_BSA_paperCats $i; done
echo "### 4 SASAFL single threads1 $(date +%T)"; for i in 1 2; do run_fl SASAFL 1 4_SASAFL_threads1 $i; done
echo "### DONE $(date +%T)"
