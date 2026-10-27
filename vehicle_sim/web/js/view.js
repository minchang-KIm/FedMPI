// 시점: 자유(orbit) · 따라가기(chase) · 1인칭(fpv, 운전석). 확대(휠·더블클릭·＋/－·영역), 차량 고르기·툴팁, 유스케이스 위치로 이동
import * as THREE from "three";
import { $, S, STATE, clamp, vtypeOf, kindLabel } from "./util.js";
import { renderer, camera, controls, P, W } from "./scene.js";
import { CARS, STYLES, liveCarState, pickCar } from "./cars.js";
import { DRIVE, setDrive, renderHud } from "./drive.js";

let FLY = null, fitted = false;
export const LOOK = { yaw: 0, pitch: -0.04, drag: null, moved: false };
const ray = new THREE.Raycaster(), mouse = new THREE.Vector2(), ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

function setRay(cx, cy) {
  const r = renderer.domElement.getBoundingClientRect();
  mouse.set(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(mouse, camera);
}
const groundAt = (cx, cy) => { setRay(cx, cy); return ray.ray.intersectPlane(ground, new THREE.Vector3()); };

/** 맵 전체가 보이게 (처음 한 번은 바로, 그 뒤로는 날아가듯) */
export function fitView() {
  setCam("orbit");
  const v = THREE.MathUtils.degToRad(camera.fov) / 2, h = Math.atan(Math.tan(v) * camera.aspect);
  const d = Math.max((W.W2 + 60) / Math.tan(h), (W.H2 + 60) / Math.tan(v)) * 0.95;
  const dir = new THREE.Vector3(0, 0.82, 0.57).normalize();
  controls.maxDistance = d * 1.3;
  flyTo(new THREE.Vector3(0, 0, 40), new THREE.Vector3(0, 0, 40).addScaledVector(dir, d), fitted ? 700 : 0);
  fitted = true;
}
export function flyTo(target, pos, ms = 650) {
  if (S.CAM !== "orbit") setCam("orbit");
  if (!ms) { controls.target.copy(target); camera.position.copy(pos); controls.update(); FLY = null; return; }
  FLY = { t0: performance.now(), ms, ft: controls.target.clone(), fp: camera.position.clone(), tt: target.clone(), tp: pos.clone() };
}
export function look(x, z, d = 60, h = 0.6) { flyTo(P(x, z), P(x - d * 0.6, z + d * 0.8, d * h), 0); }

export function setCam(mode) {
  const prev = S.CAM;
  if (mode !== "fpv" && DRIVE.on) setDrive(false);
  S.CAM = mode;
  FLY = null;
  controls.enabled = mode === "orbit";
  $("#camOrbit").classList.toggle("on", mode === "orbit");
  $("#btnChase").classList.toggle("on", mode === "chase");
  $("#camFpv").classList.toggle("on", mode === "fpv");
  $("#btnChase").innerHTML = mode === "chase" ? `🎥 V${S.selected} 따라가는 중` : "🎥 따라가기";
  $("#camFpv").innerHTML = mode === "fpv" ? `👁 V${S.selected} 1인칭` : "👁 1인칭";
  $("#pane-map").classList.toggle("fpv", mode === "fpv");
  $("#hud").classList.toggle("hidden", mode !== "fpv");
  camera.fov = mode === "fpv" ? 72 : 45;
  camera.updateProjectionMatrix();
  if (mode === "fpv") { LOOK.yaw = 0; LOOK.pitch = -0.04; renderHud(); }
  if (mode === "orbit" && prev === "fpv") {              // 1인칭에서 나오면 그 차 위에서 내려다보기
    const car = CARS[S.selected];
    if (car) {
      const h = -car.g.rotation.y, c = car.g.position;
      controls.target.set(c.x, 0, c.z);
      camera.position.set(c.x - Math.cos(h) * 45, 38, c.z - Math.sin(h) * 45);
    }
  }
  if (mode === "orbit") { controls.target.y = 0; controls.update(); }
}

export function zoomBy(f) {                               // 화면 가운데를 향해 확대·축소
  setCam("orbit");
  const off = camera.position.clone().sub(controls.target);
  const L = clamp(off.length() * f, controls.minDistance, controls.maxDistance);
  flyTo(controls.target.clone(), controls.target.clone().add(off.setLength(L)), 350);
}
function zoomToRect(a, b) {                               // 화면에서 그린 사각형의 땅 영역이 화면을 채우게
  const pts = [[a[0], a[1]], [b[0], a[1]], [a[0], b[1]], [b[0], b[1]]].map(([x, y]) => groundAt(x, y)).filter(Boolean);
  if (pts.length < 2) return;
  const xs = pts.map((p) => p.x), zs = pts.map((p) => p.z);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cz = (Math.min(...zs) + Math.max(...zs)) / 2;
  const span = Math.max(Math.max(...xs) - Math.min(...xs), (Math.max(...zs) - Math.min(...zs)) * camera.aspect, 30);
  const d = clamp((span / 2) / Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) / camera.aspect * 1.1, controls.minDistance, controls.maxDistance);
  const dir = camera.position.clone().sub(controls.target).normalize();
  if (dir.y < 0.5) { dir.y = 0.5; dir.normalize(); }
  const t = new THREE.Vector3(cx, 0, cz);
  flyTo(t, t.clone().addScaledVector(dir, d));
}
let BOX = null, boxMode = false;
export function setBoxMode(on) {
  boxMode = on;
  $("#zoomBox").classList.toggle("on", on);
  $("#pane-map").classList.toggle("boxmode", on);
}
export const toggleBoxMode = () => setBoxMode(!boxMode);

