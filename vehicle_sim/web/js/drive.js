// 직접 운전(선택 차량 1인칭)과 계기판. 0.1초마다 입력을 보내고 그 차 위치를 바로 받아 그린다
import { $, el, S, ME, STATE, ZONE_ICON, ZONE_NAME, api, clamp, vtypeOf, kindLabel } from "./util.js";
import { CARS, STYLES, drawCar, liveCarState } from "./cars.js";
import { updateWalkers } from "./walkers.js";
import { setCam } from "./view.js";
import { toast } from "./events.js";

export const DRIVE = { on: false, keys: new Set(), steer: 0, thr: 0, brk: 0, rev: false, park: false, timer: null, sending: false, vid: null };
const KEYMAP = { KeyW: "up", ArrowUp: "up", KeyS: "down", ArrowDown: "down", KeyA: "left", ArrowLeft: "left",
  KeyD: "right", ArrowRight: "right", Space: "brake" };

export function setDrive(on) {
  if (on && S.REPLAY) { toast({ msg: "다시 보기 중에는 운전할 수 없습니다" }); return; }
  if (on && S.LAST?.procs?.world !== "running") { toast({ msg: "시뮬레이션이 실행 중일 때 운전할 수 있습니다 (▶ 시작)" }); return; }
  DRIVE.on = on;
  DRIVE.keys.clear();
  DRIVE.steer = DRIVE.thr = DRIVE.brk = 0;
  DRIVE.rev = false;
  const b = $("#btnDrive");
  b.classList.toggle("drive-on", on);
  b.innerHTML = on ? `🕹 V${S.selected} 운전 중 · 끄기` : "🕹 운전";
  clearInterval(DRIVE.timer);
  DRIVE.timer = null;
  if (on) {
    if (S.CAM !== "fpv") setCam("fpv");
    DRIVE.vid = S.selected;
    DRIVE.timer = setInterval(sendDrive, 100);
    sendDrive();
  } else {
    api.post("/api/drive", { vid: DRIVE.vid, on: false, client: ME.id }).catch(() => {});
  }
  renderHud();
}

export function initDriveInput() {
  window.addEventListener("keydown", (e) => {
    if (e.target.closest?.("input, select, textarea")) return;
    if (e.code === "KeyF" && !e.repeat && !e.ctrlKey && !e.metaKey) { setCam(S.CAM === "fpv" ? "orbit" : "fpv"); return; }
    if (!DRIVE.on) return;
    if (KEYMAP[e.code]) { DRIVE.keys.add(KEYMAP[e.code]); e.preventDefault(); }
    else if (e.code === "KeyR" && !e.repeat) {
      if ((liveCarState(S.selected)?.speed_kmh ?? 0) < 3) DRIVE.rev = !DRIVE.rev;
      else toast({ msg: "기어를 바꾸려면 먼저 멈추세요" });
    } else if (e.code === "KeyP" && !e.repeat) DRIVE.park = true;
    else if (e.code === "Escape") setDrive(false);
  });
  window.addEventListener("keyup", (e) => {
    if (KEYMAP[e.code]) DRIVE.keys.delete(KEYMAP[e.code]);
    if (e.code === "KeyP") DRIVE.park = false;
  });
  window.addEventListener("blur", () => DRIVE.keys.clear());
  window.addEventListener("beforeunload", () => { if (DRIVE.on) api.beacon("/api/drive", { vid: DRIVE.vid, on: false, client: ME.id }); });
}

let lastT = performance.now();
async function sendDrive() {
  const now = performance.now(), dt = Math.min(0.3, (now - lastT) / 1000);
  lastT = now;
  const k = DRIVE.keys;
  // 키보드 입력을 실제 페달·핸들처럼 서서히 바꾼다
  const st = (k.has("right") ? 1 : 0) - (k.has("left") ? 1 : 0);
  DRIVE.steer = st ? clamp(DRIVE.steer + st * dt * 1.4, -1, 1) : DRIVE.steer * Math.max(0, 1 - dt * 6);
  DRIVE.thr = k.has("up") ? Math.min(1, DRIVE.thr + dt * 2.5) : 0;
  DRIVE.brk = k.has("brake") ? 1 : k.has("down") ? Math.min(0.75, DRIVE.brk + dt * 1.5) : 0;
  if (S.selected !== DRIVE.vid) {                         // 다른 차를 고르면 그 차로 바꿔 탄다
    DRIVE.vid = S.selected;
    $("#btnDrive").innerHTML = `🕹 V${S.selected} 운전 중 · 끄기`;
  }
  if (DRIVE.sending) return;
  DRIVE.sending = true;
  try {
    const j = await api.post("/api/drive", { vid: S.selected, on: true, throttle: DRIVE.thr, brake: DRIVE.brk, steer: DRIVE.steer,
      reverse: DRIVE.rev, park: DRIVE.park });
    if (!j.ok) { toast({ msg: (j.busy ? "" : "운전 종료: ") + (j.error || "서버 응답 없음") }); setDrive(false); }
    else if (j.v && S.LAST?.world?.vehicles) {
      S.LAST.world.vehicles[S.selected] = { ...S.LAST.world.vehicles[S.selected], ...j.v };
      const s = liveCarState(S.selected);
      if (s) drawCar(S.selected, s);
      if (j.walkers) updateWalkers(j.walkers, true);
    }
  } catch (e) { console.error(e); }
  DRIVE.sending = false;
}

