#!/usr/bin/env bash
# wise-175에서 실행: 10분마다 wise-176이 차지한(claims/*/host = wise-176) E7·E8 실행 폴더만 가져오고 그림·SUMMARY를 다시 만든다.
# (175가 돌린 실행 폴더는 건드리지 않는다.) E7 9개 + E8 27개가 모두 완료되면 SYNC_ALL_DONE을 찍고 끝난다.
cd /home/wise-175/Mando/FedMPI
PY=/home/wise-175/anaconda3/envs/FL/bin/python
X=k30_reproduction/experiments
R176=wise-176@210.107.197.176:/home/wise-176/Mando/FedMPI
while true; do
    for exp in E7_adaptive_off_2023code E8_K10; do
        for c in "$X/$exp"/claims/*/host; do
            [ -f "$c" ] && [ "$(cat "$c")" = wise-176 ] || continue
            name=$(basename "$(dirname "$c")")
            mkdir -p "$X/$exp/runs/$name"
            rsync -a --exclude pids -e "ssh -o BatchMode=yes -o ConnectTimeout=10" \
                "$R176/$X/$exp/runs/$name/" "$X/$exp/runs/$name/" 2>&1 | tail -1
        done
    done
    $PY k30_reproduction/pipeline/run_pipeline.py --report-only --quiet --only E7 E8 E6 > /dev/null 2>&1
    n7=$(for f in "$X"/E7_*/runs/ERR_*/result.json; do [ -f "$f" ] && grep -q '"outcome": "completed"' "$f" && echo x; done | wc -l)
    n8=$(for f in "$X"/E8_K10/runs/K10_*/result.json; do [ -f "$f" ] && grep -q '"outcome": "completed"' "$f" && echo x; done | wc -l)
    echo "[$(date '+%F %T')] 동기화: E7 완료 $n7/9, E8 완료 $n8/27"
    if (( n7 >= 9 && n8 >= 27 )); then echo "[$(date '+%F %T')] SYNC_ALL_DONE"; break; fi
    sleep 600
done
