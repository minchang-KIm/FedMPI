#!/usr/bin/env bash
# wise-175에서 실행: 10분마다 wise-176이 차지한(claims/*/host = wise-176) E7 실행 폴더만 가져오고 그림·SUMMARY를 다시 만든다.
# (175가 돌린 실행 폴더는 건드리지 않는다.) 9개가 모두 완료되면 E7_ALL_DONE을 찍고 끝난다.
cd /home/wise-175/Mando/FedMPI
PY=/home/wise-175/anaconda3/envs/FL/bin/python
E7=k30_reproduction/experiments/E7_adaptive_off_2023code
REMOTE=wise-176@210.107.197.176:/home/wise-176/Mando/FedMPI/$E7/runs
while true; do
    for c in "$E7"/claims/*/host; do
        [ -f "$c" ] && [ "$(cat "$c")" = wise-176 ] || continue
        name=$(basename "$(dirname "$c")")
        rsync -a --exclude pids -e "ssh -o BatchMode=yes -o ConnectTimeout=10" "$REMOTE/$name/" "$E7/runs/$name/" 2>&1 | tail -1
    done
    $PY k30_reproduction/pipeline/run_pipeline.py --report-only --quiet --only E7 E6 > /dev/null 2>&1
    done_n=$(for f in "$E7"/runs/ERR_*/result.json; do [ -f "$f" ] && grep -q '"outcome": "completed"' "$f" && echo x; done | wc -l)
    echo "[$(date '+%F %T')] 동기화: 완료 $done_n/9"
    if (( done_n >= 9 )); then echo "[$(date '+%F %T')] E7_ALL_DONE"; break; fi
    sleep 600
done
