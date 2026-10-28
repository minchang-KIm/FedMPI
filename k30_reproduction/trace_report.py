#!/usr/bin/env python3
"""K30_TRACE=1로 돌린 실행의 run.log를 표로 풀고, 변인통제 점검과 제안기법 동작 요약을 만든다.

사용법: python k30_reproduction/trace_report.py <runs/실행이름 폴더 또는 run.log> [...]
출력:   <실행 폴더>/trace/*.csv, <실행 폴더>/trace/summary.md

CSV
  proc.csv           rank별 호스트, 노드, 요청/실제 스레드, affinity 수, 터보, 버전
  data.csv           클라이언트별 데이터 개수, 레이블 수, 레이블 분포
  agg_clients.csv    집계마다 참여 클라이언트별 staleness, 0.9^s, 데이터 계수, 실제 반영 가중치, 노드, 스레드
  rounds.csv         라운드별 정확도, loss, 쿼터, 참여 수, 노드별 참여 수, 대기/집계/평가 시간
  quota.csv          (SASAFL) 라운드별 global loss 변화 → 다음 쿼터 결정 과정
  client_updates.csv 로컬 학습마다 epoch 계획/최종/실행, 교체 횟수, 2 하한, 시간, 실제 코어 사용, 모델 변화량
  reception.csv      (SASAFL) 학습 중 글로벌 모델 수신 판단 (텍스트 로그에서 추출)
"""
import csv
import json
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

DEC = json.JSONDecoder()
RECV_BETTER = re.compile(r"CLIENT (\d+) >> gl: ([-\d.e]+), gl\^r-si: ([-\d.e]+) 이므로 최신 글로벌 모델을 받습니다")
RECV_KEEP = re.compile(r"CLIENT (\d+) >> gl: ([-\d.e]+), gl\^r-si: ([-\d.e]+)이므로 최신 글로벌 모델을 받지 않고")
RECV_LAG = re.compile(r"CLIENT (\d+) >> 로컬 staleness (\d+) 이므로 최신 글로벌 모델을 받습니다")
COMM = re.compile(r"CLIENT (\d+) >> communication delay는 (\d+)입니다")


def parse(log):
    ev = defaultdict(list)
    reception, comm = [], {}
    with open(log, errors="replace") as f:
        for line in f:
            i = line.find("TRACE {")
            while i != -1:
                try:
                    rec, end = DEC.raw_decode(line, i + 6)
                    ev[rec["ev"]].append(rec)
                except ValueError:
                    end = i + 6
                i = line.find("TRACE {", end)
            for m in RECV_BETTER.finditer(line):
                reception.append({"client": int(m[1]), "decision": "accept_better_loss", "gl": float(m[2]), "gl_prev": float(m[3])})
            for m in RECV_KEEP.finditer(line):
                reception.append({"client": int(m[1]), "decision": "keep_local", "gl": float(m[2]), "gl_prev": float(m[3])})
            for m in RECV_LAG.finditer(line):
                reception.append({"client": int(m[1]), "decision": "accept_lag_tolerance", "lag": int(m[2])})
            for m in COMM.finditer(line):
                comm[int(m[1])] = int(m[2])
    return ev, reception, comm


def write_csv(path, rows, fields=None):
    if not rows:
        return
    fields = fields or list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()})


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def fmt(x, d=3):
    return "—" if x is None else (f"{x:.{d}f}" if isinstance(x, float) else str(x))


def ok(cond):
    return "✅" if cond else "❌"


