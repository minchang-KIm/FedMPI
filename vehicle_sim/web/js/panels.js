// 오른쪽 패널: 연합학습 상태(라운드·정확도·참여 분포·시간대별 참여·라운드별 차량), 설정 폼(차량·전체), 차량 고르기, 머리글 상태
import { $, el, S, STATE, PCOL, KIND, KCOL, PERIODS, ZONE_NAME, api, fmtH, vtypeOf, kindLabel } from "./util.js";
import { CARS, STYLES, liveCarState } from "./cars.js";
import { FX } from "./map3d.js";
import { DRIVE } from "./drive.js";
import { setCam } from "./view.js";
import { toast } from "./events.js";

// ------------------------------------------------------------------ 설정 폼 정의: [키, 이름, 종류, 최소, 최대, 단위, 유스케이스, 재시작 필요]
const VFIELDS = [
  ["차량 종류·성능", [
    ["vtype", "차량 종류", "sel:new=신형 EV (고성능),old=구형 EV (저성능)", 0, 0, 0, "4-1 · 7-1"],
    ["ecu_factor", "연산 속도 배수 (비우면 종류 기본값)", "num", 1, 4, 0.1, "4-1"],
    ["crash_prob", "계산 도중 중단 확률", "num", 0, 0.5, 0.01, "1-1"]]],
  ["긴급제동·연산 점유", [
    ["emergency_rate", "긴급 상황 민감도 (보행자 돌발·끼어들기 배수)", "num", 0, 10, 0.1, "1-4 · 4-5"],
    ["adas_base_s", "연산 점유 기본 시간 (초)", "num", 0, 30, 0.5, "4-5"],
    ["adas_per_10kmh_s", "속도 10 km/h당 추가 점유 (초)", "num", 0, 10, 0.1, "4-5"],
    ["adas_slowdown", "점유 중 학습 지연 배수", "num", 0, 10, 0.1, "4-5"],
    ["safety_preempt_prob", "긴급제동 시 FL 종료 확률", "num", 0, 1, 0.05, "1-4"],
    ["aeb", "수동 운전 시 ADAS 자동 긴급제동 (끄면 사람·차에 부딪힐 수 있음)", "bool", 0, 0, 0, "1-4 · 4-5"]]],
  ["참여 조건", [
    ["min_data", "학습 최소 새 데이터 (개)", "num", 0, 2000, 8, "3-2"],
    ["data_rate_per_s", "주행 중 데이터 수집 (개/초)", "num", 0, 100, 1, "3-2"],
    ["energy_gate", "에너지 안전 기준 확인 (끄면 방전까지 학습)", "bool", 0, 0, 0, "3-1 · 1-3"],
    ["battery_scale", "배터리 크기 배수 (전체 예산 × 배수)", "num", 0.05, 4, 0.05, "1-3 · 2-6"],
    ["data_mult", "학습 데이터 배수 (비우면 택시 2배·나머지 1배)", "num", 0.2, 5, 0.1, "4-6"],
    ["wifi_only", "비과금망(Wi-Fi)에서만 참여", "bool", 0, 0, 0, "3-3"],
    ["leave", "맵에서 이탈", "bool", 0, 0, 0, ""]]],
  ["전송", [
    ["store_forward", "끊기면 보관 후 한꺼번에 전송", "bool", 0, 0, 0, "5-1 · 5-2"],
    ["retransmit", "패킷 오류 시 재전송", "bool", 0, 0, 0, "4-3"]]],
  ["오류 값 지속 전송", [
    ["backdoor_boost", "악의적 조작: 업데이트 증폭", "num", 0, 50, 0.5, "6-1"],
    ["sensor_fault_classes", "센서 고장 라벨 (예: 3,8)", "text", 0, 0, 0, "6-2", true],
    ["sensor_fault_level", "센서 고장 오염 비율", "num", 0, 1, 0.05, "6-2", true],
    ["lr_override", "학습률 설정 오류 (비우면 정상)", "num", 0, 1, 0.001, "6-3"]]],
];
const GFIELDS = [
  ["학습 방식·연합학습", "fl", [
    ["method", "학습 방식", "method", 0, 0, 0, "", true], ["seed", "시드 (같으면 같은 조건)", "num", 0, 99999, 1, "", true],
    ["K", "차량 수 K", "num", 2, 16, 1, "", true], ["dataset", "데이터셋", "sel:MNIST,FashionMNIST,CIFAR10", 0, 0, 0, "", true],
    ["C", "최소 참여 비율 C", "num", 0.1, 1, 0.1, "", true], ["tau", "lag tolerance τ", "num", 1, 20, 1, "8-3", true],
    ["epochs", "로컬 epoch", "num", 1, 5, 1, "", true], ["lr", "학습률", "num", 0.0001, 0.1, 0.001, "", true],
    ["split", "데이터 분할", "sel:gaussian,uniform,dirichlet", 0, 0, 0, "", true], ["alpha", "Dirichlet α", "num", 0.01, 10, 0.05, "", true],
    ["rejoin", "끊긴 차량 복귀 허용 (끄면 원본처럼 영구 제외)", "bool", 0, 0, 0, "3-x"]]],
  ["통신", "net", [
    ["bandwidth_mbps", "상향 대역폭 (Mbps)", "num", 1, 200, 1, "4-4"], ["payload_mb", "업데이트 크기 (MB, 0=실제 모델 크기)", "num", 0, 500, 1, "2-x · 4-4"],
    ["fragments", "전송 시간 조각 수", "num", 1, 50, 1, "2-x"],
    ["frag_fail", "조각당 패킷 오류 확률", "num", 0, 0.5, 0.01, "2-3"], ["doppler_kmh", "도플러 기준 속도 (km/h)", "num", 30, 150, 5, "2-2"],
    ["doppler_fail", "고속 조각 실패 확률", "num", 0, 1, 0.05, "2-2"], ["cell_capacity", "셀당 동시 업로드 수", "num", 1, 10, 1, "4-2"],
    ["tdma_groups", "TDMA 그룹 수 G (1=끔)", "num", 1, 10, 1, "4-7"], ["tdma_slot_s", "TDMA 슬롯 길이 (초)", "num", 0.5, 20, 0.5, "4-7"],
    ["retx_timeout_s", "재전송 대기 (초)", "num", 1, 30, 1, "4-3"], ["retx_total_s", "재전송 전체 제한 (초)", "num", 1, 120, 1, "4-3"],
    ["gilbert_p", "음영지역 좋음 유지 p", "num", 0, 1, 0.05, "5-1"], ["gilbert_q", "음영지역 나쁨 유지 q", "num", 0, 1, 0.05, "5-1"],
    ["region_instability", "권역 경계 끊김 확률", "num", 0, 1, 0.05, "2-4"], ["handover_drops", "핸드오버 시 업로드 끊김", "bool", 0, 0, 0, "2-1"],
    ["weather_bw_mult", "강우 구역 대역폭 배수", "num", 0.05, 1, 0.05, "4-4"], ["edge_quality", "전송 보류 기준 통신 품질", "num", 0, 1, 0.05, "5-2"]]],
  ["에너지", "energy", [
    ["budget_j", "에너지 예산 (J)", "num", 100, 5000, 50, "1-3", true], ["round_j_min", "라운드당 소모 최소 (J)", "num", 0, 200, 1, "1-3"],
    ["round_j_max", "라운드당 소모 최대 (J)", "num", 0, 200, 1, "1-3"], ["min_energy_j", "참여 안전 기준 (J)", "num", 0, 2000, 10, "3-1"],
    ["charge_rate_jps", "충전 속도 (J/초)", "num", 1, 500, 5, ""], ["upload_j", "업로드 소모 (J)", "num", 0, 50, 1, "2-6"]]],
  ["주행 환경", "world", [
    ["npc_cars", "배경 차량 수 (학습 참여 안 함)", "num", 0, 60, 2, "", true],
    ["speed_scale", "주행 속도 배율", "num", 0.1, 5, 0.1, ""], ["signal_scale", "신호 주기 배율", "num", 0.2, 5, 0.1, ""],
    ["pedestrian_scale", "보행자 빈도 배율", "num", 0, 10, 0.5, "1-4 · 4-5"],
    ["walkers", "길을 걷는 사람 수", "num", 0, 200, 5, "1-4 · 4-5", true], ["jaywalk_per_min", "무단횡단 (1인당 분당 횟수)", "num", 0, 10, 0.1, "1-4 · 4-5"],
    ["ota_prob", "서비스센터 OTA 확률 (나머지는 정비 대기)", "num", 0, 1, 0.05, "1-2 · 3-2"],
    ["day_minutes", "하루 길이 (실제 분, 24시간)", "num", 2, 1440, 1, "7-3"], ["start_hour", "시작 시각 (시)", "num", 0, 23.9, 0.5, "7-3", true],
    ["weather_on", "강우 구역 켜기", "bool", 0, 0, 0, "4-4"], ["visitor_gap_mean_s", "통과 차량 재진입 평균 (초)", "num", 5, 600, 5, ""]]],
  ["서버", "server", [
    ["pause_s", "서버 장애 시간 (초)", "num", 5, 600, 5, "8-1 · 5-3"], ["p7_window", "편중 감시 창 (라운드)", "num", 5, 200, 1, "7-x", true],
    ["p7_ratio", "편중 판단 배수", "num", 1, 5, 0.1, "7-x"]]],
];
export const PRESET_ALL = {
  fl: { tau: 5 },
  net: { frag_fail: 0.03, doppler_fail: 0.25, region_instability: 0.6, cell_capacity: 1, tdma_groups: 2, tdma_slot_s: 3 },
  energy: { budget_j: 400, min_energy_j: 120, upload_j: 20 },
  world: { day_minutes: 20, ota_prob: 0.5, pedestrian_scale: 2, weather_on: true },
  server: { p7_window: 10 },
  vehicle_default: { crash_prob: 0.05 },
  vehicles: {
    "1": { min_data: 300, data_rate_per_s: 3 },                 // 3-2 새 데이터 없음
    "2": { store_forward: true, energy_gate: false, battery_scale: 0.1 },    // 5-1·5-2 보관 후 일괄, 2-6 전송 중 방전
    "3": { lr_override: 0.02, energy_gate: false, battery_scale: 0.25 },    // 6-3 학습률 오류 · 1-3 학습 중 방전
    "4": { store_forward: true },                               // 통과 차량: 5-1 터널 보관
    "5": { wifi_only: true },                                   // 3-3 Wi-Fi에서만
    "6": { backdoor_boost: 0.5, battery_scale: 0.5, store_forward: true },   // 6-1 악의적 조작 · 3-1 · 5-2
    "7": { emergency_rate: 3, safety_preempt_prob: 0.5 },       // 1-4·4-5 긴급제동
    "8": { sensor_fault_classes: "3,8", sensor_fault_level: 0.6 },   // 6-2 센서 고장 · 2-5
  },
};
export const PRESET_CLEAN = {
  fl: { tau: 9 },
  net: { frag_fail: 0.01, doppler_fail: 0.15, region_instability: 0.3, cell_capacity: 2, tdma_groups: 1 },
  energy: { budget_j: 1000, min_energy_j: 100, upload_j: 10 },
  world: { day_minutes: 30, ota_prob: 0.4, pedestrian_scale: 1 },
  vehicle_default: { crash_prob: 0.02 },
};

