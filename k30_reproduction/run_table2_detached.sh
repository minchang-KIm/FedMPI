#!/usr/bin/env bash
# Table 2 MNIST 6개 실행 + 비교표 생성. 세션과 분리해서 실행한다:
#   setsid nohup bash k30_reproduction/run_table2_detached.sh > k30_reproduction/table2_detached.out 2>&1 &
cd /home/wise-175/Mando/FedMPI
PY=/home/wise-175/anaconda3/envs/FL/bin/python
$PY k30_reproduction/run_k30.py table2 --mode single --cats 1,2,3,4,8 --stall-min 15 --max-wall-min 600 \
    > k30_reproduction/table2_console.log 2>&1
$PY k30_reproduction/make_table2.py > k30_reproduction/table2_build.log 2>&1
echo "TABLE2_DONE $(date)"
