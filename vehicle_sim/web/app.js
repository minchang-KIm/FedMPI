import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { Sky } from "three/addons/objects/Sky.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

// ================================================================== 상수
const STATE = {
  idle: ["대기", "#e2e8f0"], training: ["학습", "#3b82f6"], uploading: ["전송", "#f97316"],
  waiting: ["대기열", "#eab308"], queued: ["보관", "#a855f7"], skipped: ["미참여", "#94a3b8"],
  dead: ["끊김", "#ef4444"], excluded: ["영구 제외", "#991b1b"], parked: ["주차(시동 꺼짐)", "#64748b"], absent: ["맵 밖", "#334155"],
};
const PCOL = { 1: "#f87171", 2: "#fb923c", 3: "#cbd5e1", 4: "#facc15", 5: "#c084fc", 6: "#f472b6", 7: "#4ade80", 8: "#38bdf8" };
const PDESC = { // 서버에서 보는 모습 · 서버 대응
  1: "아무 응답 없음 → 해당 차량 제외", 2: "일부 조각만 도착 → 폐기 (SASAFL은 조각이 없어 패턴 1처럼 보임)",
  3: "이번 라운드 미참여 → 복귀 시 최신 글로벌 모델 전달", 4: "낮은 버전의 값 도착 → SASAFL은 버리지 않고 감쇄해 반영",
  5: "한 차량에서 오래된 값 여러 개 → 개별 처리 (SASAFL은 버퍼 1칸이라 덮어씀)", 6: "오류 있는 값을 계속 보냄 → 대응 없음",
  7: "같은 차량만 계속 참여 → epoch 축소(SASAFL)·CFCFM(SAFA)", 8: "서버 장애·무한 대기·성능 지속 감소 → 복구·시간 제한·강제 갱신",
};
const KIND = { commute: "통근", city: "택시", resident: "주민", visitor: "통과" };
const KCOL = { commute: "#38bdf8", city: "#facc15", resident: "#4ade80", visitor: "#c084fc" };
const PERIODS = [["night", "야간 00–07"], ["am", "출근 07–09:30"], ["day", "주간 09:30–17"], ["pm", "퇴근 17–19:30"], ["evening", "저녁 19:30–23"]];
const $ = (s) => document.querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; return e; };
const fmtT = (t) => new Date(t * 1000).toLocaleTimeString("ko-KR", { hour12: false });
const fmtH = (h) => { h = ((h % 24) + 24) % 24; const m = Math.round((h % 1) * 60) % 60; return `${String(Math.floor(h)).padStart(2, "0")}:${String(m).padStart(2, "0")}`; };
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

let STATIC = null, CFG = null, LAST = null, MAP = null, LAY = null, evOffset = 0, selected = 1, lastRoundShown = -1;
let REPLAY = null;                   // 다시 보기 상태
const caseCount = {}, caseLast = {}, caseVeh = {};
const ALL_EVENTS = [];
let logFilter = null;

// ================================================================== 3D 장면 (실제 크기: 1 = 1 m)
const holder = $("#map3d");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.55;
holder.appendChild(renderer.domElement);
const labelRenderer = new CSS2DRenderer();
Object.assign(labelRenderer.domElement.style, { position: "absolute", top: "0", pointerEvents: "none" });
holder.appendChild(labelRenderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 1, 30000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.47;
controls.minDistance = 8;
controls.screenSpacePanning = false;
const sky = new Sky();
sky.scale.setScalar(20000);
sky.material.uniforms.turbidity.value = 4;
sky.material.uniforms.rayleigh.value = 1.2;
sky.material.uniforms.mieCoefficient.value = 0.004;
sky.material.uniforms.mieDirectionalG.value = 0.8;
scene.add(sky);
scene.fog = new THREE.Fog("#cfdbe6", 2500, 9000);
const hemi = new THREE.HemisphereLight("#dbe8ff", "#5a6b4a", 0.9);
scene.add(hemi);
const sun = new THREE.DirectionalLight("#fff6e8", 2.2);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -220, right: 220, top: 220, bottom: -220, near: 10, far: 1500 });
sun.shadow.bias = -0.0005;
scene.add(sun, sun.target);
const sunDir = new THREE.Vector3(-0.5, 0.8, 0.3).normalize();
let NIGHT = 0;                       // 0 낮 … 1 밤

let W2 = 1000, H2 = 700;
const P = (x, z, y = 0) => new THREE.Vector3(x - W2, y, z - H2);
const layers = { cells: [], placeLabels: [], zones: [] };
let mapGroup = null;
const ZONE = {}, PLACE = {}, CELL = {}, SIGNAL = {}, CROSS = {};
let rain = null, weatherGroup = null, pedMesh = null, winMats = [];
const MAT = {};
const mat = (color, opts = {}) => {
  const key = color + JSON.stringify(opts);
  return MAT[key] || (MAT[key] = new THREE.MeshStandardMaterial({ color, roughness: 0.85, ...opts }));
};
// 도로 표시는 아스팔트 위에 살짝 띄우고 깊이 우선순위를 줘서 멀리서도 깜빡이지 않게
const markMat = (color) => MAT["mark" + color] || (MAT["mark" + color] = new THREE.MeshStandardMaterial({
  color, roughness: 0.6, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));

function canvasTex(size, draw, rep = 1) {
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
const TEX = {
  grass: canvasTex(256, (c, s) => {
    noise(c, s, "#6f8f4e", 0.18, 9000);
    for (let i = 0; i < 40; i++) { c.fillStyle = `rgba(90,110,60,${Math.random() * 0.25})`; c.beginPath(); c.arc(Math.random() * s, Math.random() * s, 8 + Math.random() * 30, 0, 7); c.fill(); }
  }),
  asphalt: canvasTex(256, (c, s) => noise(c, s, "#56595e", 0.22, 14000)),
  concrete: canvasTex(128, (c, s) => { noise(c, s, "#c4c2bc", 0.1, 3000); c.strokeStyle = "rgba(0,0,0,0.12)"; for (let i = 0; i <= s; i += 32) { c.beginPath(); c.moveTo(i, 0); c.lineTo(i, s); c.stroke(); c.beginPath(); c.moveTo(0, i); c.lineTo(s, i); c.stroke(); } }),
};
TEX.grass.repeat.set(1, 1);

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
const BSTYLE = {
  office: { wall: "#e6e7e8", glass: "#7f97ab", glass2: "#c3d2de", mx: 0.08, my: 0.14, bay: 3.2, floor: 3.6, walls: ["#e7e8ea", "#d5d8dc", "#c7ccd2", "#eef0f1"], roof: "#8e9399" },
  tower: { wall: "#dde3e8", glass: "#6d8aa3", glass2: "#b4c8d8", mx: 0.04, my: 0.06, bay: 2.8, floor: 3.6, walls: ["#dfe5ea", "#c9d1d8", "#b8c2cc"], roof: "#7b828a" },
  house: { wall: "#f1ece3", glass: "#6f7d8a", glass2: "#aab6c1", mx: 0.28, my: 0.3, bay: 4.0, floor: 3.0, walls: ["#f1ece3", "#e6ddd0", "#f4f1ea", "#dcd6cc"], roof: "#9a5a3c" },
  apartment: { wall: "#f4f3f0", glass: "#73859a", glass2: "#b9c6d2", mx: 0.18, my: 0.22, bay: 3.0, floor: 2.9, walls: ["#f4f3f0", "#e9e8e4", "#dedfdc"], roof: "#9aa0a6" },
  warehouse: { wall: "#e4e8ec", stripe: "#d3d9de", none: true, mx: 0, my: 0, bay: 8, floor: 1.2, walls: ["#f4f5f6", "#e3eaf1", "#f2eee6", "#d9e4ee"], roof: "#8a9198" },
};
for (const k in BSTYLE) Object.assign(BSTYLE[k], windowTex(BSTYLE[k]));

function addLabel(group, text, cls, pos, layer = "placeLabels") {
  const o = new CSS2DObject(el("div", "lbl " + (cls || ""), text));
  o.position.copy(pos);
  group.add(o);
  layers[layer].push(o);
  return o;
}
/** 바닥에 붙는 사각형 (중심 x,z · 길이 방향 u) */
function slab(group, cx, cz, len, wid, ux, uz, y, material, thick = 0) {
  const m = thick > 0 ? new THREE.Mesh(new THREE.BoxGeometry(len, thick, wid), material)
    : new THREE.Mesh(new THREE.PlaneGeometry(len, wid).rotateX(-Math.PI / 2), material);
  m.position.copy(P(cx, cz, y + thick / 2));
  m.rotation.y = -Math.atan2(uz, ux);
  group.add(m);
  return m;
}
function box(group, w, h, d, material, x, z, y = 0, rotY = 0) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), typeof material === "string" ? mat(material) : material);
  m.position.copy(P(x, z, y + h / 2));
  m.rotation.y = rotY;
  m.castShadow = m.receiveShadow = true;
  group.add(m);
  return m;
}
function overlayRect(group, r, color, opacity, y, layer = "zones") {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(r[2] - r[0], r[3] - r[1]).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4 }));
  m.position.copy(P((r[0] + r[2]) / 2, (r[1] + r[3]) / 2, y));
  group.add(m);
  if (layer) layers[layer].push(m);
  return m;
}
function disposeGroup(g) {
  g.traverse((o) => {
    if (o.isCSS2DObject && o.element) o.element.remove();
    if (o.geometry) o.geometry.dispose();
    if (o.material && !Object.values(MAT).includes(o.material) && !o.userData.sharedMat)
      (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose());
  });
  scene.remove(g);
}
const segDist = (p, a, b) => {
  const dx = b[0] - a[0], dz = b[1] - a[1], L2 = dx * dx + dz * dz;
  const t = clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / (L2 || 1), 0, 1);
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dz));
};
function roadDist(p) {
  let d = 1e9;
  for (const rd of MAP.roads) for (let i = 0; i < rd.pts.length - 1; i++) d = Math.min(d, segDist(p, rd.pts[i], rd.pts[i + 1]));
  return d;
}

/** 건물 상자들을 한 geometry로 (벽 4면 + 지붕). 벽 uv는 실제 크기 → 창 크기가 건물마다 같다 */
function buildingMesh(list, style) {
  const pos = [], nor = [], uv = [], col = [], idx = [];
  const c = new THREE.Color(), roof = new THREE.Color(style.roof);
  const quad = (pts, n, uvs, color) => {
    const b = pos.length / 3;
    pts.forEach((p, i) => { pos.push(...p); nor.push(...n); uv.push(...uvs[i]); col.push(color.r, color.g, color.b); });
    idx.push(b, b + 1, b + 2, b, b + 2, b + 3);
  };
  for (const [x0r, z0r, x1r, z1r, h, , seed] of list) {
    const x0 = x0r - W2, x1 = x1r - W2, z0 = z0r - H2, z1 = z1r - H2;
    c.set(style.walls[Math.abs(Math.floor(seed * 997)) % style.walls.length]);
    const fu = (w) => w / style.bay, fv = h / style.floor;
    const v0 = Math.floor(seed * 13);                                // 밤 창문 무늬 시작 위치를 건물마다 다르게
    quad([[x0, 0, z1], [x1, 0, z1], [x1, h, z1], [x0, h, z1]], [0, 0, 1], [[0, v0], [fu(x1 - x0), v0], [fu(x1 - x0), v0 + fv], [0, v0 + fv]], c);
    quad([[x1, 0, z0], [x0, 0, z0], [x0, h, z0], [x1, h, z0]], [0, 0, -1], [[0, v0], [fu(x1 - x0), v0], [fu(x1 - x0), v0 + fv], [0, v0 + fv]], c);
    quad([[x1, 0, z1], [x1, 0, z0], [x1, h, z0], [x1, h, z1]], [1, 0, 0], [[0, v0], [fu(z1 - z0), v0], [fu(z1 - z0), v0 + fv], [0, v0 + fv]], c);
    quad([[x0, 0, z0], [x0, 0, z1], [x0, h, z1], [x0, h, z0]], [-1, 0, 0], [[0, v0], [fu(z1 - z0), v0], [fu(z1 - z0), v0 + fv], [0, v0 + fv]], c);
    quad([[x0, h, z1], [x1, h, z1], [x1, h, z0], [x0, h, z0]], [0, 1, 0], [[0, 0], [0, 0], [0, 0], [0, 0]], roof);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("normal", new THREE.Float32BufferAttribute(nor, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx);
  const m = new THREE.MeshStandardMaterial({ map: style.day, emissiveMap: style.night, emissive: "#ffffff", emissiveIntensity: 0,
    vertexColors: true, roughness: 0.75, metalness: 0.05 });
  winMats.push(m);
  const mesh = new THREE.Mesh(g, m);
  mesh.castShadow = mesh.receiveShadow = true;
  return mesh;
}

/** 언덕·터널 덮개 높이: 사각형 안에서 매끈하게 솟고, 터널 밖 도로는 깎아 낸다 */
function hillHeight(x, z, hill, tunnels, lw) {
  const [x0, z0, x1, z1] = hill.rect;
  if (x < x0 || x > x1 || z < z0 || z > z1) return 0;
  let bx = Math.sin(Math.PI * (x - x0) / (x1 - x0)), bz = Math.sin(Math.PI * (z - z0) / (z1 - z0));
  if (hill.cover === "x") bx = 1;              // 터널 덮개: 길이 방향은 평평 (입구 벽이 끝을 막는다)
  if (hill.cover === "z") bz = 1;
  let h = hill.height * Math.pow(Math.max(0, bx * bz), hill.cover ? 0.35 : 0.7);
  const inTunnel = tunnels.some((t) => x >= t[0] - 1 && x <= t[2] + 1 && z >= t[1] - 30 && z <= t[3] + 30);
  if (!inTunnel) {
    const d = roadDist([x, z]);
    h *= clamp((d - (lw + 5)) / 25, 0, 1);
  }
  return h;
}
function terrain(group, hill, tunnels, lw, color) {
  const [x0, z0, x1, z1] = hill.rect;
  const nx = Math.max(8, Math.round((x1 - x0) / 10)), nz = Math.max(8, Math.round((z1 - z0) / 10));
  const g = new THREE.PlaneGeometry(x1 - x0, z1 - z0, nx, nz).rotateX(-Math.PI / 2);
  const p = g.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i) + (x0 + x1) / 2, z = p.getZ(i) + (z0 + z1) / 2;
    p.setY(i, hillHeight(x, z, hill, tunnels, lw));
  }
  g.computeVertexNormals();
  const tm = new THREE.MeshStandardMaterial({ map: TEX.grass, color, roughness: 0.95 });
  const m = new THREE.Mesh(g, tm);
  m.position.copy(P((x0 + x1) / 2, (z0 + z1) / 2, 0.05));
  m.castShadow = m.receiveShadow = true;
  group.add(m);
}

