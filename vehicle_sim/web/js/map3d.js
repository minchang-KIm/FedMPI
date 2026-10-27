// 맵 그리기: 땅·물·언덕, 도로(차선·보도·서킷 연석)·횡단보도·정지선, 주차장, 건물·나무, 터널, 기지국, 구역, 장소 건물, 신호등, 장식
import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { $, S, clamp } from "./util.js";
import { scene, P, W, TEX, BSTYLE, winMats, layers, mapLabels, mat, markMat, addLabel, box, overlayRect, disposeGroup, segDist, fitFog } from "./scene.js";
import { createWalkerMesh } from "./walkers.js";

export const ZONE = {}, PLACE = {}, CELL = {}, SIGNAL = {}, CROSS = {};
export const FX = { rain: null, weather: null, peds: null };
let mapGroup = null;

function roadDist(p) {
  let d = 1e9;
  for (const rd of S.MAP.roads) for (let i = 0; i < rd.pts.length - 1; i++) d = Math.min(d, segDist(p, rd.pts[i], rd.pts[i + 1]));
  return d;
}
export function isHorizontalRoad(M, p) {
  let best = 1e9, hor = true;
  for (const rd of M.roads) for (let i = 0; i < rd.pts.length - 1; i++) {
    const a = rd.pts[i], b = rd.pts[i + 1], d = segDist(p, a, b);
    if (d < best) { best = d; hor = Math.abs(b[0] - a[0]) > Math.abs(b[1] - a[1]); }
  }
  return hor;
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
    const x0 = x0r - W.W2, x1 = x1r - W.W2, z0 = z0r - W.H2, z1 = z1r - W.H2;
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
  if (!inTunnel) h *= clamp((roadDist([x, z]) - (lw + 5)) / 25, 0, 1);
  return h;
}
function terrain(group, hill, tunnels, lw, color) {
  const [x0, z0, x1, z1] = hill.rect;
  const nx = Math.min(160, Math.max(8, Math.round((x1 - x0) / 12))), nz = Math.min(160, Math.max(8, Math.round((z1 - z0) / 12)));
  const g = new THREE.PlaneGeometry(x1 - x0, z1 - z0, nx, nz).rotateX(-Math.PI / 2);
  const p = g.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i) + (x0 + x1) / 2, z = p.getZ(i) + (z0 + z1) / 2;
    p.setY(i, hillHeight(x, z, hill, tunnels, lw));
  }
  g.computeVertexNormals();
  const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ map: TEX.grass, color, roughness: 0.95 }));
  m.position.copy(P((x0 + x1) / 2, (z0 + z1) / 2, 0.05));
  m.castShadow = m.receiveShadow = true;
  group.add(m);
}

export function buildScene(M, L) {
  if (mapGroup) disposeGroup(mapGroup);
  for (const k of Object.keys(layers)) layers[k] = [];
  for (const o of [ZONE, PLACE, CELL, SIGNAL, CROSS]) for (const k in o) delete o[k];
  FX.rain = FX.weather = FX.peds = null;
  winMats.length = 0;
  mapLabels.length = 0;
  S.MAP = M; S.LAY = L;
  const [MW, MH] = M.size;
  W.W2 = MW / 2; W.H2 = MH / 2;
  fitFog(MW, MH);
  const g = (mapGroup = new THREE.Group());
  scene.add(g);
  const lw = M.lane_width || 3.5, SW = 3.0, B = lw + SW;
  // ---------------------------------------------------------------- 땅·물·언덕
  const gt = TEX.grass.clone(); gt.needsUpdate = true; gt.repeat.set((MW + 6000) / 60, (MH + 6000) / 60);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(MW + 6000, MH + 6000).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({ map: gt, roughness: 1 }));
  ground.position.copy(P(MW / 2, MH / 2, -0.05));
  ground.receiveShadow = true;
  g.add(ground);
  const waterMat = new THREE.MeshStandardMaterial({ color: "#2f6b8f", roughness: 0.12, metalness: 0.35, polygonOffset: true, polygonOffsetFactor: 2, polygonOffsetUnits: 2 });
  for (const w of M.water || []) {
    const r = w.rect;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(r[2] - r[0], r[3] - r[1]).rotateX(-Math.PI / 2), waterMat);
    m.position.copy(P((r[0] + r[2]) / 2, (r[1] + r[3]) / 2, 0.0));
    m.receiveShadow = true;
    g.add(m);
  }
  const tunnels = M.zones.filter((z) => z.kind === "tunnel").map((z) => z.rect);
  for (const h of L.hills || []) terrain(g, h, tunnels, lw, h.height > 300 ? "#7d8f62" : "#8aa06a");
  buildRoads(g, M, L, lw, SW, B);
  buildLots(g, L, lw, SW);
  buildBuildings(g, L, tunnels, lw);
  buildTunnels(g, M, L, lw);
  buildCells(g, M);
  buildZones(g, M, lw, MH);
  buildPlaces(g, M, L);
  buildSignals(g, M, L, lw, SW, B);
  buildDecor(g, L);
  g.add(createWalkerMesh());
  FX.peds = new THREE.InstancedMesh(new THREE.CapsuleGeometry(0.25, 1.1, 4, 8), new THREE.MeshStandardMaterial({ color: "#ffffff" }), 128);
  FX.peds.count = 0;
  FX.peds.castShadow = true;
  FX.peds.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  g.add(FX.peds);
  for (const o of layers.placeLabels) o.visible = $("#optPlaces").checked;
  for (const o of layers.cells) o.visible = $("#optCells").checked;
  for (const o of layers.zones) o.visible = $("#optZones").checked;
}

