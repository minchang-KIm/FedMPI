// 차량: 차종(외형) 카탈로그, FL 차량·배경 차량 그리기, 움직임 보간, 떠오르는 사건·도착 선
// 연산 성능은 신형/구형 두 종류뿐이지만 외형은 차종·색으로 다양하게 (같은 vid는 늘 같은 차)
import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { $, el, S, STATE, hash, vtypeOf } from "./util.js";
import { scene, camera, canvasTex, P, W } from "./scene.js";
import { CELL, PLACE } from "./map3d.js";

// ------------------------------------------------------------------ 모양 도우미 (차 좌표: x 앞, y 위, z 오른쪽)
/** 윗면을 앞(f)·뒤(b)·옆(s)으로 좁힌 상자 → 유리창 기울기·보닛 경사 */
function T(l, h, w, x, y, z, { f = 0, b = 0, s = 0 } = {}) {
  const g = new THREE.BoxGeometry(l, h, w);
  const p = g.attributes.position;
  for (let i = 0; i < p.count; i++) {
    if (p.getY(i) <= 0) continue;
    p.setX(i, p.getX(i) > 0 ? p.getX(i) - f : p.getX(i) + b);
    p.setZ(i, p.getZ(i) > 0 ? p.getZ(i) - s : p.getZ(i) + s);
  }
  g.computeVertexNormals();
  return g.translate(x, y, z);
}
const B = (l, h, w, x, y, z) => new THREE.BoxGeometry(l, h, w).translate(x, y, z);
/** 앞을 보는 둥근 등 (원통을 x축으로 눕힘) */
const R = (r, d, x, y, z) => new THREE.CylinderGeometry(r, r, d, 16).rotateZ(Math.PI / 2).translate(x, y, z);
const pair = (fn, zz) => [fn(zz), fn(-zz)];
function wheels(r, w, xf, xr, zz, out) {
  for (const x of [xf, xr]) for (const z of [zz, -zz]) {
    out.tire.push(new THREE.CylinderGeometry(r, r, w, 18).rotateX(Math.PI / 2).translate(x, r, z));
    out.rim.push(new THREE.CylinderGeometry(r * 0.62, r * 0.62, w + 0.02, 12).rotateX(Math.PI / 2).translate(x, r, z));
  }
}