function buildScene(M, L) {
  if (mapGroup) disposeGroup(mapGroup);
  for (const k of Object.keys(layers)) layers[k] = [];
  for (const o of [ZONE, PLACE, CELL, SIGNAL, CROSS]) for (const k in o) delete o[k];
  rain = null; weatherGroup = null; pedMesh = null; winMats = [];
  MAP = M; LAY = L;
  const [MW, MH] = M.size;
  W2 = MW / 2; H2 = MH / 2;
  const g = (mapGroup = new THREE.Group());
  scene.add(g);
  const lw = M.lane_width || 3.5, SW = 3.0, B = lw + SW;
  // 땅
  const gt = TEX.grass.clone(); gt.needsUpdate = true; gt.repeat.set((MW + 4000) / 60, (MH + 4000) / 60);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(MW + 4000, MH + 4000).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({ map: gt, roughness: 1 }));
  ground.position.copy(P(MW / 2, MH / 2, -0.05));
  ground.receiveShadow = true;
  g.add(ground);
  for (const w of M.water || []) {
    const r = w.rect;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(r[2] - r[0], r[3] - r[1]).rotateX(-Math.PI / 2),
      new THREE.MeshStandardMaterial({ color: "#3d6f8f", roughness: 0.15, metalness: 0.3 }));
    m.position.copy(P((r[0] + r[2]) / 2, (r[1] + r[3]) / 2, 0.02));
    m.receiveShadow = true;
    g.add(m);
  }
  const tunnels = M.zones.filter((z) => z.kind === "tunnel").map((z) => z.rect);
  for (const h of L.hills || []) terrain(g, h, tunnels, lw, "#8aa06a");
  // ---------------------------------------------------------------- 도로
  const nodes = L.junctions.map((j) => ({ pos: j.pos, arms: j.arms }));
  for (const rd of M.roads) for (let i = 1; i < rd.pts.length - 1; i++) {
    const a = rd.pts[i - 1], p = rd.pts[i], b = rd.pts[i + 1];
    const u1 = [a[0] - p[0], a[1] - p[1]], u2 = [b[0] - p[0], b[1] - p[1]];
    const n1 = Math.hypot(...u1), n2 = Math.hypot(...u2);
    nodes.push({ pos: p, arms: [[u1[0] / n1, u1[1] / n1], [u2[0] / n2, u2[1] / n2]], corner: true });
  }
  const asphalt = new THREE.MeshStandardMaterial({ map: TEX.asphalt, roughness: 0.92 });
  asphalt.map = TEX.asphalt.clone(); asphalt.map.needsUpdate = true; asphalt.map.repeat.set(1 / 12, 1 / 12);
  const sidewalkMat = new THREE.MeshStandardMaterial({ map: TEX.concrete, roughness: 0.9 });
  const asGeo = [], swGeo = [], whiteGeo = [], yellowGeo = [];
  const strip = (arr, cx, cz, len, wid, ux, uz, y, thick = 0) => {
    const gg = thick > 0 ? new THREE.BoxGeometry(len, thick, wid) : new THREE.PlaneGeometry(len, wid).rotateX(-Math.PI / 2);
    gg.rotateY(-Math.atan2(uz, ux));
    gg.translate(cx - W2, y + thick / 2, cz - H2);
    // 아스팔트 uv는 월드 좌표 기준 (이음매 없이)
    if (arr === asGeo || arr === swGeo) {
      const p = gg.attributes.position, uvA = gg.attributes.uv;
      for (let i = 0; i < p.count; i++) uvA.setXY(i, p.getX(i), p.getZ(i));
    }
    arr.push(gg);
  };
  const intervals = (len, cuts) => {
    let segs = [[0, len]];
    for (const [c0, c1] of cuts) {
      const nxt = [];
      for (const [s0, s1] of segs) {
        if (c1 <= s0 || c0 >= s1) { nxt.push([s0, s1]); continue; }
        if (c0 > s0) nxt.push([s0, c0]);
        if (c1 < s1) nxt.push([c1, s1]);
      }
      segs = nxt;
    }
    return segs.filter(([a, b]) => b - a > 0.3);
  };
  for (const rd of M.roads) for (let i = 0; i < rd.pts.length - 1; i++) {
    const a = rd.pts[i], b = rd.pts[i + 1];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const ux = (b[0] - a[0]) / len, uz = (b[1] - a[1]) / len, nx = -uz, nz = ux;
    const at = (s, off) => [a[0] + ux * s + nx * off, a[1] + uz * s + nz * off];
    const endA = !nodes.some((n) => Math.hypot(n.pos[0] - a[0], n.pos[1] - a[1]) < 1), endB = !nodes.some((n) => Math.hypot(n.pos[0] - b[0], n.pos[1] - b[1]) < 1);
    const ext0 = endA ? 0 : lw, ext1 = endB ? 0 : lw, cc = at((len + ext1 - ext0) / 2, 0);   // 교차로 쪽 끝은 차로 폭만큼 늘림
    strip(asGeo, cc[0], cc[1], len + ext0 + ext1, 2 * lw, ux, uz, 0.02);
    // 이 구간에 걸치는 교차로·모서리: 그 쪽으로 갈래가 있는 면만 끊는다
    const near = nodes.map((n) => ({ n, t: (n.pos[0] - a[0]) * ux + (n.pos[1] - a[1]) * uz, d: segDist(n.pos, a, b) })).filter((o) => o.d < 1);
    for (const side of [1, -1]) {
      const cuts = [], ext = [0, 0];
      for (const { n, t } of near) {
        const toSide = n.arms.some((arm) => arm[0] * nx * side + arm[1] * nz * side > 0.7);
        if (toSide) cuts.push([t - B, t + B]);
        else if (t < 1) ext[0] = lw; else if (t > len - 1) ext[1] = lw;
      }
      for (const [s0, s1] of intervals(len, cuts)) {
        const e0 = s0 < 0.5 ? ext[0] : 0, e1 = s1 > len - 0.5 ? ext[1] : 0;
        const mid = (s0 - e0 + s1 + e1) / 2, L2 = s1 - s0 + e0 + e1;
        const sw = at(mid, side * (lw + SW / 2)), ed = at(mid, side * (lw - 0.25));
        strip(swGeo, sw[0], sw[1], L2, SW, ux, uz, 0, 0.16);
        strip(whiteGeo, ed[0], ed[1], L2, 0.15, ux, uz, 0.03);
      }
    }
    const ccuts = near.map(({ t }) => [t - B, t + B]);
    for (const [s0, s1] of intervals(len, ccuts)) for (const off of [-0.12, 0.12]) {
      const c = at((s0 + s1) / 2, off);
      strip(yellowGeo, c[0], c[1], s1 - s0, 0.12, ux, uz, 0.035);
    }
    if (i === 0) addLabel(g, `${rd.name} · ${rd.speed} km/h`, "road", P(at(Math.min(60, len / 2), 0)[0], at(Math.min(60, len / 2), 0)[1], 3));
  }
  // 모서리 보도 (교차로 네 귀퉁이)
  for (const n of nodes) for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
    const c = [n.pos[0] + sx * (lw + SW / 2), n.pos[1] + sz * (lw + SW / 2)];
    if (roadDist(c) > lw + 0.4) strip(swGeo, c[0], c[1], SW, SW, 1, 0, 0, 0.16);
  }
  const addMerged = (arr, m, shadow = true) => {
    if (!arr.length) return;
    const mesh = new THREE.Mesh(mergeGeometries(arr), m);
    mesh.receiveShadow = shadow;
    mesh.userData.sharedMat = true;
    g.add(mesh);
    arr.forEach((x) => x.dispose());
  };
  addMerged(asGeo, asphalt);
  addMerged(swGeo, sidewalkMat);
  // 정지선·화살표 (신호 교차로의 들어오는 차로)
  const arrowShape = new THREE.Shape([[-2.6, -0.12], [0.6, -0.12], [0.6, -0.45], [2.4, 0], [0.6, 0.45], [0.6, 0.12], [-2.6, 0.12]].map(([x, y]) => new THREE.Vector2(x, y)));
  for (const s of M.signals || []) {
    const j = L.junctions.find((jj) => Math.hypot(jj.pos[0] - s.pos[0], jj.pos[1] - s.pos[1]) < 8);
    for (const u of j ? j.arms : []) {
      const rx = u[1], rz = -u[0];                        // 들어오는 방향(-u)의 오른쪽
      const c = [s.pos[0] + u[0] * (B + 0.6) + rx * lw / 2, s.pos[1] + u[1] * (B + 0.6) + rz * lw / 2];
      strip(whiteGeo, c[0], c[1], 0.45, lw - 0.3, u[0], u[1], 0.035);
      const ac = [s.pos[0] + u[0] * (B + 14) + rx * lw / 2, s.pos[1] + u[1] * (B + 14) + rz * lw / 2];
      const ag = new THREE.ShapeGeometry(arrowShape).rotateX(-Math.PI / 2);
      ag.rotateY(-Math.atan2(-u[1], -u[0]));
      ag.translate(ac[0] - W2, 0.04, ac[1] - H2);
      whiteGeo.push(ag);
    }
  }
  // 횡단보도 (얼룩무늬) + 마름모 예고 표시
  for (const c of M.crosswalks || []) {
    CROSS[c.id] = c;
    const [x, z] = c.pos;
    const hor = isHorizontalRoad(M, c.pos);
    const ux = hor ? 1 : 0, uz = hor ? 0 : 1;
    for (let k = -lw + 0.45; k <= lw - 0.3; k += 0.9) strip(whiteGeo, x + (hor ? 0 : k), z + (hor ? k : 0), 4, 0.45, ux, uz, 0.04);
    for (const sgn of [-1, 1]) {
      const dpos = [x + ux * sgn * 28 + (hor ? 0 : -sgn * lw / 2), z + uz * sgn * 28 + (hor ? -sgn * lw / 2 : 0)];
      const dg = new THREE.RingGeometry(1.0, 1.25, 4, 1).rotateX(-Math.PI / 2).scale(2.2, 1, 0.8);
      dg.rotateY(hor ? 0 : Math.PI / 2);
      dg.translate(dpos[0] - W2, 0.04, dpos[1] - H2);
      whiteGeo.push(dg);
    }
    addLabel(g, `🚸 ${c.name}${c.school ? " (등하교 시간 혼잡)" : ""}`, "zone", P(x, z, 6));
  }
  addMerged(whiteGeo, markMat("#f3f3f0"), true);
  addMerged(yellowGeo, markMat("#f0b429"), true);
  // ---------------------------------------------------------------- 주차장
  const lotGeo = [], lineGeo = [];
  for (const lot of Object.values(L.lots)) {
    const [cx, cz] = lot.center, [ux, uz] = lot.u, [nx, nz] = lot.n;
    strip(lotGeo, cx, cz, lot.w + 1, lot.d + 1, ux, uz, 0.18);
    const k = lot.slots.length;
    for (let j = 0; j <= k; j++) {
      const s = (j - k / 2) * 2.8;
      strip(lineGeo, cx + ux * s, cz + uz * s, lot.d, 0.12, nx, nz, 0.2);
    }
    const ent = [cx - nx * (lot.d / 2 + SW / 2 + 0.5), cz - nz * (lot.d / 2 + SW / 2 + 0.5)];
    strip(lotGeo, ent[0], ent[1], SW + 1.2, 5, nx, nz, 0.19);
  }
  addMerged(lotGeo, asphalt);
  addMerged(lineGeo, markMat("#f3f3f0"));
  // ---------------------------------------------------------------- 건물·나무
  const groups = {};
  for (const bd of L.buildings) {
    const style = bd[5] === "tower" ? "tower" : bd[5];
    (groups[style] = groups[style] || []).push([...bd, (bd[0] * 7.13 + bd[1] * 3.71) % 1]);
  }
  for (const pb of L.place_buildings) {
    if (["apartment", "office"].includes(pb.kind))
      (groups[pb.kind] = groups[pb.kind] || []).push([pb.x - pb.w / 2, pb.z - pb.d / 2, pb.x + pb.w / 2, pb.z + pb.d / 2, pb.h, pb.kind, 0.37]);
  }
  for (const [k, list] of Object.entries(groups)) if (BSTYLE[k]) g.add(buildingMesh(list, BSTYLE[k]));
  const trees = L.trees;
  if (trees.length) {
    const trunk = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.16, 0.24, 2.6, 6), mat("#6b4f35"), trees.length);
    const crown = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(2.1, 1), new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.9, flatShading: true }), trees.length);
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = new THREE.Vector3(), c = new THREE.Color();
    trees.forEach(([x, z, s], i) => {
      const y = (L.hills || []).reduce((h, hl) => Math.max(h, hillHeight(x, z, hl, tunnels, lw)), 0);
      m4.compose(P(x, z, y + 1.3 * s), q, sc.set(s, s, s)); trunk.setMatrixAt(i, m4);
      m4.compose(P(x, z, y + 3.6 * s), q, sc.set(s, s * 1.15, s)); crown.setMatrixAt(i, m4);
      crown.setColorAt(i, c.setHSL(0.24 + ((x * 13 + z * 7) % 10) / 120, 0.42, 0.26 + ((x + z) % 7) / 70));
    });
    trunk.castShadow = crown.castShadow = true;
    g.add(trunk, crown);
  }
  // ---------------------------------------------------------------- 터널 입구·덮개
  for (const z of M.zones) {
    ZONE[z.id] = z;
    if (z.kind !== "tunnel") continue;
    const [x0, z0, x1, z1] = z.rect;
    const hor = x1 - x0 > z1 - z0;
    const onHill = (L.hills || []).some((h) => x0 >= h.rect[0] && x1 <= h.rect[2] && z0 >= h.rect[1] && z1 <= h.rect[3]);
    if (!onHill) terrain(g, { rect: hor ? [x0, (z0 + z1) / 2 - 40, x1, (z0 + z1) / 2 + 40] : [(x0 + x1) / 2 - 40, z0, (x0 + x1) / 2 + 40, z1],
      height: 11, cover: hor ? "x" : "z" }, [z.rect], lw, "#7f9a62");
    const portalH = onHill ? 14 : 9;
    for (const end of [0, 1]) {
      const px = hor ? (end ? x1 : x0) : (x0 + x1) / 2, pz = hor ? (z0 + z1) / 2 : (end ? z1 : z0);
      const rot = hor ? Math.PI / 2 : 0, wid = 2 * lw + 2;
      const fr = new THREE.Group();
      const wall = mat("#b9b5ad");
      for (const s of [-1, 1]) { const w = box(fr, 6, portalH, 1.5, wall, 0, 0); w.position.set(s * (wid / 2 + 3), portalH / 2, 0); }
      const top = box(fr, wid + 12, portalH - 6, 1.5, wall, 0, 0); top.position.set(0, 6 + (portalH - 6) / 2, 0);
      const hole = new THREE.Mesh(new THREE.PlaneGeometry(wid, 6), new THREE.MeshBasicMaterial({ color: "#0b0d10", side: THREE.DoubleSide }));
      hole.position.set(0, 3, -0.3); fr.add(hole);
      fr.position.copy(P(px, pz, 0));
      fr.rotation.y = rot;
      g.add(fr);
    }
    addLabel(g, `🚇 ${z.name} (무선 단절)`, "zone", P((x0 + x1) / 2, (z0 + z1) / 2, portalH + 14));
  }
  // ---------------------------------------------------------------- 셀(기지국)
  for (const c of M.cells) {
    const [x, z] = c.pos;
    const ring = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(Array.from({ length: 160 }, (_, k) =>
      new THREE.Vector3(Math.cos((k / 160) * Math.PI * 2) * c.r, 0, Math.sin((k / 160) * Math.PI * 2) * c.r))),
      new THREE.LineBasicMaterial({ color: c.color, transparent: true, opacity: 0.9 }));
    ring.position.copy(P(x, z, 1.0));
    const disc = new THREE.Mesh(new THREE.CircleGeometry(c.r, 96).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: c.color, transparent: true, opacity: 0.06, depthWrite: false }));
    disc.position.copy(P(x, z, 0.5));
    g.add(ring, disc);
    layers.cells.push(ring, disc);
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.9, 34, 8), mat("#9aa1a8", { metalness: 0.5 }));
    mast.position.copy(P(x, z, 17)); mast.castShadow = true;
    g.add(mast);
    for (let k = 0; k < 3; k++) {
      const a = (k / 3) * Math.PI * 2;
      const pnl = new THREE.Mesh(new THREE.BoxGeometry(0.3, 2.4, 0.7), mat("#e5e7eb"));
      pnl.position.copy(P(x + Math.cos(a) * 0.9, z + Math.sin(a) * 0.9, 32.5));
      pnl.rotation.y = -a;
      g.add(pnl);
    }
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.6, 12, 8), new THREE.MeshStandardMaterial({ color: c.color, emissive: c.color, emissiveIntensity: 1.5 }));
    head.position.copy(P(x, z, 34.6));
    g.add(head);
    CELL[c.id] = { ...c, top: P(x, z, 33) };
    addLabel(g, `📡 ${c.name} · 반경 ${c.r} m`, "cell", P(x, z, 42));
  }
  if (M.region_border_x) {
    const bx = M.region_border_x;
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([P(bx, -40, 1), P(bx, MH + 40, 1)]),
      new THREE.LineDashedMaterial({ color: "#f59e0b", dashSize: 14, gapSize: 10 }));
    line.computeLineDistances();
    g.add(line);
    layers.zones.push(line);
    addLabel(g, "W 권역 ◀ 권역 경계(망 불안정) ▶ E 권역", "zone", P(bx, 20, 12));
  }
  // ---------------------------------------------------------------- 구역
  for (const z of M.zones) {
    if (z.kind === "tunnel") continue;
    if (z.kind === "shadow") {
      const [x0, z0, x1, z1] = z.rect;
      overlayRect(g, z.rect, "#475569", 0.18, 0.3);
      addLabel(g, "🏢 빌딩 숲 (음영지역: 끊김이 몰려옴)", "zone", P((x0 + x1) / 2, (z0 + z1) / 2, 100));
    } else if (z.rect) {
      const [x0, z0, x1, z1] = z.rect;
      if (z.kind === "school") {          // 어린이 보호구역: 도로를 붉게 칠함
        for (const rd of M.roads) for (let i = 0; i < rd.pts.length - 1; i++) {
          const a = rd.pts[i], b = rd.pts[i + 1];
          const r = [Math.max(x0, Math.min(a[0], b[0]) - lw), Math.max(z0, Math.min(a[1], b[1]) - lw), Math.min(x1, Math.max(a[0], b[0]) + lw), Math.min(z1, Math.max(a[1], b[1]) + lw)];
          if (r[2] > r[0] && r[3] > r[1]) overlayRect(g, r, "#b8322b", 0.55, 0.03, null);
        }
      } else {
        const col = { congestion: "#f97316", wifi: "#22d3ee" }[z.kind] || "#94a3b8";
        overlayRect(g, z.rect, col, 0.2, 0.3);
        const pts = [P(x0, z0, 0.5), P(x1, z0, 0.5), P(x1, z1, 0.5), P(x0, z1, 0.5), P(x0, z0, 0.5)];
        const ln = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: col }));
        g.add(ln); layers.zones.push(ln);
      }
      const icon = { congestion: "🚦", school: "🏫", wifi: "📶" }[z.kind] || "";
      addLabel(g, `${icon} ${z.name}${z.speed ? ` · ${z.speed} km/h` : ""}`, "zone", P((x0 + x1) / 2, (z0 + z1) / 2, 10));
    } else if (z.circle) {
      const [x, zz, r] = z.circle;
      weatherGroup = new THREE.Group();
      const disc = new THREE.Mesh(new THREE.CircleGeometry(r, 64).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: "#1e3a5f", transparent: true, opacity: 0.12, depthWrite: false }));
      disc.position.copy(P(x, zz, 0.4));
      layers.zones.push(disc);
      const N = 2500, pos = new Float32Array(N * 3);
      for (let i = 0; i < N; i++) {
        const a = Math.random() * Math.PI * 2, rr = Math.sqrt(Math.random()) * r * 0.95;
        pos[i * 3] = x - W2 + Math.cos(a) * rr; pos[i * 3 + 1] = Math.random() * 120; pos[i * 3 + 2] = zz - H2 + Math.sin(a) * rr;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      rain = new THREE.Points(geo, new THREE.PointsMaterial({ color: "#a5c8e8", size: 1.2, transparent: true, opacity: 0.55 }));
      weatherGroup.add(disc, rain);
      g.add(weatherGroup);
      weatherGroup.userData.label = addLabel(g, "🌧 강우 구역 (대역폭↓)", "zone", P(x, zz, 60));
    }
  }
  // ---------------------------------------------------------------- 장소 건물
  for (const p of M.places) PLACE[p.id] = { ...p };
  for (const pb of L.place_buildings) {
    const p = PLACE[pb.place];
    const wifi = p.wifi ? " 📶" : "";
    const rotY = 0;
    if (pb.kind === "canopy") {                       // 충전소: 지붕 + 기둥 + 충전기
      const roof = box(g, pb.w + 4, 0.5, pb.d + 4, "#f4f4f2", pb.x, pb.z, 5.2, rotY);
      roof.castShadow = true;
      box(g, pb.w + 4.2, 0.6, 0.3, "#16a34a", pb.x, pb.z - (pb.d + 4) / 2, 5.0);
      for (const sx of [-1, 1]) for (const sz of [-1, 1]) box(g, 0.4, 5.2, 0.4, "#d1d5db", pb.x + sx * pb.w / 2, pb.z + sz * pb.d / 2.5);
    } else if (pb.kind === "garage") {
      box(g, pb.w, pb.h, pb.d, "#d6d9dd", pb.x, pb.z);
      box(g, pb.w * 0.8, 4.5, pb.d + 0.2, "#4b5563", pb.x, pb.z);
      box(g, pb.w + 0.4, 1.2, pb.d + 0.4, "#1d4ed8", pb.x, pb.z, pb.h - 1.2);
    } else if (pb.kind === "shed") {
      box(g, pb.w, pb.h, pb.d, "#c5c9a8", pb.x, pb.z);
      box(g, pb.w + 1, 0.6, pb.d + 1, "#5b6b4c", pb.x, pb.z, pb.h);
    } else if (pb.kind === "datacenter") {
      box(g, pb.w, pb.h, pb.d, "#2b3442", pb.x, pb.z);
      for (let i = 0; i < 4; i++) box(g, 4, 2.5, 4, "#9ca3af", pb.x - pb.w / 2 + 6 + i * 9, pb.z, pb.h);
      const glow = new THREE.Mesh(new THREE.SphereGeometry(2.5, 16, 12), new THREE.MeshBasicMaterial({ color: "#60a5fa" }));
      glow.position.copy(P(pb.x, pb.z, pb.h + 6));
      g.add(glow);
      p.glow = glow; p.top = P(pb.x, pb.z, pb.h + 6);
    }
    const icon = { home: "🏠", work: "🏢", gas: "⚡", service: "🔧", depot: "🚕", server: "🖥" }[p.kind] || "";
    const note = { home: " (주차 = 시동 꺼짐)", work: " (근무 중 주차)", gas: " (충전 중 새 데이터 없음)", service: " (OTA·정비 대기)", depot: " (택시 차고지)" }[p.kind] || "";
    addLabel(g, `${icon} ${p.name}${note}${wifi}`, "place", P(pb.x, pb.z, (pb.h || 6) + 8));
  }
  for (const p of M.places) if (p.kind === "gate") {
    const [x, z] = p.pos;
    addLabel(g, x < W2 ? "➡ 진입 게이트" : "이탈 게이트 ➡", "place", P(x + (x < W2 ? 40 : -40), z - 12, 8));
  }
  // ---------------------------------------------------------------- 신호등: 들어오는 차로마다 기둥·팔·등 (가로 3구)
  for (const s of M.signals || []) {
    const j = L.junctions.find((jj) => Math.hypot(jj.pos[0] - s.pos[0], jj.pos[1] - s.pos[1]) < 8);
    const lamps = { x: [], z: [] };
    for (const u of j ? j.arms : []) {
      const axis = Math.abs(u[0]) > Math.abs(u[1]) ? "x" : "z";
      const rx = u[1], rz = -u[0];
      const base = [s.pos[0] + u[0] * (B + 1.2) + rx * (lw + SW * 0.6), s.pos[1] + u[1] * (B + 1.2) + rz * (lw + SW * 0.6)];
      box(g, 0.25, 6.2, 0.25, "#6b7280", base[0], base[1]);
      const arm = new THREE.Mesh(new THREE.BoxGeometry(lw + 1.2, 0.18, 0.18), mat("#6b7280"));
      arm.position.copy(P(base[0] - rx * (lw + 1.2) / 2, base[1] - rz * (lw + 1.2) / 2, 6.0));
      arm.rotation.y = -Math.atan2(rz, rx);
      g.add(arm);
      const hc = [base[0] - rx * (lw * 0.9), base[1] - rz * (lw * 0.9)];
      const housing = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.45, 0.35), mat("#1f2937"));
      housing.position.copy(P(hc[0], hc[1], 5.6));
      housing.rotation.y = -Math.atan2(rz, rx);
      g.add(housing);
      const lm = {};
      ["red", "yellow", "green"].forEach((c, k) => {
        const m = new THREE.MeshStandardMaterial({ color: "#111", emissive: "#000" });
        const b = new THREE.Mesh(new THREE.SphereGeometry(0.15, 10, 8), m);
        const off = (k - 1) * 0.4;
        b.position.copy(P(hc[0] - rx * off + u[0] * 0.2, hc[1] - rz * off + u[1] * 0.2, 5.6));
        g.add(b);
        lm[c] = m;
      });
      lamps[axis].push(lm);
    }
    SIGNAL[s.id] = { ...s, lamps };
    addLabel(g, `🚦 ${s.id} ${s.name}`, "sig", P(s.pos[0], s.pos[1], 9));
  }
  pedMesh = new THREE.InstancedMesh(new THREE.CapsuleGeometry(0.25, 1.1, 4, 8), new THREE.MeshStandardMaterial({ color: "#ffffff" }), 128);
  pedMesh.count = 0;
  pedMesh.castShadow = true;
  pedMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  g.add(pedMesh);
  for (const o of layers.placeLabels) o.visible = $("#optPlaces").checked;
  for (const o of layers.cells) o.visible = $("#optCells").checked;
  for (const o of layers.zones) o.visible = $("#optZones").checked;
  fitView();
}