// ---------------------------------------------------------------- 도로: 아스팔트·보도·흰 차선·중앙 이중 황색선 (서킷은 연석·흰 가장자리)
function buildRoads(g, M, L, lw, SW, B) {
  const nodes = L.junctions.map((j) => ({ pos: j.pos, arms: j.arms }));
  for (const rd of M.roads) for (let i = 1; i < rd.pts.length - 1; i++) {
    const a = rd.pts[i - 1], p = rd.pts[i], b = rd.pts[i + 1];
    const u1 = [a[0] - p[0], a[1] - p[1]], u2 = [b[0] - p[0], b[1] - p[1]];
    const n1 = Math.hypot(...u1), n2 = Math.hypot(...u2);
    nodes.push({ pos: p, arms: [[u1[0] / n1, u1[1] / n1], [u2[0] / n2, u2[1] / n2]], corner: true, track: rd.track });
  }
  const asphalt = new THREE.MeshStandardMaterial({ map: TEX.asphalt.clone(), roughness: 0.92 });
  asphalt.map.needsUpdate = true; asphalt.map.repeat.set(1 / 12, 1 / 12);
  const trackMat = new THREE.MeshStandardMaterial({ map: TEX.track.clone(), roughness: 0.8 });
  trackMat.map.needsUpdate = true; trackMat.map.repeat.set(1 / 12, 1 / 12);
  const kerbTex = TEX.kerb.clone(); kerbTex.needsUpdate = true;
  const kerbMat = new THREE.MeshStandardMaterial({ map: kerbTex, roughness: 0.7 });
  const sidewalkMat = new THREE.MeshStandardMaterial({ map: TEX.concrete, roughness: 0.9 });
  const G = { as: [], tr: [], sw: [], white: [], yellow: [], kerb: [], sand: [] };
  const strip = (arr, cx, cz, len, wid, ux, uz, y, thick = 0, uvMode = "world") => {
    const gg = thick > 0 ? new THREE.BoxGeometry(len, thick, wid) : new THREE.PlaneGeometry(len, wid).rotateX(-Math.PI / 2);
    if (uvMode === "len") {                                               // 연석: 2 m마다 빨강·흰색
      const uvA = gg.attributes.uv;
      for (let i = 0; i < uvA.count; i++) uvA.setX(i, uvA.getX(i) * len / 4);
    }
    gg.rotateY(-Math.atan2(uz, ux));
    gg.translate(cx - W.W2, y + thick / 2, cz - W.H2);
    if (uvMode === "world") {                                              // 아스팔트 uv는 월드 좌표 기준 (이음매 없이)
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
  for (const rd of M.roads) {
    const track = !!rd.track;
    for (let i = 0; i < rd.pts.length - 1; i++) {
      const a = rd.pts[i], b = rd.pts[i + 1];
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const ux = (b[0] - a[0]) / len, uz = (b[1] - a[1]) / len, nx = -uz, nz = ux;
      const at = (s, off) => [a[0] + ux * s + nx * off, a[1] + uz * s + nz * off];
      const endA = !nodes.some((n) => Math.hypot(n.pos[0] - a[0], n.pos[1] - a[1]) < 1), endB = !nodes.some((n) => Math.hypot(n.pos[0] - b[0], n.pos[1] - b[1]) < 1);
      const ext0 = endA ? 0 : lw, ext1 = endB ? 0 : lw, cc = at((len + ext1 - ext0) / 2, 0);   // 교차로 쪽 끝은 차로 폭만큼 늘림
      strip(track ? G.tr : G.as, cc[0], cc[1], len + ext0 + ext1, 2 * lw, ux, uz, 0.02);
      if (track) {                                                         // 서킷: 연석 + 흰 가장자리선, 중앙선 없음
        for (const side of [1, -1]) {
          const k = at(len / 2, side * (lw + 0.6)), e = at(len / 2, side * (lw - 0.3));
          strip(G.kerb, k[0], k[1], len + 1.2, 1.2, ux, uz, 0.02, 0.06, "len");
          const sd = at(len / 2, side * (lw + 8));                          // 모래 완충지대
          strip(G.sand, sd[0], sd[1], len + 2, 13, ux, uz, 0.01);
          strip(G.white, e[0], e[1], len + 0.6, 0.25, ux, uz, 0.03);
        }
        if (i === 0) addLabel(g, `🏁 ${rd.name} · ${rd.speed} km/h`, "road", P(at(Math.min(60, len / 2), 0)[0], at(Math.min(60, len / 2), 0)[1], 3));
        continue;
      }
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
          strip(G.sw, sw[0], sw[1], L2, SW, ux, uz, 0, 0.16);
          strip(G.white, ed[0], ed[1], L2, 0.15, ux, uz, 0.03);
        }
      }
      const ccuts = near.map(({ t }) => [t - B, t + B]);
      for (const [s0, s1] of intervals(len, ccuts)) for (const off of [-0.12, 0.12]) {
        const c = at((s0 + s1) / 2, off);
        strip(G.yellow, c[0], c[1], s1 - s0, 0.12, ux, uz, 0.035);
      }
      if (i === 0) addLabel(g, `${rd.name} · ${rd.speed} km/h`, "road", P(at(Math.min(60, len / 2), 0)[0], at(Math.min(60, len / 2), 0)[1], 3));
    }
  }
  // 모서리 보도 (교차로 네 귀퉁이)
  for (const n of nodes) {
    if (n.track) continue;
    for (const sx of [-1, 1]) for (const sz of [-1, 1]) {
      const c = [n.pos[0] + sx * (lw + SW / 2), n.pos[1] + sz * (lw + SW / 2)];
      if (roadDist(c) > lw + 0.4) strip(G.sw, c[0], c[1], SW, SW, 1, 0, 0, 0.16);
    }
  }
  const add = (arr, m, shadow = true) => {
    if (!arr.length) return;
    const mesh = new THREE.Mesh(mergeGeometries(arr), m);
    mesh.receiveShadow = shadow;
    mesh.userData.sharedMat = true;
    g.add(mesh);
    arr.forEach((x) => x.dispose());
  };
  const sandMat = new THREE.MeshStandardMaterial({ map: TEX.sand.clone(), roughness: 1 });
  sandMat.map.needsUpdate = true; sandMat.map.repeat.set(1 / 10, 1 / 10);
  add(G.sand, sandMat); add(G.as, asphalt); add(G.tr, trackMat); add(G.sw, sidewalkMat); add(G.kerb, kerbMat);
  // 정지선·화살표 (신호 교차로의 들어오는 차로)
  const arrowShape = new THREE.Shape([[-2.6, -0.12], [0.6, -0.12], [0.6, -0.45], [2.4, 0], [0.6, 0.45], [0.6, 0.12], [-2.6, 0.12]].map(([x, y]) => new THREE.Vector2(x, y)));
  for (const s of M.signals || []) {
    const j = L.junctions.find((jj) => Math.hypot(jj.pos[0] - s.pos[0], jj.pos[1] - s.pos[1]) < 8);
    for (const u of j ? j.arms : []) {
      const rx = u[1], rz = -u[0];                        // 들어오는 방향(-u)의 오른쪽
      const c = [s.pos[0] + u[0] * (B + 0.6) + rx * lw / 2, s.pos[1] + u[1] * (B + 0.6) + rz * lw / 2];
      strip(G.white, c[0], c[1], 0.45, lw - 0.3, u[0], u[1], 0.035);
      const ac = [s.pos[0] + u[0] * (B + 14) + rx * lw / 2, s.pos[1] + u[1] * (B + 14) + rz * lw / 2];
      const ag = new THREE.ShapeGeometry(arrowShape).rotateX(-Math.PI / 2);
      ag.rotateY(-Math.atan2(-u[1], -u[0]));
      ag.translate(ac[0] - W.W2, 0.04, ac[1] - W.H2);
      G.white.push(ag);
    }
  }
  // 횡단보도 (얼룩무늬) + 마름모 예고 표시
  for (const c of M.crosswalks || []) {
    CROSS[c.id] = c;
    const [x, z] = c.pos;
    const hor = isHorizontalRoad(M, c.pos);
    const ux = hor ? 1 : 0, uz = hor ? 0 : 1;
    for (let k = -lw + 0.45; k <= lw - 0.3; k += 0.9) strip(G.white, x + (hor ? 0 : k), z + (hor ? k : 0), 4, 0.45, ux, uz, 0.04);
    for (const sgn of [-1, 1]) {
      const dpos = [x + ux * sgn * 28 + (hor ? 0 : -sgn * lw / 2), z + uz * sgn * 28 + (hor ? -sgn * lw / 2 : 0)];
      const dg = new THREE.RingGeometry(1.0, 1.25, 4, 1).rotateX(-Math.PI / 2).scale(2.2, 1, 0.8);
      dg.rotateY(hor ? 0 : Math.PI / 2);
      dg.translate(dpos[0] - W.W2, 0.04, dpos[1] - W.H2);
      G.white.push(dg);
    }
    addLabel(g, `🚸 ${c.name}${c.school ? " (등하교 시간 혼잡)" : ""}`, "zone", P(x, z, 6));
  }
  add(G.white, markMat("#f3f3f0"));
  add(G.yellow, markMat("#f0b429"));
}

