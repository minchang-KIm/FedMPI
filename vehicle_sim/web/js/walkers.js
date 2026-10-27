// 길을 걷는 사람: 차에 치이면 날아갔다가(포물선·회전) 쓰러지고 다시 일어나 걷는다. 서버 상태를 받아 프레임마다 내다보며 그린다
import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { S } from "./util.js";
import { W } from "./scene.js";

// 한 사람 = 다리·몸통·팔·머리. 원점은 몸 가운데(키 1.75 m의 0.9 m 높이)라 넘어지고 회전하는 축이 된다
const WALKER_GEO = mergeGeometries([
  new THREE.BoxGeometry(0.16, 0.82, 0.14).translate(0, -0.49, -0.11), new THREE.BoxGeometry(0.16, 0.82, 0.14).translate(0, -0.49, 0.11),
  new THREE.BoxGeometry(0.26, 0.62, 0.42).translate(0, 0.22, 0),
  new THREE.BoxGeometry(0.12, 0.6, 0.1).translate(0, 0.2, -0.27), new THREE.BoxGeometry(0.12, 0.6, 0.1).translate(0, 0.2, 0.27),
  new THREE.SphereGeometry(0.13, 10, 8).translate(0, 0.7, 0)].map((g) => g.toNonIndexed()));
const WCOL = ["#1e3a8a", "#b91c1c", "#f8fafc", "#065f46", "#a16207", "#6d28d9", "#334155", "#be185d"];
const WK = {};                                           // id → {s: 마지막 상태, t: 받은 시각, p: 그려진 위치, tilt, yaw}
let mesh = null;

export function createWalkerMesh() {
  for (const k of Object.keys(WK)) delete WK[k];
  mesh = new THREE.InstancedMesh(WALKER_GEO, new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.8 }), 256);
  mesh.count = 0;
  mesh.castShadow = true;
  mesh.frustumCulled = false;
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  return mesh;
}

const tmp = new THREE.Vector3();
/** list = [[id, x, z, y, yaw, tilt, 상태, vx, vz, vy, 회전 속도], ...]. partial = 일부만 받음 (운전 중 주변 사람) */
export function updateWalkers(list, partial = false) {
  const now = performance.now(), seen = new Set();
  for (const a of list || []) {
    const [id, x, z, y, yaw, tilt, st, vx = 0, vz = 0, vy = 0, spin = 0] = a;
    seen.add(id);
    const w = WK[id] || (WK[id] = { p: new THREE.Vector3(x - W.W2, y, z - W.H2), tilt, yaw });
    w.s = { x: x - W.W2, z: z - W.H2, y, yaw, tilt, st, vx, vz, vy, spin };
    w.t = now;
    if (w.p.distanceTo(tmp.set(x - W.W2, y, z - W.H2)) > 30) { w.p.copy(tmp); w.tilt = tilt; }
  }
  if (!partial) for (const k of Object.keys(WK)) if (!seen.has(Number(k))) delete WK[k];
}

const q = new THREE.Quaternion(), q2 = new THREE.Quaternion(), m4 = new THREE.Matrix4(), one = new THREE.Vector3(1, 1, 1),
  col = new THREE.Color(), AX_Y = new THREE.Vector3(0, 1, 0), AX_Z = new THREE.Vector3(0, 0, 1);
export function drawWalkers(now, dt) {
  if (!mesh) return;
  let n = 0;
  for (const [id, w] of Object.entries(WK)) {
    if (n >= 256) break;
    const s = w.s, age = Math.min(S.REPLAY ? 0 : 0.6, (now - w.t) / 1000);
    // 받은 상태에서 속도로 내다본 위치 (날아가는 중엔 포물선)
    tmp.set(s.x + s.vx * age, s.st === 2 ? Math.max(0, s.y + s.vy * age - 4.9 * age * age) : s.y, s.z + s.vz * age);
    w.p.lerp(tmp, Math.min(1, dt * (s.st === 2 || s.st === 3 ? 20 : 8)));
    const tt = s.tilt + (s.st === 2 ? s.spin * age : 0);
    w.tilt += (tt - w.tilt) * Math.min(1, dt * (s.st === 2 ? 20 : 8));
    let dy = s.yaw - w.yaw;
    dy = Math.atan2(Math.sin(dy), Math.cos(dy));
    w.yaw += dy * Math.min(1, dt * 8);
    const bob = s.st <= 1 ? Math.abs(Math.sin(now / 160 + Number(id))) * 0.05 : 0;
    const ct = Math.abs(Math.cos(w.tilt)), stt = Math.abs(Math.sin(w.tilt));
    q.setFromAxisAngle(AX_Y, -w.yaw).multiply(q2.setFromAxisAngle(AX_Z, w.tilt));
    tmp.set(w.p.x, w.p.y + 0.9 * ct + 0.2 * stt + bob, w.p.z);
    mesh.setMatrixAt(n, m4.compose(tmp, q, one));
    mesh.setColorAt(n, col.set(WCOL[Number(id) % WCOL.length]));
    n++;
  }
  mesh.count = n;
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
}