/** 유스케이스 → 맵에서 볼 곳 (맵마다 장소·구역 종류가 같다) */
export function focusPoint(id) {
  const M = S.MAP;
  const zone = (k) => M.zones.find((z) => z.kind === k);
  const place = (k) => M.places.find((p) => p.kind === k);
  const zc = (z) => (z ? (z.rect ? [(z.rect[0] + z.rect[2]) / 2, (z.rect[1] + z.rect[3]) / 2] : [z.circle[0], z.circle[1]]) : null);
  const fast = [...M.roads].sort((a, b) => b.speed - a.speed)[0];
  const school = (M.crosswalks || []).find((c) => c.school) || (M.crosswalks || [])[0];
  const c0 = M.cells[0];
  const m = {
    "1-2": place("service")?.pos, "1-4": school?.pos, "4-5": school?.pos, "1-5": place("home")?.pos,
    "2-2": fast && [(fast.pts[0][0] + fast.pts[1][0]) / 2, (fast.pts[0][1] + fast.pts[1][1]) / 2],
    "2-4": M.region_border_x && fast && [M.region_border_x, fast.pts[0][1]], "2-5": zc(zone("tunnel")),
    "3-2": place("gas")?.pos, "3-3": zc(zone("wifi")), "4-2": zc(zone("congestion")), "4-4": zc(zone("weather")),
    "5-1": zc(zone("shadow")), "5-2": c0 && [c0.pos[0] + c0.r * 0.92, c0.pos[1]], "2-1": c0 && [c0.pos[0] + c0.r, c0.pos[1]],
    "5-3": place("server")?.pos, "8-1": place("server")?.pos, "8-2": place("server")?.pos, "7-3": place("work")?.pos,
    "1-3": place("gas")?.pos, "2-6": place("gas")?.pos, "3-1": place("gas")?.pos, "4-6": place("depot")?.pos,
  };
  return m[id] || null;
}
export function focusOn(pt) {
  if (!pt) return;
  document.querySelector('[data-tab="map"]').click();
  flyTo(P(pt[0], pt[1]), P(pt[0] - 60, pt[1] + 160, 140));
}