function buildLots(g, L, lw, SW) {
  const lotGeo = [], lineGeo = [];
  const strip = (arr, cx, cz, len, wid, ux, uz, y) => {
    const gg = new THREE.PlaneGeometry(len, wid).rotateX(-Math.PI / 2);
    gg.rotateY(-Math.atan2(uz, ux));
    gg.translate(cx - W.W2, y, cz - W.H2);
    arr.push(gg);
  };
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
  if (lotGeo.length) g.add(Object.assign(new THREE.Mesh(mergeGeometries(lotGeo), mat("#4b4e53", { roughness: 0.9 })), { receiveShadow: true }));
  if (lineGeo.length) g.add(new THREE.Mesh(mergeGeometries(lineGeo), markMat("#f3f3f0")));
}

function buildBuildings(g, L, tunnels, lw) {
  const groups = {};
  for (const bd of L.buildings) (groups[bd[5]] = groups[bd[5]] || []).push([...bd, (bd[0] * 7.13 + bd[1] * 3.71) % 1]);
  for (const pb of L.place_buildings) {
    if (["apartment", "office"].includes(pb.kind))
      (groups[pb.kind] = groups[pb.kind] || []).push([pb.x - pb.w / 2, pb.z - pb.d / 2, pb.x + pb.w / 2, pb.z + pb.d / 2, pb.h, pb.kind, 0.37]);
  }
  for (const [k, list] of Object.entries(groups)) if (BSTYLE[k]) g.add(buildingMesh(list, BSTYLE[k]));
  const trees = L.trees;
  if (!trees.length) return;
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

function buildTunnels(g, M, L, lw) {
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
      const wid = 2 * lw + 2, fr = new THREE.Group(), wall = mat("#b9b5ad");
      for (const s of [-1, 1]) { const w = box(fr, 6, portalH, 1.5, wall, 0, 0); w.position.set(s * (wid / 2 + 3), portalH / 2, 0); }
      const top = box(fr, wid + 12, portalH - 6, 1.5, wall, 0, 0); top.position.set(0, 6 + (portalH - 6) / 2, 0);
      const hole = new THREE.Mesh(new THREE.PlaneGeometry(wid, 6), new THREE.MeshBasicMaterial({ color: "#0b0d10", side: THREE.DoubleSide }));
      hole.position.set(0, 3, -0.3); fr.add(hole);
      fr.position.copy(P(px, pz, 0));
      fr.rotation.y = hor ? Math.PI / 2 : 0;
      g.add(fr);
    }
    addLabel(g, `🚇 ${z.name} (무선 단절)`, "zone", P((x0 + x1) / 2, (z0 + z1) / 2, portalH + 14));
  }
}

