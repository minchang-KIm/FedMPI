import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";

// ================================================================== 상수
const STATE = {
  idle: ["대기", "#e2e8f0"], training: ["학습", "#60a5fa"], uploading: ["전송", "#fb923c"],
  waiting: ["대기열", "#facc15"], queued: ["보관", "#c084fc"], skipped: ["미참여", "#94a3b8"],
  dead: ["끊김", "#f87171"], excluded: ["영구 제외", "#b91c1c"], absent: ["맵 밖", "#475569"],
};
const PCOL = { 1: "#f87171", 2: "#fb923c", 3: "#cbd5e1", 4: "#facc15", 5: "#c084fc", 6: "#f472b6", 7: "#4ade80", 8: "#38bdf8" };
const PDESC = { // 서버에서 보는 모습 · 서버 대응
  1: "아무 응답 없음 → 해당 차량 제외", 2: "일부 조각만 도착 → 폐기 (SASAFL은 조각이 없어 패턴 1처럼 보임)",
  3: "이번 라운드 미참여 → 복귀 시 최신 글로벌 모델 전달", 4: "낮은 버전의 값 도착 → SASAFL은 버리지 않고 감쇄해 반영",
  5: "한 차량에서 오래된 값 여러 개 → 개별 처리 (SASAFL은 버퍼 1칸이라 덮어씀)", 6: "오류 있는 값을 계속 보냄 → 대응 없음",
  7: "같은 차량만 계속 참여 → epoch 축소(SASAFL)·CFCFM(SAFA)", 8: "서버 장애·무한 대기·성능 지속 감소 → 복구·시간 제한·강제 갱신",
};
const FOCUS = {
  "1-2": "service", "1-4": "X1", "1-5": "home", "2-1": [1000, 300], "2-2": [1450, 300], "2-4": [1100, 900],
  "2-5": "tunnel", "3-2": "gas", "3-3": "wifi_pub", "4-2": "congest", "4-4": "weather", "4-5": "X1", "4-7": [650, 900],
  "5-1": "shadow", "5-3": "datacenter", "8-1": "datacenter", "8-2": "datacenter",
};
const $ = (s) => document.querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; return e; };
const fmtT = (t) => new Date(t * 1000).toLocaleTimeString("ko-KR", { hour12: false });
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

let STATIC = null, CFG = null, LAST = null, MAP = null, evOffset = 0, selected = 1, lastRoundShown = -1;
let REPLAY = null;                   // 다시 보기 상태
const caseCount = {}, caseLast = {}, caseVeh = {};
const ALL_EVENTS = [];
let logFilter = null;

// ================================================================== 3D 장면
const holder = $("#map3d");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
holder.appendChild(renderer.domElement);
const labelRenderer = new CSS2DRenderer();
Object.assign(labelRenderer.domElement.style, { position: "absolute", top: "0", pointerEvents: "none" });
holder.appendChild(labelRenderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color("#0a1222");
const camera = new THREE.PerspectiveCamera(38, 1, 5, 12000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.46;
controls.minDistance = 120;
controls.maxDistance = 3400;
controls.screenSpacePanning = false;
scene.add(new THREE.HemisphereLight("#dbe7ff", "#1a2433", 1.15));
const sun = new THREE.DirectionalLight("#ffffff", 1.25);
sun.position.set(-600, 1400, 800);
scene.add(sun);

let W2 = 1000, H2 = 700;
const P = (x, z, y = 0) => new THREE.Vector3(x - W2, y, z - H2);
const layers = { cells: [], placeLabels: [] };
let mapGroup = null;
const ZONE = {}, PLACE = {}, CELL = {}, SIGNAL = {}, CROSS = {};
let rain = null, weatherGroup = null, pedMesh = null;
const MAT = {};
const mat = (color, opts = {}) => {
  const key = color + JSON.stringify(opts);
  return MAT[key] || (MAT[key] = new THREE.MeshStandardMaterial({ color, roughness: 0.85, ...opts }));
};

function addLabel(group, text, cls, pos, layer = "placeLabels") {
  const o = new CSS2DObject(el("div", "lbl " + (cls || ""), text));
  o.position.copy(pos);
  group.add(o);
  layers[layer].push(o);
  return o;
}
function flat(group, geom, color, opacity, y, x, z, layer) {
  const m = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthWrite: false, side: THREE.DoubleSide }));
  m.rotation.x = -Math.PI / 2;
  m.position.copy(P(x, z, y));
  group.add(m);
  if (layer) layers[layer].push(m);
  return m;
}
function box(group, w, h, d, color, x, z, y = 0, opts) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), opts ? new THREE.MeshStandardMaterial({ color, roughness: 0.8, ...opts }) : mat(color));
  m.position.copy(P(x, z, y + h / 2));
  group.add(m);
  return m;
}

function disposeGroup(g) {
  g.traverse((o) => {
    if (o.isCSS2DObject && o.element) o.element.remove();
    if (o.geometry) o.geometry.dispose();
    if (o.material && !Object.values(MAT).includes(o.material)) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose());
  });
  scene.remove(g);
}