function isHorizontalRoad(M, p) {
  let best = 1e9, hor = true;
  for (const rd of M.roads) for (let i = 0; i < rd.pts.length - 1; i++) {
    const a = rd.pts[i], b = rd.pts[i + 1];
    const d = segDist(p, a, b);
    if (d < best) { best = d; hor = Math.abs(b[0] - a[0]) > Math.abs(b[1] - a[1]); }
  }
  return hor;
}

let CHASE = false;
function fitView() {
  CHASE = false; controls.enabled = true; $("#btnChase")?.classList.remove("on");
  const v = THREE.MathUtils.degToRad(camera.fov) / 2;
  const h = Math.atan(Math.tan(v) * camera.aspect);
  const d = Math.max((W2 + 60) / Math.tan(h), (H2 + 60) / Math.tan(v)) * 0.95;
  const dir = new THREE.Vector3(0, 0.82, 0.57).normalize();
  controls.target.set(0, 0, 40);
  camera.position.copy(controls.target).addScaledVector(dir, d);
  controls.maxDistance = d * 1.2;
  controls.update();
}

// 하루 시계 → 해 위치·하늘·조명·창문 불빛·전조등
function applyTime(tod) {
  if (tod === undefined || tod === null) return;
  const elev = Math.sin(Math.PI * (tod - 6) / 12);                       // 6시 0 → 12시 1 → 18시 0
  const az = Math.PI * (tod - 6) / 12;
  const e = Math.max(-0.25, elev);
  sunDir.set(Math.cos(az) * 0.8, Math.max(0.02, 0.25 + 0.5 * e), -0.55).normalize();   // 낮게 비춰 벽면에 명암
  sky.material.uniforms.sunPosition.value.set(Math.cos(az), e, -0.45);
  const day = clamp((elev + 0.08) / 0.35, 0, 1);
  NIGHT = 1 - day;
  // 밤에는 달빛(푸른 약한 직사광) + 하늘빛으로 길·건물 윤곽이 보이게
  sun.intensity = day > 0 ? 0.35 + 2.1 * Math.pow(clamp(elev, 0, 1), 0.5) : 0.35;
  sun.color.set(day > 0.15 ? new THREE.Color().setHSL(0.09, 0.6, 0.55 + 0.35 * clamp(elev * 2, 0, 1)) : new THREE.Color("#9fb4ff"));
  hemi.intensity = 0.55 + 0.85 * day;
  hemi.color.set(day > 0.3 ? "#dbe8ff" : "#7d8fc4");
  hemi.groundColor.set(day > 0.3 ? "#5a6b4a" : "#2a3140");
  renderer.toneMappingExposure = 0.6 + 0.28 * day;
  scene.fog.color.setHSL(0.58, 0.3 * day, 0.08 + 0.7 * day);
  for (const m of winMats) m.emissiveIntensity = 1.1 * NIGHT;
}
let TIME_FIX = null;                 // 점검용: 시각 고정