function inputFor(def, value, onchange) {
  const [key, name, type, min, max, step, uc, restart] = def;
  const f = el("div", "field");
  f.appendChild(el("label", "", `${name}${uc ? `<span class="uc">${uc}</span>` : ""}${restart ? '<span class="restart">재시작</span>' : ""}`));
  let inp;
  if (type === "bool") {
    inp = el("label", "switch", `<input type="checkbox" ${value ? "checked" : ""}><span></span>`);
    inp.querySelector("input").onchange = (e) => onchange(e.target.checked);
  } else if (type === "method" || type.startsWith("sel:")) {
    inp = el("select");
    const opts = type === "method" ? Object.entries(S.STATIC.methods).map(([k, m]) => [k, m.name]) : type.slice(4).split(",").map((o) => o.split("="));
    for (const [v, label] of opts) inp.appendChild(new Option(label || v, v, false, v === value));
    inp.onchange = () => onchange(inp.value);
  } else {
    inp = el("input"); inp.type = type === "text" ? "text" : "number";
    if (type !== "text") { inp.min = min; inp.max = max; inp.step = step; }
    inp.value = value === null || value === undefined ? "" : value;
    inp.onchange = () => onchange(type === "text" ? inp.value : (inp.value === "" ? null : Number(inp.value)));
  }
  inp.dataset.key = key;
  f.appendChild(inp);
  return f;
}
export async function postCfg(patch) {
  S.CFG = (await api.post("/api/config", patch)).config;
  renderMethodChip();
}
export function buildGlobalForm() {
  const box = $("#globalForm");
  box.innerHTML = "";
  for (const [title, sec, defs] of GFIELDS) {
    const grp = el("details", "fgroup-box", `<summary class="fgroup">${title}</summary>`);
    grp.open = true;
    for (const d of defs) grp.appendChild(inputFor(d, S.CFG[sec][d[0]], (v) => postCfg({ [sec]: { [d[0]]: v } })));
    box.appendChild(grp);
  }
}
export function buildVehForm() {
  const box = $("#vehForm");
  box.innerHTML = "";
  const all = el("div", "field apply-all", `<label><b>모든 차량에 적용</b><span class="uc">기본값을 바꿈</span></label>`);
  all.appendChild(el("label", "switch", `<input type="checkbox" id="applyAll"><span></span>`));
  box.appendChild(all);
  const cur = { ...S.CFG.vehicle_default, ...(S.CFG.vehicles[String(S.selected)] || {}) };
  if (!cur.vtype) cur.vtype = vtypeOf(S.selected);
  for (const [title, defs] of VFIELDS) {
    const grp = el("details", "fgroup-box", `<summary class="fgroup">${title}</summary>`);
    grp.open = true;
    for (const d of defs) grp.appendChild(inputFor(d, cur[d[0]], (v) => {
      if ($("#applyAll").checked) postCfg({ vehicle_default: { [d[0]]: v } });
      else postCfg({ vehicles: { [String(S.selected)]: { [d[0]]: v } } });
    }));
    box.appendChild(grp);
  }
}
/** 다른 사람이 바꾼 설정도 내 화면 폼에 반영 (입력 중인 칸이 있으면 끝난 뒤) */
let CFG_SEEN = "", formDirty = false;
export function syncForms() {
  const cs = JSON.stringify(S.CFG);
  if (cs === CFG_SEEN && !formDirty) return;
  if (CFG_SEEN && document.activeElement?.closest?.(".form, .presets")) { formDirty = true; CFG_SEEN = cs; return; }
  const first = !CFG_SEEN;
  CFG_SEEN = cs; formDirty = false;
  if (!first) { buildGlobalForm(); buildVehForm(); renderMethodChip(); }
}