function buildScene(M) {
  if (mapGroup) disposeGroup(mapGroup);
  for (const k of Object.keys(layers)) layers[k] = [];
  for (const o of [ZONE, PLACE, CELL, SIGNAL, CROSS]) for (const k in o) delete o[k];
  rain = null; weatherGroup = null; pedMesh = null;
  MAP = M;
  const [MW, MH] = M.size;
  W2 = MW / 2; H2 = MH / 2;
  const g = (mapGroup = new THREE.Group());
  scene.add(g);
  const lw = M.lane_width || 7;
  flat(g, new THREE.PlaneGeometry(MW + 300, MH + 300), "#11281f", 1, -1, MW / 2, MH / 2);
  const grid = new THREE.GridHelper(Math.max(MW, MH) + 400, 24, "#1d3d30", "#173326");
  grid.position.y = -0.5;
  g.add(grid);
  // 도로: 2차선 (가운데 노란 점선, 가장자리 흰 선)
  for (const rd of M.roads) {
    for (let i = 0; i < rd.pts.length - 1; i++) {
      const [ax, az] = rd.pts[i], [bx, bz] = rd.pts[i + 1];
      const len = Math.hypot(bx - ax, bz - az), rot = -Math.atan2(bz - az, bx - ax);
      const road = new THREE.Mesh(new THREE.BoxGeometry(len + 2 * lw + 6, 1, 2 * lw + 6), mat(rd.id === "highway" ? "#3d465b" : "#323a4c"));
      road.position.copy(P((ax + bx) / 2, (az + bz) / 2, 0.5));
      road.rotation.y = rot;
      g.add(road);
      for (const side of [-1, 1]) {
        const edge = new THREE.Mesh(new THREE.BoxGeometry(len, 0.3, 0.8), mat("#e5e7eb"));
        const nx = -(bz - az) / len, nz = (bx - ax) / len;
        edge.position.copy(P((ax + bx) / 2 + nx * side * (lw + 2), (az + bz) / 2 + nz * side * (lw + 2), 1.1));
        edge.rotation.y = rot;
        g.add(edge);
      }
      for (let s = 10; s < len - 10; s += 26) {
        const t = s / len;
        const d = new THREE.Mesh(new THREE.BoxGeometry(12, 0.3, 0.9), mat("#facc15"));
        d.position.copy(P(ax + (bx - ax) * t, az + (bz - az) * t, 1.1));
        d.rotation.y = rot;
        g.add(d);
      }
    }
    const mid = rd.pts[Math.floor((rd.pts.length - 1) / 2)];
    addLabel(g, `${rd.name} · ${rd.speed} km/h`, "", P(mid[0], mid[1] + 30, 4));
  }
  // 셀
  for (const c of M.cells) {
    const [x, z] = c.pos;
    flat(g, new THREE.CircleGeometry(c.r, 72), c.color || "#3b82f6", 0.07, 1.3, x, z, "cells");
    flat(g, new THREE.RingGeometry(c.r - 4, c.r, 96), c.color || "#3b82f6", 0.7, 1.5, x, z, "cells");
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(2.5, 5, 80, 8), mat("#cbd5e1"));
    mast.position.copy(P(x, z, 40));
    const head = new THREE.Mesh(new THREE.SphereGeometry(7, 16, 12), new THREE.MeshStandardMaterial({ color: c.color, emissive: c.color, emissiveIntensity: 0.9 }));
    head.position.copy(P(x, z, 82));
    g.add(mast, head);
    CELL[c.id] = { ...c, top: P(x, z, 84) };
    addLabel(g, `📡 ${c.name} · 반경 ${c.r} m`, "cell", P(x, z, 112));
  }
  if (M.region_border_x) {
    const bx = M.region_border_x;
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([P(bx, -60, 3), P(bx, MH + 60, 3)]),
      new THREE.LineDashedMaterial({ color: "#fbbf24", dashSize: 24, gapSize: 16 }));
    line.computeLineDistances();
    g.add(line);
    addLabel(g, "W 권역 ◀ 권역 경계 ▶ E 권역", "zone", P(bx, -40, 10));
  }
  // 구역
  for (const z of M.zones) {
    ZONE[z.id] = z;
    if (z.kind === "tunnel") {
      const [x0, z0, x1, z1] = z.rect;
      box(g, x1 - x0, 32, z1 - z0 + 24, "#64748b", (x0 + x1) / 2, (z0 + z1) / 2, 0, { transparent: true, opacity: 0.8 });
      box(g, 14, 38, z1 - z0 + 34, "#334155", x0, (z0 + z1) / 2);
      box(g, 14, 38, z1 - z0 + 34, "#334155", x1, (z0 + z1) / 2);
      addLabel(g, "🚇 터널 (무선 단절)", "zone", P((x0 + x1) / 2, z0 - 40, 52));
    } else if (z.kind === "shadow") {
      const [x0, z0, x1, z1] = z.rect;
      for (let x = x0 + 18; x < x1 - 10; x += 42)
        for (const [za, zb] of [[z0 + 10, 1180], [1222, z1 - 4]])
          for (let zz = za + 14; zz < zb; zz += 40) box(g, 30, 50 + ((x * 7 + zz * 3) % 120), 28, "#3b4a63", x, zz);
      addLabel(g, "🏢 빌딩 숲 (음영지역)", "zone", P((x0 + x1) / 2, z0 - 20, 175));
    } else if (z.rect) {
      const [x0, z0, x1, z1] = z.rect;
      const col = { congestion: "#f97316", school: "#facc15", wifi: "#22d3ee" }[z.kind] || "#94a3b8";
      flat(g, new THREE.PlaneGeometry(x1 - x0, z1 - z0), col, 0.22, 1.8, (x0 + x1) / 2, (z0 + z1) / 2);
      const pts = [P(x0, z0, 3), P(x1, z0, 3), P(x1, z1, 3), P(x0, z1, 3), P(x0, z0, 3)];
      g.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: col })));
      const icon = { congestion: "🚦", school: "🏫", wifi: "📶" }[z.kind] || "";
      addLabel(g, `${icon} ${z.name}${z.speed ? ` · ${z.speed} km/h` : ""}`, "zone", P((x0 + x1) / 2, z0 - 16, 30));
    } else if (z.circle) {
      const [x, zz, r] = z.circle;
      weatherGroup = new THREE.Group();
      const disc = new THREE.Mesh(new THREE.CircleGeometry(r, 64), new THREE.MeshBasicMaterial({ color: "#38bdf8", transparent: true, opacity: 0.1, depthWrite: false }));
      disc.rotation.x = -Math.PI / 2;
      disc.position.copy(P(x, zz, 2));
      const N = 700, pos = new Float32Array(N * 3);
      for (let i = 0; i < N; i++) {
        const a = Math.random() * Math.PI * 2, rr = Math.sqrt(Math.random()) * r * 0.9;
        pos[i * 3] = x - W2 + Math.cos(a) * rr; pos[i * 3 + 1] = Math.random() * 215; pos[i * 3 + 2] = zz - H2 + Math.sin(a) * rr;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      rain = new THREE.Points(geo, new THREE.PointsMaterial({ color: "#7dd3fc", size: 3, transparent: true, opacity: 0.7 }));
      weatherGroup.add(disc, rain);
      g.add(weatherGroup);
      weatherGroup.userData.label = addLabel(g, "🌧 강우 구역 (대역폭↓)", "zone", P(x, zz - r + 10, 240));
    }
  }
  // 장소
  for (const p of M.places) {
    PLACE[p.id] = p;
    const [x, z] = p.pos;
    const wifi = p.wifi ? " 📶" : "";
    if (p.kind === "home") {
      for (let i = -1; i <= 1; i++) {
        box(g, 34, 22, 30, "#e2e8f0", x + i * 60, z + 52);
        const roof = new THREE.Mesh(new THREE.ConeGeometry(28, 18, 4), mat("#b45309"));
        roof.position.copy(P(x + i * 60, z + 52, 31));
        roof.rotation.y = Math.PI / 4;
        g.add(roof);
      }
      addLabel(g, `🏠 ${p.name} (시동 꺼짐)${wifi}`, "place", P(x, z + 92, 50));
    } else if (p.kind === "gas") {
      box(g, 60, 4, 40, "#16a34a", x - 70, z, 24);
      for (const [dx, dz] of [[-26, -16], [26, -16], [-26, 16], [26, 16]]) box(g, 3, 24, 3, "#d1d5db", x - 70 + dx, z + dz);
      addLabel(g, `⚡ ${p.name} (충전 중 새 데이터 없음)${wifi}`, "place", P(x - 70, z - 34, 46));
    } else if (p.kind === "service") {
      box(g, 90, 34, 50, "#1d4ed8", x, z - 56);
      addLabel(g, `🔧 ${p.name}${wifi}`, "place", P(x, z - 96, 50));
    } else if (p.kind === "server") {
      for (let i = 0; i < 4; i++) box(g, 18, 40, 26, "#0f172a", x - 36 + i * 24, z, 0, { emissive: "#1e3a8a", emissiveIntensity: 0.6 });
      const glow = new THREE.Mesh(new THREE.SphereGeometry(11, 16, 12), new THREE.MeshBasicMaterial({ color: "#60a5fa" }));
      glow.position.copy(P(x, z, 62));
      g.add(glow);
      PLACE[p.id].glow = glow;
      PLACE[p.id].top = P(x, z, 62);
      addLabel(g, `🖥 ${p.name}`, "place", P(x, z - 32, 84));
    } else if (p.kind === "gate") {
      const dx = x < 10 ? 12 : -12;
      box(g, 6, 40, 6, "#a3a3a3", x + dx, z - 24); box(g, 6, 40, 6, "#a3a3a3", x + dx, z + 24); box(g, 6, 6, 54, "#a3a3a3", x + dx, z, 40);
      addLabel(g, x < 10 ? "➡ 진입 게이트" : "이탈 게이트 ➡", "place", P(x + (x < 10 ? 70 : -60), z - 40, 50));
    }
  }
  // 신호등: 기둥 + 동서(x)·남북(z) 신호 두 개
  for (const s of M.signals || []) {
    const [x, z] = s.pos;
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(1.5, 1.5, 26, 6), mat("#9ca3af"));
    pole.position.copy(P(x + 14, z - 14, 13));
    g.add(pole);
    const lamps = {};
    for (const [axis, dz] of [["x", -3], ["z", 3]]) {
      const lm = new THREE.MeshStandardMaterial({ color: "#22c55e", emissive: "#22c55e", emissiveIntensity: 1 });
      const lamp = new THREE.Mesh(new THREE.SphereGeometry(3.6, 12, 10), lm);
      lamp.position.copy(P(x + 14, z - 14 + dz, 28));
      g.add(lamp);
      lamps[axis] = lm;
    }
    SIGNAL[s.id] = { ...s, lamps };
    addLabel(g, `🚦 ${s.id}`, "sig", P(x + 14, z - 14, 40));
  }
  // 횡단보도 (얼룩무늬) + 보행자 (InstancedMesh, 개수 고정 → 메모리 일정)
  for (const c of M.crosswalks || []) {
    CROSS[c.id] = c;
    const [x, z] = c.pos;
    const horizontalRoad = isHorizontalRoad(M, c.pos);
    for (let k = -2; k <= 2; k++) {
      const stripe = new THREE.Mesh(new THREE.BoxGeometry(horizontalRoad ? 3 : 2 * lw + 6, 0.4, horizontalRoad ? 2 * lw + 6 : 3), mat("#f8fafc"));
      stripe.position.copy(P(x + (horizontalRoad ? k * 5 : 0), z + (horizontalRoad ? 0 : k * 5), 1.2));
      g.add(stripe);
    }
    addLabel(g, `🚸 ${c.name}`, "zone", P(x, z + (horizontalRoad ? -28 : 0), 18));
  }
  pedMesh = new THREE.InstancedMesh(new THREE.CylinderGeometry(2.2, 2.2, 9, 8), new THREE.MeshStandardMaterial({ color: "#ffffff" }), 96);
  pedMesh.count = 0;
  pedMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  g.add(pedMesh);
  for (const o of layers.placeLabels) o.visible = $("#optPlaces").checked;
  for (const o of layers.cells) o.visible = $("#optCells").checked;
  fitView();
}