// ================================================================== 차량 (실제 크기: 길이 4.6 m, 폭 1.9 m)
const CARS = {};
const GEO = {
  newLow: new THREE.BoxGeometry(4.5, 0.62, 1.86), newCab: new THREE.BoxGeometry(2.3, 0.55, 1.62), newBar: new THREE.BoxGeometry(0.06, 0.08, 1.5),
  oldLow: new THREE.BoxGeometry(4.4, 0.8, 1.88), oldCab: new THREE.BoxGeometry(2.9, 0.78, 1.74), oldRack: new THREE.BoxGeometry(2.2, 0.08, 1.4),
  wheel: new THREE.CylinderGeometry(0.34, 0.34, 0.26, 16).rotateX(Math.PI / 2), lamp: new THREE.BoxGeometry(0.06, 0.16, 0.42),
};
const MARK_TEX = canvasTex(64, (c, s) => {
  c.clearRect(0, 0, s, s);
  c.beginPath(); c.arc(s / 2, s / 2, s / 2 - 4, 0, 7); c.fillStyle = "#ffffff"; c.fill();
  c.lineWidth = 5; c.strokeStyle = "rgba(15,23,42,0.85)"; c.stroke();
});
function makeCar(vid, vtype) {
  const g = new THREE.Group();
  const bodyMat = new THREE.MeshStandardMaterial({ color: "#e2e8f0", roughness: 0.35, metalness: 0.45 });
  const glass = mat("#1c2733", { metalness: 0.7, roughness: 0.15 });
  const isNew = vtype === "new";
  const body = new THREE.Mesh(isNew ? GEO.newLow : GEO.oldLow, bodyMat);
  body.position.y = isNew ? 0.6 : 0.7;
  body.userData.vid = vid;
  const cab = new THREE.Mesh(isNew ? GEO.newCab : GEO.oldCab, glass);
  cab.position.set(isNew ? -0.25 : -0.45, isNew ? 1.18 : 1.49, 0);
  body.castShadow = cab.castShadow = true;
  g.add(body, cab);
  if (isNew) {
    const bar = new THREE.Mesh(GEO.newBar, new THREE.MeshStandardMaterial({ color: "#22d3ee", emissive: "#22d3ee", emissiveIntensity: 2 }));
    bar.position.set(2.26, 0.75, 0);
    g.add(bar);
  } else {
    const rack = new THREE.Mesh(GEO.oldRack, mat("#3f3f46"));
    rack.position.set(-0.45, 1.93, 0);
    g.add(rack);
  }
  for (const sx of [-1.45, 1.45]) for (const sz of [-0.86, 0.86]) {
    const w = new THREE.Mesh(GEO.wheel, mat("#111214"));
    w.position.set(sx, 0.34, sz);
    g.add(w);
  }
  const headMat = new THREE.MeshStandardMaterial({ color: "#f8fafc", emissive: "#fff6d5", emissiveIntensity: 0 });
  const brakeMat = new THREE.MeshStandardMaterial({ color: "#7f1d1d", emissive: "#ff2020", emissiveIntensity: 0 });
  for (const sz of [-0.62, 0.62]) {
    const h = new THREE.Mesh(GEO.lamp, headMat); h.position.set(isNew ? 2.26 : 2.21, isNew ? 0.68 : 0.82, sz);
    const t = new THREE.Mesh(GEO.lamp, brakeMat); t.position.set(isNew ? -2.26 : -2.21, isNew ? 0.72 : 0.86, sz);
    g.add(h, t);
  }
  const markMatS = new THREE.SpriteMaterial({ map: MARK_TEX, color: "#e2e8f0", depthTest: false, sizeAttenuation: false });
  const marker = new THREE.Sprite(markMatS);
  marker.scale.set(0.022, 0.022, 1);
  marker.position.y = 3;
  marker.renderOrder = 10;
  marker.userData.vid = vid;
  g.add(marker);
  const d = el("div", "vlbl", `V${vid}`);
  const lo = new CSS2DObject(d);
  lo.position.set(0, 3.4, 0);
  g.add(lo);
  scene.add(g);
  const beam = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
    new THREE.LineDashedMaterial({ color: "#f97316", dashSize: 3, gapSize: 2 }));
  beam.visible = false;
  scene.add(beam);
  return (CARS[vid] = { g, body, bodyMat, brakeMat, headMat, marker, markMatS, d, lo, beam, vtype, target: null, heading: 0, floats: 0 });
}
function removeCar(vid) {
  const c = CARS[vid];
  if (!c) return;
  c.lo.element.remove();
  scene.remove(c.g);
  scene.remove(c.beam);
  c.beam.geometry.dispose(); c.beam.material.dispose();
  for (const m of [c.bodyMat, c.brakeMat, c.headMat, c.markMatS]) m.dispose();
  delete CARS[vid];
}
function clearCars() { for (const k of Object.keys(CARS)) removeCar(k); }

function vtypeOf(vid, cfg = CFG) {
  const v = { ...(cfg.vehicle_default || {}), ...((cfg.vehicles || {})[String(vid)] || {}) };
  return v.vtype || (vid % 2 === 1 ? "new" : "old");
}

/** 차량 하나 그리기. s = {pos, heading, present, status, version, badges, emergency, cell, braking} */
function drawCar(vid, s) {
  let car = CARS[vid];
  const vt = vtypeOf(vid);
  if (car && car.vtype !== vt) { removeCar(vid); car = null; }
  car = car || makeCar(vid, vt);
  car.g.visible = s.present !== false;
  car.lo.visible = car.g.visible && $("#optLabels").checked;
  car.target = P(s.pos[0], s.pos[1]);
  car.heading = -s.heading;
  if (!car.init || car.g.position.distanceTo(car.target) > 40) { car.g.position.copy(car.target); car.g.rotation.y = car.heading; car.init = true; }
  const [name, col] = STATE[s.status] || STATE.idle;
  car.bodyMat.color.set(col);
  car.markMatS.color.set(col);
  car.brakeMat.emissiveIntensity = s.braking || s.emergency > 0 ? 3 : 0.3 * NIGHT;
  car.headMat.emissiveIntensity = (s.engine_off ? 0 : 2.5) * NIGHT;
  car.d.className = "vlbl" + (vid === selected ? " sel" : "") + (s.emergency > 0 ? " emerg" : "");
  car.d.style.background = col;
  car.d.innerHTML = `V${vid}<span class="ty ${vt}">${vt === "new" ? "신형" : "구형"}</span> <small>${name}${s.version !== undefined ? ` v${s.version}` : ""}</small> ${s.badges || ""}`;
  const cell = s.cell && CELL[s.cell];
  car.beam.visible = $("#optBeams").checked && s.status === "uploading" && !!cell && car.g.visible;
  if (car.beam.visible) {
    const pos = car.beam.geometry.attributes.position;
    pos.setXYZ(0, car.g.position.x, 2, car.g.position.z);
    pos.setXYZ(1, cell.top.x, cell.top.y, cell.top.z);
    pos.needsUpdate = true;
    car.beam.geometry.computeBoundingSphere();
    car.beam.computeLineDistances();
  }
}

function liveCarState(vid) {
  const w = LAST?.world?.vehicles?.[vid];
  if (!w) return null;
  const c = LAST?.clients?.[vid] || {};
  const status = w.present === false ? "absent" : w.engine_off && ["dead", "skipped", "idle"].includes(c.status) ? "parked" : (c.status || "idle");
  const badges = [w.engine_off && w.present ? "🅿" : "", w.charging ? "⚡" : "", w.ota ? "🔧" : "", w.zones?.tunnel ? "🚇" : "",
    w.wifi ? "📶" : "", !w.link_up && w.present ? "📵" : "", c.queue ? `📦${c.queue}` : "",
    w.emergency > 0 ? `⚠${Math.ceil(w.emergency)}s` : "", (c.energy ?? 999) < CFG.energy.min_energy_j ? "🪫" : ""].join("");
  return { ...w, status, version: c.version, badges };
}