// ------------------------------------------------------------------ 차량 고르기·정보
export function selectVehicle(v) {
  const other = S.DRIVERS[String(v)];
  if (DRIVE.on && other && v !== DRIVE.vid) {             // 운전 중에는 남이 운전하는 차로 갈아탈 수 없다
    toast({ msg: `V${v}은 ${other} 님이 운전 중입니다. 운전을 끄면 그 차 시점으로 볼 수 있어요.` });
    return;
  }
  S.selected = v;
  buildVehForm(); renderVehPicker(); renderVehInfo();
  if (S.CAM !== "orbit") setCam(S.CAM);                   // 따라가기·1인칭이면 새로 고른 차로
}
export function renderVehPicker() {
  const K = S.CFG.fl.K;
  for (const id of ["#vehPicker", "#vehGrid"]) {
    const box = $(id);
    if (box.children.length !== K) {
      box.innerHTML = "";
      for (let v = 1; v <= K; v++) { const b = el("button", "vchip"); b.onclick = () => selectVehicle(v); box.appendChild(b); }
    }
    [...box.children].forEach((b, i) => {
      const v = i + 1, s = S.REPLAY ? null : liveCarState(v);
      const [n, c] = STATE[s?.status] || STATE.idle;
      const vt = vtypeOf(v), dv = !S.REPLAY && S.DRIVERS[String(v)];
      b.style.setProperty("--st", c);
      b.className = `vchip ${vt}` + (v === S.selected ? " sel" : "");
      b.title = `${vt === "new" ? "신형 EV" : "구형 EV"} · ${STYLES[CARS[v]?.style]?.name || ""}`;
      b.innerHTML = `<b>V${v}</b><small>${S.REPLAY ? "-" : n}</small>` + (dv ? `<span class="drv" title="${dv} 님이 운전 중">🕹${dv}</span>` : "");
    });
  }
}
export function renderVehInfo() {
  const box = $("#vehInfo");
  if (S.REPLAY) { box.innerHTML = "<span class='muted'>다시 보기 중 — 실시간 차량 정보 없음</span>"; return; }
  const v = S.selected, s = liveCarState(v) || {}, c = S.LAST?.clients?.[v] || {};
  const zones = Object.entries(s.zones || {}).filter(([, b]) => b).map(([k]) => ZONE_NAME[k]).join(", ");
  const hist = c.label_hist || [], mx = Math.max(1, ...hist), cn = c.counters || {};
  const [name, col] = STATE[s.status] || STATE.idle;
  box.innerHTML = `
    <div class="vi-head"><span class="vi-dot" style="background:${col}"></span><b>V${v}</b>
      <span class="tag ${vtypeOf(v)}">${vtypeOf(v) === "new" ? "신형 EV" : "구형 EV"}</span><span class="muted">${STYLES[CARS[v]?.style]?.name || ""}</span></div>
    <div class="vi-sub">${kindLabel(s)} · ${S.MAP?.routes?.[s.route]?.name || "-"} · <b style="color:${col}">${name}</b> — ${c.detail || ""}</div>
    <div class="vi-grid">
      <div><span>일정</span>${s.sched || "-"}</div><div><span>주차</span>${s.parked ? `🅿 ${s.park_why} · ${Math.ceil(s.stop_left || 0)}초` : "-"}</div>
      <div><span>속도</span>${s.speed_kmh ?? "-"} km/h</div><div><span>통신</span>${s.link_up ? "🟢 연결" : "🔴 없음"}${s.wifi ? " 📶" : ""} · 셀 ${s.cell || "밖"} (${s.quality ?? "-"})</div>
      <div><span>구역</span>${zones || "없음"}</div><div><span>권역</span>${s.region || "-"}</div>
      <div><span>에너지</span>${c.energy ?? "-"} / ${c.budget ?? "-"} J</div><div><span>모델</span>v${c.version ?? "-"} / 서버 v${c.server_version ?? "-"}</div>
      <div><span>새 데이터</span>${c.new_data ?? "-"} · 연산 ×${c.ecu ?? "-"} · 데이터 ×${c.data_mult ?? "-"}</div><div><span>낭비</span>${c.wasted_mb ?? 0} MB</div>
    </div>
    ${s.emergency > 0 ? `<div class="vi-alert">⚠ 긴급제동(${s.emergency_cause}) — ADAS 연산 점유 ${s.emergency}초</div>` : ""}
    <div class="vi-cnt">학습 ${cn.trained ?? 0} · 전송 ${cn.sent ?? 0} · 폐기 ${cn.dropped ?? 0} · 중단 ${cn.aborted ?? 0} · 미참여 ${cn.skipped ?? 0} · 보관 ${cn.queued ?? 0}</div>
    <div class="muted small">라벨 분포 (데이터 ${c.n_data ?? "-"}개, 최다 라벨 ${Math.round((c.label_skew || 0) * 100)}%) · 새 모델 연속 거부 ${c.keep_streak ?? 0}회</div>
    <div class="bars">${hist.map((h, i) => `<div title="${i}: ${h}" style="height:${(h / mx) * 100}%"></div>`).join("")}</div>`;
}