// ------------------------------------------------------------------ 차종 (신형 EV / 구형 EV). 실제 차를 본뜬 모양, 상표는 넣지 않음
const PAINTS = {
  eclass: ["#15171a", "#f2f3f4", "#7b8087", "#24344d", "#b9bec4"],          // 고급 세단: 검정·흰색·회색·짙은 청색·은색
  avanten: ["#3a6fb0", "#f2f2f2", "#2b2d31", "#8d9499", "#b3262d"],         // 고성능 세단: 퍼포먼스 블루 등
  ioniq: ["#d9dcdf", "#2e3a46", "#6c7a5f", "#c9b79c", "#1b1d22"],
  suv: ["#f4f4f2", "#3b4a59", "#8a8f94", "#5b2e2e", "#1f2a24"],
  casper: ["#8b8a63", "#e7e0cc", "#9dc5b8", "#2f4a6d", "#d9773a"],          // 경형 SUV: 카키·아이보리·민트·청색·주황
  starex: ["#f4f5f6", "#b9bec4", "#26364f", "#1c1d20", "#7a1f24"],          // 승합 밴
  porter: ["#1f4fae", "#f5f5f5", "#2a2c30"],                               // 1톤 트럭
  sedan: ["#c7cbd0", "#f1f1f1", "#1d1f23", "#6e1f2b", "#3d4a3c"],
  boxsuv: ["#4b5a3f", "#b9b3a3", "#2b2f36", "#8c2f22", "#d8d8d2"],
  racer: ["#e11d48", "#2563eb", "#16a34a", "#f59e0b", "#111827", "#f5f5f5", "#7c3aed"],
};
export const STYLES = {
  eclass: { name: "고급 세단 (E클래스 풍)", type: "new", eye: [0.25, 1.18, -0.38], roof: 1.47, build(o) {
    o.paint.push(T(4.92, 0.62, 1.86, 0, 0.62, 0, { f: 0.3, b: 0.22, s: 0.05 }), B(1.45, 0.06, 1.36, -0.42, 1.44, 0),
      ...pair((z) => B(0.16, 0.1, 0.14, 0.78, 1.0, z), 0.98));
    o.glass.push(T(2.6, 0.5, 1.72, -0.32, 1.17, 0, { f: 0.78, b: 0.58, s: 0.16 }));
    o.chrome.push(B(0.06, 0.32, 0.92, 2.44, 0.72, 0), R(0.1, 0.03, 2.48, 0.76, 0), B(2.3, 0.025, 1.74, -0.32, 0.935, 0));
    o.trim.push(B(0.22, 0.18, 1.82, 2.38, 0.4, 0), B(0.22, 0.18, 1.82, -2.38, 0.4, 0));
    o.head.push(...pair((z) => B(0.08, 0.09, 0.44, 2.42, 0.83, z), 0.62));
    o.tail.push(...pair((z) => B(0.06, 0.12, 0.5, -2.44, 0.86, z), 0.6), B(0.05, 0.035, 1.1, -2.45, 0.86, 0));
    wheels(0.36, 0.26, 1.48, -1.42, 0.81, o);
  } },
  avanten: { name: "고성능 세단 (아반떼 N 풍)", type: "new", eye: [0.12, 1.12, -0.38], roof: 1.4, build(o) {
    o.paint.push(T(4.68, 0.58, 1.83, 0, 0.6, 0, { f: 0.38, b: 0.16, s: 0.06 }), B(1.0, 0.05, 1.3, -0.25, 1.37, 0),
      ...pair((z) => B(0.14, 0.09, 0.14, 0.62, 0.98, z), 0.97));
    o.glass.push(T(2.35, 0.48, 1.66, -0.22, 1.12, 0, { f: 0.82, b: 0.8, s: 0.18 }));
    o.trim.push(B(0.06, 0.3, 1.3, 2.32, 0.55, 0), B(0.2, 0.16, 1.8, -2.25, 0.4, 0),
      ...pair((z) => B(0.06, 0.15, 0.06, -2.12, 1.0, z), 0.58), B(0.34, 0.04, 1.62, -2.16, 1.09, 0));
    o.paint2.push(B(0.26, 0.05, 1.8, 2.24, 0.33, 0), B(3.1, 0.05, 1.86, 0.05, 0.34, 0));      // 빨간 립·사이드 스커트
    o.head.push(...pair((z) => B(0.06, 0.06, 0.52, 2.31, 0.83, z), 0.6));
    o.tail.push(B(0.05, 0.06, 1.62, -2.34, 0.9, 0));
    o.chrome.push(...pair((z) => R(0.065, 0.1, -2.36, 0.38, z), 0.36));
    wheels(0.36, 0.28, 1.42, -1.36, 0.8, o);
  } },
  ioniq: { name: "전기 해치백", type: "new", eye: [0.18, 1.3, -0.4], roof: 1.6, build(o) {
    o.paint.push(T(4.6, 0.7, 1.88, 0, 0.66, 0, { f: 0.22, b: 0.06, s: 0.04 }), B(1.9, 0.06, 1.5, -0.35, 1.58, 0));
    o.glass.push(T(2.7, 0.56, 1.76, -0.28, 1.29, 0, { f: 0.62, b: 0.22, s: 0.14 }));
    o.trim.push(B(0.2, 0.2, 1.86, 2.25, 0.42, 0), B(0.2, 0.2, 1.86, -2.25, 0.42, 0));
    o.head.push(B(0.05, 0.06, 1.5, 2.3, 0.93, 0));
    o.tail.push(B(0.05, 0.08, 1.5, -2.3, 0.97, 0));
    wheels(0.36, 0.26, 1.45, -1.45, 0.82, o);
  } },
  suv: { name: "전기 SUV", type: "new", eye: [0.2, 1.48, -0.42], roof: 1.8, build(o) {
    o.paint.push(T(4.75, 0.82, 1.92, 0, 0.76, 0, { f: 0.22, b: 0.08, s: 0.04 }), B(2.2, 0.06, 1.56, -0.4, 1.78, 0));
    o.glass.push(T(2.95, 0.62, 1.8, -0.32, 1.47, 0, { f: 0.58, b: 0.18, s: 0.12 }));
    o.trim.push(B(0.22, 0.24, 1.9, 2.3, 0.45, 0), B(0.22, 0.24, 1.9, -2.3, 0.45, 0), ...pair((z) => B(1.8, 0.05, 0.05, -0.4, 1.84, z), 0.66));
    o.head.push(B(0.05, 0.05, 1.6, 2.38, 1.05, 0));
    o.tail.push(B(0.05, 0.1, 1.6, -2.38, 1.1, 0));
    wheels(0.4, 0.3, 1.5, -1.45, 0.83, o);
  } },
  casper: { name: "경형 SUV (캐스퍼 풍)", type: "old", eye: [0.05, 1.45, -0.35], roof: 1.8, build(o) {
    o.paint.push(T(3.6, 0.78, 1.6, 0, 0.68, 0, { f: 0.08, b: 0.03, s: 0.02 }));
    o.glass.push(T(2.4, 0.66, 1.52, -0.2, 1.39, 0, { f: 0.36, b: 0.1, s: 0.08 }));
    o.paint2.push(B(2.05, 0.07, 1.46, -0.25, 1.74, 0));                                    // 투톤 지붕
    o.trim.push(...pair((z) => B(1.8, 0.05, 0.05, -0.25, 1.81, z), 0.62), ...[1.15, -1.15].map((x) => B(0.9, 0.24, 1.64, x, 0.46, 0)),
      B(0.12, 0.2, 1.5, 1.78, 0.5, 0), B(0.12, 0.2, 1.5, -1.78, 0.5, 0));
    o.head.push(...pair((z) => R(0.14, 0.06, 1.8, 0.86, z), 0.52), B(0.05, 0.05, 1.1, 1.79, 1.03, 0));   // 둥근 등 + 위쪽 주간등
    o.tail.push(...pair((z) => B(0.05, 0.22, 0.18, -1.8, 0.96, z), 0.62));
    wheels(0.32, 0.24, 1.2, -1.2, 0.7, o);
  } },
  starex: { name: "승합 밴 (스타렉스 풍)", type: "old", eye: [1.25, 1.78, -0.42], roof: 2.0, build(o) {
    o.paint.push(T(4.15, 1.6, 1.92, -0.48, 1.15, 0, { f: 0.55, b: 0.02, s: 0.06 }), T(0.98, 0.55, 1.88, 2.06, 0.66, 0, { f: 0.42, s: 0.04 }));
    o.glass.push(B(3.3, 0.5, 1.94, -0.6, 1.52, 0), T(0.62, 0.62, 1.78, 1.38, 1.47, 0, { f: 0.5, s: 0.04 }));
    o.trim.push(B(0.03, 0.9, 1.96, 0.3, 0.95, 0), B(0.2, 0.22, 1.9, 2.52, 0.42, 0), B(0.2, 0.22, 1.9, -2.56, 0.45, 0));
    o.chrome.push(B(0.06, 0.24, 1.36, 2.55, 0.66, 0));
    o.head.push(...pair((z) => B(0.06, 0.18, 0.42, 2.54, 0.88, z), 0.62));
    o.tail.push(...pair((z) => B(0.05, 0.56, 0.18, -2.57, 1.22, z), 0.86));
    wheels(0.36, 0.26, 1.58, -1.62, 0.82, o);
  } },
  porter: { name: "1톤 트럭", type: "old", eye: [1.62, 1.78, -0.4], roof: 1.95, build(o) {
    o.paint.push(T(1.6, 1.45, 1.74, 1.55, 1.08, 0, { f: 0.25, s: 0.05 }), ...pair((z) => B(2.9, 0.42, 0.05, -0.8, 1.03, z), 0.88),
      B(0.05, 0.42, 1.8, -2.25, 1.03, 0));
    o.glass.push(B(1.22, 0.5, 1.76, 1.58, 1.48, 0));
    o.trim.push(B(2.95, 0.14, 1.8, -0.8, 0.76, 0), B(0.06, 0.62, 1.8, 0.67, 1.12, 0), B(0.2, 0.2, 1.78, 2.33, 0.45, 0));
    o.head.push(...pair((z) => B(0.06, 0.16, 0.34, 2.36, 0.78, z), 0.66));
    o.tail.push(...pair((z) => B(0.05, 0.14, 0.24, -2.28, 0.72, z), 0.7));
    wheels(0.33, 0.24, 1.72, -1.3, 0.78, o);
  } },
  sedan: { name: "중형 세단", type: "old", eye: [0.15, 1.2, -0.38], roof: 1.48, build(o) {
    o.paint.push(T(4.7, 0.66, 1.82, 0, 0.62, 0, { f: 0.16, b: 0.12, s: 0.04 }), B(1.4, 0.06, 1.4, -0.3, 1.45, 0));
    o.glass.push(T(2.5, 0.56, 1.7, -0.25, 1.23, 0, { f: 0.52, b: 0.46, s: 0.12 }));
    o.trim.push(B(0.2, 0.2, 1.8, 2.3, 0.42, 0), B(0.2, 0.2, 1.8, -2.3, 0.42, 0));
    o.chrome.push(B(0.05, 0.2, 0.8, 2.36, 0.72, 0));
    o.head.push(...pair((z) => B(0.06, 0.14, 0.38, 2.35, 0.82, z), 0.62));
    o.tail.push(...pair((z) => B(0.06, 0.16, 0.42, -2.35, 0.86, z), 0.6));
    wheels(0.34, 0.24, 1.42, -1.42, 0.8, o);
  } },
  boxsuv: { name: "각진 SUV", type: "old", eye: [0.1, 1.55, -0.42], roof: 2.0, build(o) {
    o.paint.push(B(4.4, 0.8, 1.88, 0, 0.72, 0), B(1.2, 0.06, 1.7, -0.45, 1.87, 0));
    o.glass.push(T(2.9, 0.78, 1.76, -0.45, 1.5, 0, { f: 0.2, s: 0.05 }));
    o.trim.push(B(2.2, 0.08, 1.4, -0.45, 1.94, 0), B(0.18, 0.24, 1.9, 2.22, 0.45, 0), B(0.18, 0.24, 1.9, -2.22, 0.45, 0));
    o.chrome.push(B(0.05, 0.3, 1.0, 2.21, 0.78, 0));
    o.head.push(...pair((z) => R(0.12, 0.06, 2.21, 0.82, z), 0.66));
    o.tail.push(...pair((z) => B(0.05, 0.3, 0.16, -2.21, 0.95, z), 0.78));
    wheels(0.38, 0.28, 1.45, -1.45, 0.84, o);
  } },
  racer: { name: "레이싱 카", type: "new", eye: [-0.35, 1.08, 0], roof: 1.15, build(o) {
    o.paint.push(T(4.9, 0.42, 2.0, 0, 0.42, 0, { f: 0.95, b: 0.12, s: 0.18 }), ...pair((z) => B(2.0, 0.3, 0.42, -0.5, 0.42, z), 0.72));
    o.glass.push(T(1.3, 0.32, 0.82, -0.25, 0.78, 0, { f: 0.62, b: 0.22, s: 0.16 }));
    o.trim.push(B(0.42, 0.04, 2.02, 2.36, 0.18, 0), ...pair((z) => B(0.08, 0.32, 0.06, -2.28, 0.84, z), 0.5));
    o.paint2.push(B(0.46, 0.05, 1.95, -2.3, 1.02, 0), B(4.1, 0.02, 0.38, -0.1, 0.645, 0), ...pair((z) => B(0.36, 0.3, 0.04, -2.3, 0.95, z), 0.97));
    o.head.push(...pair((z) => B(0.05, 0.05, 0.3, 2.32, 0.42, z), 0.62));
    o.tail.push(B(0.05, 0.06, 0.4, -2.46, 0.5, 0));
    wheels(0.34, 0.38, 1.6, -1.5, 0.86, o);
  } },
};
const BY_TYPE = { new: ["eclass", "avanten", "ioniq", "suv"], old: ["casper", "starex", "porter", "sedan", "boxsuv"] };