function buildCells(g, M) {
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
}

function buildZones(g, M, lw, MH) {
  if (M.region_border_x) {
    const bx = M.region_border_x;
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([P(bx, -40, 1), P(bx, MH + 40, 1)]),
      new THREE.LineDashedMaterial({ color: "#f59e0b", dashSize: 14, gapSize: 10 }));
    line.computeLineDistances();
    g.add(line);
    layers.zones.push(line);
    addLabel(g, "W 권역 ◀ 권역 경계(망 불안정) ▶ E 권역", "zone", P(bx, 20, 12));
  }
  for (const z of M.zones) {
    if (z.kind === "tunnel") continue;
    if (z.kind === "shadow") {
      const [x0, z0, x1, z1] = z.rect;
      overlayRect(g, z.rect, "#475569", 0.18, 0.3);
      addLabel(g, `🏢 ${z.name} (끊김이 몰려옴)`, "zone", P((x0 + x1) / 2, (z0 + z1) / 2, 60));
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
      FX.weather = new THREE.Group();
      const disc = new THREE.Mesh(new THREE.CircleGeometry(r, 64).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: "#1e3a5f", transparent: true, opacity: 0.12, depthWrite: false }));
      disc.position.copy(P(x, zz, 0.4));
      layers.zones.push(disc);
      const N = 2500, pos = new Float32Array(N * 3);
      for (let i = 0; i < N; i++) {
        const a = Math.random() * Math.PI * 2, rr = Math.sqrt(Math.random()) * r * 0.95;
        pos[i * 3] = x - W.W2 + Math.cos(a) * rr; pos[i * 3 + 1] = Math.random() * 120; pos[i * 3 + 2] = zz - W.H2 + Math.sin(a) * rr;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      FX.rain = new THREE.Points(geo, new THREE.PointsMaterial({ color: "#a5c8e8", size: 1.2, transparent: true, opacity: 0.55 }));
      FX.weather.add(disc, FX.rain);
      g.add(FX.weather);
      FX.weather.userData.label = addLabel(g, `🌧 ${z.name}`, "zone", P(x, zz, 60));
    }
  }
}