function isHorizontalRoad(M, p) {
  let best = 1e9, hor = true;
  for (const rd of M.roads) for (let i = 0; i < rd.pts.length - 1; i++) {
    const [ax, az] = rd.pts[i], [bx, bz] = rd.pts[i + 1];
    const dx = bx - ax, dz = bz - az, L2 = dx * dx + dz * dz;
    const t = clamp(((p[0] - ax) * dx + (p[1] - az) * dz) / (L2 || 1), 0, 1);
    const d = Math.hypot(p[0] - (ax + t * dx), p[1] - (az + t * dz));
    if (d < best) { best = d; hor = Math.abs(dx) > Math.abs(dz); }
  }
  return hor;
}

function fitView() {
  const v = THREE.MathUtils.degToRad(camera.fov) / 2;
  const h = Math.atan(Math.tan(v) * camera.aspect);
  const d = Math.max((W2 + 120) / Math.tan(h), (H2 + 120) / Math.tan(v)) * 1.02;
  const dir = new THREE.Vector3(0, 0.80, 0.60).normalize();
  controls.target.set(0, 0, 30);
  camera.position.copy(controls.target).addScaledVector(dir, d);
  controls.maxDistance = d * 1.15;
  controls.update();
}

// ================================================================== 차량
const CARS = {};
const GEO = {
  newBody: new THREE.BoxGeometry(16, 5, 7), newCab: new THREE.BoxGeometry(8, 3.5, 6.2), newBar: new THREE.BoxGeometry(1, 1.4, 6.6),
  oldBody: new THREE.BoxGeometry(14, 7, 7), oldCab: new THREE.BoxGeometry(8, 5, 6.6), oldRack: new THREE.BoxGeometry(7, 1, 6),
  halo: new THREE.CircleGeometry(13, 24), brake: new THREE.BoxGeometry(0.8, 1.6, 6.8),
};
function makeCar(vid, vtype) {
  const g = new THREE.Group();
  const bodyMat = new THREE.MeshStandardMaterial({ color: "#e2e8f0", roughness: 0.45, metalness: 0.2 });
  const isNew = vtype === "new";
  const body = new THREE.Mesh(isNew ? GEO.newBody : GEO.oldBody, bodyMat);
  body.position.y = isNew ? 3.5 : 4.5;
  body.userData.vid = vid;
  const cab = new THREE.Mesh(isNew ? GEO.newCab : GEO.oldCab, mat(isNew ? "#0b2533" : "#3f3f46", isNew ? { metalness: 0.6, roughness: 0.2 } : {}));
  cab.position.set(isNew ? -1 : -1.5, isNew ? 7.6 : 10.5, 0);
  const extra = new THREE.Mesh(isNew ? GEO.newBar : GEO.oldRack, new THREE.MeshStandardMaterial(
    isNew ? { color: "#22d3ee", emissive: "#22d3ee", emissiveIntensity: 1.2 } : { color: "#a16207" }));
  extra.position.set(isNew ? 8 : -1.5, isNew ? 4 : 13.5, 0);
  const brakeMat = new THREE.MeshStandardMaterial({ color: "#7f1d1d", emissive: "#000000" });
  const brake = new THREE.Mesh(GEO.brake, brakeMat);
  brake.position.set(isNew ? -8.2 : -7.2, 4, 0);
  const haloMat = new THREE.MeshBasicMaterial({ color: "#e2e8f0", transparent: true, opacity: 0.35, depthWrite: false });
  const halo = new THREE.Mesh(GEO.halo, haloMat);
  halo.rotation.x = -Math.PI / 2;
  halo.position.y = 1.6;
  g.add(body, cab, extra, brake, halo);
  const d = el("div", "vlbl", `V${vid}`);
  const lo = new CSS2DObject(d);
  lo.position.set(0, 26, 0);
  g.add(lo);
  scene.add(g);
  const beam = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
    new THREE.LineDashedMaterial({ color: "#fb923c", dashSize: 10, gapSize: 7 }));
  beam.visible = false;
  scene.add(beam);
  return (CARS[vid] = { g, body, bodyMat, brakeMat, haloMat, d, lo, beam, vtype, target: null, heading: 0, floats: 0 });
}
function removeCar(vid) {
  const c = CARS[vid];
  if (!c) return;
  c.lo.element.remove();
  scene.remove(c.g);
  scene.remove(c.beam);
  c.beam.geometry.dispose(); c.beam.material.dispose();
  c.bodyMat.dispose(); c.brakeMat.dispose(); c.haloMat.dispose();
  delete CARS[vid];
}
function clearCars() { for (const k of Object.keys(CARS)) removeCar(k); }

