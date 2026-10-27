// 공용: 상수(상태·패턴 색), DOM 도우미, 화면 전체가 함께 쓰는 상태 S, 접속자(ME)와 서버 요청
export const STATE = {
  idle: ["대기", "#e2e8f0"], training: ["학습", "#3b82f6"], uploading: ["전송", "#f97316"],
  waiting: ["대기열", "#eab308"], queued: ["보관", "#a855f7"], skipped: ["미참여", "#94a3b8"],
  dead: ["끊김", "#ef4444"], excluded: ["영구 제외", "#991b1b"], parked: ["주차(시동 꺼짐)", "#64748b"], absent: ["맵 밖", "#334155"],
};
export const PCOL = { 1: "#f87171", 2: "#fb923c", 3: "#cbd5e1", 4: "#facc15", 5: "#c084fc", 6: "#f472b6", 7: "#4ade80", 8: "#38bdf8" };
export const PDESC = { // 서버에서 보는 모습 · 서버 대응
  1: "아무 응답 없음 → 해당 차량 제외", 2: "일부 조각만 도착 → 폐기 (SASAFL은 조각이 없어 패턴 1처럼 보임)",
  3: "이번 라운드 미참여 → 복귀 시 최신 글로벌 모델 전달", 4: "낮은 버전의 값 도착 → SASAFL은 버리지 않고 감쇄해 반영",
  5: "한 차량에서 오래된 값 여러 개 → 개별 처리 (SASAFL은 버퍼 1칸이라 덮어씀)", 6: "오류 있는 값을 계속 보냄 → 대응 없음",
  7: "같은 차량만 계속 참여 → epoch 축소(SASAFL)·CFCFM(SAFA)", 8: "서버 장애·무한 대기·성능 지속 감소 → 복구·시간 제한·강제 갱신",
};
export const KIND = { commute: "통근", city: "택시", resident: "주민", visitor: "통과" };
export const KCOL = { commute: "#38bdf8", city: "#facc15", resident: "#4ade80", visitor: "#c084fc" };
export const PERIODS = [["night", "야간 00–07"], ["am", "출근 07–09:30"], ["day", "주간 09:30–17"], ["pm", "퇴근 17–19:30"], ["evening", "저녁 19:30–23"]];
export const ZONE_NAME = { tunnel: "터널", shadow: "음영", congestion: "혼잡", school: "보호구역", wifi: "Wi-Fi", weather: "강우" };
export const ZONE_ICON = { tunnel: "🚇", shadow: "🏙", congestion: "🚗", school: "🏫", wifi: "📶", weather: "🌧" };

export const $ = (s) => document.querySelector(s);
export const $$ = (s) => [...document.querySelectorAll(s)];
export const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; return e; };
export const fmtT = (t) => new Date(t * 1000).toLocaleTimeString("ko-KR", { hour12: false });
export const fmtH = (h) => { h = ((h % 24) + 24) % 24; const m = Math.round((h % 1) * 60) % 60; return `${String(Math.floor(h)).padStart(2, "0")}:${String(m).padStart(2, "0")}`; };
export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const hash = (n) => { let x = (n | 0) * 2654435761; x ^= x >>> 15; return Math.abs(x) >>> 0; };
export const store = {                                    // 브라우저 저장 (막혀 있어도 동작)
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 저장 못 해도 화면은 그대로 */ } },
};

/** 화면 전체가 함께 쓰는 상태 */
export const S = {
  STATIC: null, CFG: null, LAST: null, MAP: null, LAY: null, MAP_ID: null,
  evOffset: 0, selected: 1, REPLAY: null, PEERS: [], DRIVERS: {}, CAM: "orbit", TIME_FIX: null,
};

// 접속자: 브라우저마다 id·이름. 모든 요청 헤더에 붙여 접속자 목록·운전자·설정 변경 기록에 쓴다
export const ME = store.get("vfl_me", {});
if (!ME.id) ME.id = Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
store.set("vfl_me", ME);
export function askName() {
  const n = prompt("이름을 입력하세요 (다른 사람에게 운전자·설정 변경자로 보입니다)", ME.name || "");
  if (n && n.trim()) { ME.name = n.trim().slice(0, 20); store.set("vfl_me", ME); }
  $("#meName").textContent = ME.name || "이름 없음";
}
async function request(url, opt = {}) {
  const r = await fetch(url, { ...opt, headers: { ...(opt.headers || {}), "X-Client-Id": ME.id, "X-Client-Name": encodeURIComponent(ME.name || "") } });
  if (r.status === 401) location.reload();                // 접속 코드가 바뀜 → 코드 입력 화면
  return r;
}
export const api = {
  get: async (url) => (await request(url)).json(),
  post: async (url, body) => (await request(url, { method: "POST", body: typeof body === "string" || body instanceof ArrayBuffer ? body : JSON.stringify(body) })).json(),
  beacon: (url, body) => navigator.sendBeacon(url, JSON.stringify(body)),
};

export function vtypeOf(vid, cfg = S.CFG) {
  const v = { ...(cfg?.vehicle_default || {}), ...((cfg?.vehicles || {})[String(vid)] || {}) };
  return v.vtype || (vid % 2 === 1 ? "new" : "old");
}
/** 경로 이름표 (맵 경로에 label이 있으면 그것, 아니면 종류) */
export function kindLabel(s) {
  return S.MAP?.routes?.[s?.route]?.label || KIND[s?.kind] || "";
}
