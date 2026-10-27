#!/usr/bin/env python3
"""화면 서버 + 실행 관리. 표준 라이브러리만 쓴다 (FL 환경에 flask 없음).

  python vehicle_sim/serve.py [--port 8765]
  → 브라우저에서 http://localhost:8765  (원격이면 VS Code 포트 포워딩)

API
  GET  /api/static              맵·패턴·유스케이스·학습 방식·차량 종류·설정 기본값·맵 목록
  GET  /api/state?ev=<오프셋>    world / server / clients / 새 사건 / 실행 상태
  POST /api/config              설정 일부 변경 (깊은 병합)
  POST /api/drive               {vid, on, throttle, brake, steer, reverse, park} 선택 차량 수동 운전 입력
                                (차량마다 한 사람: 다른 사람이 운전 중인 차는 409)
여러 사람이 함께 쓰기
  --host 0.0.0.0 으로 띄우면 같은 네트워크의 다른 컴퓨터가 접속한다. --code 를 주면 처음 접속할 때 그 코드를 물어본다.
  브라우저마다 X-Client-Id / X-Client-Name 헤더 → 접속자 목록·운전자 이름·설정을 바꾼 사람이 사건 기록에 남는다.
  POST /api/control             {"action": "start"|"stop"|"server_down"|"ablation"|"save"|"load"|"reset_config", ...}
  GET  /api/maps · POST /api/map {name, map}           맵 목록 · 맵 올리기(검사 후 저장)
  GET  /api/saves                                     저장한 상태 목록
  GET  /api/runs · /api/replay?run= · /api/export?run=  실행 기록 목록 · 다시 보기 데이터 · 묶음 내려받기
  POST /api/import (tar.gz 본문)                       실행 기록 불러오기
"""

import argparse
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "simcore"))
import common as C  # noqa: E402
import mapgeo as G  # noqa: E402