// ------------------------------------------------------------------ 계기판
export function renderHud() {
  if (S.CAM !== "fpv") return;
  const vid = S.selected, s = liveCarState(vid) || {}, c = S.LAST?.clients?.[vid] || {};
  const [name, col] = STATE[s.status] || STATE.idle;
  const style = STYLES[CARS[vid]?.style]?.name || "";
  $("#hudTitle").innerHTML = `V${vid} · ${vtypeOf(vid) === "new" ? "신형 EV" : "구형 EV"} · ${style} · ${kindLabel(s)}` +
    (s.manual ? `<span class="tag man">수동 운전${s.driver ? " · " + s.driver : ""}</span>` : `<span class="tag auto">자동 운전</span>`);
  $("#hudFl").innerHTML = `<i style="background:${col}"></i><b>${name}</b> — ${c.detail || "-"} · 모델 v${c.version ?? "-"} / 서버 v${c.server_version ?? "-"} · 에너지 ${c.energy ?? "-"} J`;
  const zones = Object.entries(s.zones || {}).filter(([, b]) => b).map(([k]) => ZONE_ICON[k] + ZONE_NAME[k]).join(" ");
  $("#hudNet").textContent = `${s.link_up ? "🟢 연결" : "🔴 연결 없음"} · 셀 ${s.cell || "범위 밖"}${s.quality ? ` (${Math.round(s.quality * 100)}%)` : ""} · 권역 ${s.region || "-"}` +
    (zones ? ` · ${zones}` : "") + (s.offroad ? " · ⚠도로 밖" : "") + (s.parked ? ` · 🅿 ${s.park_why}` : "");
  const al = $("#hudAlert");
  const msg = s.present === false ? "맵 밖에 있는 차량입니다" : s.emergency > 0 ? `⚠ 긴급제동(${s.emergency_cause}) — ADAS 연산 점유 ${s.emergency}초 → 학습 지연/중단` : "";
  al.classList.toggle("hidden", !msg);
  al.textContent = msg;
  $("#hudKeys").innerHTML = DRIVE.on
    ? "<kbd>W</kbd><kbd>↑</kbd> 가속 <kbd>S</kbd><kbd>↓</kbd> 제동 <kbd>A</kbd><kbd>D</kbd> 조향 <kbd>Space</kbd> 급제동 <kbd>R</kbd> 후진 <kbd>P</kbd> 주차·출발 <kbd>Esc</kbd> 운전 끄기"
    : "<b>🕹 운전</b>으로 직접 운전 · <kbd>F</kbd> 1인칭 켜고 끄기 · 드래그 둘러보기 · 더블클릭 정면 · 다른 차량을 고르면 그 차로";
}
/** 1인칭에서 보고 있는 차량에 일어난 사건(유스케이스·운전 사건)을 계기판 위에 잠깐 띄운다 */
export function hudNote(text, color) {
  const box = $("#hudNotes");
  const n = el("div", "hud-note", text);
  n.style.borderLeftColor = color;
  box.appendChild(n);
  while (box.children.length > 3) box.firstChild.remove();
  setTimeout(() => n.remove(), 6000);
}
export function renderHudFast() {
  const sm = CARS[S.selected]?.sample, s = S.LAST?.world?.vehicles?.[S.selected];
  $("#hudSpeed").textContent = Math.round(Math.abs(sm?.v ?? 0) * 3.6);
  const gear = s?.parked ? "P" : DRIVE.on && DRIVE.rev ? "R" : "D", g = $("#hudGear");
  g.textContent = gear;
  g.className = "hud-gear " + gear.toLowerCase();
  $("#hudSteer").style.setProperty("--steer", DRIVE.on ? DRIVE.steer : 0);
}