function vtypeOf(vid, cfg = CFG) {
  const v = { ...(cfg.vehicle_default || {}), ...((cfg.vehicles || {})[String(vid)] || {}) };
  return v.vtype || (vid % 2 === 1 ? "new" : "old");
}

/** 차량 하나 그리기. s = {pos, heading, present, status, version, badges, emergency, cell, uploading} */
function drawCar(vid, s) {
  let car = CARS[vid];
  const vt = vtypeOf(vid);
  if (car && car.vtype !== vt) { removeCar(vid); car = null; }
  car = car || makeCar(vid, vt);
  car.g.visible = s.present !== false;
  car.lo.visible = car.g.visible && $("#optLabels").checked;
  car.target = P(s.pos[0], s.pos[1]);
  car.heading = -s.heading;
  if (!car.init) { car.g.position.copy(car.target); car.init = true; }
  const [name, col] = STATE[s.status] || STATE.idle;
  car.bodyMat.color.set(col);
  car.haloMat.color.set(col);
  car.brakeMat.emissive.set(s.braking || s.emergency > 0 ? "#ef4444" : "#000000");
  car.d.className = "vlbl" + (vid === selected ? " sel" : "") + (s.emergency > 0 ? " emerg" : "");
  car.d.style.background = col;
  car.d.innerHTML = `V${vid}<span class="ty ${vt}">${vt === "new" ? "신형" : "구형"}</span> <small>${name}${s.version !== undefined ? ` v${s.version}` : ""}</small> ${s.badges || ""}`;
  const cell = s.cell && CELL[s.cell];
  car.beam.visible = $("#optBeams").checked && s.status === "uploading" && !!cell && car.g.visible;
  if (car.beam.visible) {
    const pos = car.beam.geometry.attributes.position;
    pos.setXYZ(0, car.g.position.x, 12, car.g.position.z);
    pos.setXYZ(1, cell.top.x, cell.top.y, cell.top.z);
    pos.needsUpdate = true;
    car.beam.computeLineDistances();
  }
}