// 차종별 부품 geometry는 한 번만 합쳐 두고 모든 차가 같이 쓴다
const GEO_CACHE = {};
function styleGeo(style) {
  if (GEO_CACHE[style]) return GEO_CACHE[style];
  const o = { paint: [], paint2: [], glass: [], trim: [], chrome: [], head: [], tail: [], tire: [], rim: [] };
  STYLES[style].build(o);
  const out = {};
  for (const [k, arr] of Object.entries(o)) if (arr.length) out[k] = mergeGeometries(arr.map((g) => g.index ? g.toNonIndexed() : g));
  return (GEO_CACHE[style] = out);
}
const SHARED = {
  glass: new THREE.MeshStandardMaterial({ color: "#7d93ab", metalness: 0.1, roughness: 0.06 }),
  trim: new THREE.MeshStandardMaterial({ color: "#1d1f22", roughness: 0.7 }),
  chrome: new THREE.MeshStandardMaterial({ color: "#d6dade", metalness: 0.95, roughness: 0.18 }),
  tire: new THREE.MeshStandardMaterial({ color: "#121314", roughness: 0.9 }),
  rim: new THREE.MeshStandardMaterial({ color: "#9aa1a8", metalness: 0.8, roughness: 0.3 }),
  sign: new THREE.MeshStandardMaterial({ color: "#fde68a", emissive: "#facc15", emissiveIntensity: 0.6 }),
};
const PAINT_MATS = {};
const paintMat = (c) => PAINT_MATS[c] || (PAINT_MATS[c] = new THREE.MeshStandardMaterial({ color: c, metalness: 0.3, roughness: 0.35 }));