function updateSignalsAndPeds(sigs, peds) {
  const st = { green: "green", yellow: "yellow", red: "red", g: "green", y: "yellow", r: "red" };
  const COL = { red: "#ff3b30", yellow: "#ffcc00", green: "#22e07a" };
  for (const [id, v] of Object.entries(sigs || {})) {
    const s = SIGNAL[id];
    if (!s) continue;
    const ax = { x: st[v[0]], z: st[v[1]] };
    for (const axis of ["x", "z"]) for (const lm of s.lamps[axis]) for (const c of ["red", "yellow", "green"]) {
      const on = ax[axis] === c;
      lm[c].color.set(on ? COL[c] : "#1a1a1a");
      lm[c].emissive.set(on ? COL[c] : "#000000");
      lm[c].emissiveIntensity = on ? 3 : 0;
    }
  }
  if (!pedMesh) return;
  const m = new THREE.Matrix4(), c = new THREE.Color();
  const n = Math.min(128, (peds || []).length);
  for (let i = 0; i < n; i++) {
    const [x, z, dart] = peds[i];
    m.setPosition(x - W2, 0.9, z - H2);
    pedMesh.setMatrixAt(i, m);
    pedMesh.setColorAt(i, c.set(dart ? "#ef4444" : ["#334155", "#f8fafc", "#a16207", "#1d4ed8"][i % 4]));
  }
  pedMesh.count = n;
  pedMesh.instanceMatrix.needsUpdate = true;
  if (pedMesh.instanceColor) pedMesh.instanceColor.needsUpdate = true;
}

// 떠오르는 사건 표시 (동시에 최대 24개, 끝나면 DOM까지 제거 → 메모리 일정)
let activeFloats = 0;
function floatAt(vid, text, color) {
  const car = CARS[vid];
  if (!car || activeFloats >= 24 || car.floats >= 2) return;
  const o = new CSS2DObject(el("div", "float", text));
  o.element.style.background = color;
  o.position.set(0, 6 + car.floats * 2.5, 0);
  car.g.add(o);
  car.floats++; activeFloats++;
  setTimeout(() => { car.g.remove(o); o.element.remove(); car.floats--; activeFloats--; }, 2600);
}
// 도착 선: 미리 만든 12개를 돌려 쓴다 (새 geometry를 만들지 않음)
const FLASH = [];
for (let i = 0; i < 12; i++) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(9), 3));
  const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: "#4ade80", transparent: true, opacity: 0, depthTest: false }));
  line.visible = false;
  line.renderOrder = 9;
  scene.add(line);
  FLASH.push({ line, t0: 0 });
}
function flashArrival(vid) {
  const car = CARS[vid], dc = PLACE.datacenter;
  if (!car || !dc?.top) return;
  const f = FLASH.find((x) => !x.line.visible) || FLASH.reduce((a, b) => (a.t0 < b.t0 ? a : b));
  const w = LAST?.world?.vehicles?.[vid];
  const cell = w?.cell && CELL[w.cell];
  const p = f.line.geometry.attributes.position;
  const a = car.g.position, mid = cell ? cell.top : a;
  p.setXYZ(0, a.x, 2, a.z); p.setXYZ(1, mid.x, mid.y, mid.z); p.setXYZ(2, dc.top.x, dc.top.y, dc.top.z);
  p.needsUpdate = true;
  f.line.geometry.computeBoundingSphere();
  f.line.visible = true; f.t0 = performance.now();
  dc.glow.material.color.set("#4ade80");
  setTimeout(() => dc.glow.material.color.set("#60a5fa"), 500);
}

// ================================================================== 렌더 루프
let fitted = false;
function resize() {
  const r = holder.getBoundingClientRect();
  if (!r.width) return;
  renderer.setSize(r.width, r.height);
  labelRenderer.setSize(r.width, r.height);
  camera.aspect = r.width / Math.max(1, r.height);
  camera.updateProjectionMatrix();
  if (!fitted && MAP) { fitted = true; fitView(); }
}
window.addEventListener("resize", resize);
let lastFrame = performance.now();
const tmpV = new THREE.Vector3(), chaseLook = new THREE.Vector3();
function frame(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  for (const car of Object.values(CARS)) {
    if (!car.target) continue;
    car.g.position.lerp(car.target, Math.min(1, dt * 5));
    let dh = car.heading - car.g.rotation.y;
    dh = Math.atan2(Math.sin(dh), Math.cos(dh));
    car.g.rotation.y += dh * Math.min(1, dt * 6);
    car.marker.visible = camera.position.distanceTo(car.g.position) > 140;
    if (car.beam.visible) car.beam.material.dashOffset -= dt * 20;
  }
  if (rain && weatherGroup?.visible) {
    const p = rain.geometry.attributes.position;
    for (let i = 0; i < p.count; i++) { let y = p.getY(i) - dt * 60; if (y < 0) y = 120; p.setY(i, y); }
    p.needsUpdate = true;
  }
  for (const f of FLASH) {
    if (!f.line.visible) continue;
    const a = 1 - (now - f.t0) / 1400;
    if (a <= 0) f.line.visible = false; else f.line.material.opacity = a;
  }
  const car = CHASE && CARS[selected];
  if (car && car.g.visible) {                       // 차량 따라가기: 뒤 12 m, 위 5 m
    const h = -car.g.rotation.y;
    tmpV.set(car.g.position.x - Math.cos(h) * 12, car.g.position.y + 5, car.g.position.z - Math.sin(h) * 12);
    camera.position.lerp(tmpV, Math.min(1, dt * 3));
    chaseLook.lerp(tmpV.set(car.g.position.x + Math.cos(h) * 10, 1.2, car.g.position.z + Math.sin(h) * 10), Math.min(1, dt * 4));
    camera.lookAt(chaseLook);
    controls.target.copy(chaseLook);
  } else {
    // 카메라가 맵 밖으로 나가지 않게: 바라보는 점을 맵 안으로, 높이는 지면 위로
    controls.target.x = clamp(controls.target.x, -W2 - 40, W2 + 40);
    controls.target.z = clamp(controls.target.z, -H2 - 40, H2 + 40);
    controls.target.y = 0;
    controls.update();
    if (camera.position.y < 2) camera.position.y = 2;
  }
  const dist = camera.position.distanceTo(controls.target);
  camera.near = clamp(dist / 400, 0.3, 8);
  camera.far = Math.max(12000, dist * 8);
  camera.updateProjectionMatrix();
  // 그림자 카메라는 보고 있는 곳을 따라간다
  const span = clamp(dist * 0.8, 120, 900);
  Object.assign(sun.shadow.camera, { left: -span, right: span, top: span, bottom: -span });
  sun.shadow.camera.updateProjectionMatrix();
  sun.target.position.copy(controls.target);
  sun.position.copy(controls.target).addScaledVector(sunDir, 900);
  renderer.render(scene, camera);
  labelRenderer.render(scene, camera);
  requestAnimationFrame(frame);
}

const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
function pick(ev) {
  const r = renderer.domElement.getBoundingClientRect();
  mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(mouse, camera);
  const objs = Object.values(CARS).filter((c) => c.g.visible).flatMap((c) => (c.marker.visible ? [c.body, c.marker] : [c.body]));
  const hit = ray.intersectObjects(objs)[0];
  return hit ? hit.object.userData.vid : null;
}
renderer.domElement.addEventListener("click", (ev) => { const v = pick(ev); if (v) selectVehicle(v); });
renderer.domElement.addEventListener("mousemove", (ev) => {
  const v = pick(ev), tip = $("#tooltip");
  if (!v || REPLAY) { tip.style.display = "none"; return; }
  const s = liveCarState(v) || {}, c = LAST?.clients?.[v] || {};
  tip.innerHTML = `<b>V${v} ${vtypeOf(v) === "new" ? "신형 EV" : "구형 EV"} · ${KIND[s.kind] || ""}</b> · ${STATE[s.status]?.[0] || ""} — ${c.detail || ""}<br>
    ${s.sched || ""}${s.parked ? ` · 🅿 ${s.park_why}` : ""}<br>
    ${s.speed_kmh ?? "-"} km/h · 셀 ${s.cell || "없음"} · ${s.link_up ? "연결" : "연결 없음"}${s.wifi ? " · Wi-Fi" : ""} · 권역 ${s.region}<br>
    에너지 ${c.energy ?? "-"} / ${c.budget ?? "-"} J · 새 데이터 ${c.new_data ?? "-"} · 모델 v${c.version ?? "-"} (서버 v${c.server_version ?? "-"})
    ${s.emergency > 0 ? `<br><b style="color:#f87171">긴급제동(${s.emergency_cause}) — ADAS 연산 점유 ${s.emergency}초</b>` : ""}`;
  Object.assign(tip.style, { display: "block", left: ev.clientX + 14 + "px", top: ev.clientY + 10 + "px" });
});
renderer.domElement.addEventListener("pointerdown", () => { if (CHASE) setChase(false); });

function setChase(on) {
  CHASE = on;
  controls.enabled = !on;
  $("#btnChase").classList.toggle("on", on);
  $("#btnChase").textContent = on ? `🎥 V${selected} 따라가는 중 (끄기)` : "🎥 선택 차량 따라가기";
  if (!on) { controls.target.y = 0; controls.update(); }
}

/** 유스케이스 → 맵에서 볼 곳 (맵마다 장소·구역 id가 같다) */
function focusPoint(id) {
  const zone = (k) => MAP.zones.find((z) => z.kind === k);
  const place = (k) => MAP.places.find((p) => p.kind === k);
  const zc = (z) => (z ? (z.rect ? [(z.rect[0] + z.rect[2]) / 2, (z.rect[1] + z.rect[3]) / 2] : [z.circle[0], z.circle[1]]) : null);
  const fast = [...MAP.roads].sort((a, b) => b.speed - a.speed)[0];
  const school = (MAP.crosswalks || []).find((c) => c.school) || (MAP.crosswalks || [])[0];
  const m = {
    "1-2": place("service")?.pos, "1-4": school?.pos, "4-5": school?.pos, "1-5": place("home")?.pos,
    "2-2": fast && [(fast.pts[0][0] + fast.pts[1][0]) / 2, (fast.pts[0][1] + fast.pts[1][1]) / 2],
    "2-4": MAP.region_border_x && fast && [MAP.region_border_x, fast.pts[0][1]], "2-5": zc(zone("tunnel")),
    "3-2": place("gas")?.pos, "3-3": zc(zone("wifi")), "4-2": zc(zone("congestion")), "4-4": zc(zone("weather")),
    "5-1": zc(zone("shadow")), "5-2": MAP.cells[0] && [MAP.cells[0].pos[0] + MAP.cells[0].r * 0.92, MAP.cells[0].pos[1]],
    "2-1": MAP.cells[0] && [MAP.cells[0].pos[0] + MAP.cells[0].r, MAP.cells[0].pos[1]],
    "5-3": place("server")?.pos, "8-1": place("server")?.pos, "8-2": place("server")?.pos, "7-3": place("work")?.pos,
    "1-3": place("gas")?.pos, "2-6": place("gas")?.pos, "3-1": place("gas")?.pos, "4-6": place("depot")?.pos,
  };
  return m[id] || null;
}
function focusOn(pt) {
  if (!pt) return;
  document.querySelector('[data-tab="map"]').click();
  setChase(false);
  controls.target.copy(P(pt[0], pt[1]));
  camera.position.copy(P(pt[0] - 60, pt[1] + 160, 140));
  controls.update();
}

let MAP_ID = null;

// ================================================================== 탭·범례
document.querySelectorAll(".tabs").forEach((nav) => nav.addEventListener("click", (e) => {
  const b = e.target.closest(".tab");
  if (!b) return;
  nav.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === b));
  nav.parentElement.querySelectorAll(":scope > .tabpane").forEach((p) => p.classList.toggle("active", p.id === "pane-" + b.dataset.tab));
  if (b.dataset.tab === "map") resize();
  if (b.dataset.tab === "runs") loadRuns();
  if (b.dataset.tab === "save") loadSaves();
}));
function buildLegends() {
  $("#legendState").innerHTML = "<b>차체 색 = 연합학습 상태 · 모양 = 신형 EV(낮은 세단, 청록 라이트) / 구형 EV(높은 SUV, 루프랙)</b>" +
    Object.entries(STATE).map(([, [n, c]]) => `<span><i style="background:${c}"></i>${n}</span>`).join("") +
    "<span style='grid-column:1/-1' class='muted'>🅿주차(시동 꺼짐) ⚡충전 🔧OTA 🚇터널 📶Wi-Fi 📵연결 없음 📦보관 ⚠긴급제동 🪫에너지↓ · 멀리서는 동그라미 표시 · 빨간 사람 = 돌발 보행자</span>";
  $("#legendPatterns").innerHTML = "<b>사건 색 = 패턴 (서버가 받은 모습)</b>" +
    Object.entries(STATIC.patterns).map(([k, n]) => `<span><i style="background:${PCOL[k]}"></i>P${k} ${n}</span>`).join("");
}

