// 저장·맵(상태 저장/불러오기, 맵 카드·올리기·내려받기)과 기록·비교(실행 목록·정확도 겹쳐 보기·ablation·다시 보기)
import { $, el, S, api, clamp, fmtH, fmtT } from "./util.js";
import { applyTime } from "./scene.js";
import { buildScene, updateSignals, updateCrossPeds } from "./map3d.js";
import { clearCars, drawCar, drawNpcs } from "./cars.js";
import { updateWalkers } from "./walkers.js";
import { fitView } from "./view.js";
import { replayEvents, renderCases, resetEvents } from "./events.js";
import { canvasCtx, postCfg, renderFL, resetRounds } from "./panels.js";

let afterStartFn = null;
export const setAfterStart = (fn) => (afterStartFn = fn);
export async function control(action, extra = {}) {
  const r = await api.post("/api/control", { action, ...extra });
  if (r.config) S.CFG = r.config;
  return r;
}
/** 서버가 준 맵(/api/static)을 지금 맵으로 그린다 */
export async function showMap(st) {
  S.STATIC = st;
  S.MAP_ID = st.map_id;
  clearCars();
  buildScene(st.map, st.layout);
  fitView();
}

// ------------------------------------------------------------------ 저장·맵
export async function loadSaves() {
  const r = await api.get("/api/saves");
  const box = $("#savesList");
  box.innerHTML = r.saves.length ? "" : "<span class='muted small'>저장한 상태가 없습니다.</span>";
  for (const s of r.saves) {
    const it = el("div", "item", `<span><b>${s.name || s.id}</b> · ${s.round ?? "-"}라운드 · ${s.method || ""} · ${s.map || ""} · ${s.saved ? fmtT(s.saved) : ""}</span>`);
    const b = el("button", "btn small", "불러오기");
    b.onclick = async () => { await control("load", { id: s.id }); await afterStartFn(); document.querySelector('[data-tab="map"]').click(); };
    it.appendChild(b);
    box.appendChild(it);
  }
  renderMapCards();
  $("#mapDownload").href = "data:application/json;charset=utf-8," + encodeURIComponent(JSON.stringify(S.STATIC.map, null, 2));
  $("#mapDownload").download = `${S.CFG.world.map || "map"}.json`;
  if (S.LAST?.run) $("#btnExport").href = `/api/export?run=${encodeURIComponent(S.LAST.run)}`;
}
// 맵 고르기: 맵마다 34개 유스케이스를 일으킬 조건(장소·구역)을 갖췄는지 표시
async function renderMapCards() {
  const info = (await api.get("/api/maps")).info;
  const box = $("#mapCards");
  box.innerHTML = "";
  const curId = S.CFG.world.map || "default";
  for (const m of info) {
    const cur = m.id === curId;
    const km = (m.size || []).map((v) => (v / 1000).toFixed(1)).join(" × ");
    const c = el("div", "mapcard" + (cur ? " cur" : ""), `<div class="mc-head"><b>${m.name}</b><span class="muted small">${km} km</span></div>
      <div class="small muted">${m.desc || ""}</div>
      <div class="cov ${m.ok === 34 ? "ok" : "bad"}">유스케이스 조건 ${m.ok}/34${m.missing.length ? " · 없음: " + m.missing.join(", ") : " ✓"}</div>`);
    const b = el("button", "btn small" + (cur ? "" : " primary"), cur ? "사용 중" : "이 맵 사용");
    b.disabled = cur;
    b.onclick = async () => {
      await postCfg({ world: { map: m.id } });
      const running = S.LAST?.procs?.fl === "running";
      if (!running) { await showMap(await api.get("/api/static")); renderCases(); }
      $("#mapNote").textContent = running ? `맵 '${m.name}' — 지금 실행이 끝나고 다음 ▶ 시작부터 적용됩니다.` : `맵 '${m.name}'으로 바꿨습니다. ▶ 시작을 누르세요.`;
      renderMapCards();
    };
    c.appendChild(b);
    box.appendChild(c);
  }
  const cov = S.STATIC.coverage || [];
  $("#mapCoverage").innerHTML = `<div class="fgroup">지금 맵에서 유스케이스를 일으키는 곳 (${cov.filter((x) => x.ok).length}/34)</div>` +
    `<table class="covtab">${cov.map((x) => `<tr><td>${x.ok ? "✅" : "❌"}</td><td><b>${x.id}</b></td><td>${x.how}</td></tr>`).join("")}</table>` +
    ((S.STATIC.problems || []).length ? `<p class="bad small">맵 문제: ${S.STATIC.problems.join(" / ")}</p>` : "");
}
export function initRecordInput() {
  $("#btnSave").onclick = async () => {
    const r = await control("save", { name: $("#saveName").value || "상태" });
    $("#mapNote").textContent = r.id ? `저장됨: ${r.id}` : "실행 중인 시뮬레이션이 없습니다.";
    loadSaves();
  };
  $("#mapFile").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    let m;
    try { m = JSON.parse(await f.text()); } catch { $("#mapNote").textContent = "JSON 형식이 아닙니다."; return; }
    const r = await api.post("/api/map", { name: f.name.replace(/\.json$/, ""), map: m });
    $("#mapNote").textContent = r.ok ? `맵 '${r.name}' 저장됨${r.missing?.length ? ` (조건 없는 유스케이스: ${r.missing.join(", ")})` : " (34/34)"} — 위에서 '이 맵 사용'을 누르세요.` : `맵 오류: ${r.errors.join(", ")}`;
    loadSaves();
  };
  $("#btnRunsRefresh").onclick = loadRuns;
  $("#btnAblation").onclick = async () => {
    const m = $("#ablMethod").value;
    if (!confirm(`지금 설정·시드 그대로 '${S.STATIC.methods[m].name}'(으)로 새로 실행합니다.`)) return;
    if (S.LAST?.run) CMP_SEL.add(S.LAST.run);
    await control("ablation", { method: m });
    await afterStartFn();
  };
  $("#importFile").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const r = await api.post("/api/import", await f.arrayBuffer());
    if (r.ok) { await loadRuns(); alert(`불러옴: ${r.run} — '다시 보기'로 재생할 수 있습니다.`); }
  };
  $("#rpSlider").oninput = (e) => seekReplay(Number(e.target.value));
  $("#rpPlay").onclick = () => { S.REPLAY.playing = !S.REPLAY.playing; $("#rpPlay").textContent = S.REPLAY.playing ? "❚❚" : "▶"; };
  $("#rpExit").onclick = () => exitReplay(true);
  setInterval(() => {
    const R = S.REPLAY;
    if (!R || !R.playing) return;
    R.acc += Number($("#rpSpeed").value) * 0.5;           // 0.5초마다, 기록은 1초 간격
    const step = Math.floor(R.acc);
    if (step >= 1) { R.acc -= step; seekReplay(R.idx + step); if (R.idx >= R.world.length - 1) R.playing = false; }
  }, 500);
}