function buildPlaces(g, M, L) {
  for (const p of M.places) PLACE[p.id] = { ...p };
  for (const pb of L.place_buildings) {
    const p = PLACE[pb.place];
    if (pb.kind === "canopy") {                       // 충전소: 지붕 + 기둥
      box(g, pb.w + 4, 0.5, pb.d + 4, "#f4f4f2", pb.x, pb.z, 5.2);
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
    const note = { home: " (주차 = 시동 꺼짐)", work: " (근무 중 주차)", gas: " (충전 중 새 데이터 없음)", service: " (OTA·정비 대기)", depot: " (차고지)" }[p.kind] || "";
    addLabel(g, `${icon} ${p.name}${note}${p.wifi ? " 📶" : ""}`, "place", P(pb.x, pb.z, (pb.h || 6) + 8));
  }
  for (const p of M.places) if (p.kind === "gate")
    addLabel(g, `🚩 ${p.name}`, "place", P(p.pos[0] + (p.pos[0] < W.W2 ? 40 : p.pos[0] > W.W2 ? -40 : 0), p.pos[1] + (p.pos[1] < 50 ? 30 : p.pos[1] > 2 * W.H2 - 50 ? -30 : -12), 8));
}

// 신호등: 들어오는 차로마다 기둥·팔·등 (가로 3구)
function buildSignals(g, M, L, lw, SW, B) {
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
}

// 장식: 관중석(계단식 + 지붕 + 관중 점), 활주로, 출발선
function buildDecor(g, L) {
  for (const d of L.decor || []) {
    const [x0, z0, x1, z1] = d.rect, cx = (x0 + x1) / 2, cz = (z0 + z1) / 2, w = x1 - x0, dd = z1 - z0;
    const hor = w >= dd;
    if (d.kind === "grandstand") {
      const steps = 6, len = hor ? w : dd, dep = hor ? dd : w;
      for (let k = 0; k < steps; k++) {
        const off = (k / steps - 0.5) * dep;
        const bx = box(g, hor ? len : dep / steps, 1.2 + k * 1.3, hor ? dep / steps : len, k % 2 ? "#c9ced6" : "#b4bac3",
          cx + (hor ? 0 : off), cz + (hor ? off : 0));
        bx.receiveShadow = true;
      }
      const roof = box(g, hor ? len + 4 : dep + 4, 0.6, hor ? dep + 4 : len + 4, "#e5e7eb", cx, cz, 12);
      roof.castShadow = true;
      const n = Math.min(900, Math.floor(len * dep / 6));
      const crowd = new THREE.InstancedMesh(new THREE.BoxGeometry(0.5, 0.9, 0.5), new THREE.MeshStandardMaterial({ roughness: 0.9 }), n);
      const m4 = new THREE.Matrix4(), c = new THREE.Color();
      for (let i = 0; i < n; i++) {
        const k = i % steps, t = Math.random() - 0.5, off = ((k + 0.5) / steps - 0.5) * dep;
        m4.makeTranslation(cx - W.W2 + (hor ? t * len : off), 1.2 + k * 1.3 + 0.45, cz - W.H2 + (hor ? off : t * len));
        crowd.setMatrixAt(i, m4);
        crowd.setColorAt(i, c.setHSL(Math.random(), 0.6, 0.5));
      }
      g.add(crowd);
    } else if (d.kind === "runway") {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(w, dd).rotateX(-Math.PI / 2), mat("#3a3d42", { roughness: 0.9 }));
      m.position.copy(P(cx, cz, 0.03)); m.receiveShadow = true; g.add(m);
      for (let s = 30; s < (hor ? w : dd) - 30; s += 60) {
        const ln = new THREE.Mesh(new THREE.PlaneGeometry(hor ? 30 : 1.2, hor ? 1.2 : 30).rotateX(-Math.PI / 2), markMat("#f3f3f0"));
        ln.position.copy(P(hor ? x0 + s : cx, hor ? cz : z0 + s, 0.05)); g.add(ln);
      }
    } else if (d.kind === "startline") {
      const t = TEX.checker.clone(); t.needsUpdate = true; t.repeat.set(1, 4);
      const m = new THREE.Mesh(new THREE.PlaneGeometry(Math.max(w, 2.5), Math.max(dd, 10)).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({ map: t, polygonOffset: true, polygonOffsetFactor: -3, polygonOffsetUnits: -3 }));
      m.position.copy(P(cx, cz, 0.05)); g.add(m);
      const gantry = new THREE.Group();
      for (const s of [-1, 1]) box(gantry, 0.5, 7, 0.5, "#374151", 0, 0).position.set(0, 3.5, s * 7);
      box(gantry, 0.8, 1.2, 15, "#111827", 0, 0).position.set(0, 7, 0);
      gantry.position.copy(P(cx, cz, 0)); g.add(gantry);
    }
  }
}

