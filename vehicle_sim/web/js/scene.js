// 3D 장면 기본: 렌더러·카메라·조명·하늘, 재질·텍스처, 바닥에 붙이는 도형 도우미, 하루 시계 조명 (실제 크기: 1 = 1 m)
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { Sky } from "three/addons/objects/Sky.js";
import { $, el, clamp } from "./util.js";

export const holder = $("#map3d");
export const renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.6;
holder.appendChild(renderer.domElement);
export const labelRenderer = new CSS2DRenderer();
Object.assign(labelRenderer.domElement.style, { position: "absolute", top: "0", pointerEvents: "none" });
holder.appendChild(labelRenderer.domElement);

export const scene = new THREE.Scene();
export const camera = new THREE.PerspectiveCamera(45, 1, 1, 60000);
export const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.47;
controls.minDistance = 8;
controls.screenSpacePanning = false;
controls.zoomToCursor = true;                             // 휠 확대는 커서가 가리키는 곳으로

const sky = new Sky();
sky.scale.setScalar(50000);
sky.material.uniforms.turbidity.value = 4;
sky.material.uniforms.rayleigh.value = 1.2;
sky.material.uniforms.mieCoefficient.value = 0.004;
sky.material.uniforms.mieDirectionalG.value = 0.8;
scene.add(sky);
scene.fog = new THREE.Fog("#cfdbe6", 2500, 9000);
const hemi = new THREE.HemisphereLight("#dbe8ff", "#5a6b4a", 0.9);
scene.add(hemi);
export const sun = new THREE.DirectionalLight("#fff6e8", 2.2);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -220, right: 220, top: 220, bottom: -220, near: 10, far: 2000 });
sun.shadow.bias = -0.0005;
scene.add(sun, sun.target);
export const sunDir = new THREE.Vector3(-0.5, 0.8, 0.3).normalize();

/** 맵 크기(맵 중심이 원점)와 밤 정도 (0 낮 … 1 밤) */
export const W = { W2: 1000, H2: 700, NIGHT: 0 };
export const P = (x, z, y = 0) => new THREE.Vector3(x - W.W2, y, z - W.H2);

// ------------------------------------------------------------------ 재질·텍스처
const MAT = {};
export const isShared = (m) => Object.values(MAT).includes(m);
export const mat = (color, opts = {}) => {
  const key = color + JSON.stringify(opts);
  return MAT[key] || (MAT[key] = new THREE.MeshStandardMaterial({ color, roughness: 0.85, ...opts }));
};
// 도로 표시는 아스팔트 위에 살짝 띄우고 깊이 우선순위를 줘서 멀리서도 깜빡이지 않게
export const markMat = (color) => MAT["mark" + color] || (MAT["mark" + color] = new THREE.MeshStandardMaterial({
  color, roughness: 0.6, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));

export function canvasTex(size, draw, rep = 1) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  draw(c.getContext("2d"), size);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(rep, rep);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}
function noise(ctx, s, base, spread, n) {
  ctx.fillStyle = base; ctx.fillRect(0, 0, s, s);
  for (let i = 0; i < n; i++) {
    const v = (Math.random() - 0.5) * spread;
    ctx.fillStyle = `rgba(${v > 0 ? 255 : 0},${v > 0 ? 255 : 0},${v > 0 ? 255 : 0},${Math.abs(v)})`;
    ctx.fillRect(Math.random() * s, Math.random() * s, 1 + Math.random() * 2, 1 + Math.random() * 2);
  }
}
export const TEX = {
  grass: canvasTex(256, (c, s) => {
    noise(c, s, "#6f8f4e", 0.18, 9000);
    for (let i = 0; i < 40; i++) { c.fillStyle = `rgba(90,110,60,${Math.random() * 0.25})`; c.beginPath(); c.arc(Math.random() * s, Math.random() * s, 8 + Math.random() * 30, 0, 7); c.fill(); }
  }),
  sand: canvasTex(256, (c, s) => noise(c, s, "#cdb88a", 0.14, 9000)),
  asphalt: canvasTex(256, (c, s) => noise(c, s, "#56595e", 0.22, 14000)),
  track: canvasTex(256, (c, s) => noise(c, s, "#3d4045", 0.18, 14000)),
  concrete: canvasTex(128, (c, s) => {
    noise(c, s, "#c4c2bc", 0.1, 3000);
    c.strokeStyle = "rgba(0,0,0,0.12)";
    for (let i = 0; i <= s; i += 32) { c.beginPath(); c.moveTo(i, 0); c.lineTo(i, s); c.stroke(); c.beginPath(); c.moveTo(0, i); c.lineTo(s, i); c.stroke(); }
  }),
  kerb: canvasTex(64, (c, s) => { for (let i = 0; i < 2; i++) { c.fillStyle = i ? "#f4f4f4" : "#d72626"; c.fillRect(i * s / 2, 0, s / 2, s); } }),
  checker: canvasTex(64, (c, s) => { for (let i = 0; i < 8; i++) for (let j = 0; j < 8; j++) { c.fillStyle = (i + j) % 2 ? "#111" : "#f5f5f5"; c.fillRect(i * 8, j * 8, 8, 8); } }),
};