// ------------------------------------------------------------------ 연합학습 패널
let lastRoundShown = -1;
export function resetRounds() { lastRoundShown = -1; $("#roundFeed").innerHTML = ""; }
export function renderFL(server, downLeft) {
  const s = server || {}, hist = s.history || [], last = hist[hist.length - 1];
  $("#kRound").textContent = s.round ?? "-";
  $("#kAcc").textContent = last ? last.acc.toFixed(1) + "%" : "-";
  $("#kQuota").textContent = s.quota ?? "-";
  $("#kBuf").textContent = s.cached !== undefined ? `${s.cached}/${s.quota}` : "-";
  const wsec = s.phase === "waiting" ? s.waiting_s || 0 : 0;
  $("#waitFill").style.width = s.phase === "down" ? "100%" : Math.min(100, (wsec / 60) * 100) + "%";
  $("#waitText").textContent = s.phase === "down" ? `⛔ 집계 서버 장애 — ${downLeft ? Math.ceil(downLeft) + "초 뒤 복구" : "중단"} (8-1)`
    : s.phase === "waiting" ? `quota ${s.quota}개 모일 때까지 ${wsec.toFixed(0)}초 (버퍼 ${s.cached}개${wsec > 60 ? " · ⚠ 8-2 무한 대기" : ""})` : "집계 중";
  const ph = $("#flPhase");
  ph.textContent = { waiting: "값 대기", aggregated: "집계 완료", start: "시작", down: "서버 장애" }[s.phase] || "-";
  ph.dataset.phase = s.phase || "";
  drawAcc(hist);
  drawFair(s.participation);
  drawPeriod(s.participation);
  const feed = $("#roundFeed");
  for (const r of hist) {
    if (r.round <= lastRoundShown || !r.picked) continue;
    lastRoundShown = r.round;
    if (!r.picked.length) continue;
    const card = el("div", "round");
    card.innerHTML = `<div class="round-head"><b>${r.round}라운드</b><span>정확도 ${r.acc}% · quota ${r.quota}→${r.next_quota ?? "-"} · ${r.dur ?? "-"}초</span></div>`;
    const cars = el("div", "round-cars");
    r.picked.forEach((p, i) => {
      const chip = el("span", `pcar ${vtypeOf(p.vid)}` + (p.staleness > 0 ? " stale" : "") + ((r.dups || []).includes(p.vid) ? " dup" : ""),
        `V${p.vid} · s${p.staleness} · ${Math.round(p.weight * 100)}%`);
      chip.style.animationDelay = i * 140 + "ms";
      chip.title = `모델 v${p.version}, staleness ${p.staleness}, 집계 비중 ${p.weight}`;
      cars.appendChild(chip);
    });
    card.appendChild(cars);
    feed.prepend(card);
    while (feed.children.length > 50) feed.lastChild.remove();
  }
}
export function canvasCtx(cv, h) {
  const dp = devicePixelRatio, W = (cv.width = cv.clientWidth * dp), H = (cv.height = h * dp);
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  ctx.font = `${11.5 * dp}px Pretendard, "Noto Sans KR", sans-serif`;
  return [ctx, W, H, dp];
}
function drawAcc(hist) {
  const [ctx, W, H, dp] = canvasCtx($("#accChart"), 120);
  ctx.strokeStyle = "rgba(148,163,184,0.15)"; ctx.lineWidth = 1;
  for (let y = 1; y < 4; y++) { ctx.beginPath(); ctx.moveTo(0, (H * y) / 4); ctx.lineTo(W, (H * y) / 4); ctx.stroke(); }
  ctx.fillStyle = "#8ea0c2"; ctx.fillText("정확도 % (라운드별)", 8 * dp, 15 * dp);
  if (hist.length < 2) return;
  const n = hist.length - 1, pts = hist.map((h, i) => [(i / n) * W, H - (h.acc / 100) * (H - 6 * dp)]);
  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, "rgba(91,156,255,0.35)"); grad.addColorStop(1, "rgba(91,156,255,0)");
  ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.lineTo(W, H); ctx.lineTo(0, H); ctx.fillStyle = grad; ctx.fill();
  ctx.strokeStyle = "#5b9cff"; ctx.lineWidth = 2 * dp; ctx.beginPath();
  pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.stroke();
}
function drawFair(part) {
  const [ctx, W, H, dp] = canvasCtx($("#fairChart"), 104);
  const win = part?.window || {}, K = S.CFG.fl.K;
  const vals = Array.from({ length: K }, (_, i) => win[String(i + 1)] || 0);
  const top = 22 * dp, bottom = 16 * dp, mx = Math.max(1, ...vals), bw = W / K;
  ctx.fillStyle = "#8ea0c2";
  ctx.fillText(`■ 청록 = 신형 EV   ■ 주황 = 구형 EV   (최근 ${part?.window_rounds ?? 0}라운드)`, 8 * dp, 15 * dp);
  vals.forEach((v, i) => {
    const h = (v / mx) * (H - top - bottom);
    ctx.fillStyle = vtypeOf(i + 1) === "new" ? "#22d3ee" : "#f59e0b";
    ctx.fillRect(i * bw + 3 * dp, H - bottom - h, bw - 6 * dp, h);
    ctx.fillStyle = "#cbd5e1";
    ctx.fillText(`V${i + 1}`, i * bw + 3 * dp, H - 3 * dp);
  });
}
// 시간대별 참여: 각 시간대에 집계된 값이 어떤 차량 종류(통근·택시·주민·통과)에서 왔는지 (7-3)
function drawPeriod(part) {
  const [ctx, W, H, dp] = canvasCtx($("#periodChart"), 112);
  const per = part?.period || {}, K = S.CFG.fl.K;
  const kindOf = (v) => S.LAST?.world?.vehicles?.[v]?.kind || "visitor";
  const fleet = {};
  for (let v = 1; v <= K; v++) fleet[kindOf(v)] = (fleet[kindOf(v)] || 0) + 1;
  const rows = [["fleet", "차량 구성"], ...PERIODS];
  const top = 4 * dp, rh = (H - top) / rows.length, x0 = 120 * dp;
  rows.forEach(([key, label], r) => {
    const cnt = {};
    let tot = 0;
    if (key === "fleet") for (const [k, n] of Object.entries(fleet)) { cnt[k] = n; tot += n; }
    else for (const [v, n] of Object.entries(per[key] || {})) { const k = kindOf(v); cnt[k] = (cnt[k] || 0) + n; tot += n; }
    const y = top + r * rh;
    ctx.fillStyle = key === S.LAST?.world?.period ? "#fde68a" : "#cbd5e1";
    ctx.fillText(label + (key === "fleet" ? "" : ` (${tot})`), 4 * dp, y + rh * 0.7);
    let x = x0;
    for (const k of ["commute", "city", "resident", "visitor"]) {
      if (!tot || !cnt[k]) continue;
      const w = ((W - x0 - 4 * dp) * cnt[k]) / tot;
      ctx.fillStyle = KCOL[k];
      ctx.fillRect(x, y + 2 * dp, w - 1, rh - 4 * dp);
      if (w > 34 * dp) { ctx.fillStyle = "#0f172a"; ctx.fillText(`${KIND[k]} ${Math.round((100 * cnt[k]) / tot)}%`, x + 3 * dp, y + rh * 0.7); }
      x += w;
    }
  });
}