// ------------------------------------------------------------------ 기록·비교·다시 보기
let RUNS = [];
const CMP_SEL = new Set();
const CMP_COL = ["#5b9cff", "#f472b6", "#4ade80", "#facc15", "#fb923c", "#c084fc", "#38bdf8", "#f87171"];
export async function loadRuns() {
  RUNS = (await api.get("/api/runs")).runs;
  const t = $("#runsTable");
  t.innerHTML = "<tr><th></th><th>실행</th><th>학습 방식</th><th>시드</th><th>맵</th><th>K</th><th>라운드</th><th>정확도</th><th>사건</th><th></th></tr>";
  if (!RUNS.length) t.innerHTML += "<tr><td colspan='10' class='muted'>아직 실행 기록이 없습니다. ▶ 시작을 누르면 쌓입니다.</td></tr>";
  for (const r of RUNS) {
    const tr = el("tr");
    tr.innerHTML = `<td><input type="checkbox" ${CMP_SEL.has(r.run) ? "checked" : ""}></td><td>${r.run}</td>
      <td>${S.STATIC.methods[r.method]?.name || r.method || "-"}</td><td>${r.seed ?? "-"}</td><td>${r.map || "-"}</td><td>${r.K ?? "-"}</td>
      <td>${r.rounds ?? "-"}</td><td>${r.acc ?? "-"}</td><td>${r.events}</td><td></td>`;
    tr.querySelector("input").onchange = (e) => { e.target.checked ? CMP_SEL.add(r.run) : CMP_SEL.delete(r.run); drawCompare(); };
    const b = el("button", "btn small", "다시 보기");
    b.onclick = () => startReplay(r.run);
    const a = el("a", "btn small", "내보내기");
    a.href = `/api/export?run=${encodeURIComponent(r.run)}`;
    tr.lastChild.append(b, " ", a);
    t.appendChild(tr);
  }
  const sel = $("#ablMethod");
  if (!sel.children.length) for (const [k, m] of Object.entries(S.STATIC.methods)) sel.appendChild(new Option(m.name, k));
  drawCompare();
}
function drawCompare() {
  const [ctx, W, H, dp] = canvasCtx($("#cmpChart"), 260);
  ctx.strokeStyle = "rgba(148,163,184,0.15)";
  for (let y = 1; y < 4; y++) { ctx.beginPath(); ctx.moveTo(0, (H * y) / 4); ctx.lineTo(W, (H * y) / 4); ctx.stroke(); }
  const sel = RUNS.filter((r) => CMP_SEL.has(r.run));
  const maxR = Math.max(10, ...sel.flatMap((r) => r.curve.map((c) => c[0])));
  sel.forEach((r, i) => {
    ctx.strokeStyle = CMP_COL[i % CMP_COL.length]; ctx.lineWidth = 2.2 * dp; ctx.beginPath();
    r.curve.forEach(([rd, acc], j) => { const x = (rd / maxR) * W, y = H - (acc / 100) * H; j ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
    ctx.fillStyle = CMP_COL[i % CMP_COL.length];
    ctx.fillText(`${S.STATIC.methods[r.method]?.name || r.method} · 시드 ${r.seed} · ${r.run}`, 8 * dp, (16 + i * 16) * dp);
  });
  if (!sel.length) { ctx.fillStyle = "#8ea0c2"; ctx.fillText("아래 목록에서 실행을 체크하면 정확도 곡선을 겹쳐 그립니다 (가로 = 라운드)", 10 * dp, 20 * dp); }
}
async function startReplay(run) {
  const d = await api.get(`/api/replay?run=${encodeURIComponent(run)}`);
  if (!d.world?.length) { alert("이 실행에는 주행 기록이 없습니다."); return; }
  S.REPLAY = { run, ...d, idx: 0, playing: true, acc: 0 };
  document.body.classList.add("replaying");
  $("#replayBar").classList.remove("hidden");
  $("#replayName").textContent = `${run} · ${S.STATIC.methods[d.config?.fl?.method]?.name || ""}`;
  const slider = $("#rpSlider");
  slider.max = d.world.length - 1; slider.value = 0;
  const mapName = d.config?.world?.map || "default";
  if (mapName !== S.MAP_ID) {
    const st = await api.get(`/api/static?map=${encodeURIComponent(mapName)}`);
    S.MAP_ID = st.map_id; buildScene(st.map, st.layout);
  }
  clearCars(); resetEvents();
  document.querySelector('[data-tab="map"]').click();
  seekReplay(0);
}
function seekReplay(i) {
  const R = S.REPLAY;
  R.idx = clamp(i, 0, R.world.length - 1);
  const f = R.world[R.idx];
  $("#rpSlider").value = R.idx;
  $("#rpTime").textContent = `${f.h !== undefined ? "🕒 " + fmtH(f.h) + " · " : ""}${fmtT(f.t)} · ${Math.floor(f.c / 60)}분 ${Math.floor(f.c % 60)}초`;
  applyTime(f.h);
  const recent = {};
  for (const e of R.events) if (e.t <= f.t && e.t > f.t - 4 && e.vid && e.pattern) recent[e.vid] = e;
  for (const [vid, a] of Object.entries(f.v)) {
    const [x, z, h, kmh, flags] = a, ev = recent[vid];
    const status = !(flags & 1) ? "absent" : ev ? ({ 1: "dead", 2: "dead", 3: "skipped", 4: "waiting", 5: "queued" }[ev.pattern] || "training")
      : (flags & 32 ? "idle" : "dead");
    drawCar(Number(vid), { pos: [x, z], heading: h, present: !!(flags & 1), status, emergency: flags & 16 ? 1 : 0, braking: !!(flags & 64), engine_off: !!(flags & 2),
      badges: [flags & 2 && flags & 1 ? "🅿" : "", flags & 4 ? "⚡" : "", flags & 8 ? "🔧" : "", flags & 16 ? "⚠" : "", ` ${kmh}km/h`].join("") });
  }
  drawNpcs((f.n || []).map(([id, x, z, h]) => [id, x, z, h, 0, 0]));
  const sigs = {};
  for (const [id, s] of Object.entries(f.s || {})) sigs[id] = [s[0], s[1]];
  updateSignals(sigs);
  updateCrossPeds(f.p);
  updateWalkers(f.w || []);
  const hist = (R.server?.history || []).filter((h) => h.t <= f.t);
  resetRounds();
  renderFL({ ...(R.server || {}), history: hist, round: hist.length ? hist[hist.length - 1].round : 0, phase: "aggregated" }, 0);
  replayEvents(R.events.filter((e) => e.t <= f.t));
  renderCases(f.t);
}
export function exitReplay(resume) {
  if (!S.REPLAY) return;
  S.REPLAY = null;
  document.body.classList.remove("replaying");
  $("#replayBar").classList.add("hidden");
  clearCars();
  if (S.MAP_ID !== S.STATIC.map_id) { S.MAP_ID = S.STATIC.map_id; buildScene(S.STATIC.map, S.STATIC.layout); }
  if (resume) { S.evOffset = 0; resetEvents(); resetRounds(); }
}