// 건물 벽: 한 칸 = 창 하나 (u = 폭/칸 폭, v = 높이/층 높이). 낮에는 창, 밤에는 일부 창에 불
function windowTex(style) {
  const N = 8, s = 512, cell = s / N;
  const day = canvasTex(s, (c) => {
    c.fillStyle = style.wall; c.fillRect(0, 0, s, s);
    for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
      const x = i * cell, y = j * cell;
      if (style.none) { c.fillStyle = j % 2 ? style.wall : style.stripe; c.fillRect(x, y, cell, cell / 2); continue; }
      const g = c.createLinearGradient(x, y, x + cell, y + cell);
      g.addColorStop(0, style.glass); g.addColorStop(1, style.glass2);
      c.fillStyle = g;
      c.fillRect(x + cell * style.mx, y + cell * style.my, cell * (1 - 2 * style.mx), cell * (1 - 2 * style.my));
      c.fillStyle = "rgba(255,255,255,0.18)";
      c.fillRect(x + cell * style.mx, y + cell * style.my, cell * (1 - 2 * style.mx), 2);
    }
    c.fillStyle = style.wall; c.fillRect(0, s - 6, 6, 6);          // uv (0,0) = 벽색 (지붕 면)
  });
  const night = canvasTex(s, (c) => {
    c.fillStyle = "#000"; c.fillRect(0, 0, s, s);
    if (style.none) return;
    for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
      if (Math.random() < 0.45) continue;
      c.fillStyle = ["#ffd9a0", "#fff1c9", "#cfe3ff"][Math.floor(Math.random() * 3)];
      c.fillRect(i * cell + cell * style.mx, j * cell + cell * style.my, cell * (1 - 2 * style.mx), cell * (1 - 2 * style.my));
    }
  });
  day.repeat.set(1 / N, 1 / N); night.repeat.set(1 / N, 1 / N);
  return { day, night };
}
export const BSTYLE = {
  office: { wall: "#e6e7e8", glass: "#7f97ab", glass2: "#c3d2de", mx: 0.08, my: 0.14, bay: 3.2, floor: 3.6, walls: ["#e7e8ea", "#d5d8dc", "#c7ccd2", "#eef0f1"], roof: "#8e9399" },
  tower: { wall: "#dde3e8", glass: "#6d8aa3", glass2: "#b4c8d8", mx: 0.04, my: 0.06, bay: 2.8, floor: 3.6, walls: ["#dfe5ea", "#c9d1d8", "#b8c2cc"], roof: "#7b828a" },
  house: { wall: "#f1ece3", glass: "#6f7d8a", glass2: "#aab6c1", mx: 0.28, my: 0.3, bay: 4.0, floor: 3.0, walls: ["#f1ece3", "#e6ddd0", "#f4f1ea", "#dcd6cc"], roof: "#9a5a3c" },
  apartment: { wall: "#f4f3f0", glass: "#73859a", glass2: "#b9c6d2", mx: 0.18, my: 0.22, bay: 3.0, floor: 2.9, walls: ["#f4f3f0", "#e9e8e4", "#dedfdc"], roof: "#9aa0a6" },
  warehouse: { wall: "#e4e8ec", stripe: "#d3d9de", none: true, mx: 0, my: 0, bay: 8, floor: 1.2, walls: ["#f4f5f6", "#e3eaf1", "#f2eee6", "#d9e4ee"], roof: "#8a9198" },
};
for (const k in BSTYLE) Object.assign(BSTYLE[k], windowTex(BSTYLE[k]));
export const winMats = [];

