// 사건: 실시간 사건 목록·전체 기록·알림, 유스케이스 34 표(발생 횟수·차량), 맵에서 그 장소로 이동
import { $, el, S, PCOL, PDESC, fmtT } from "./util.js";
import { floatAt, flashArrival } from "./cars.js";
import { hudNote } from "./drive.js";
import { focusOn, focusPoint } from "./view.js";

const caseCount = {}, caseLast = {}, caseVeh = {};
export const ALL_EVENTS = [];
let logFilter = null, casesTimer = null;
const KIND_TAG = { round: "집계", arrive: "도착", upload: "전송", world: "환경", control: "제어", fl: "FL" };

export function evLine(e) {
  const p = e.pattern, d = el("div", "ev");
  d.style.setProperty("--pc", p ? PCOL[p] : "var(--line)");
  const tag = p ? `<span class="pt" style="background:${PCOL[p]}">${e.example}</span>` : `<span class="pt neutral">${KIND_TAG[e.kind] || e.kind}</span>`;
  d.innerHTML = `${tag}<span class="msg">${e.vid ? `<b>V${e.vid}</b> ` : ""}${e.msg}</span><span class="tm">${fmtT(e.t)}</span>`;
  return d;
}
const shortName = (ex) => { const u = S.STATIC.usecases.find((x) => x[0] === ex); return u ? u[1].split(" (")[0] : ""; };
/** 실시간 사건 목록에 보여 줄 사건 (환경 사건은 긴급제동·운전·충돌만) */
const showInFeed = (e) => e.kind !== "world" || /긴급제동/.test(e.msg) || e.manual || e.ped_hit !== undefined;

export function handleEvents(evs, quiet = false) {
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
    if (S.CAM === "fpv" && e.vid === S.selected && (e.manual || e.example || e.ped_hit !== undefined))
      hudNote(e.example ? `${e.example} ${shortName(e.example)} — ${e.msg}` : e.msg, e.example ? PCOL[e.pattern] : "#334155");
    if (showInFeed(e)) {
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
/** 다시 보기: 그 시점까지의 사건으로 목록을 다시 채운다 */
export function replayEvents(upto) {
  resetEvents();
  handleEvents(upto, true);
  for (const e of upto.slice(-80)) if (showInFeed(e)) $("#eventFeed").prepend(evLine(e));
}
export function toast(e) {
  const box = $("#toastBox");
  const head = e.pattern ? `<b style="color:${PCOL[e.pattern]}">P${e.pattern} ${S.STATIC.patterns[e.pattern]} · ${e.example} ${shortName(e.example)}</b><br>` : "";
  const t = el("div", "toast", `${head}${e.vid ? `V${e.vid} — ` : ""}${e.msg}`);
  if (e.pattern) t.style.setProperty("--pc", PCOL[e.pattern]);
  box.appendChild(t);
  while (box.children.length > 4) box.firstChild.remove();
  setTimeout(() => t.remove(), 5000);
}
export function resetEvents() {
  for (const o of [caseCount, caseLast, caseVeh]) for (const k in o) delete o[k];
  ALL_EVENTS.length = 0;
  for (const id of ["#roundFeed", "#eventFeed", "#logList", "#toastBox"]) $(id).innerHTML = "";
}

// ------------------------------------------------------------------ 유스케이스 표 (갱신은 1초에 한 번)
function scheduleCases() { if (!casesTimer) casesTimer = setTimeout(() => { casesTimer = null; renderCases(); }, 1000); }
export function renderCases(nowT = Date.now() / 1000) {
  const total = Object.keys(caseCount).length;
  const cov = Object.fromEntries((S.STATIC.coverage || []).map((c) => [c.id, c]));
  const okN = (S.STATIC.coverage || []).filter((c) => c.ok).length;
  $("#caseCount").textContent = `${total}/34`;
  let html = `<div class="case-sum"><div><b>${total}</b><span>이번 실행에서 일어난 유스케이스</span></div>
    <div><b class="ok">${okN}/34</b><span>지금 맵(${S.MAP?.name || ""})에서 일으킬 수 있음</span></div>
    <p class="muted small">행을 누르면 맵에서 그 장소로 이동합니다.</p></div>`;
  for (const [p, name] of Object.entries(S.STATIC.patterns)) {
    const rows = S.STATIC.usecases.filter((u) => u[0].startsWith(p + "-"));
    const sum = rows.reduce((a, u) => a + (caseCount[u[0]] || 0), 0);
    html += `<div class="ptitle"><span class="pt" style="background:${PCOL[p]}">P${p}</span>${name}<span class="muted small">${sum}회</span></div>
      <div class="pdesc">${PDESC[p]}</div>
      <table class="cases"><tr><th style="width:46px">id</th><th>예시</th><th>근거</th><th>맵·설정에서</th><th style="width:46px">이 맵</th><th style="width:56px">발생</th><th style="width:90px">차량</th></tr>`;
    for (const [id, ex, ev, where] of rows) {
      const n = caseCount[id] || 0, recent = caseLast[id] && nowT - caseLast[id] < 6;
      html += `<tr class="${recent ? "recent" : n ? "hit" : ""}" data-id="${id}"><td><b>${id}</b></td><td>${ex}</td><td class="muted">${ev}</td>
        <td>${where}</td><td title="${cov[id]?.how || ""}">${cov[id] ? (cov[id].ok ? "✅" : "❌") : ""}</td><td class="cnt">${n || "-"}</td>
        <td>${caseVeh[id] ? [...caseVeh[id]].sort((a, b) => a - b).map((v) => "V" + v).join(" ") : ""}</td></tr>`;
    }
    html += "</table>";
  }
  const box = $("#caseTable");
  box.innerHTML = html;
  box.querySelectorAll("tr[data-id]").forEach((tr) => (tr.onclick = () => focusOn(focusPoint(tr.dataset.id))));
}
export function buildLogFilter() {
  const box = $("#logFilter");
  box.innerHTML = "";
  const mk = (p, text, col) => {
    const b = el("button", "btn small" + (p === logFilter ? " on" : ""), text);
    if (col) b.style.setProperty("--pc", col);
    b.onclick = () => {
      logFilter = p;
      box.querySelectorAll(".btn").forEach((x) => x.classList.toggle("on", x === b));
      const log = $("#logList");
      log.innerHTML = "";
      for (const e of ALL_EVENTS.slice(-600)) if (!p || e.pattern === p) log.prepend(evLine(e));
    };
    box.appendChild(b);
  };
  mk(null, "전체");
  for (const [p, n] of Object.entries(S.STATIC.patterns)) mk(Number(p), `P${p} ${n}`, PCOL[p]);
}