function liveCarState(vid) {
  const w = LAST?.world?.vehicles?.[vid];
  if (!w) return null;
  const c = LAST?.clients?.[vid] || {};
  const status = w.present === false ? "absent" : (c.status || "idle");
  const badges = [w.engine_off && w.present ? "🅿" : "", w.charging ? "⚡" : "", w.ota ? "🔧" : "", w.zones?.tunnel ? "🚇" : "",
    w.wifi ? "📶" : "", !w.link_up && w.present ? "📵" : "", c.queue ? `📦${c.queue}` : "",
    w.emergency > 0 ? `⚠${Math.ceil(w.emergency)}s` : "", (c.energy ?? 999) < CFG.energy.min_energy_j ? "🪫" : ""].join("");
  return { ...w, status, version: c.version, badges };
}

function updateSignalsAndPeds(sigs, peds) {
  const COL = { green: "#22c55e", yellow: "#facc15", red: "#ef4444", g: "#22c55e", y: "#facc15", r: "#ef4444" };
  for (const [id, st] of Object.entries(sigs || {})) {
    const s = SIGNAL[id];
    if (!s) continue;
    const xs = Array.isArray(st) ? st[0] : st[0], zs = Array.isArray(st) ? st[1] : st[1];
    s.lamps.x.color.set(COL[xs]); s.lamps.x.emissive.set(COL[xs]);
    s.lamps.z.color.set(COL[zs]); s.lamps.z.emissive.set(COL[zs]);
  }
  if (!pedMesh) return;
  const m = new THREE.Matrix4(), c = new THREE.Color();
  const n = Math.min(96, (peds || []).length);
  for (let i = 0; i < n; i++) {
    const [x, z, dart] = peds[i];
    m.setPosition(x - W2, 6, z - H2);
    pedMesh.setMatrixAt(i, m);
    pedMesh.setColorAt(i, c.set(dart ? "#ef4444" : "#f8fafc"));
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
  o.position.set(0, 44 + car.floats * 16, 0);
  car.g.add(o);
  car.floats++; activeFloats++;
  setTimeout(() => { car.g.remove(o); o.element.remove(); car.floats--; activeFloats--; }, 2600);
}
// 도착 선: 미리 만든 12개를 돌려 쓴다 (새 geometry를 만들지 않음)
const FLASH = [];
for (let i = 0; i < 12; i++) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(9), 3));
  const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: "#4ade80", transparent: true, opacity: 0 }));
  line.visible = false;
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
  p.setXYZ(0, a.x, 12, a.z); p.setXYZ(1, mid.x, mid.y, mid.z); p.setXYZ(2, dc.top.x, dc.top.y, dc.top.z);
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
function frame(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  for (const car of Object.values(CARS)) {
    if (!car.target) continue;
    car.g.position.lerp(car.target, Math.min(1, dt * 6));
    let dh = car.heading - car.g.rotation.y;
    dh = Math.atan2(Math.sin(dh), Math.cos(dh));
    car.g.rotation.y += dh * Math.min(1, dt * 8);
    if (car.beam.visible) car.beam.material.dashOffset -= dt * 60;
  }
  if (rain && weatherGroup?.visible) {
    const p = rain.geometry.attributes.position;
    for (let i = 0; i < p.count; i++) { let y = p.getY(i) - dt * 160; if (y < 0) y = 215; p.setY(i, y); }
    p.needsUpdate = true;
  }
  for (const f of FLASH) {
    if (!f.line.visible) continue;
    const a = 1 - (now - f.t0) / 1400;
    if (a <= 0) f.line.visible = false; else f.line.material.opacity = a;
  }
  // 카메라가 맵 밖으로 나가지 않게: 바라보는 점을 맵 안으로, 높이는 지면 위로
  controls.target.x = clamp(controls.target.x, -W2 - 60, W2 + 60);
  controls.target.z = clamp(controls.target.z, -H2 - 60, H2 + 60);
  controls.target.y = 0;
  controls.update();
  if (camera.position.y < 30) camera.position.y = 30;
  renderer.render(scene, camera);
  labelRenderer.render(scene, camera);
  requestAnimationFrame(frame);
}