/** 이 차량의 차종·색. FL 차량은 신형/구형 안에서 vid로 고정, 택시·버스·레이싱 경로는 그에 맞는 차 */
export function lookOf(vid, vtype, route) {
  const r = S.MAP?.routes?.[route] || {};
  const h = hash(vid + 7);
  if (route === "race" || r.label === "레이싱 카") {
    const pal = PAINTS.racer;
    return { style: "racer", paint: pal[h % pal.length], paint2: pal[(h >> 4) % pal.length] === pal[h % pal.length] ? "#f5f5f5" : pal[(h >> 4) % pal.length] };
  }
  if (r.kind === "city" && !r.label) {                                  // 택시: 주황 + 지붕 표시등
    const style = vtype === "new" ? "ioniq" : "sedan";
    return { style, paint: "#f08a24", paint2: "#202124", taxi: true };
  }
  if (r.label === "버스" || r.label === "셔틀") return { style: "starex", paint: r.label === "버스" ? "#1f8f4e" : "#f4f5f6", paint2: "#202124" };
  const list = vtype ? BY_TYPE[vtype] : [...BY_TYPE.new, ...BY_TYPE.old];
  const style = list[h % list.length];
  const pal = PAINTS[style];
  return { style, paint: pal[(h >> 5) % pal.length], paint2: style === "avanten" ? "#c8102e" : "#1b1c1f" };
}