// ------------------------------------------------------------------ 신호등 불빛 · 횡단보도 보행자
const SIGST = { green: "green", yellow: "yellow", red: "red", g: "green", y: "yellow", r: "red" };
const SIGCOL = { red: "#ff3b30", yellow: "#ffcc00", green: "#22e07a" };
export function updateSignals(sigs) {
  for (const [id, v] of Object.entries(sigs || {})) {
    const s = SIGNAL[id];
    if (!s) continue;
    const ax = { x: SIGST[v[0]], z: SIGST[v[1]] };
    for (const axis of ["x", "z"]) for (const lm of s.lamps[axis]) for (const c of ["red", "yellow", "green"]) {
      const on = ax[axis] === c;
      lm[c].color.set(on ? SIGCOL[c] : "#1a1a1a");
      lm[c].emissive.set(on ? SIGCOL[c] : "#000000");
      lm[c].emissiveIntensity = on ? 3 : 0;
    }
  }
}
export function updateCrossPeds(peds) {
  const mesh = FX.peds;
  if (!mesh) return;
  const m = new THREE.Matrix4(), c = new THREE.Color();
  const n = Math.min(128, (peds || []).length);
  for (let i = 0; i < n; i++) {
    const [x, z, dart] = peds[i];
    m.setPosition(x - W.W2, 0.9, z - W.H2);
    mesh.setMatrixAt(i, m);
    mesh.setColorAt(i, c.set(dart ? "#ef4444" : ["#334155", "#f8fafc", "#a16207", "#1d4ed8"][i % 4]));
  }
  mesh.count = n;
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
}
export function animateFx(dt) {
  if (FX.rain && FX.weather?.visible) {
    const p = FX.rain.geometry.attributes.position;
    for (let i = 0; i < p.count; i++) { let y = p.getY(i) - dt * 60; if (y < 0) y = 120; p.setY(i, y); }
    p.needsUpdate = true;
  }
}