// ================================================================== 설정 폼
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
    ["safety_preempt_prob", "긴급제동 시 FL 종료 확률", "num", 0, 1, 0.05, "1-4"]]],
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
    ["speed_scale", "주행 속도 배율", "num", 0.1, 5, 0.1, ""], ["signal_scale", "신호 주기 배율", "num", 0.2, 5, 0.1, ""],
    ["pedestrian_scale", "보행자 빈도 배율", "num", 0, 10, 0.5, "1-4 · 4-5"], ["ota_prob", "서비스센터 OTA 확률 (나머지는 정비 대기)", "num", 0, 1, 0.05, "1-2 · 3-2"],
    ["day_minutes", "하루 길이 (실제 분, 24시간)", "num", 2, 1440, 1, "7-3"], ["start_hour", "시작 시각 (시)", "num", 0, 23.9, 0.5, "7-3", true],
    ["weather_on", "강우 구역 켜기", "bool", 0, 0, 0, "4-4"], ["visitor_gap_mean_s", "통과 차량 재진입 평균 (초)", "num", 5, 600, 5, ""]]],
  ["서버", "server", [
    ["pause_s", "서버 장애 시간 (초)", "num", 5, 600, 5, "8-1 · 5-3"], ["p7_window", "편중 감시 창 (라운드)", "num", 5, 200, 1, "7-x", true],
    ["p7_ratio", "편중 판단 배수", "num", 1, 5, 0.1, "7-x"]]],
];
function inputFor(def, value, onchange) {
  const [key, name, type, min, max, step, uc, restart] = def;
  const f = el("div", "field");
  f.appendChild(el("label", "", `${name}${uc ? `<span class="uc">${uc}</span>` : ""}${restart ? '<span class="restart">재시작</span>' : ""}`));
  let inp;
  if (type === "bool") {
    inp = el("input"); inp.type = "checkbox"; inp.checked = !!value;
    inp.onchange = () => onchange(inp.checked);
  } else if (type === "method" || type.startsWith("sel:")) {
    inp = el("select");
    const opts = type === "method" ? Object.entries(STATIC.methods).map(([k, m]) => [k, m.name]) : type.slice(4).split(",").map((o) => o.split("="));
    for (const [v, label] of opts) inp.appendChild(new Option(label || v, v, false, v === value));
    inp.onchange = () => onchange(inp.value);
  } else {
    inp = el("input"); inp.type = type === "text" ? "text" : "number";
    if (type !== "text") { inp.min = min; inp.max = max; inp.step = step; }
    inp.value = value === null || value === undefined ? "" : value;
    inp.onchange = () => onchange(type === "text" ? inp.value : (inp.value === "" ? null : Number(inp.value)));
  }
  f.appendChild(inp);
  return f;
}
async function postCfg(patch) {
  const r = await fetch("/api/config", { method: "POST", body: JSON.stringify(patch) });
  CFG = (await r.json()).config;
  renderMethodChip();
}
function buildGlobalForm() {
  const box = $("#globalForm");
  box.innerHTML = "";
  for (const [title, sec, defs] of GFIELDS) {
    box.appendChild(el("div", "fgroup", title));
    for (const d of defs) box.appendChild(inputFor(d, CFG[sec][d[0]], (v) => postCfg({ [sec]: { [d[0]]: v } })));
  }
}
function buildVehForm() {
  const box = $("#vehForm");
  box.innerHTML = "";
  const all = el("div", "field");
  all.innerHTML = `<label><b>모든 차량에 적용</b><span class="uc">기본값을 바꿈</span></label>`;
  const cb = el("input"); cb.type = "checkbox"; cb.id = "applyAll";
  all.appendChild(cb);
  box.appendChild(all);
  const cur = { ...CFG.vehicle_default, ...(CFG.vehicles[String(selected)] || {}) };
  if (!cur.vtype) cur.vtype = vtypeOf(selected);
  for (const [title, defs] of VFIELDS) {
    box.appendChild(el("div", "fgroup", title));
    for (const d of defs) box.appendChild(inputFor(d, cur[d[0]], (v) => {
      if ($("#applyAll").checked) postCfg({ vehicle_default: { [d[0]]: v } });
      else postCfg({ vehicles: { [String(selected)]: { [d[0]]: v } } });
    }));
  }
}
function selectVehicle(v) { selected = v; buildVehForm(); renderVehPicker(); renderVehInfo(); }
function renderVehPicker() {
  const K = CFG.fl.K;
  for (const id of ["#vehPicker", "#vehGrid"]) {
    const box = $(id);
    if (box.children.length !== K) {
      box.innerHTML = "";
      for (let v = 1; v <= K; v++) { const b = el("div", "vchip"); b.onclick = () => selectVehicle(v); box.appendChild(b); }
    }
    [...box.children].forEach((b, i) => {
      const v = i + 1, s = REPLAY ? null : liveCarState(v);
      const [n, c] = STATE[s?.status] || STATE.idle;
      b.style.background = c;
      b.style.borderTop = `4px solid ${vtypeOf(v) === "new" ? "#0891b2" : "#b45309"}`;
      b.classList.toggle("sel", v === selected);
      b.title = vtypeOf(v) === "new" ? "신형 EV" : "구형 EV";
      b.innerHTML = `V${v}<small>${REPLAY ? "-" : n}</small>`;
    });
  }
}
function renderVehInfo() {
  if (REPLAY) { $("#vehInfo").innerHTML = "<span class='muted'>다시 보기 중 — 실시간 차량 정보 없음</span>"; return; }
  const s = liveCarState(selected) || {}, c = LAST?.clients?.[selected] || {};
  const route = `${KIND[s.kind] || ""} · ${MAP?.routes?.[s.route]?.name || "-"}`;
  const zones = Object.entries(s.zones || {}).filter(([, b]) => b).map(([k]) =>
    ({ tunnel: "터널", shadow: "음영", congestion: "혼잡", school: "보호구역", wifi: "Wi-Fi", weather: "강우" }[k])).join(", ");
  const hist = c.label_hist || [], mx = Math.max(1, ...hist), cn = c.counters || {};
  $("#vehInfo").innerHTML = `
    <div class="row"><b>V${selected} · ${vtypeOf(selected) === "new" ? "신형 EV" : "구형 EV"} · ${route}</b><span>${STATE[s.status]?.[0] || ""} — ${c.detail || ""}</span></div>
    <div class="row"><span>🕒 ${s.sched || "-"}</span><span>${s.parked ? `🅿 ${s.park_why} · ${Math.ceil(s.stop_left || 0)}초 남음` : ""}</span></div>
    <div class="row"><span>속도 ${s.speed_kmh ?? "-"} km/h · 셀 ${s.cell || "범위 밖"} · 품질 ${s.quality ?? "-"}</span><span>권역 ${s.region || "-"}</span></div>
    <div class="row"><span>구역: ${zones || "없음"}</span><span>${s.link_up ? "🟢 연결" : "🔴 연결 없음"}${s.wifi ? " 📶" : ""}</span></div>
    ${s.emergency > 0 ? `<div class="row" style="color:#f87171"><b>⚠ 긴급제동(${s.emergency_cause}) — ADAS 연산 점유 ${s.emergency}초</b></div>` : ""}
    <div class="row"><span>에너지 ${c.energy ?? "-"} / ${c.budget ?? "-"} J · 새 데이터 ${c.new_data ?? "-"} · 연산 ×${c.ecu ?? "-"} · 데이터 ×${c.data_mult ?? "-"}</span><span>모델 v${c.version ?? "-"} / 서버 v${c.server_version ?? "-"}</span></div>
    <div class="row"><span>학습 ${cn.trained ?? 0} · 전송 ${cn.sent ?? 0} · 폐기 ${cn.dropped ?? 0} · 중단 ${cn.aborted ?? 0} · 미참여 ${cn.skipped ?? 0} · 보관 ${cn.queued ?? 0}</span><span>낭비 ${c.wasted_mb ?? 0} MB</span></div>
    <div class="muted small">라벨 분포 (데이터 ${c.n_data ?? "-"}개, 최다 라벨 ${Math.round((c.label_skew || 0) * 100)}%) · 새 모델 연속 거부 ${c.keep_streak ?? 0}회</div>
    <div class="bars">${hist.map((h, i) => `<div title="${i}: ${h}" style="height:${(h / mx) * 100}%"></div>`).join("")}</div>`;
}