// ------------------------------------------------------------------ 도형 도우미
export const layers = { cells: [], placeLabels: [], zones: [] };
export const mapLabels = [];
export function addLabel(group, text, cls, pos, layer = "placeLabels") {
  const o = new CSS2DObject(el("div", "lbl " + (cls || ""), text));
  o.position.copy(pos);
  group.add(o);
  if (layer) layers[layer].push(o);
  mapLabels.push(o);
  return o;
}
/** 멀리 있는 장소·도로 이름표는 흐리게 감춘다 (넓은 맵에서 지평선에 글자가 쌓이지 않게) */
let cullTick = 0;
export function cullLabels() {
  if (++cullTick % 8) return;
  const reach = Math.max(700, camera.position.distanceTo(controls.target) * 2.2);
  for (const o of mapLabels) o.element.style.opacity = camera.position.distanceTo(o.getWorldPosition(_v)) > reach ? 0 : 1;
}
const _v = new THREE.Vector3();
export function box(group, w, h, d, material, x, z, y = 0, rotY = 0) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), typeof material === "string" ? mat(material) : material);
  m.position.copy(P(x, z, y + h / 2));
  m.rotation.y = rotY;
  m.castShadow = m.receiveShadow = true;
  group.add(m);
  return m;
}
export function overlayRect(group, r, color, opacity, y, layer = "zones") {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(r[2] - r[0], r[3] - r[1]).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 }));
  m.position.copy(P((r[0] + r[2]) / 2, (r[1] + r[3]) / 2, y));
  group.add(m);
  if (layer) layers[layer].push(m);
  return m;
}
export function disposeGroup(g) {
  g.traverse((o) => {
    if (o.isCSS2DObject && o.element) o.element.remove();
    if (o.geometry) o.geometry.dispose();
    if (o.material && !isShared(o.material) && !o.userData.sharedMat)
      (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose());
  });
  scene.remove(g);
}
export const segDist = (p, a, b) => {
  const dx = b[0] - a[0], dz = b[1] - a[1], L2 = dx * dx + dz * dz;
  const t = clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / (L2 || 1), 0, 1);
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dz));
};

// ------------------------------------------------------------------ 하루 시계 → 해 위치·하늘·조명·창문 불빛
export function applyTime(tod) {
  if (tod === undefined || tod === null) return;
  const elev = Math.sin(Math.PI * (tod - 6) / 12);                       // 6시 0 → 12시 1 → 18시 0
  const az = Math.PI * (tod - 6) / 12;
  const e = Math.max(-0.25, elev);
  sunDir.set(Math.cos(az) * 0.8, Math.max(0.02, 0.25 + 0.5 * e), -0.55).normalize();   // 낮게 비춰 벽면에 명암
  sky.material.uniforms.sunPosition.value.set(Math.cos(az), e, -0.45);
  const day = clamp((elev + 0.08) / 0.35, 0, 1);
  W.NIGHT = 1 - day;
  // 밤에는 달빛(푸른 약한 직사광) + 하늘빛으로 길·건물 윤곽이 보이게
  sun.intensity = day > 0 ? 0.35 + 2.1 * Math.pow(clamp(elev, 0, 1), 0.5) : 0.35;
  sun.color.set(day > 0.15 ? new THREE.Color().setHSL(0.09, 0.6, 0.55 + 0.35 * clamp(elev * 2, 0, 1)) : new THREE.Color("#9fb4ff"));
  hemi.intensity = 0.55 + 0.85 * day;
  hemi.color.set(day > 0.3 ? "#dbe8ff" : "#7d8fc4");
  hemi.groundColor.set(day > 0.3 ? "#5a6b4a" : "#2a3140");
  renderer.toneMappingExposure = 0.62 + 0.28 * day;
  scene.fog.color.setHSL(0.58, 0.3 * day, 0.08 + 0.7 * day);
  for (const m of winMats) m.emissiveIntensity = 1.1 * W.NIGHT;
}
/** 맵 크기에 맞춰 안개 거리를 늘린다 (넓은 맵을 멀리서 볼 때 흐려지지 않게) */
export function fitFog(MW, MH) {
  const diag = Math.hypot(MW, MH);
  scene.fog.near = Math.max(2500, diag * 0.9);
  scene.fog.far = Math.max(9000, diag * 2.6);
}
export function resizeRenderer() {
  const r = holder.getBoundingClientRect();
  if (!r.width) return false;
  renderer.setSize(r.width, r.height);
  labelRenderer.setSize(r.width, r.height);
  camera.aspect = r.width / Math.max(1, r.height);
  camera.updateProjectionMatrix();
  return true;
}
/** 그림자 카메라는 보고 있는 곳을 따라간다 */
export function renderScene() {
  const dist = camera.position.distanceTo(controls.target);
  const span = clamp(dist * 0.8, 120, 900);
  Object.assign(sun.shadow.camera, { left: -span, right: span, top: span, bottom: -span });
  sun.shadow.camera.updateProjectionMatrix();
  sun.target.position.copy(controls.target);
  sun.position.copy(controls.target).addScaledVector(sunDir, 1200);
  renderer.render(scene, camera);
  labelRenderer.render(scene, camera);
}