// ------------------------------------------------------------------ 차 한 대 만들기
const MARK_TEX = canvasTex(64, (c, s) => {
  c.clearRect(0, 0, s, s);
  c.beginPath(); c.arc(s / 2, s / 2, s / 2 - 4, 0, 7); c.fillStyle = "#ffffff"; c.fill();
  c.lineWidth = 5; c.strokeStyle = "rgba(15,23,42,0.85)"; c.stroke();
});
const RING_GEO = new THREE.RingGeometry(2.8, 3.25, 40).rotateX(-Math.PI / 2);
function buildCar(look, withStatus) {
  const g = new THREE.Group();
  const geo = styleGeo(look.style), st = STYLES[look.style];
  const head = new THREE.MeshStandardMaterial({ color: "#f8fafc", emissive: "#fff6d5", emissiveIntensity: 0 });
  const tail = new THREE.MeshStandardMaterial({ color: "#7f1d1d", emissive: "#ff2020", emissiveIntensity: 0.2 });
  const mats = { paint: paintMat(look.paint), paint2: paintMat(look.paint2 || "#1b1c1f"), head, tail, ...SHARED };
  let body = null;
  for (const [k, gg] of Object.entries(geo)) {
    const m = new THREE.Mesh(gg, mats[k]);
    m.castShadow = k !== "glass";
    g.add(m);
    if (k === "paint") body = m;
  }
  if (look.taxi) {
    const sign = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.2, 0.28), SHARED.sign);
    sign.position.set(-0.35, st.roof + 0.1, 0);
    g.add(sign);
  }
  const car = { g, body, head, tail, style: look.style, look, target: null, heading: 0, floats: 0 };
  if (withStatus) {                                                      // 연합학습 상태: 바닥 링 + 지붕 표시등 + 멀리서 보이는 점
    car.ringMat = new THREE.MeshBasicMaterial({ color: "#e2e8f0", transparent: true, opacity: 0.85, depthWrite: false });
    car.ring = new THREE.Mesh(RING_GEO, car.ringMat);
    car.ring.position.y = 0.07;
    car.ring.renderOrder = 2;
    car.beaconMat = new THREE.MeshStandardMaterial({ color: "#e2e8f0", emissive: "#e2e8f0", emissiveIntensity: 1.2 });
    car.beacon = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.2, 0.16, 12), car.beaconMat);
    car.beacon.position.set(-0.2, st.roof + (look.taxi ? 0.3 : 0.09), 0);
    car.markMat = new THREE.SpriteMaterial({ map: MARK_TEX, color: "#e2e8f0", depthTest: false, sizeAttenuation: false });
    car.marker = new THREE.Sprite(car.markMat);
    car.marker.scale.set(0.022, 0.022, 1);
    car.marker.position.y = st.roof + 1.4;
    car.marker.renderOrder = 10;
    car.d = el("div", "vlbl", "");
    car.lo = new CSS2DObject(car.d);
    car.lo.position.set(0, st.roof + 1.9, 0);
    g.add(car.ring, car.beacon, car.marker, car.lo);
  }
  scene.add(g);
  return car;
}
function disposeCar(c) {
  scene.remove(c.g);
  c.lo?.element.remove();
  c.beam && (scene.remove(c.beam), c.beam.geometry.dispose(), c.beam.material.dispose());
  for (const m of [c.head, c.tail, c.ringMat, c.beaconMat, c.markMat]) m?.dispose();
}