const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
function pick(ev) {
  const r = renderer.domElement.getBoundingClientRect();
  mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(mouse, camera);
  const hit = ray.intersectObjects(Object.values(CARS).filter((c) => c.g.visible).map((c) => c.body))[0];
  return hit ? hit.object.userData.vid : null;
}
renderer.domElement.addEventListener("click", (ev) => { const v = pick(ev); if (v) selectVehicle(v); });
renderer.domElement.addEventListener("mousemove", (ev) => {
  const v = pick(ev), tip = $("#tooltip");
  if (!v || REPLAY) { tip.style.display = "none"; return; }
  const s = liveCarState(v) || {}, c = LAST?.clients?.[v] || {};
  tip.innerHTML = `<b>V${v} ${vtypeOf(v) === "new" ? "신형 EV" : "구형 EV"}</b> · ${STATE[s.status]?.[0] || ""} — ${c.detail || ""}<br>
    ${s.speed_kmh ?? "-"} km/h · 셀 ${s.cell || "없음"} · ${s.link_up ? "연결" : "연결 없음"}${s.wifi ? " · Wi-Fi" : ""} · 권역 ${s.region}<br>
    에너지 ${c.energy ?? "-"} J · 새 데이터 ${c.new_data ?? "-"} · 모델 v${c.version ?? "-"} (서버 v${c.server_version ?? "-"})
    ${s.emergency > 0 ? `<br><b style="color:#f87171">긴급제동(${s.emergency_cause}) — ADAS 연산 점유 ${s.emergency}초</b>` : ""}`;
  Object.assign(tip.style, { display: "block", left: ev.clientX + 14 + "px", top: ev.clientY + 10 + "px" });
});