// ================================================================== 연합학습 패널
function renderFL(server, downLeft) {
  const s = server || {};
  const hist = s.history || [];
  const last = hist[hist.length - 1];
  $("#kRound").textContent = s.round ?? "-";
  $("#kAcc").textContent = last ? last.acc.toFixed(1) + "%" : "-";
  $("#kQuota").textContent = s.quota ?? "-";
  $("#kBuf").textContent = s.cached !== undefined ? `${s.cached}/${s.quota}` : "-";
  const wsec = s.phase === "waiting" ? s.waiting_s || 0 : 0;
  $("#waitFill").style.width = s.phase === "down" ? "100%" : Math.min(100, (wsec / 60) * 100) + "%";
  $("#waitText").textContent = s.phase === "down" ? `⛔ 집계 서버 장애 — ${downLeft ? Math.ceil(downLeft) + "초 뒤 복구" : "중단"} (8-1)`
    : s.phase === "waiting" ? `quota ${s.quota}개 모일 때까지 ${wsec.toFixed(0)}초 (버퍼 ${s.cached}개${wsec > 60 ? " · ⚠ 8-2 무한 대기" : ""})` : "집계 중";
  $("#flPhase").textContent = { waiting: "값 대기", aggregated: "집계 완료", start: "시작", down: "서버 장애" }[s.phase] || "-";
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
function canvasCtx(cv, h) {
  const W = (cv.width = cv.clientWidth * devicePixelRatio), H = (cv.height = h * devicePixelRatio);
  const ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  ctx.font = `${12 * devicePixelRatio}px sans-serif`;
  return [ctx, W, H];
}
function drawAcc(hist) {
  const [ctx, W, H] = canvasCtx($("#accChart"), 120);
  ctx.strokeStyle = "#2a3b60"; ctx.lineWidth = 1;
  for (let y = 0; y <= 4; y++) { ctx.beginPath(); ctx.moveTo(0, (H * y) / 4); ctx.lineTo(W, (H * y) / 4); ctx.stroke(); }
  ctx.fillStyle = "#a3b3d1"; ctx.fillText("정확도 % (라운드별)", 6 * devicePixelRatio, 14 * devicePixelRatio);
  if (hist.length < 2) return;
  const n = hist.length - 1;
  ctx.strokeStyle = "#5b9cff"; ctx.lineWidth = 2.2 * devicePixelRatio; ctx.beginPath();
  hist.forEach((h, i) => { const x = (i / n) * W, y = H - (h.acc / 100) * H; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.stroke();
}
function drawFair(part) {
  const [ctx, W, H] = canvasCtx($("#fairChart"), 104);
  const win = part?.window || {}, K = CFG.fl.K;
  const vals = Array.from({ length: K }, (_, i) => win[String(i + 1)] || 0);
  const dp = devicePixelRatio, top = 20 * dp, bottom = 16 * dp;
  const mx = Math.max(1, ...vals), bw = W / K;
  ctx.fillStyle = "#a3b3d1";
  ctx.fillText(`■ 청록 = 신형 EV   ■ 주황 = 구형 EV   (최근 ${part?.window_rounds ?? 0}라운드)`, 6 * dp, 14 * dp);
  vals.forEach((v, i) => {
    const h = (v / mx) * (H - top - bottom);
    ctx.fillStyle = vtypeOf(i + 1) === "new" ? "#22d3ee" : "#d97706";
    ctx.fillRect(i * bw + 4, H - bottom - h, bw - 8, h);
    ctx.fillStyle = "#e2e8f0";
    ctx.fillText(`V${i + 1} ${v}`, i * bw + 4, H - 3 * dp);
  });
}

// 시간대별 참여: 각 시간대에 집계된 값이 어떤 차량 종류(통근·택시·주민·통과)에서 왔는지 (7-3)
function drawPeriod(part) {
  const [ctx, W, H] = canvasCtx($("#periodChart"), 112);
  const dp = devicePixelRatio, per = part?.period || {}, K = CFG.fl.K;
  const kindOf = (v) => LAST?.world?.vehicles?.[v]?.kind || "visitor";
  const fleet = {};
  for (let v = 1; v <= K; v++) fleet[kindOf(v)] = (fleet[kindOf(v)] || 0) + 1;
  const rows = [["fleet", "차량 구성"], ...PERIODS];
  const top = 6 * dp, rh = (H - top) / rows.length, x0 = 132 * dp;
  rows.forEach(([key, label], r) => {
    const cnt = {};
    let tot = 0;
    if (key === "fleet") for (const [k, n] of Object.entries(fleet)) { cnt[k] = n; tot += n; }
    else for (const [v, n] of Object.entries(per[key] || {})) { const k = kindOf(v); cnt[k] = (cnt[k] || 0) + n; tot += n; }
    const y = top + r * rh;
    ctx.fillStyle = key === LAST?.world?.period ? "#fde68a" : "#cbd5e1";
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

// ================================================================== 사건
function evLine(e) {
  const p = e.pattern, d = el("div", "ev");
  d.style.borderLeftColor = p ? PCOL[p] : "#2a3b60";
  const tag = p ? `<span class="pt" style="background:${PCOL[p]}">${e.example}</span>` :
    `<span class="pt neutral">${{ round: "집계", arrive: "도착", upload: "전송", world: "환경", control: "제어", fl: "FL" }[e.kind] || e.kind}</span>`;
  d.innerHTML = `${tag}${e.vid ? `<b>V${e.vid}</b> ` : ""}${e.msg}<span class="tm">${fmtT(e.t)}</span>`;
  return d;
}
function shortName(ex) { const u = STATIC.usecases.find((u) => u[0] === ex); return u ? u[1].split(" (")[0] : ""; }
function handleEvents(evs, quiet = false) {
  const feed = $("#eventFeed"), log = $("#logList");
  for (const e of evs) {
    if (e.example) {
      caseCount[e.example] = (caseCount[e.example] || 0) + 1;
      caseLast[e.example] = e.t;
      if (e.vid) (caseVeh[e.example] = caseVeh[e.example] || new Set()).add(e.vid);
    }
    ALL_EVENTS.push(e);
    if (ALL_EVENTS.length > 3000) ALL_EVENTS.splice(0, ALL_EVENTS.length - 3000);
    if (quiet) continue;
    if (e.kind === "arrive") flashArrival(e.vid);
    if (e.example && e.vid) floatAt(e.vid, `${e.example} ${shortName(e.example)}`, PCOL[e.pattern]);
    if (e.kind !== "world" || /긴급제동/.test(e.msg)) {
      feed.prepend(evLine(e));
      while (feed.children.length > 100) feed.lastChild.remove();
    }
    if (!logFilter || e.pattern === logFilter) {
      log.prepend(evLine(e));
      while (log.children.length > 600) log.lastChild.remove();
    }
    if (e.example && e.pattern) toast(e);
  }
  if (evs.some((e) => e.example)) scheduleCases();
}
function toast(e) {
  const box = $("#toastBox");
  const t = el("div", "toast", `<b style="color:${PCOL[e.pattern]}">P${e.pattern} ${STATIC.patterns[e.pattern]} · ${e.example} ${shortName(e.example)}</b><br>${e.vid ? `V${e.vid} — ` : ""}${e.msg}`);
  t.style.borderLeftColor = PCOL[e.pattern];
  box.appendChild(t);
  while (box.children.length > 4) box.firstChild.remove();
  setTimeout(() => t.remove(), 5000);
}
function resetEvents() {
  for (const o of [caseCount, caseLast, caseVeh]) for (const k in o) delete o[k];
  ALL_EVENTS.length = 0; lastRoundShown = -1;
  for (const id of ["#roundFeed", "#eventFeed", "#logList", "#toastBox"]) $(id).innerHTML = "";
}

// ================================================================== 유스케이스 표 (갱신은 1초에 한 번)
let casesTimer = null;
function scheduleCases() { if (!casesTimer) casesTimer = setTimeout(() => { casesTimer = null; renderCases(); }, 1000); }
function renderCases(nowT = Date.now() / 1000) {
  const total = Object.keys(caseCount).length;
  const cov = Object.fromEntries((STATIC.coverage || []).map((c) => [c.id, c]));
  const okN = (STATIC.coverage || []).filter((c) => c.ok).length;
  let html = `<p class="muted">34개 유스케이스 중 이번 실행에서 <b style="color:#f1f5ff">${total}</b>개가 일어났습니다.
    지금 맵(<b>${MAP?.name || ""}</b>)에서 일으킬 수 있는 것 <b style="color:#4ade80">${okN}/34</b>. 행을 누르면 맵에서 그 장소로 이동합니다.</p>`;
  for (const [p, name] of Object.entries(STATIC.patterns)) {
    const rows = STATIC.usecases.filter((u) => u[0].startsWith(p + "-"));
    const sum = rows.reduce((a, u) => a + (caseCount[u[0]] || 0), 0);
    html += `<div class="ptitle"><span class="pt" style="background:${PCOL[p]}">P${p}</span>${name}<span class="muted small">${sum}회</span></div>
      <div class="pdesc">${PDESC[p]}</div>
      <table class="cases"><tr><th style="width:46px">id</th><th>예시</th><th>근거</th><th>맵·설정에서</th><th style="width:46px">이 맵</th><th style="width:56px">발생</th><th style="width:90px">차량</th></tr>`;
    for (const [id, ex, ev, where] of rows) {
      const n = caseCount[id] || 0, recent = caseLast[id] && nowT - caseLast[id] < 6;
      html += `<tr class="${recent ? "recent" : n ? "hit" : ""}" data-id="${id}"><td><b>${id}</b></td><td>${ex}</td><td class="muted">${ev}</td>
        <td>${where}</td><td title="${cov[id]?.how || ""}">${cov[id] ? (cov[id].ok ? "✅" : "❌") : ""}</td><td class="cnt">${n || "-"}</td><td>${caseVeh[id] ? [...caseVeh[id]].sort((a, b) => a - b).map((v) => "V" + v).join(" ") : ""}</td></tr>`;
    }
    html += "</table>";
  }
  const box = $("#caseTable");
  box.innerHTML = html;
  box.querySelectorAll("tr[data-id]").forEach((tr) => tr.onclick = () => focusOn(focusPoint(tr.dataset.id)));
}
function buildLogFilter() {
  const box = $("#logFilter");
  const mk = (p, text, col) => {
    const b = el("button", "btn small", text);
    if (col) b.style.borderColor = col;
    b.onclick = () => {
      logFilter = p;
      const log = $("#logList");
      log.innerHTML = "";
      for (const e of ALL_EVENTS.slice(-600)) if (!p || e.pattern === p) log.prepend(evLine(e));
    };
    box.appendChild(b);
  };
  mk(null, "전체");
  for (const [p, n] of Object.entries(STATIC.patterns)) mk(Number(p), `P${p} ${n}`, PCOL[p]);
}

// ================================================================== 실행 제어
async function control(action, extra = {}) {
  const r = await (await fetch("/api/control", { method: "POST", body: JSON.stringify({ action, ...extra }) })).json();
  if (r.config) CFG = r.config;
  return r;
}
async function afterStart() {
  exitReplay(false);
  evOffset = 0;
  resetEvents();
  clearCars();
  STATIC = await (await fetch("/api/static")).json();
  if (!MAP || STATIC.map_id !== MAP_ID) { MAP_ID = STATIC.map_id; buildScene(STATIC.map, STATIC.layout); }
  buildVehForm(); buildGlobalForm(); renderMethodChip(); renderCases();
}
$("#btnStart").onclick = async () => { await control("start"); await afterStart(); };
$("#btnStop").onclick = () => control("stop");
$("#btnDown").onclick = () => {
  const s = CFG.server.pause_s;
  if (confirm(`집계 서버를 ${s}초 동안 멈췄다가 복구합니다 (8-1). 그동안 차량은 값을 보관했다가 복구 후 한꺼번에 보냅니다 (5-3).`)) control("server_down", { seconds: s });
};
$("#btnReset").onclick = async () => { await control("reset_config"); buildGlobalForm(); buildVehForm(); renderMethodChip(); };
$("#btnView").onclick = fitView;
$("#btnChase").onclick = () => setChase(!CHASE);
$("#optCells").onchange = (e) => layers.cells.forEach((m) => (m.visible = e.target.checked));
$("#optZones").onchange = (e) => layers.zones.forEach((m) => (m.visible = e.target.checked));
$("#optPlaces").onchange = (e) => layers.placeLabels.forEach((m) => (m.visible = e.target.checked));
function renderMethodChip() { $("#methodChip").textContent = STATIC.methods[CFG.fl.method]?.name || CFG.fl.method; }

const PRESET_ALL = {
  fl: { tau: 5 },
  net: { frag_fail: 0.03, doppler_fail: 0.25, region_instability: 0.6, cell_capacity: 1, tdma_groups: 2, tdma_slot_s: 3 },
  energy: { budget_j: 400, min_energy_j: 120, upload_j: 20 },
  world: { day_minutes: 20, ota_prob: 0.5, pedestrian_scale: 2, weather_on: true },
  server: { p7_window: 10 },
  vehicle_default: { crash_prob: 0.05 },
  vehicles: {
    "1": { min_data: 300, data_rate_per_s: 3 },                 // 3-2 새 데이터 없음
    "2": { store_forward: true, energy_gate: false, battery_scale: 0.1 },    // 5-1·5-2 보관 후 일괄, 2-6 전송 중 방전 (배터리가 거의 바닥인 택시: 학습 한 번 뒤 전송하다 꺼짐)
    "3": { lr_override: 0.02, energy_gate: false, battery_scale: 0.25 },    // 6-3 학습률 오류 · 1-3 학습 중 방전 (집에서 충전 후 복귀)
    "4": { store_forward: true },                               // 통과 차량: 5-1 터널 보관
    "5": { wifi_only: true },                                   // 3-3 Wi-Fi에서만
    "6": { backdoor_boost: 0.5, battery_scale: 0.5, store_forward: true },   // 6-1 악의적 조작 · 3-1 작은 배터리 → 충전소에서 회복 · 5-2 셀 가장자리 보류
    "7": { emergency_rate: 3, safety_preempt_prob: 0.5 },       // 1-4·4-5 긴급제동 (어린이 보호구역을 지나는 주민 차량)
    "8": { sensor_fault_classes: "3,8", sensor_fault_level: 0.6 },   // 6-2 센서 고장 (재시작) · 터널을 지나는 통과 차량 → 2-5
  },
};
const PRESET_CLEAN = {
  fl: { tau: 9 },
  net: { frag_fail: 0.01, doppler_fail: 0.15, region_instability: 0.3, cell_capacity: 2, tdma_groups: 1 },
  energy: { budget_j: 1000, min_energy_j: 100, upload_j: 10 },
  world: { day_minutes: 30, ota_prob: 0.4, pedestrian_scale: 1 },
  vehicle_default: { crash_prob: 0.02 },
};
$("#presetAll").onclick = async () => {
  await postCfg(PRESET_ALL);
  $("#presetNote").textContent = "적용됨. 센서 고장(V7)·τ·감시 창은 다음 시작부터 → ▶ 시작을 다시 누르세요. 8-1·5-3은 '서버 장애' 버튼으로 일으킵니다. 하루는 20분.";
  buildGlobalForm(); buildVehForm();
};
$("#presetClean").onclick = async () => {
  const clear = {};
  for (const k of Object.keys(CFG.vehicles || {})) clear[k] = null;
  await postCfg({ ...PRESET_CLEAN, vehicles: clear });
  $("#presetNote").textContent = "장애 설정을 껐습니다 (주행 환경에 따른 끊김은 그대로).";
  buildGlobalForm(); buildVehForm();
};

// ================================================================== 저장·맵
async function loadSaves() {
  const r = await (await fetch("/api/saves")).json();
  const box = $("#savesList");
  box.innerHTML = r.saves.length ? "" : "<span class='muted small'>저장한 상태가 없습니다.</span>";
  for (const s of r.saves) {
    const it = el("div", "item", `<span><b>${s.name || s.id}</b> · ${s.round ?? "-"}라운드 · ${s.method || ""} · ${s.saved ? fmtT(s.saved) : ""}</span>`);
    const b = el("button", "btn small", "불러오기");
    b.onclick = async () => { await control("load", { id: s.id }); await afterStart(); document.querySelector('[data-tab="map"]').click(); };
    it.appendChild(b);
    box.appendChild(it);
  }
  renderMapCards();
  $("#mapDownload").href = "data:application/json;charset=utf-8," + encodeURIComponent(JSON.stringify(STATIC.map, null, 2));
  $("#mapDownload").download = `${CFG.world.map || "map"}.json`;
  if (LAST?.run) $("#btnExport").href = `/api/export?run=${encodeURIComponent(LAST.run)}`;
}
$("#btnSave").onclick = async () => {
  const r = await control("save", { name: $("#saveName").value || "상태" });
  $("#mapNote").textContent = r.id ? `저장됨: ${r.id}` : "실행 중인 시뮬레이션이 없습니다.";
  loadSaves();
};
// 맵 고르기: 맵마다 34개 유스케이스를 일으킬 조건(장소·구역)을 갖췄는지 표시
async function renderMapCards() {
  const info = (await (await fetch("/api/maps")).json()).info;
  const box = $("#mapCards");
  box.innerHTML = "";
  const curId = CFG.world.map || "default";
  for (const m of info) {
    const cur = m.id === curId;
    const c = el("div", "mapcard" + (cur ? " cur" : ""), `<div><b>${m.name}</b> <span class="muted small">${(m.size || []).join(" × ")} m · ${m.id}</span></div>
      <div class="small">${m.desc || ""}</div>
      <div class="cov ${m.ok === 34 ? "ok" : "bad"}">유스케이스 조건 ${m.ok}/34${m.missing.length ? " · 없음: " + m.missing.join(", ") : " ✓"}</div>`);
    const b = el("button", "btn small" + (cur ? "" : " primary"), cur ? "사용 중" : "이 맵 사용");
    b.disabled = cur;
    b.onclick = async () => {
      await postCfg({ world: { map: m.id } });
      const running = LAST?.procs?.fl === "running";
      if (!running) {
        STATIC = await (await fetch("/api/static")).json();
        MAP_ID = STATIC.map_id; clearCars(); buildScene(STATIC.map, STATIC.layout); renderCases();
      }
      $("#mapNote").textContent = running ? `맵 '${m.name}' — 지금 실행이 끝나고 다음 ▶ 시작부터 적용됩니다.` : `맵 '${m.name}'으로 바꿨습니다. ▶ 시작을 누르세요.`;
      renderMapCards();
    };
    c.appendChild(b);
    box.appendChild(c);
  }
  const cov = STATIC.coverage || [];
  $("#mapCoverage").innerHTML = `<div class="fgroup">지금 맵에서 유스케이스를 일으키는 곳 (${cov.filter((x) => x.ok).length}/34)</div>` +
    `<table class="covtab">${cov.map((x) => `<tr><td>${x.ok ? "✅" : "❌"}</td><td><b>${x.id}</b></td><td>${x.how}</td></tr>`).join("")}</table>` +
    ((STATIC.problems || []).length ? `<p class="bad small">맵 문제: ${STATIC.problems.join(" / ")}</p>` : "");
}
$("#mapFile").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  let m;
  try { m = JSON.parse(await f.text()); } catch { $("#mapNote").textContent = "JSON 형식이 아닙니다."; return; }
  const r = await (await fetch("/api/map", { method: "POST", body: JSON.stringify({ name: f.name.replace(/\.json$/, ""), map: m }) })).json();
  $("#mapNote").textContent = r.ok ? `맵 '${r.name}' 저장됨${r.missing?.length ? ` (조건 없는 유스케이스: ${r.missing.join(", ")})` : " (34/34)"} — 아래에서 '이 맵 사용'을 누르세요.` : `맵 오류: ${r.errors.join(", ")}`;
  loadSaves();
};

// ================================================================== 기록·비교·다시 보기
let RUNS = [];
const CMP_SEL = new Set();
async function loadRuns() {
  RUNS = (await (await fetch("/api/runs")).json()).runs;
  const t = $("#runsTable");
  t.innerHTML = "<tr><th></th><th>실행</th><th>학습 방식</th><th>시드</th><th>맵</th><th>K</th><th>라운드</th><th>정확도</th><th>사건</th><th></th></tr>";
  for (const r of RUNS) {
    const tr = el("tr");
    tr.innerHTML = `<td><input type="checkbox" ${CMP_SEL.has(r.run) ? "checked" : ""}></td><td>${r.run}</td>
      <td>${STATIC.methods[r.method]?.name || r.method || "-"}</td><td>${r.seed ?? "-"}</td><td>${r.map || "-"}</td><td>${r.K ?? "-"}</td>
      <td>${r.rounds ?? "-"}</td><td>${r.acc ?? "-"}</td><td>${r.events}</td><td></td>`;
    tr.querySelector("input").onchange = (e) => { e.target.checked ? CMP_SEL.add(r.run) : CMP_SEL.delete(r.run); drawCompare(); };
    const cell = tr.lastChild;
    const b = el("button", "btn small", "다시 보기");
    b.onclick = () => startReplay(r.run);
    const a = el("a", "btn small", "내보내기");
    a.href = `/api/export?run=${encodeURIComponent(r.run)}`;
    cell.append(b, " ", a);
    t.appendChild(tr);
  }
  const sel = $("#ablMethod");
  if (!sel.children.length) for (const [k, m] of Object.entries(STATIC.methods)) sel.appendChild(new Option(m.name, k));
  drawCompare();
}
const CMP_COL = ["#5b9cff", "#f472b6", "#4ade80", "#facc15", "#fb923c", "#c084fc", "#38bdf8", "#f87171"];
function drawCompare() {
  const [ctx, W, H] = canvasCtx($("#cmpChart"), 260);
  ctx.strokeStyle = "#2a3b60";
  for (let y = 0; y <= 4; y++) { ctx.beginPath(); ctx.moveTo(0, (H * y) / 4); ctx.lineTo(W, (H * y) / 4); ctx.stroke(); }
  const sel = RUNS.filter((r) => CMP_SEL.has(r.run));
  const maxR = Math.max(10, ...sel.flatMap((r) => r.curve.map((c) => c[0])));
  sel.forEach((r, i) => {
    ctx.strokeStyle = CMP_COL[i % CMP_COL.length]; ctx.lineWidth = 2.2 * devicePixelRatio; ctx.beginPath();
    r.curve.forEach(([rd, acc], j) => { const x = (rd / maxR) * W, y = H - (acc / 100) * H; j ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
    ctx.fillStyle = CMP_COL[i % CMP_COL.length];
    ctx.fillText(`${STATIC.methods[r.method]?.name || r.method} · 시드 ${r.seed} · ${r.run}`, 8 * devicePixelRatio, (16 + i * 16) * devicePixelRatio);
  });
  if (!sel.length) { ctx.fillStyle = "#a3b3d1"; ctx.fillText("아래 목록에서 실행을 체크하면 정확도 곡선을 겹쳐 그립니다 (가로 = 라운드)", 10 * devicePixelRatio, 20 * devicePixelRatio); }
}
$("#btnRunsRefresh").onclick = loadRuns;
$("#btnAblation").onclick = async () => {
  const m = $("#ablMethod").value;
  if (!confirm(`지금 설정·시드 그대로 '${STATIC.methods[m].name}'(으)로 새로 실행합니다.`)) return;
  if (LAST?.run) CMP_SEL.add(LAST.run);
  await control("ablation", { method: m });
  await afterStart();
};
$("#importFile").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const r = await (await fetch("/api/import", { method: "POST", body: await f.arrayBuffer() })).json();
  if (r.ok) { await loadRuns(); alert(`불러옴: ${r.run} — '다시 보기'로 재생할 수 있습니다.`); }
};

async function startReplay(run) {
  const d = await (await fetch(`/api/replay?run=${encodeURIComponent(run)}`)).json();
  if (!d.world?.length) { alert("이 실행에는 주행 기록이 없습니다."); return; }
  REPLAY = { run, ...d, idx: 0, playing: true, acc: 0 };
  document.body.classList.add("replaying");
  $("#replayBar").classList.remove("hidden");
  $("#replayName").textContent = `${run} · ${STATIC.methods[d.config?.fl?.method]?.name || ""}`;
  const slider = $("#rpSlider");
  slider.max = d.world.length - 1; slider.value = 0;
  const mapName = d.config?.world?.map || "default";
  if (mapName !== MAP_ID) {
    const st = await (await fetch(`/api/static?map=${encodeURIComponent(mapName)}`)).json();
    MAP_ID = st.map_id; buildScene(st.map, st.layout);
  }
  clearCars(); resetEvents();
  document.querySelector('[data-tab="map"]').click();
  seekReplay(0);
}
function seekReplay(i) {
  const R = REPLAY;
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
      badges: [flags & 2 && flags & 1 ? "🅿" : "", flags & 4 ? "⚡" : "", flags & 8 ? "🔧" : "", flags & 16 ? "⚠" : "", `${kmh}km/h`].join("") });
  }
  const sigs = {};
  for (const [id, s] of Object.entries(f.s || {})) sigs[id] = [s[0], s[1]];
  updateSignalsAndPeds(sigs, f.p);
  // 그 시점까지의 라운드·사건
  const hist = (R.server?.history || []).filter((h) => h.t <= f.t);
  lastRoundShown = -1; $("#roundFeed").innerHTML = "";
  renderFL({ ...(R.server || {}), history: hist, round: hist.length ? hist[hist.length - 1].round : 0, phase: "aggregated" }, 0);
  for (const o of [caseCount, caseLast, caseVeh]) for (const k in o) delete o[k];
  ALL_EVENTS.length = 0;
  $("#eventFeed").innerHTML = ""; $("#logList").innerHTML = "";
  const upto = R.events.filter((e) => e.t <= f.t);
  handleEvents(upto, true);
  for (const e of upto.slice(-80)) if (e.kind !== "world" || /긴급제동/.test(e.msg)) $("#eventFeed").prepend(evLine(e));
  renderCases(f.t);
}
$("#rpSlider").oninput = (e) => seekReplay(Number(e.target.value));
$("#rpPlay").onclick = () => { REPLAY.playing = !REPLAY.playing; $("#rpPlay").textContent = REPLAY.playing ? "❚❚" : "▶"; };
$("#rpExit").onclick = () => exitReplay(true);
function exitReplay(resume) {
  if (!REPLAY) return;
  REPLAY = null;
  document.body.classList.remove("replaying");
  $("#replayBar").classList.add("hidden");
  clearCars();
  if (MAP_ID !== STATIC.map_id) { MAP_ID = STATIC.map_id; buildScene(STATIC.map, STATIC.layout); }
  if (resume) { evOffset = 0; resetEvents(); }
}
setInterval(() => {
  if (!REPLAY || !REPLAY.playing) return;
  const sp = Number($("#rpSpeed").value);
  REPLAY.acc += sp * 0.5;                       // 0.5초마다, 기록은 1초 간격
  const step = Math.floor(REPLAY.acc);
  if (step >= 1) { REPLAY.acc -= step; seekReplay(REPLAY.idx + step); if (REPLAY.idx >= REPLAY.world.length - 1) REPLAY.playing = false; }
}, 500);

// ================================================================== 실시간 갱신
function renderRun() {
  const procs = LAST.procs || {};
  const running = procs.fl === "running";
  const chip = $("#runChip");
  chip.className = "chip " + (LAST.server_down_left > 0 ? "warn" : running ? "run" : LAST.note ? "bad" : "");
  chip.textContent = LAST.server_down_left > 0 ? "서버 장애 중" : running ? "학습 실행 중" : LAST.note ? "학습 종료" : "정지";
  const e = LAST.world?.elapsed;
  $("#runInfo").textContent = (LAST.run ? `실행 ${LAST.run}` : "") + (e ? ` · ${Math.floor(e / 60)}분 ${Math.floor(e % 60)}초` : "") + (LAST.note ? ` · ${LAST.note}` : "");
  if (weatherGroup) { weatherGroup.visible = CFG.world.weather_on; weatherGroup.userData.label.visible = CFG.world.weather_on && $("#optPlaces").checked; }
  const w = LAST.world;
  const icon = { night: "🌙", am: "🌅", day: "☀️", pm: "🌇", evening: "🌆" }[w?.period] || "🕒";
  $("#clock").innerHTML = w?.tod !== undefined ? `${icon} <b>${fmtH(w.tod)}</b> · ${w.day}일차 · ${w.period_name} 시간대` : "🕒 -";
}
async function poll() {
  if (!REPLAY) {
    try {
      const r = await (await fetch(`/api/state?ev=${evOffset}`)).json();
      LAST = r; CFG = r.config; evOffset = r.ev;
      renderRun(); renderMethodChip();
      if (r.world?.vehicles) {
        for (let v = 1; v <= CFG.fl.K; v++) { const s = liveCarState(v); if (s) drawCar(v, s); }
        for (const k of Object.keys(CARS)) if (Number(k) > CFG.fl.K) removeCar(k);
        updateSignalsAndPeds(r.world.signals, r.world.peds);
        applyTime(TIME_FIX ?? r.world.tod);
      }
      renderVehPicker(); renderVehInfo();
      renderFL(r.server, r.server_down_left);
      handleEvents(r.events || []);
    } catch (e) { console.error(e); }
  }
  setTimeout(poll, 400);
}

(async function main() {
  STATIC = await (await fetch("/api/static")).json();
  CFG = (await (await fetch("/api/state?ev=999999999")).json()).config;
  MAP_ID = STATIC.map_id;
  buildScene(STATIC.map, STATIC.layout);
  applyTime(CFG.world.start_hour ?? 12);
  buildLegends(); buildGlobalForm(); buildVehForm(); buildLogFilter(); renderCases(); renderMethodChip();
  resize();
  requestAnimationFrame(frame);
  poll();
})();
// 화면 점검용 (브라우저 콘솔): __sim.applyTime(12), __sim.look(x, z, 거리)
window.__sim = {
  applyTime, focusOn, setChase, selectVehicle,
  fixTime: (h) => { TIME_FIX = h; applyTime(h); },
  loadMap: async (id) => { const st = await (await fetch(`/api/static?map=${id}`)).json(); clearCars(); MAP_ID = st.map_id; buildScene(st.map, st.layout); },
  look: (x, z, d = 60, h = 0.6) => { setChase(false); controls.target.copy(P(x, z)); camera.position.copy(P(x - d * 0.6, z + d * 0.8, d * h)); controls.update(); },
};