// ------------------------------------------------------------------ FL 차량
export const CARS = {};
export function removeCar(vid) { if (CARS[vid]) { disposeCar(CARS[vid]); delete CARS[vid]; } }
export function clearCars() { for (const k of Object.keys(CARS)) removeCar(k); for (const k of Object.keys(NPCS)) removeNpc(k); }

export function liveCarState(vid) {
  const w = S.LAST?.world?.vehicles?.[vid];
  if (!w) return null;
  const c = S.LAST?.clients?.[vid] || {};
  const status = w.present === false ? "absent" : w.engine_off && ["dead", "skipped", "idle"].includes(c.status) ? "parked" : (c.status || "idle");
  const badges = [w.engine_off && w.present ? "🅿" : "", w.charging ? "⚡" : "", w.ota ? "🔧" : "", w.zones?.tunnel ? "🚇" : "",
    w.wifi ? "📶" : "", !w.link_up && w.present ? "📵" : "", c.queue ? `📦${c.queue}` : "",
    w.emergency > 0 ? `⚠${Math.ceil(w.emergency)}s` : "", (c.energy ?? 999) < (S.CFG?.energy?.min_energy_j ?? 0) ? "🪫" : ""].join("");
  return { ...w, status, version: c.version, badges };
}
function setSample(car, s) {
  car.target = P(s.pos[0], s.pos[1]);
  car.heading = -s.heading;
  car.sample = { t: performance.now(), x: car.target.x, z: car.target.z, h: s.heading, v: (s.speed_kmh || 0) / 3.6 * (s.reverse ? -1 : 1) };
  if (!car.init || car.g.position.distanceTo(car.target) > 40) { car.g.position.copy(car.target); car.g.rotation.y = car.heading; car.init = true; }
}