// ------------------------------------------------------------------ 매 프레임 카메라
const tmp = new THREE.Vector3(), lookAt = new THREE.Vector3();
export function updateCamera(now, dt) {
  const car = S.CAM !== "orbit" && CARS[S.selected];
  if (car && car.g.visible && S.CAM === "chase") {        // 따라가기: 뒤 12 m, 위 5 m
    const h = -car.g.rotation.y;
    tmp.set(car.g.position.x - Math.cos(h) * 12, car.g.position.y + 5, car.g.position.z - Math.sin(h) * 12);
    camera.position.lerp(tmp, Math.min(1, dt * (3 + Math.abs(car.sample?.v || 0) / 6)));   // 빠른 차일수록 바짝 따라간다
    lookAt.lerp(tmp.set(car.g.position.x + Math.cos(h) * 10, 1.2, car.g.position.z + Math.sin(h) * 10), Math.min(1, dt * 4));
    camera.lookAt(lookAt);
    controls.target.copy(lookAt);
  } else if (car && S.CAM === "fpv") {                    // 1인칭: 차종마다 운전석(왼쪽) 눈높이, 드래그로 둘러보기
    car.g.updateMatrixWorld();
    const [ex, ey, ez] = STYLES[car.style].eye;
    car.g.localToWorld(tmp.set(ex, ey, ez));
    camera.position.copy(tmp);
    const h = -car.g.rotation.y + LOOK.yaw;
    lookAt.set(tmp.x + Math.cos(h) * 30 * Math.cos(LOOK.pitch), tmp.y - 1.2 + 30 * Math.sin(LOOK.pitch), tmp.z + Math.sin(h) * 30 * Math.cos(LOOK.pitch));
    camera.lookAt(lookAt);
    controls.target.copy(lookAt);
  } else if (FLY) {
    const k = Math.min(1, (now - FLY.t0) / FLY.ms), e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
    controls.target.lerpVectors(FLY.ft, FLY.tt, e);
    camera.position.lerpVectors(FLY.fp, FLY.tp, e);
    controls.update();
    if (k >= 1) FLY = null;
  } else {                                                // 카메라가 맵 밖으로 나가지 않게
    controls.target.x = clamp(controls.target.x, -W.W2 - 40, W.W2 + 40);
    controls.target.z = clamp(controls.target.z, -W.H2 - 40, W.H2 + 40);
    controls.target.y = 0;
    controls.update();
    if (camera.position.y < 2) camera.position.y = 2;
  }
  const dist = camera.position.distanceTo(controls.target);
  camera.near = S.CAM === "fpv" ? 0.1 : clamp(dist / 600, 0.3, 6);
  camera.far = Math.max(20000, dist * 10);
  camera.updateProjectionMatrix();
}