// ------------------------------------------------------------------ 머리글: 실행 상태·시계·학습 방식·접속자·범례
export function renderMethodChip() { $("#methodChip").textContent = S.STATIC.methods[S.CFG.fl.method]?.name || S.CFG.fl.method; }
export function renderRun() {
  const L = S.LAST, running = L.procs?.fl === "running";
  const chip = $("#runChip");
  chip.className = "chip status " + (L.server_down_left > 0 ? "warn" : running ? "run" : L.note ? "bad" : "");
  chip.innerHTML = `<i></i>${L.server_down_left > 0 ? "서버 장애 중" : running ? "학습 실행 중" : L.note ? "학습 종료" : "정지"}`;
  const e = L.world?.elapsed;
  $("#runInfo").textContent = (e ? `${Math.floor(e / 60)}분 ${Math.floor(e % 60)}초 경과` : "") + (L.note ? ` · ${L.note}` : "");
  $("#runInfo").title = L.run ? `실행 ${L.run}` : "";
  if (FX.weather) { FX.weather.visible = S.CFG.world.weather_on; FX.weather.userData.label.visible = S.CFG.world.weather_on && $("#optPlaces").checked; }
  const w = L.world;
  const icon = { night: "🌙", am: "🌅", day: "☀️", pm: "🌇", evening: "🌆" }[w?.period] || "🕒";
  $("#clock").innerHTML = w?.tod !== undefined ? `${icon} <b>${fmtH(w.tod)}</b><span>${w.day}일차 · ${w.period_name}</span>` : "🕒 -";
  $("#mapChip").textContent = `🗺 ${S.MAP?.name || ""}`;
}
export function renderPeers() {
  const rows = S.PEERS.map((p) => `<div>${p.me ? "<b>나</b> · " : ""}${p.name}${p.driving ? ` · 🕹 V${p.driving} 운전 중` : p.sel ? ` · V${p.sel} 보는 중` : ""}</div>`).join("");
  $("#peersChip").innerHTML = `👥 ${S.PEERS.length}<div class="peers-list"><b>지금 접속한 사람</b>${rows || "-"}</div>`;
  const b = $("#btnDrive"), other = S.DRIVERS[String(S.selected)];
  if (!DRIVE.on) {
    const busy = other && !S.PEERS.some((p) => p.me && String(p.driving) === String(S.selected));
    b.disabled = !!busy;
    b.innerHTML = busy ? `🕹 V${S.selected} — ${other} 님 운전 중` : "🕹 운전";
  }
}
export function buildLegends() {
  $("#legendState").innerHTML = "<b>바닥 링·지붕 등·이름표 색 = 연합학습 상태</b>" +
    Object.values(STATE).map(([n, c]) => `<span><i style="background:${c}"></i>${n}</span>`).join("") +
    "<span class='wide muted'>신형 EV: 고급 세단·고성능 세단·전기 해치백·전기 SUV · 구형 EV: 경형 SUV·승합 밴·1톤 트럭·중형 세단·각진 SUV · 링이 없는 차 = 배경 차량</span>" +
    "<span class='wide muted'>🅿주차 ⚡충전 🔧OTA 🚇터널 📶Wi-Fi 📵연결 없음 📦보관 ⚠긴급제동 🪫에너지↓ · 빨간 사람 = 돌발 보행자</span>";
  $("#legendPatterns").innerHTML = "<b>사건 색 = 패턴 (서버가 받은 모습)</b>" +
    Object.entries(S.STATIC.patterns).map(([k, n]) => `<span><i style="background:${PCOL[k]}"></i>P${k} ${n}</span>`).join("");
}