/** FL 차량 하나 그리기. s = liveCarState(vid) 또는 다시 보기 상태 */
export function drawCar(vid, s) {
  const vt = vtypeOf(vid);
  const vr = S.MAP?.vehicle_routes || [];
  const look = lookOf(vid, vt, s.route || vr[(vid - 1) % Math.max(1, vr.length)]);
  let car = CARS[vid];
  if (car && (car.style !== look.style || car.look.paint !== look.paint)) { removeCar(vid); car = null; }
  car = car || (CARS[vid] = Object.assign(buildCar(look, true), { vid, vtype: vt }));
  car.body.userData.vid = car.marker.userData.vid = vid;
  car.g.visible = s.present !== false;
  car.lo.visible = car.g.visible && $("#optLabels").checked && !(S.CAM === "fpv" && vid === S.selected);
  setSample(car, s);
  const [name, col] = STATE[s.status] || STATE.idle;
  const sel = vid === S.selected;
  car.ringMat.color.set(sel ? "#ffffff" : col);
  car.ringMat.opacity = sel ? 1 : 0.8;
  car.ring.scale.setScalar(sel ? 1.12 : 1);
  car.beaconMat.color.set(col); car.beaconMat.emissive.set(col);
  car.markMat.color.set(col);
  car.tail.emissiveIntensity = s.braking || s.emergency > 0 ? 3 : 0.3 + 0.4 * W.NIGHT;
  car.head.emissiveIntensity = (s.engine_off ? 0 : 2.5) * W.NIGHT;
  car.d.className = "vlbl" + (sel ? " sel" : "") + (s.emergency > 0 ? " emerg" : "");
  car.d.style.setProperty("--st", col);
  car.d.innerHTML = `<b>V${vid}</b><span class="ty ${vt}">${vt === "new" ? "신형" : "구형"}</span><small>${name}${s.version !== undefined ? ` v${s.version}` : ""}</small>${s.badges ? `<span class="bd">${s.badges}</span>` : ""}` +
    (s.driver ? `<span class="drv">🕹${s.driver}</span>` : "");
  drawBeam(car, s);
}
function drawBeam(car, s) {
  const cell = s.cell && CELL[s.cell];
  const on = $("#optBeams").checked && s.status === "uploading" && !!cell && car.g.visible;
  if (on && !car.beam) {
    car.beam = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
      new THREE.LineDashedMaterial({ color: "#f97316", dashSize: 3, gapSize: 2 }));
    scene.add(car.beam);
  }
  if (!car.beam) return;
  car.beam.visible = on;
  if (!on) return;
  const pos = car.beam.geometry.attributes.position;
  pos.setXYZ(0, car.g.position.x, 2, car.g.position.z);
  pos.setXYZ(1, cell.top.x, cell.top.y, cell.top.z);
  pos.needsUpdate = true;
  car.beam.geometry.computeBoundingSphere();
  car.beam.computeLineDistances();
}

// ------------------------------------------------------------------ 배경 차량 (학습 참여 안 함: 길을 채운다)
export const NPCS = {};
function removeNpc(id) { if (NPCS[id]) { disposeCar(NPCS[id]); delete NPCS[id]; } }
/** list = [[id, x, z, heading, kmh, braking, route], ...] */
export function drawNpcs(list) {
  const seen = new Set();
  for (const [id, x, z, h, kmh, brk, route] of list || []) {
    seen.add(String(id));
    const nr = S.MAP?.npc_routes || Object.keys(S.MAP?.routes || {});
    const car = NPCS[id] || (NPCS[id] = buildCar(lookOf(id, null, route || nr[(id - 1000) % Math.max(1, nr.length)]), false));
    car.g.visible = true;
    setSample(car, { pos: [x, z], heading: h, speed_kmh: kmh });
    car.tail.emissiveIntensity = brk ? 2.5 : 0.3 + 0.4 * W.NIGHT;
    car.head.emissiveIntensity = 2.5 * W.NIGHT;
  }
  for (const k of Object.keys(NPCS)) if (!seen.has(k)) removeNpc(k);
}

