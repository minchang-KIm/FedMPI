#!/usr/bin/env bash
# K=30 재현 실험 상태 한눈에 보기
#   bash k30_reproduction/status.sh            # 한 번 출력 (tmux 접속: tmux attach -t k30, HOW_TO_ACCESS.md)
#   watch -n 30 bash k30_reproduction/status.sh  # 30초마다 갱신 (Ctrl+C로 종료)
K30=/home/wise-175/Mando/FedMPI/k30_reproduction
now=$(date +%s)

echo "================ K=30 재현 실험 상태 ($(date '+%F %T')) ================"

echo
echo "[1] 프로세스"
check() {  # 라벨 패턴
    if pgrep -f "$2" > /dev/null; then echo "  ✔ $1"; else echo "  · $1 (실행 중 아님)"; fi
}
check "Table 2(MNIST) 실행기      run_k30.py table2" "^/home/wise-175/anaconda3/envs/FL/bin/python k30_reproduction/run_k30.py table2"
check "파이프라인 대기 스크립트   start_pipeline_after_table2.sh" "^bash k30_reproduction/start_pipeline_after_table2.sh"
check "파이프라인 본체            run_pipeline.py" "^/home/wise-175/anaconda3/envs/FL/bin/python k30_reproduction/pipeline/run_pipeline.py"
check "175 대조군 진단            run_175_controls_between_runs.sh" "^bash k30_reproduction/diagnostics/run_175_controls_between_runs.sh"
if pgrep -f "^/home/wise-175/anaconda3/envs/FL/bin/python k30_reproduction/run_k30.py table2" > /dev/null; then
    st=$(ps -o stat= -p "$(pgrep -f '^/home/wise-175/anaconda3/envs/FL/bin/python k30_reproduction/run_k30.py table2' | head -1)")
    [[ "$st" == T* ]] && echo "    (Table 2 실행기가 일시정지 상태: 대조군 진단 중일 수 있음)"
fi
echo "  학습 프로세스(harness_entry) 수: $(pgrep -fc '^/home/wise-175/anaconda3/envs/FL/bin/python.*harness_entry.py')"

echo
echo "[2] 지금 돌고 있는 실행"
# config.json이 있는 실제 실행 폴더 중 가장 최근 것 (smoke/fallback/재테스트/진단 S·F·R·H 제외)
latest=$(ls -t $K30/runs/*/config.json $K30/experiments/*/runs/*/config.json 2>/dev/null \
         | grep -v "_old_" | grep -vE "/runs/([SFR][0-9]_|H176_)" | xargs -r -n1 dirname 2>/dev/null \
         | while read -r d; do [ -f "$d/result.json" ] || [ "$(jq -r '.host // "wise-175"' "$d/config.json" 2>/dev/null)" != "$(hostname)" ] || { echo "$d"; break; }; done)
if [ -n "$latest" ] && [ ! -f "$latest/result.json" ]; then
    name=$(basename "$latest")
    last=$(grep -E "SERVER >> [0-9]+번째 글로벌 모델" "$latest/run.log" | tail -1)
    rnd=$(echo "$last" | grep -oE "[0-9]+번째" | grep -oE "[0-9]+")
    ts=$(echo "$last" | grep -oE "^\[[^]]+\]" | tr -d '[]' | cut -d. -f1)
    acc=$(grep -A2 "SERVER >> ${rnd}번째 글로벌 모델" "$latest/run.log" | grep -oE "test_accuracy: [0-9.]+" | head -1 | grep -oE "[0-9.]+$")
    req=$(grep -oE '"rounds": [0-9]+' "$latest/config.json" | head -1 | grep -oE "[0-9]+")
    start=$(grep -oE '"start": "[^"]+"' "$latest/config.json" | cut -d'"' -f4)
    echo "  실행: $name"
    echo "  진행: ${rnd:-0}/${req} 라운드, 최근 정확도 ${acc:-?}%  (시작 $start)"
    if [ -n "$ts" ]; then
        gap=$(( now - $(date -d "$ts" +%s) ))
        echo "  마지막 라운드 이후: ${gap}초 $( [ $gap -gt 600 ] && echo '⚠ 10분 넘게 진행 없음 — 확인 필요')"
        el=$(( now - $(date -d "$start" +%s) ))
        if [ "${rnd:-0}" -gt 0 ]; then
            eta=$(( el * (req - rnd) / rnd / 60 ))
            echo "  경과 $((el / 60))분, 이 실행 남은 시간 약 ${eta}분 (현재 속도 기준)"
        fi
    fi
else
    echo "  (진행 중인 실행 없음 — 실행 사이 대기이거나 전체 종료)"
fi

echo
echo "[3] 끝난 실행"
for f in $(ls -t $K30/runs/*/result.json $K30/experiments/*/runs/*/result.json 2>/dev/null | grep -v "_old_" \
          | xargs -r realpath | awk '!seen[$0]++' | head -40); do
    python3 - "$f" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
import re
if re.match(r"([SFR][0-9]_|H176_)", r["name"]):   # smoke/fallback/재테스트/진단은 생략
    sys.exit()
flag = "✔" if r["outcome"] == "completed" else "✘"
print(f"  {flag} {r['name']:<42} {r['outcome']:<9} {r['rounds_done']:>4}/{r['rounds_requested']:<4} "
      f"최고 {r['best_acc']}%  {r['wall_min']}분")
EOF
done

echo
echo "[4] 진행 기록 (PROGRESS.md 최근)"
tail -6 $K30/PROGRESS.md 2>/dev/null | sed 's/^/  /'
grep -q PIPELINE_DONE $K30/pipeline_console.log 2>/dev/null && echo "  ★ PIPELINE_DONE — 전체 완료"

echo
echo "[5] 서버"
echo "  $(uptime | sed 's/^ *//')"
echo "  최근 1시간 커널 하드웨어 오류/세그폴트:"
found=0
while IFS= read -r line; do
    t=$(date -d "$(echo "$line" | cut -c1-15)" +%s 2>/dev/null) || continue
    if [ $(( now - t )) -le 3600 ]; then echo "    $(echo "$line" | cut -c1-150)"; found=1; fi
done < <(grep -aE "segfault|mce:|Hardware Error" /var/log/kern.log 2>/dev/null | tail -20)
[ $found -eq 0 ] && echo "    없음"
echo "========================================================================"