PY = os.environ.get("SIM_PY", "/home/wise-175/anaconda3/envs/FL/bin/python")
WEB = HERE / "web"
SAVED_CFG = HERE / "config_last.json"
ACCESS_CODE = ""                       # --code: 비어 있으면 묻지 않음
PEERS = {}                             # 접속자 id → {name, seen, sel}
DRIVES = {}                            # 차량 id(str) → {client, name, 입력…, t}
DRIVE_LOCK = threading.Lock()
LOGIN_HTML = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>차량 FL 시뮬레이터</title><body style="font-family:system-ui;background:#090e1b;color:#f1f5ff;display:grid;place-items:center;height:100vh;margin:0">
<form style="background:#101a2f;padding:28px 32px;border-radius:14px;border:1px solid #2a3b60;display:flex;flex-direction:column;gap:10px">
<b style="font-size:18px">차량 연합학습 장애 시뮬레이터</b><span style="color:#a3b3d1">접속 코드를 입력하세요</span>
<input name=code autofocus style="font-size:18px;padding:8px;border-radius:8px;border:1px solid #2a3b60;background:#0b1328;color:#fff">
<button style="padding:8px;border-radius:8px;background:#5b9cff;color:#fff;border:0;font-weight:700">입장</button></form></body>"""
SAVE_FILES = ["config.json", "world_state.json", "checkpoint.pt", "server.json", "events.jsonl", "world_hist.jsonl"]


def deep_merge(base, patch):
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        elif v is None and isinstance(base, dict) and k in base and k.isdigit():
            base.pop(k)
        else:
            base[k] = v
    return base


def fill_defaults(cfg):
    for k, v in C.DEFAULT_CONFIG.items():
        if isinstance(v, dict):
            cfg.setdefault(k, {})
            for kk, vv in v.items():
                cfg[k].setdefault(kk, vv)
    return cfg


def describe_patch(patch, prefix=""):
    """{"fl": {"lr": 0.02}, "vehicles": {"3": {"aeb": false}}} → "fl.lr=0.02, V3.aeb=false" """
    out = []
    for k, v in patch.items():
        key = f"V{k}" if prefix == "vehicles." else prefix + k
        if isinstance(v, dict):
            out.append(describe_patch(v, "vehicles." if k == "vehicles" and not prefix else key + "."))
        else:
            out.append(f"{key}={json.dumps(v, ensure_ascii=False)}")
    return ", ".join(x for x in out if x)


def safe_name(s):
    return "".join(ch for ch in str(s) if ch.isalnum() or ch in "-_") or "save"


class Manager:
    def __init__(self):
        self.lock = threading.Lock()
        self.run_dir = None
        self.procs = {}
        self.started = None
        self.note = ""
        self.cfg = fill_defaults(C.read_json(SAVED_CFG, None) or json.loads(json.dumps(C.DEFAULT_CONFIG)))
        cur = C.RUNS / "current"
        if cur.exists():
            self.run_dir = cur.resolve()

    def save_cfg(self):
        C.write_json(SAVED_CFG, self.cfg)
        fl = self.procs.get("fl")
        if self.run_dir and fl is not None and fl.poll() is None:   # 실행 중일 때만 반영 (끝난 실행 기록은 그대로)
            C.write_json(self.run_dir / "config.json", self.cfg)

    def status(self):
        st = {name: ("running" if p.poll() is None else f"exit {p.returncode}") for name, p in self.procs.items()}
        fl = self.procs.get("fl")
        if fl is not None and fl.poll() is not None and not getattr(fl, "_reported", False):
            fl._reported = True
            self.report_fl_exit(fl.returncode)
        return st

    def report_fl_exit(self, code):
        try:
            tail = (self.run_dir / "fl.log").read_text(errors="replace").splitlines()[-400:]
        except FileNotFoundError:
            tail = []
        errs = [ln.strip() for ln in tail if ln.strip().startswith(("ValueError", "RuntimeError", "TypeError",
                                                                    "AttributeError", "IndexError", "KeyError"))]
        cause = errs[-1] if errs else ""
        if "NaN" in cause:
            msg = ("서버 종료: 오류 값(패턴 6)으로 global loss가 NaN → SASAFL quota 계산 int(NaN) 예외 "
                   "(SASAFLServer.py:194)")
        else:
            msg = f"학습 프로세스 종료 (exit {code}) {cause}"
        if code != 0:
            self.note = msg
            C.emit(self.run_dir, "fl", example="8-1", msg=msg)

    # ---------------------------------------------------------------- 실행
    def start(self, resume_dir=None, tag=""):
        with self.lock:
            self.stop_locked()
            self.run_dir = C.new_run_dir(tag)
            if resume_dir:
                saved = C.read_json(Path(resume_dir) / "config.json", None)
                if saved:
                    self.cfg = fill_defaults(saved)
                    C.write_json(SAVED_CFG, self.cfg)
            C.write_json(self.run_dir / "config.json", self.cfg)
            fl = self.cfg["fl"]
            K = int(fl["K"])
            env = dict(os.environ, SIM_RUN_DIR=str(self.run_dir), PYTHONUNBUFFERED="1",
                       OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
            if resume_dir:
                env["SIM_RESUME_DIR"] = str(resume_dir)
            self.procs["world"] = subprocess.Popen(
                [PY, str(HERE / "simcore" / "world.py"), str(self.run_dir)], env=env,
                stdout=open(self.run_dir / "world.log", "w"), stderr=subprocess.STDOUT, start_new_session=True)
            port = 29880 + int(time.time()) % 90
            args = ["--selection_ratio", str(fl["C"]), "--round", "100000", "--batch_size", str(fl["batch"]),
                    "--local_epochs", str(fl["epochs"]), "--lr", str(fl["lr"]), "--target_acc", "1.0",
                    "--dataset", fl["dataset"], "--iid", "False",
                    "--split", "gaussian" if fl["split"] == "dirichlet" else fl["split"],
                    "--method", "SASAFL", "--lag_tolerance", str(fl["tau"]), "--wandb_on", "False",
                    "--repeat", "1", "--cluster_type", "KISTI", "--num_threads", "1" * (K + 1)]
            self.procs["fl"] = subprocess.Popen(
                [PY, "-m", "torch.distributed.run", "--nnodes=1", f"--nproc_per_node={K + 1}",
                 f"--rdzv_id=vfl{port}", "--master_addr=127.0.0.1", f"--master_port={port}",
                 f"--rdzv_endpoint=127.0.0.1:{port}", str(HERE / "fl" / "fl_entry.py")] + args,
                cwd=str(C.REPO), env=env, stdout=open(self.run_dir / "fl.log", "w"),
                stderr=subprocess.STDOUT, start_new_session=True)
            self.started = time.time()
            self.note = ""
            m, meth = C.method_of(self.cfg)
            C.emit(self.run_dir, "control", msg=f"시작: 차량 {K}대, {fl['dataset']}, {meth['name']}, C={fl['C']}, "
                                                f"τ={fl['tau']}, 시드 {fl.get('seed')}, 맵 {self.cfg['world'].get('map')}"
                                                + (f" — 저장 상태 {Path(resume_dir).name}에서 이어서" if resume_dir else ""))

    def stop_locked(self):
        for p in list(self.procs.values()):
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                p.wait(timeout=10)
        self.procs = {}

    def stop(self):
        with self.lock:
            self.stop_locked()
            if self.run_dir:
                C.emit(self.run_dir, "control", msg="시뮬레이션 정지")

    def server_down(self, seconds):
        """8-1 집계 서버 장애: 정해진 시간 동안 배포·수신·집계를 멈췄다가 복구"""
        if not self.run_dir:
            return
        C.write_json(self.run_dir / "server_ctl.json", {"down_until": time.time() + float(seconds)})
        C.emit(self.run_dir, "control", msg=f"집계 서버 장애 주입: {seconds:.0f}초 동안 중단 후 복구")

    def save(self, name):
        if not self.run_dir:
            return None
        d = C.SAVES / f"{safe_name(name)}_{time.strftime('%m%d_%H%M%S')}"
        d.mkdir(parents=True, exist_ok=True)
        for f in SAVE_FILES:
            if (self.run_dir / f).exists():
                shutil.copy2(self.run_dir / f, d / f)
        for f in self.run_dir.glob("client_*.json"):
            shutil.copy2(f, d / f.name)
        s = C.read_json(self.run_dir / "server.json", {}) or {}
        C.write_json(d / "meta.json", {"name": name, "saved": time.time(), "run": self.run_dir.name,
                                       "round": s.get("round"), "method": self.cfg["fl"].get("method"),
                                       "map": self.cfg["world"].get("map")})
        C.emit(self.run_dir, "control", msg=f"현재 상태 저장: {d.name} ({s.get('round')}라운드)")
        return d.name


MGR = Manager()


_LAYOUT = {}


def layout_of(name, m):
    """맵 배치(주차장·건물·나무)는 계산이 조금 걸려 맵 파일 시각으로 캐시"""
    key = (name, (C.MAPS / f"{name}.json").stat().st_mtime if (C.MAPS / f"{name}.json").exists() else 0)
    if key not in _LAYOUT:
        _LAYOUT.clear()
        _LAYOUT[key] = G.map_layout(m)
    return _LAYOUT[key]


def map_list():
    out = []
    for n in G.list_maps():
        m = G.load_map(n)
        cov = G.map_coverage(m, MGR.cfg)
        out.append({"id": n, "name": m.get("name", n), "desc": m.get("desc", ""), "size": m.get("size"),
                    "ok": sum(c["ok"] for c in cov), "missing": [c["id"] for c in cov if not c["ok"]]})
    return out


def read_events(path, offset, limit=400):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if offset > size:
                offset = 0
            if size - offset > 400_000:
                offset = size - 400_000
            f.seek(offset)
            data = f.read()
    except FileNotFoundError:
        return [], 0
    lines = data.split(b"\n")
    tail = lines.pop()
    end = offset + len(data) - len(tail)
    out = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out, end


def run_summary(d):
    cfg = C.read_json(d / "config.json", {}) or {}
    s = C.read_json(d / "server.json", {}) or {}
    hist = s.get("history") or []
    return {"run": d.name, "method": cfg.get("fl", {}).get("method"), "seed": cfg.get("fl", {}).get("seed"),
            "map": cfg.get("world", {}).get("map"), "K": cfg.get("fl", {}).get("K"),
            "rounds": s.get("round"), "acc": hist[-1]["acc"] if hist else None,
            "curve": [[h["round"], h["acc"]] for h in hist[:: max(1, len(hist) // 120)]],
            "events": sum(1 for _ in open(d / "events.jsonl")) if (d / "events.jsonl").exists() else 0}


def load_jsonl(path, limit=None, every=1):
    out = []
    try:
        with open(path) as f:
            for i, ln in enumerate(f):
                if i % every:
                    continue
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    return out[-limit:] if limit else out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def authed(self, q):
        if not ACCESS_CODE:
            return True
        if q.get("code", [""])[0] == ACCESS_CODE:
            return True
        cookie = self.headers.get("Cookie", "")
        return any(c.strip() == f"vfl_code={ACCESS_CODE}" for c in cookie.split(";"))

    def gate(self, u, q):
        """접속 코드 확인. 통과하면 None, 아니면 응답을 보내고 True"""
        if self.authed(q):
            if ACCESS_CODE and q.get("code"):          # 코드를 쿠키로 바꾸고 주소에서 지운다
                self.send(302, b"", "text/plain", {"Location": u.path or "/",
                          "Set-Cookie": f"vfl_code={ACCESS_CODE}; Path=/; Max-Age=2592000; SameSite=Lax"})
                return True
            return None
        if u.path.startswith("/api/"):
            self.send(401, {"ok": False, "error": "접속 코드 필요"})
        else:
            self.send(200, LOGIN_HTML, "text/html; charset=utf-8")
        return True

    def who(self):
        """요청한 접속자 (id, 이름) — 접속자 목록도 갱신"""
        cid = self.headers.get("X-Client-Id", "")[:40]
        name = unquote(self.headers.get("X-Client-Name", ""))[:20] or "익명"
        if cid:
            PEERS[cid] = {**PEERS.get(cid, {}), "name": name, "seen": time.time(), "ip": self.client_address[0]}
        return cid, name

    def run_path(self, q):
        name = q.get("run", [""])[0]
        d = (C.RUNS / name).resolve()
        if not name or C.RUNS.resolve() not in d.parents or not d.is_dir():
            return None
        return d

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if self.gate(u, q):
            return
        cid, _ = self.who()
        if u.path == "/api/static":
            name = q.get("map", [MGR.cfg["world"].get("map", "default")])[0]
            m = G.load_map(name)
            return self.send(200, {"map": m, "map_id": name, "layout": layout_of(name, m), "maps": map_list(),
                                   "coverage": G.map_coverage(m, MGR.cfg), "problems": G.map_problems(m),
                                   "patterns": C.PATTERNS, "usecases": C.USECASES, "methods": C.METHODS,
                                   "vtypes": C.VTYPES, "defaults": C.DEFAULT_CONFIG})
        if u.path == "/api/state":
            off = int(q.get("ev", ["0"])[0])
            if cid and q.get("sel"):
                PEERS[cid]["sel"] = q["sel"][0]
            now = time.time()
            with DRIVE_LOCK:
                drivers = {k: d["name"] for k, d in DRIVES.items() if d.get("on") and now - d["t"] < 2}
            peers = [{"id": k[:6], "me": k == cid, "name": p["name"], "sel": p.get("sel"),
                      "driving": next((v for v, d in DRIVES.items() if d.get("client") == k and d.get("on")), None)}
                     for k, p in sorted(PEERS.items(), key=lambda kv: kv[1]["name"]) if now - p["seen"] < 6]
            rd = MGR.run_dir
            if not rd:
                return self.send(200, {"run": None, "config": MGR.cfg, "procs": {}, "events": [], "ev": 0,
                                       "peers": peers, "drivers": drivers})
            K = int((C.read_json(rd / "config.json", MGR.cfg) or MGR.cfg)["fl"]["K"])
            evs, end = read_events(rd / "events.jsonl", off)
            ctl = C.read_json(rd / "server_ctl.json", {}) or {}
            return self.send(200, {
                "run": rd.name, "procs": MGR.status(), "note": MGR.note, "started": MGR.started,
                "config": MGR.cfg, "world": C.read_json(rd / "world.json", {}),
                "server": C.read_json(rd / "server.json", {}),
                "server_down_left": max(0.0, float(ctl.get("down_until", 0)) - time.time()),
                "clients": {str(i): C.read_json(rd / f"client_{i}.json", {}) for i in range(1, K + 1)},
                "events": evs, "ev": end, "peers": peers, "drivers": drivers})
        if u.path == "/api/maps":
            return self.send(200, {"maps": G.list_maps(), "info": map_list()})
        if u.path == "/api/saves":
            out = []
            for d in sorted(C.SAVES.glob("*"), reverse=True) if C.SAVES.exists() else []:
                m = C.read_json(d / "meta.json", {}) or {}
                out.append({"id": d.name, **m})
            return self.send(200, {"saves": out})
        if u.path == "/api/runs":
            runs = [d for d in sorted(C.RUNS.glob("2*"), reverse=True) if d.is_dir()][:40]
            return self.send(200, {"runs": [run_summary(d) for d in runs]})
        if u.path == "/api/replay":
            d = self.run_path(q)
            if not d:
                return self.send(404, {"error": "run not found"})
            hist_lines = sum(1 for _ in open(d / "world_hist.jsonl")) if (d / "world_hist.jsonl").exists() else 0
            return self.send(200, {
                "run": d.name, "config": C.read_json(d / "config.json", {}),
                "server": C.read_json(d / "server.json", {}),
                "events": load_jsonl(d / "events.jsonl", limit=20000),
                "world": load_jsonl(d / "world_hist.jsonl", every=max(1, hist_lines // 3600))})
        if u.path == "/api/export":
            d = self.run_path(q)
            if not d:
                return self.send(404, {"error": "run not found"})
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                for f in ["config.json", "server.json", "events.jsonl", "world_hist.jsonl", "fl.log"]:
                    if (d / f).exists():
                        tar.add(d / f, arcname=f"{d.name}/{f}")
            return self.send(200, buf.getvalue(), "application/gzip",
                             {"Content-Disposition": f'attachment; filename="vfl_log_{d.name}.tar.gz"'})
        path = (WEB / ("index.html" if u.path in ("/", "") else u.path.lstrip("/"))).resolve()
        if path.is_file() and WEB.resolve() in path.parents:
            ctype = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8",
                     "css": "text/css; charset=utf-8"}.get(path.suffix[1:], "application/octet-stream")
            return self.send(200, path.read_bytes(), ctype)
        self.send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n else b""
        u = urlparse(self.path)
        if self.gate(u, parse_qs(u.query)):
            return
        cid, name = self.who()
        if u.path == "/api/import":
            d = C.RUNS / f"imported_{time.strftime('%Y%m%d_%H%M%S')}"
            d.mkdir(parents=True)
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
                for m in tar.getmembers():
                    name = Path(m.name).name
                    if m.isfile() and name in ("config.json", "server.json", "events.jsonl", "world_hist.jsonl", "fl.log"):
                        (d / name).write_bytes(tar.extractfile(m).read())
            # 다시 보기 목록(2로 시작)에 나오도록 이름 정리
            final = C.RUNS / f"{time.strftime('%Y%m%d_%H%M%S')}_imported"
            d.rename(final)
            return self.send(200, {"ok": True, "run": final.name})
        body = json.loads(raw or b"{}")
        if u.path == "/api/config":
            deep_merge(MGR.cfg, body)
            MGR.save_cfg()
            if MGR.run_dir and name != "익명":
                C.emit(MGR.run_dir, "control", by=name, msg=f"{name}: 설정 변경 {describe_patch(body)}")
            return self.send(200, {"ok": True, "config": MGR.cfg})
        if u.path == "/api/drive":               # 수동 운전 입력 (world.py가 매 틱 읽음)
            if not MGR.run_dir or MGR.procs.get("world") is None or MGR.procs["world"].poll() is not None:
                return self.send(409, {"ok": False, "error": "시뮬레이션이 실행 중이 아님"})
            cid = cid or str(body.get("client", ""))[:40]
            vid, now = str(body.get("vid")), time.time()
            with DRIVE_LOCK:
                cur = DRIVES.get(vid)
                if body.get("on") and cur and cur.get("on") and cur["client"] != cid and now - cur["t"] < 2:
                    return self.send(409, {"ok": False, "busy": True, "error": f"V{vid}은 {cur['name']} 님이 운전 중"})
                for k in [k for k, d in DRIVES.items() if (d["client"] == cid and k != vid) or now - d["t"] > 10]:
                    DRIVES.pop(k)                         # 한 사람은 한 대만 · 오래된 입력 정리
                if body.get("on"):
                    DRIVES[vid] = {k: body[k] for k in ("throttle", "brake", "steer", "reverse", "park") if k in body}
                    DRIVES[vid].update(on=True, client=cid, name=name, t=now)
                elif cur and cur["client"] == cid:
                    DRIVES.pop(vid)
                C.write_json(MGR.run_dir / "drive.json", {"cars": {k: {kk: vv for kk, vv in d.items() if kk != "client"}
                                                                  for k, d in DRIVES.items()}})
            w = C.read_json(MGR.run_dir / "world.json", {}) or {}
            near = None
            me = (w.get("vehicles") or {}).get(vid)
            if me:                                        # 운전 중인 차 주변 사람도 바로 그린다
                near = [x for x in w.get("walkers", []) if abs(x[1] - me["pos"][0]) + abs(x[2] - me["pos"][1]) < 120]
            return self.send(200, {"ok": True, "v": me, "walkers": near})
        if u.path == "/api/map":
            m, name = body.get("map"), safe_name(body.get("name", "custom"))
            errs = G.validate_map(m or {}) or G.map_problems(m)
            if errs:
                return self.send(400, {"ok": False, "errors": errs})
            miss = [c["id"] for c in G.map_coverage(m, MGR.cfg) if not c["ok"]]
            C.write_json(C.MAPS / f"{name}.json", m)
            return self.send(200, {"ok": True, "name": name, "maps": G.list_maps(), "missing": miss})
        if u.path == "/api/control":
            act = body.get("action")
            label = {"start": "시작", "stop": "정지", "server_down": "서버 장애 주입", "ablation": "방식만 바꿔 다시 실행",
                     "save": "상태 저장", "load": "저장 상태 불러오기", "reset_config": "설정 초기화"}.get(act, act)
            if act == "start":
                MGR.start()
            elif act == "stop":
                MGR.stop()
            elif act == "server_down":
                MGR.server_down(float(body.get("seconds", MGR.cfg["server"].get("pause_s", 60))))
            elif act == "ablation":
                # 다른 설정·시드는 그대로 두고 학습 방식만 바꿔 다시 실행 (이전 실행 기록은 건드리지 않게 먼저 정지)
                MGR.stop()
                MGR.cfg["fl"]["method"] = body.get("method", MGR.cfg["fl"]["method"])
                MGR.save_cfg()
                MGR.start(tag=f"abl_{MGR.cfg['fl']['method']}")
            elif act == "save":
                return self.send(200, {"ok": True, "id": MGR.save(body.get("name", "state"))})
            elif act == "load":
                d = (C.SAVES / safe_name(body.get("id", ""))).resolve()
                if not d.is_dir() or C.SAVES.resolve() not in d.parents:
                    return self.send(404, {"ok": False, "error": "save not found"})
                MGR.start(resume_dir=d, tag="resume")
            elif act == "reset_config":
                MGR.cfg = json.loads(json.dumps(C.DEFAULT_CONFIG))
                MGR.save_cfg()
            if MGR.run_dir and name != "익명":
                C.emit(MGR.run_dir, "control", by=name, msg=f"{name}: {label}")
            return self.send(200, {"ok": True, "procs": MGR.status(), "config": MGR.cfg})
        self.send(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 = 같은 네트워크의 다른 컴퓨터도 접속")
    ap.add_argument("--code", default=os.environ.get("SIM_CODE", ""), help="접속 코드 (비우면 묻지 않음)")
    a = ap.parse_args()
    global ACCESS_CODE
    ACCESS_CODE = a.code
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"차량 FL 시뮬레이터: http://{a.host}:{a.port}" + (f"  (접속 코드 {a.code})" if a.code else ""), flush=True)
    try:
        srv.serve_forever()
    finally:
        MGR.stop()


if __name__ == "__main__":
    main()