def report(run_dir, log):
    ev, reception, comm = parse(log)
    out = run_dir / "trace"
    out.mkdir(exist_ok=True)
    procs = {p["rank"]: p for p in ev["proc"]}
    threads = {r: p.get("threads_requested") for r, p in procs.items()}
    host = {r: p["host"] for r, p in procs.items()}
    server = procs.get(0, {})
    server_host = server.get("host")

    write_csv(out / "proc.csv", [{"rank": r, "role": p["role"], "host": p["host"], "group_rank": p["group_rank"],
                                  "local_rank": p["local_rank"], "threads_requested": p["threads_requested"],
                                  "torch_threads": p["torch_threads"], "interop_threads": p["interop_threads"],
                                  "n_affinity": len(p["affinity"]), "n_logical_cpus": p["n_logical_cpus"],
                                  "no_turbo": p["no_turbo"], "governor": p["governor"], "torch": p["torch_version"],
                                  "git": (p["git_head"] or "")[:7], "comm_delay": comm.get(r)}
                                 for r, p in sorted(procs.items())])
    data = {d["client"]: d for d in ev["data_client"]}
    write_csv(out / "data.csv", [{"client": c, "host": host.get(c), "threads": threads.get(c), "size": d["size"],
                                  "n_labels": d["n_labels"], "labels": d["labels"]} for c, d in sorted(data.items())])
    aggc = [dict(a, host=host.get(a["client"]), threads=threads.get(a["client"])) for a in ev["agg_client"]]
    write_csv(out / "agg_clients.csv", aggc)
    agg_by_round = {a["global_round"]: a for a in ev["aggregate"]}
    rounds = []
    for r in ev["round"]:
        a = agg_by_round.get(r["global_round"], {})
        rounds.append(dict(r, n_server_node=a.get("n_server_node"), n_remote_node=a.get("n_remote_node"),
                           old_global_retained=a.get("old_global_retained"), picked=a.get("picked")))
    write_csv(out / "rounds.csv", rounds)
    write_csv(out / "quota.csv", ev["quota"])
    ups = [dict(u, threads_requested=threads.get(u["client"])) for u in ev["client_update"]]
    write_csv(out / "client_updates.csv", ups)
    rec_rows = [dict(r, threads=threads.get(r["client"]), host=host.get(r["client"])) for r in reception]
    write_csv(out / "reception.csv", rec_rows)

    L = [f"# Trace 요약: {run_dir.name}", "", f"원본: `{log}`", ""]

    # ── 1. 변인통제 점검 ──
    L += ["## 1. 변인통제 점검", "", "| 항목 | 값 | 판정 |", "|---|---|---|"]
    clients = [r for r in procs if r != 0]
    K = server.get("world_size", 0) - 1
    L.append(f"| 프로세스 수 | 서버 1 + 클라이언트 {len(clients)} (WORLD_SIZE-1 = {K}) | {ok(len(clients) == K and K > 0)} |")
    per_host = Counter(host[r] for r in clients)
    L.append(f"| 노드별 클라이언트 | {dict(per_host)} (서버: {server_host}) | — |")
    mism = [r for r, p in procs.items() if p["threads_requested"] is not None and p["threads_requested"] != p["torch_threads"]]
    L.append(f"| 요청 스레드 = 실제 torch 스레드 | 불일치 rank {mism or '없음'} | {ok(not mism)} |")
    cat = Counter(threads[r] for r in clients)
    L.append(f"| 스레드 카테고리별 인원 | {dict(sorted(cat.items()))} | {ok(len(set(cat.values())) == 1)} |")
    for h in sorted(set(host.values())):
        tot = sum(procs[r]["torch_threads"] for r in procs if host[r] == h)
        ncpu = next(procs[r]["n_logical_cpus"] for r in procs if host[r] == h)
        L.append(f"| {h} 스레드 합 / 논리 CPU | {tot} / {ncpu} (배율 {tot / ncpu:.2f}) | {ok(tot <= ncpu)} (KISTI: 68코어에 ≤67) |")
    aff = {r for r, p in procs.items() if len(p["affinity"]) != p["n_logical_cpus"]}
    L.append(f"| CPU affinity 제한 | {'제한된 rank ' + str(sorted(aff)) if aff else '모든 rank가 전체 CPU 사용 가능 (코어 고정 없음)'} | — |")
    turbo = {host[r]: procs[r]["no_turbo"] for r in procs}
    L.append(f"| 터보 꺼짐(no_turbo=1) | {turbo} | {ok(all(v == '1' for v in turbo.values()))} |")
    gov = {host[r]: procs[r]["governor"] for r in procs}
    L.append(f"| CPU governor | {gov} | {ok(len(set(gov.values())) == 1)} |")
    for key, label in (("torch_version", "PyTorch"), ("python", "Python"), ("git_head", "git HEAD"), ("cpu_model", "CPU")):
        vals = {host[r]: procs[r][key] for r in procs}
        L.append(f"| {label} | {dict((h, (v or '')[:40]) for h, v in vals.items())} | {ok(len(set(vals.values())) == 1)} |")
    src = defaultdict(dict)
    for s in ev["sources"]:
        src[s["host"]].update(s["sha256"])
    if len(src) >= 2:
        hs = list(src)
        diff = sorted(f for f in set(src[hs[0]]) | set(src[hs[1]]) if src[hs[0]].get(f) != src[hs[1]].get(f))
        L.append(f"| 두 노드 소스 해시 | 다른 파일: {diff or '없음'} | {ok(not diff)} |")
    omp = {p["env"]["OMP_NUM_THREADS"] for p in procs.values()}
    L.append(f"| OMP/MKL/OpenBLAS 환경변수 | OMP_NUM_THREADS={omp} | {ok(omp == {'1'})} |")
    nz = {c: d for c, d in comm.items() if d}
    L.append(f"| 통신 지연 주입 | 0이 아닌 클라이언트 {nz or '없음'} | {ok(not nz)} |")
    bad_node = [a["client"] for a in ev["agg_client"]
                if (a["node"] == "server_node") != (host.get(a["client"]) == server_host)]
    L.append(f"| 노드 판정(rank 범위) = 실제 호스트 | 불일치 {sorted(set(bad_node)) or '없음'} | {ok(not bad_node)} |")
    if data:
        sizes = [d["size"] for d in data.values()]
        nl = Counter(d["n_labels"] for d in data.values())
        L.append(f"| 데이터 개수 | 합 {sum(sizes)}, 평균 {st.mean(sizes):.0f}, 표준편차 {st.pstdev(sizes):.0f}, "
                 f"최소 {min(sizes)}, 최대 {max(sizes)} | — (실행마다 다시 뽑힘, seed 없음) |")
        L.append(f"| 클라이언트당 레이블 수 | {dict(sorted(nl.items()))} | {ok(set(nl) <= {1, 2})} (논문: 1–2개) |")
    L.append("")

    # ── 2. 이기종성이 실제로 나타났는가 ──
    L += ["## 2. 스레드 카테고리별 실제 계산 속도 (이기종성이 실제로 나타났는가)", "",
          "| 스레드 | 학습 횟수 | 실제 사용 코어(CPU시간/벽시계) | epoch당 초 | 업로드 수(서버 수신) | 집계 참여 수 | 평균 staleness |",
          "|---:|---:|---:|---:|---:|---:|---:|"]
    up_by = Counter(threads.get(u["client"]) for u in ev["upload"])
    agg_by = defaultdict(list)
    for a in ev["agg_client"]:
        agg_by[threads.get(a["client"])].append(a)
    upd_by = defaultdict(list)
    for u in ups:
        upd_by[u["threads_requested"]].append(u)
    for t in sorted(k for k in set(upd_by) | set(agg_by) if k is not None):
        us = upd_by[t]
        L.append(f"| {t} | {len(us)} | {fmt(mean(u['cores_used'] for u in us), 2)} | {fmt(mean(u['sec_per_epoch'] for u in us), 2)} | "
                 f"{up_by.get(t, 0)} | {len(agg_by[t])} | {fmt(mean(a['staleness'] for a in agg_by[t]), 2)} |")
    L.append("")

    # ── 3. 제안기법 1: staleness 가중치 ──
    if ev["agg_client"]:
        L += ["## 3. 제안기법 1: staleness에 따른 반영 가중치", "",
              "집계식: 새 글로벌 = Σ cᵢ·[αᵢ·wᵢ + (1−αᵢ)·g], αᵢ = 0.9^sᵢ, cᵢ = 데이터 개수 비율 → 로컬 모델 wᵢ의 실제 반영 가중치 = cᵢ·αᵢ", "",
              "| staleness | 건수 | α=0.9^s | 평균 데이터 계수 | 평균 실제 반영 가중치 |", "|---:|---:|---:|---:|---:|"]
        by_s = defaultdict(list)
        for a in ev["agg_client"]:
            by_s[int(a["staleness"])].append(a)
        for s in sorted(by_s):
            xs = by_s[s]
            L.append(f"| {s} | {len(xs)} | {0.9 ** s:.3f} | {fmt(mean(a['data_coef'] for a in xs))} | {fmt(mean(a['effective_weight'] for a in xs))} |")
        ret = [a["old_global_retained"] for a in ev["aggregate"]]
        L += ["", f"집계마다 이전 글로벌 모델이 그대로 남는 비율(1 − Σcᵢαᵢ): 평균 {fmt(mean(ret))}, 최대 {fmt(max(ret))}", ""]

    # ── 4. 제안기법 2: 쿼터 ──
    if ev["quota"]:
        q = ev["quota"]
        L += ["## 4. 제안기법 2: global loss에 따른 최소 참여 수(쿼터)", "",
              f"C = {q[0]['C']}, K = {q[0]['K']}, C·K = {q[0]['CK']}, 최소 쿼터 int(C·K) = {q[0]['min_quota']}", "",
              "| 항목 | 값 |", "|---|---|"]
        same = sum(1 for x in q if x["prev_equals_cur"])
        L.append(f"| 비교에 쓴 이전 loss가 현재 loss와 같은 라운드 | {same}/{len(q)} (전부면 쿼터가 절대 바뀌지 않음 = 원본 코드 동작) |")
        L.append(f"| loss 증가 → 쿼터 증가 분기 | {sum(1 for x in q if x['branch'].startswith('loss_up'))} |")
        L.append(f"| 쿼터 분포 | {dict(sorted(Counter(x['next_quota'] for x in q).items()))} |")
        L.append(f"| 최소 쿼터에 머문 비율 | {sum(1 for x in q if x['next_quota'] == x['min_quota']) / len(q):.2%} |")
        L.append(f"| K(전원)까지 오른 라운드 | {sum(1 for x in q if x['next_quota'] == x['K'])} |")
        L.append("")
    if ev["round"]:
        rs = ev["round"]
        over = sum(1 for r in rs if r["n_picked"] > r["quota"])
        L += [f"실제 집계 인원 > 쿼터인 라운드: {over}/{len(rs)} (SASAFL은 쌓인 모델을 모두 쓰고, BSA는 쿼터만큼만 쓴다). "
              f"평균 집계 인원 {fmt(mean(r['n_picked'] for r in rs), 2)}, 평균 대기 {fmt(mean(r['wait_sec'] for r in rs), 2)}초, "
              f"대기 중 서버 CPU 사용 {fmt(mean(r['wait_cpu_sec'] / r['wait_sec'] if r['wait_sec'] else None for r in rs), 2)}코어", ""]

    # ── 5. epoch ──
    if ups:
        L += ["## 5. 참여 클라이언트의 local epoch (교체될 때마다 1씩 줄고 2 미만으로는 안 내려감)", "",
              "| 스레드 | 학습 횟수 | 교체 있었던 비율 | 평균 교체 횟수 | 평균 최종 목표 epoch | 2 하한 도달 | 평균 실제 실행 epoch | 교체 후 모델 변화 0인 학습 |",
              "|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for t in sorted(k for k in upd_by if k is not None):
            us = upd_by[t]
            sw = [u for u in us if u["swaps"]]
            frozen = sum(1 for u in sw if u["delta_norm_from_base"] == 0)
            L.append(f"| {t} | {len(us)} | {len(sw) / len(us):.0%} | {fmt(mean(u['swaps'] for u in us), 2)} | "
                     f"{fmt(mean(u['epochs_final_target'] for u in us), 2)} | {sum(u['hit_floor_2'] for u in us)} | "
                     f"{fmt(mean(u['epochs_executed_total'] for u in us), 2)} | {frozen}/{len(sw)} |")
        L += ["", "‘교체 후 모델 변화 0’: 글로벌 모델로 교체한 뒤 남은 epoch을 돌았는데 모델이 전혀 바뀌지 않은 학습 "
              "(optimizer가 교체 전 모델의 파라미터를 계속 가리키면 생긴다).", ""]

    # ── 6. 노드 ──
    if ev["agg_client"]:
        n = Counter(a["node"] for a in ev["agg_client"])
        L += ["## 6. 집계 참여자의 노드 (서버와 같은 노드 / 다른 노드에서 네트워크로 온 모델)", "",
              f"서버 노드({server_host}): {n.get('server_node', 0)}건, 다른 노드: {n.get('remote_node', 0)}건", "",
              "| 노드 | 스레드 | 집계 참여 | 평균 큐 대기(초) |", "|---|---:|---:|---:|"]
        g = defaultdict(list)
        for a in ev["agg_client"]:
            g[(a["node"], threads.get(a["client"]))].append(a)
        for (nd, t), xs in sorted(g.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
            L.append(f"| {nd} | {t} | {len(xs)} | {fmt(mean(a['queue_wait_sec'] for a in xs), 2)} |")
        L.append("")

    # ── 7. 수신 판단 ──
    if reception:
        L += ["## 7. 학습 중 글로벌 모델 수신 판단 (SASAFL)", "", "| 스레드 | 받음(loss 개선) | 받음(lag tolerance) | 안 받음 |", "|---:|---:|---:|---:|"]
        rb = defaultdict(Counter)
        for r in rec_rows:
            rb[r["threads"]][r["decision"]] += 1
        for t in sorted(k for k in rb if k is not None):
            c = rb[t]
            L.append(f"| {t} | {c['accept_better_loss']} | {c['accept_lag_tolerance']} | {c['keep_local']} |")
        L.append("")

    (out / "summary.md").write_text("\n".join(L) + "\n")
    print(f"{run_dir}: trace 이벤트 {sum(len(v) for v in ev.values())}개 → {out}/summary.md")


def main():
    for arg in sys.argv[1:]:
        p = Path(arg)
        log = p / "run.log" if p.is_dir() else p
        report(log.parent, log)


if __name__ == "__main__":
    main()