function focusOn(key) {
  let x, z;
  if (Array.isArray(key)) [x, z] = key;
  else if (PLACE[key]) [x, z] = PLACE[key].pos;
  else if (CROSS[key]) [x, z] = CROSS[key].pos;
  else if (ZONE[key]) { const zz = ZONE[key]; if (zz.rect) { x = (zz.rect[0] + zz.rect[2]) / 2; z = (zz.rect[1] + zz.rect[3]) / 2; } else [x, z] = zz.circle; }
  else return;
  document.querySelector('[data-tab="map"]').click();
  controls.target.copy(P(x, z));
  camera.position.copy(P(x - 120, z + 560, 520));
}

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
  $("#legendState").innerHTML = "<b>차량 색 = 연합학습 상태 · 모양 = 신형(낮고 긴 차체, 청록 라이트) / 구형(높은 차체, 루프랙)</b>" +
    Object.entries(STATE).map(([, [n, c]]) => `<span><i style="background:${c}"></i>${n}</span>`).join("") +
    "<span style='grid-column:1/-1' class='muted'>🅿주차 ⚡충전 🔧OTA 🚇터널 📶Wi-Fi 📵연결 없음 📦보관 ⚠긴급제동 🪫에너지↓ · 흰 점=보행자, 빨간 점=돌발</span>";
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
    ["bandwidth_mbps", "상향 대역폭 (Mbps)", "num", 1, 200, 1, "4-4"], ["fragments", "전송 시간 조각 수", "num", 1, 50, 1, "2-x"],
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
    ["availability_mode", "운행 시간대 주기", "sel:off,cycle", 0, 0, 0, "7-3"], ["availability_min", "가용률 최저", "num", 0, 1, 0.05, "7-3"],
    ["availability_max", "가용률 최고", "num", 0, 1, 0.05, "7-3"], ["availability_period_s", "하루 주기 (초)", "num", 30, 3600, 30, "7-3"],
    ["weather_on", "강우 구역 켜기", "bool", 0, 0, 0, "4-4"], ["visitor_gap_mean_s", "통과 차량 재진입 평균 (초)", "num", 5, 600, 5, ""]]],
  ["서버", "server", [
    ["pause_s", "서버 장애 시간 (초)", "num", 5, 600, 5, "8-1 · 5-3"], ["p7_window", "편중 감시 창 (라운드)", "num", 5, 200, 5, "7-x"],
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
  const route = MAP?.routes?.[s.route]?.name || "-";
  const zones = Object.entries(s.zones || {}).filter(([, b]) => b).map(([k]) =>
    ({ tunnel: "터널", shadow: "음영", congestion: "혼잡", school: "보호구역", wifi: "Wi-Fi", weather: "강우" }[k])).join(", ");
  const hist = c.label_hist || [], mx = Math.max(1, ...hist), cn = c.counters || {};
  $("#vehInfo").innerHTML = `
    <div class="row"><b>V${selected} · ${vtypeOf(selected) === "new" ? "신형 EV" : "구형 EV"} · ${route}</b><span>${STATE[s.status]?.[0] || ""} — ${c.detail || ""}</span></div>
    <div class="row"><span>속도 ${s.speed_kmh ?? "-"} km/h · 셀 ${s.cell || "범위 밖"} · 품질 ${s.quality ?? "-"}</span><span>권역 ${s.region || "-"}</span></div>
    <div class="row"><span>구역: ${zones || "없음"}</span><span>${s.link_up ? "🟢 연결" : "🔴 연결 없음"}${s.wifi ? " 📶" : ""}</span></div>
    ${s.emergency > 0 ? `<div class="row" style="color:#f87171"><b>⚠ 긴급제동(${s.emergency_cause}) — ADAS 연산 점유 ${s.emergency}초</b></div>` : ""}
    <div class="row"><span>에너지 ${c.energy ?? "-"} J · 새 데이터 ${c.new_data ?? "-"} · 연산 ×${c.ecu ?? "-"}</span><span>모델 v${c.version ?? "-"} / 서버 v${c.server_version ?? "-"}</span></div>
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
  let html = `<p class="muted">34개 유스케이스 중 이번 실행에서 <b style="color:#f1f5ff">${total}</b>개가 일어났습니다. 행을 누르면 맵에서 그 장소로 이동합니다.</p>`;
  for (const [p, name] of Object.entries(STATIC.patterns)) {
    const rows = STATIC.usecases.filter((u) => u[0].startsWith(p + "-"));
    const sum = rows.reduce((a, u) => a + (caseCount[u[0]] || 0), 0);
    html += `<div class="ptitle"><span class="pt" style="background:${PCOL[p]}">P${p}</span>${name}<span class="muted small">${sum}회</span></div>
      <div class="pdesc">${PDESC[p]}</div>
      <table class="cases"><tr><th style="width:46px">id</th><th>예시</th><th>근거</th><th>맵·설정에서</th><th style="width:56px">발생</th><th style="width:90px">차량</th></tr>`;
    for (const [id, ex, ev, where] of rows) {
      const n = caseCount[id] || 0, recent = caseLast[id] && nowT - caseLast[id] < 6;
      html += `<tr class="${recent ? "recent" : n ? "hit" : ""}" data-id="${id}"><td><b>${id}</b></td><td>${ex}</td><td class="muted">${ev}</td>
        <td>${where}</td><td class="cnt">${n || "-"}</td><td>${caseVeh[id] ? [...caseVeh[id]].sort((a, b) => a - b).map((v) => "V" + v).join(" ") : ""}</td></tr>`;
    }
    html += "</table>";
  }
  const box = $("#caseTable");
  box.innerHTML = html;
  box.querySelectorAll("tr[data-id]").forEach((tr) => tr.onclick = () => FOCUS[tr.dataset.id] && focusOn(FOCUS[tr.dataset.id]));
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
  if (!MAP || STATIC.map.name !== MAP.name || JSON.stringify(STATIC.map.size) !== JSON.stringify(MAP.size)) buildScene(STATIC.map);
  buildVehForm(); buildGlobalForm(); renderMethodChip();
}
$("#btnStart").onclick = async () => { await control("start"); await afterStart(); };
$("#btnStop").onclick = () => control("stop");
$("#btnDown").onclick = () => {
  const s = CFG.server.pause_s;
  if (confirm(`집계 서버를 ${s}초 동안 멈췄다가 복구합니다 (8-1). 그동안 차량은 값을 보관했다가 복구 후 한꺼번에 보냅니다 (5-3).`)) control("server_down", { seconds: s });
};
$("#btnReset").onclick = async () => { await control("reset_config"); buildGlobalForm(); buildVehForm(); renderMethodChip(); };
$("#btnView").onclick = fitView;
$("#optCells").onchange = (e) => layers.cells.forEach((m) => (m.visible = e.target.checked));
$("#optPlaces").onchange = (e) => layers.placeLabels.forEach((m) => (m.visible = e.target.checked));
function renderMethodChip() { $("#methodChip").textContent = STATIC.methods[CFG.fl.method]?.name || CFG.fl.method; }

const PRESET_ALL = {
  fl: { tau: 5 },
  net: { frag_fail: 0.03, doppler_fail: 0.25, region_instability: 0.5, cell_capacity: 1, tdma_groups: 2, tdma_slot_s: 3 },
  energy: { budget_j: 400, min_energy_j: 120 },
  world: { availability_mode: "cycle", availability_min: 0.5, availability_max: 1.0, availability_period_s: 300, ota_prob: 0.5, pedestrian_scale: 2, weather_on: true },
  server: { p7_window: 15 },
  vehicle_default: { crash_prob: 0.05 },
  vehicles: {
    "1": { min_data: 300, data_rate_per_s: 3 },                 // 3-2 새 데이터 없음
    "2": { store_forward: true, energy_gate: false },           // 5-1·5-2 보관 후 일괄, 1-3·2-6 방전
    "3": { lr_override: 0.02 },                                 // 6-3 학습률 오류
    "4": { store_forward: true },                               // 통과 차량: 5-1 터널 보관
    "5": { wifi_only: true },                                   // 3-3 Wi-Fi에서만
    "6": { backdoor_boost: 0.5 },                               // 6-1 악의적 조작
    "7": { sensor_fault_classes: "3,8", sensor_fault_level: 0.6 },   // 6-2 센서 고장 (재시작)
    "8": { emergency_rate: 3, safety_preempt_prob: 0.5 },       // 1-4·4-5 긴급제동
  },
};
const PRESET_CLEAN = {
  fl: { tau: 9 },
  net: { frag_fail: 0.01, doppler_fail: 0.15, region_instability: 0.3, cell_capacity: 2, tdma_groups: 1 },
  energy: { budget_j: 1000, min_energy_j: 100 },
  world: { availability_mode: "off", ota_prob: 0.4, pedestrian_scale: 1 },
  vehicle_default: { crash_prob: 0.02 },
};
$("#presetAll").onclick = async () => {
  await postCfg(PRESET_ALL);
  $("#presetNote").textContent = "적용됨. 센서 고장(V7)·에너지 예산·τ는 다음 시작부터 → ▶ 시작을 다시 누르세요. 8-1·5-3은 '서버 장애' 버튼으로 일으킵니다.";
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
  const maps = (await (await fetch("/api/maps")).json()).maps;
  const sel = $("#mapSelect");
  sel.innerHTML = "";
  for (const m of maps) sel.appendChild(new Option(m, m, false, m === CFG.world.map));
  $("#mapDownload").href = "data:application/json;charset=utf-8," + encodeURIComponent(JSON.stringify(STATIC.map, null, 2));
  $("#mapDownload").download = `${CFG.world.map || "map"}.json`;
  if (LAST?.run) $("#btnExport").href = `/api/export?run=${encodeURIComponent(LAST.run)}`;
}
$("#btnSave").onclick = async () => {
  const r = await control("save", { name: $("#saveName").value || "상태" });
  $("#mapNote").textContent = r.id ? `저장됨: ${r.id}` : "실행 중인 시뮬레이션이 없습니다.";
  loadSaves();
};
$("#btnMapUse").onclick = async () => {
  await postCfg({ world: { map: $("#mapSelect").value } });
  $("#mapNote").textContent = `맵 '${$("#mapSelect").value}' — 다음 ▶ 시작부터 적용됩니다.`;
};
$("#mapFile").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  let m;
  try { m = JSON.parse(await f.text()); } catch { $("#mapNote").textContent = "JSON 형식이 아닙니다."; return; }
  const r = await (await fetch("/api/map", { method: "POST", body: JSON.stringify({ name: f.name.replace(/\.json$/, ""), map: m }) })).json();
  $("#mapNote").textContent = r.ok ? `맵 '${r.name}' 저장됨 — 선택 후 '이 맵 사용'을 누르세요.` : `맵 오류: ${r.errors.join(", ")}`;
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
  if (mapName !== (CFG.world.map || "default")) {
    const mp = (await (await fetch("/api/maps")).json()).maps;
    if (mp.includes(mapName)) {
      const saved = CFG.world.map; CFG.world.map = mapName;
      await postCfg({ world: { map: mapName } });
      STATIC = await (await fetch("/api/static")).json();
      buildScene(STATIC.map);
      await postCfg({ world: { map: saved } });
    }
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
  $("#rpTime").textContent = `${fmtT(f.t)} · ${Math.floor(f.c / 60)}분 ${Math.floor(f.c % 60)}초`;
  const recent = {};
  for (const e of R.events) if (e.t <= f.t && e.t > f.t - 4 && e.vid && e.pattern) recent[e.vid] = e;
  for (const [vid, a] of Object.entries(f.v)) {
    const [x, z, h, kmh, flags] = a, ev = recent[vid];
    const status = !(flags & 1) ? "absent" : ev ? ({ 1: "dead", 2: "dead", 3: "skipped", 4: "waiting", 5: "queued" }[ev.pattern] || "training")
      : (flags & 32 ? "idle" : "dead");
    drawCar(Number(vid), { pos: [x, z], heading: h, present: !!(flags & 1), status, emergency: flags & 16 ? 1 : 0,
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
  buildScene(STATIC.map);
  buildLegends(); buildGlobalForm(); buildVehForm(); buildLogFilter(); renderCases(); renderMethodChip();
  resize();
  requestAnimationFrame(frame);
  poll();
})();