// ------------------------------------------------------------------ 매 프레임: 받은 위치에서 속도·방향으로 내다보며 부드럽게
const tmp = new THREE.Vector3();
export function animateCars(now, dt) {
  const step = (car, k) => {
    if (!car.target) return;
    const sm = car.sample;
    if (sm && !S.REPLAY) {
      const age = Math.min(0.5, (now - sm.t) / 1000);
      tmp.set(sm.x + Math.cos(sm.h) * sm.v * age, 0, sm.z + Math.sin(sm.h) * sm.v * age);
      car.g.position.lerp(tmp, Math.min(1, dt * k));
    } else car.g.position.lerp(car.target, Math.min(1, dt * 5));
    let dh = car.heading - car.g.rotation.y;
    dh = Math.atan2(Math.sin(dh), Math.cos(dh));
    car.g.rotation.y += dh * Math.min(1, dt * 6);
  };
  for (const [vid, car] of Object.entries(CARS)) {
    step(car, S.CAM !== "orbit" && Number(vid) === S.selected ? 12 : 8);
    const d = camera.position.distanceTo(car.g.position);
    car.marker.visible = d > 160 && !(S.CAM === "fpv" && Number(vid) === S.selected);
    car.lo.element.style.opacity = d > 1600 ? 0 : 1;                       // 아주 멀면 이름표 대신 점만
    if (car.beam?.visible) car.beam.material.dashOffset -= dt * 20;
    if (Number(vid) === S.selected) car.ring.rotation.y += dt * 1.5;
  }
  for (const car of Object.values(NPCS)) step(car, 8);
  for (const f of FLASH) {
    if (!f.line.visible) continue;
    const a = 1 - (now - f.t0) / 1400;
    if (a <= 0) f.line.visible = false; else f.line.material.opacity = a;
  }
}

/** 마우스 아래 FL 차량 */
export function pickCar(ray) {
  const objs = Object.values(CARS).filter((c) => c.g.visible).flatMap((c) => (c.marker.visible ? [c.body, c.marker] : [c.body]));
  const hit = ray.intersectObjects(objs)[0];
  return hit ? hit.object.userData.vid : null;
}

// ------------------------------------------------------------------ 떠오르는 사건 (동시에 최대 24개, 끝나면 DOM까지 제거)
let activeFloats = 0;
export function floatAt(vid, text, color) {
  const car = CARS[vid];
  if (!car || activeFloats >= 24 || car.floats >= 2) return;
  const o = new CSS2DObject(el("div", "float", text));
  o.element.style.background = color;
  o.position.set(0, STYLES[car.style].roof + 4 + car.floats * 2.5, 0);
  car.g.add(o);
  car.floats++; activeFloats++;
  setTimeout(() => { car.g.remove(o); o.element.remove(); car.floats--; activeFloats--; }, 2600);
}
// 도착 선: 차량 → 기지국 → 집계 서버. 미리 만든 12개를 돌려 쓴다
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
export function flashArrival(vid) {
  const car = CARS[vid], dc = PLACE.datacenter;
  if (!car || !dc?.top) return;
  const f = FLASH.find((x) => !x.line.visible) || FLASH.reduce((a, b) => (a.t0 < b.t0 ? a : b));
  const w = S.LAST?.world?.vehicles?.[vid];
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

/** 점검용: 모든 차종을 (x, z)부터 한 줄로 세워 보여 준다 (브라우저 콘솔 __sim.showroom(x, z)) */
export function showroom(x, z) {
  Object.keys(STYLES).forEach((style, i) => {
    const pal = PAINTS[style];
    const car = buildCar({ style, paint: pal[i % pal.length], paint2: style === "avanten" ? "#c8102e" : "#1b1c1f" }, false);
    car.g.position.copy(P(x + i * 7, z));
    car.g.rotation.y = -Math.PI / 2 + 0.5;
    const o = new CSS2DObject(el("div", "lbl place", STYLES[style].name));
    o.position.set(0, STYLES[style].roof + 1.2, 0);
    car.g.add(o);
  });
}