// ------------------------------------------------------------------ 마우스: 고르기·툴팁·더블클릭 확대·영역 확대·1인칭 둘러보기
export function initViewInput(selectVehicle) {
  const cv = renderer.domElement;
  const pick = (ev) => { setRay(ev.clientX, ev.clientY); return pickCar(ray); };
  cv.addEventListener("click", (ev) => { if (LOOK.moved) return; const v = pick(ev); if (v) selectVehicle(v); });
  cv.addEventListener("mousemove", (ev) => {
    if (LOOK.drag || BOX) return;
    const v = pick(ev), tip = $("#tooltip");
    if (!v || S.REPLAY) { tip.style.display = "none"; return; }
    const s = liveCarState(v) || {}, c = S.LAST?.clients?.[v] || {};
    const car = CARS[v];
    tip.innerHTML = `<b>V${v} · ${vtypeOf(v) === "new" ? "신형 EV" : "구형 EV"} · ${STYLES[car?.style]?.name || ""}</b><br>
      ${kindLabel(s)} · <b style="color:${STATE[s.status]?.[1]}">${STATE[s.status]?.[0] || ""}</b> — ${c.detail || ""}<br>
      ${s.sched || ""}${s.parked ? ` · 🅿 ${s.park_why}` : ""}<br>
      ${s.speed_kmh ?? "-"} km/h · 셀 ${s.cell || "없음"} · ${s.link_up ? "연결" : "연결 없음"}${s.wifi ? " · Wi-Fi" : ""} · 권역 ${s.region}<br>
      에너지 ${c.energy ?? "-"} / ${c.budget ?? "-"} J · 새 데이터 ${c.new_data ?? "-"} · 모델 v${c.version ?? "-"} (서버 v${c.server_version ?? "-"})
      ${s.emergency > 0 ? `<br><b style="color:#f87171">긴급제동(${s.emergency_cause}) — ADAS 연산 점유 ${s.emergency}초</b>` : ""}`;
    Object.assign(tip.style, { display: "block", left: ev.clientX + 14 + "px", top: ev.clientY + 10 + "px" });
  });
  cv.addEventListener("mouseleave", () => ($("#tooltip").style.display = "none"));
  cv.addEventListener("dblclick", (ev) => {
    if (S.CAM === "fpv") { LOOK.yaw = 0; LOOK.pitch = -0.04; return; }
    const g = groundAt(ev.clientX, ev.clientY);
    if (!g) return;
    const off = camera.position.clone().sub(controls.target);
    const L = clamp(off.length() / 2.5, Math.max(controls.minDistance, 25), controls.maxDistance);
    g.x = clamp(g.x, -W.W2, W.W2); g.z = clamp(g.z, -W.H2, W.H2);
    flyTo(g, g.clone().add(off.setLength(L)));
  });
  // OrbitControls보다 먼저 받아서 Shift+드래그가 이동으로 처리되지 않게
  cv.addEventListener("pointerdown", (ev) => {
    LOOK.moved = false;
    if (S.CAM === "fpv") { LOOK.drag = [ev.clientX, ev.clientY, LOOK.yaw, LOOK.pitch]; return; }
    if (ev.button === 0 && (ev.shiftKey || boxMode)) {
      ev.stopImmediatePropagation();
      if (S.CAM !== "orbit") setCam("orbit");
      controls.enabled = false;
      BOX = [ev.clientX, ev.clientY];
      cv.setPointerCapture(ev.pointerId);
      return;
    }
    if (S.CAM === "chase") setCam("orbit");
  }, { capture: true });
  cv.addEventListener("pointermove", (ev) => {
    if (LOOK.drag) {
      const [x0, y0, yw, pt] = LOOK.drag;
      if (Math.abs(ev.clientX - x0) + Math.abs(ev.clientY - y0) > 5) LOOK.moved = true;
      LOOK.yaw = clamp(yw + (ev.clientX - x0) * 0.005, -Math.PI, Math.PI);
      LOOK.pitch = clamp(pt - (ev.clientY - y0) * 0.004, -0.6, 0.5);
      return;
    }
    if (!BOX) return;
    const r = $("#pane-map").getBoundingClientRect(), z = $("#zoomRect");
    z.classList.remove("hidden");
    Object.assign(z.style, { left: Math.min(BOX[0], ev.clientX) - r.left + "px", top: Math.min(BOX[1], ev.clientY) - r.top + "px",
      width: Math.abs(ev.clientX - BOX[0]) + "px", height: Math.abs(ev.clientY - BOX[1]) + "px" });
  });
  cv.addEventListener("pointerup", (ev) => {
    LOOK.drag = null;
    if (!BOX) return;
    const a = BOX;
    BOX = null;
    $("#zoomRect").classList.add("hidden");
    controls.enabled = S.CAM === "orbit";
    setBoxMode(false);
    if (Math.abs(ev.clientX - a[0]) > 12 && Math.abs(ev.clientY - a[1]) > 12)
      zoomToRect([Math.min(a[0], ev.clientX), Math.min(a[1], ev.clientY)], [Math.max(a[0], ev.clientX), Math.max(a[1], ev.clientY)]);
  });
}
