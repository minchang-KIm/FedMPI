// 시작점: 버튼·탭·패널 연결, 0.4초마다 서버 상태 받기, 매 프레임 그리기
import { $, $$, S, ME, api, askName, store } from "./util.js";
import { applyTime, controls, cullLabels, holder, renderScene, resizeRenderer, layers } from "./scene.js";
import { animateFx, buildScene, updateCrossPeds, updateSignals } from "./map3d.js";
import { CARS, animateCars, clearCars, drawCar, drawNpcs, liveCarState, removeCar, showroom } from "./cars.js";
import { drawWalkers, updateWalkers } from "./walkers.js";
import { fitView, flyTo, initViewInput, look, setCam, toggleBoxMode, updateCamera, zoomBy, focusOn } from "./view.js";
import { DRIVE, initDriveInput, renderHud, renderHudFast, setDrive } from "./drive.js";
import { buildLogFilter, handleEvents, renderCases, resetEvents } from "./events.js";
import { PRESET_ALL, PRESET_CLEAN, buildGlobalForm, buildLegends, buildVehForm, postCfg, renderFL, renderMethodChip, renderPeers,
  renderRun, renderVehInfo, renderVehPicker, resetRounds, selectVehicle, syncForms } from "./panels.js";
import { control, exitReplay, initRecordInput, loadRuns, loadSaves, setAfterStart, showMap } from "./records.js";

// ------------------------------------------------------------------ 실행 제어
async function afterStart() {
  exitReplay(false);
  S.evOffset = 0;
  resetEvents(); resetRounds();
  const st = await api.get("/api/static");
  if (!S.MAP || st.map_id !== S.MAP_ID) await showMap(st); else { S.STATIC = st; clearCars(); }
  buildVehForm(); buildGlobalForm(); renderMethodChip(); renderCases();
}
setAfterStart(afterStart);
$("#btnStart").onclick = async () => { await control("start"); await afterStart(); };
$("#btnStop").onclick = () => control("stop");
$("#btnDown").onclick = () => {
  const s = S.CFG.server.pause_s;
  if (confirm(`집계 서버를 ${s}초 동안 멈췄다가 복구합니다 (8-1). 그동안 차량은 값을 보관했다가 복구 후 한꺼번에 보냅니다 (5-3).`)) control("server_down", { seconds: s });
};
$("#btnReset").onclick = async () => { await control("reset_config"); buildGlobalForm(); buildVehForm(); renderMethodChip(); };
$("#presetAll").onclick = async () => {
  await postCfg(PRESET_ALL);
  $("#presetNote").textContent = "적용됨. 센서 고장(V8)·τ·감시 창은 다음 시작부터 → ▶ 시작을 다시 누르세요. 8-1·5-3은 '서버 장애' 버튼으로 일으킵니다. 하루는 20분.";
  buildGlobalForm(); buildVehForm();
};
$("#presetClean").onclick = async () => {
  const clear = {};
  for (const k of Object.keys(S.CFG.vehicles || {})) clear[k] = null;
  await postCfg({ ...PRESET_CLEAN, vehicles: clear });
  $("#presetNote").textContent = "장애 설정을 껐습니다 (주행 환경에 따른 끊김은 그대로).";
  buildGlobalForm(); buildVehForm();
};

// ------------------------------------------------------------------ 지도 도구 모음
$("#btnView").onclick = fitView;
$("#btnChase").onclick = () => setCam(S.CAM === "chase" ? "orbit" : "chase");
$("#camOrbit").onclick = () => setCam("orbit");
$("#camFpv").onclick = () => setCam(S.CAM === "fpv" ? "orbit" : "fpv");
$("#btnDrive").onclick = () => setDrive(!DRIVE.on);
$("#zoomIn").onclick = () => zoomBy(0.55);
$("#zoomOut").onclick = () => zoomBy(1.8);
$("#zoomBox").onclick = toggleBoxMode;
$("#btnTour").onclick = () => toggleTour();
$("#optToggle").onclick = (e) => { e.stopPropagation(); $("#optMenu").classList.toggle("hidden"); };
document.addEventListener("click", (e) => { if (!e.target.closest(".dd")) $("#optMenu").classList.add("hidden"); });
$("#optLegend").onchange = (e) => $("#pane-map").classList.toggle("nolegend", !e.target.checked);
$("#optCells").onchange = (e) => layers.cells.forEach((m) => (m.visible = e.target.checked));
$("#optZones").onchange = (e) => layers.zones.forEach((m) => (m.visible = e.target.checked));
$("#optPlaces").onchange = (e) => layers.placeLabels.forEach((m) => (m.visible = e.target.checked));
$("#meChip").onclick = askName;
$("#meName").textContent = ME.name || "이름 없음";
if (!ME.name) setTimeout(askName, 300);

// 자동 구경: 차량을 바꿔 가며 따라가기 → 1인칭 → 하늘에서 내려다보기 (켜 두고 보기)
let tour = null;
function toggleTour() {
  if (tour) { clearInterval(tour); tour = null; $("#btnTour").classList.remove("on"); setCam("orbit"); return; }
  $("#btnTour").classList.add("on");
  let k = 0;
  const step = () => {
    const ids = Object.keys(CARS).map(Number).filter((v) => CARS[v].g.visible && (liveCarState(v)?.speed_kmh ?? 0) > 5);
    const v = ids.length ? ids[Math.floor(Math.random() * ids.length)] : S.selected;
    const mode = ["chase", "fpv", "chase", "orbit"][k++ % 4];
    if (mode === "orbit") {
      const car = CARS[v];
      if (car) flyTo(car.g.position.clone().setY(0), car.g.position.clone().add({ x: -120, y: 140, z: 160 }), 1500);
    } else { selectVehicle(v); setCam(mode); }
  };
  step();
  tour = setInterval(step, 14000);
}
controls.addEventListener("start", () => { if (tour) toggleTour(); });

// ------------------------------------------------------------------ 탭·오른쪽 패널 접기
$$(".tabs").forEach((nav) => nav.addEventListener("click", (e) => {
  const b = e.target.closest(".tab");
  if (!b) return;
  nav.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === b));
  nav.parentElement.querySelectorAll(":scope > .tabpane").forEach((p) => p.classList.toggle("active", p.id === "pane-" + b.dataset.tab));
  if (b.dataset.tab === "map") resizeRenderer();
  if (b.dataset.tab === "runs") loadRuns();
  if (b.dataset.tab === "save") loadSaves();
}));
const FOLD = store.get("vfl_fold", {});
const applyFold = () => { for (const k of ["fl", "cfg"]) $("main").classList.toggle("fold-" + k, !!FOLD[k]); };
$$(".side-rail").forEach((r) => (r.onclick = () => {
  const k = r.parentElement.dataset.key;
  FOLD[k] = !FOLD[k];
  store.set("vfl_fold", FOLD);
  applyFold();
}));
applyFold();
new ResizeObserver(() => resizeRenderer()).observe(holder);

// ------------------------------------------------------------------ 0.4초마다 서버 상태
async function poll() {
  if (!S.REPLAY) {
    try {
      const r = await api.get(`/api/state?ev=${S.evOffset}&sel=${S.selected}`);
      S.LAST = r; S.CFG = r.config; S.evOffset = r.ev;
      S.PEERS = r.peers || []; S.DRIVERS = r.drivers || {};
      renderPeers(); syncForms(); renderRun(); renderMethodChip();
      const w = r.world;
      if (w?.vehicles) {
        for (let v = 1; v <= S.CFG.fl.K; v++) { const s = liveCarState(v); if (s) drawCar(v, s); }
        for (const k of Object.keys(CARS)) if (Number(k) > S.CFG.fl.K) removeCar(k);
        drawNpcs(w.npc);
        updateSignals(w.signals);
        updateCrossPeds(w.peds);
        updateWalkers(w.walkers);
        applyTime(S.TIME_FIX ?? w.tod);
      }
      renderVehPicker(); renderVehInfo(); renderHud();
      renderFL(r.server, r.server_down_left);
      handleEvents(r.events || []);
    } catch (e) { console.error(e); }
  }
  setTimeout(poll, 400);
}

// ------------------------------------------------------------------ 매 프레임
let lastFrame = performance.now();
function frame(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  animateCars(now, dt);
  drawWalkers(now, dt);
  animateFx(dt);
  updateCamera(now, dt);
  cullLabels();
  renderScene();
  if (S.CAM === "fpv") renderHudFast();
  requestAnimationFrame(frame);
}

(async function main() {
  S.STATIC = await api.get("/api/static");
  S.CFG = (await api.get("/api/state?ev=999999999")).config;
  S.MAP_ID = S.STATIC.map_id;
  buildScene(S.STATIC.map, S.STATIC.layout);
  applyTime(S.CFG.world.start_hour ?? 12);
  initViewInput(selectVehicle);
  initDriveInput();
  initRecordInput();
  buildLegends(); buildGlobalForm(); buildVehForm(); buildLogFilter(); renderCases(); renderMethodChip();
  resizeRenderer();
  fitView();
  requestAnimationFrame(frame);
  poll();
})();

// 화면 점검용 (브라우저 콘솔): __sim.look(x, z, 거리), __sim.fixTime(12)
window.__sim = {
  applyTime, focusOn, selectVehicle, look, walkers: updateWalkers, setCam, cars: CARS, showroom,
  fixTime: (h) => { S.TIME_FIX = h; applyTime(h); },
  loadMap: async (id) => showMap(await api.get(`/api/static?map=${id}`)),
};
