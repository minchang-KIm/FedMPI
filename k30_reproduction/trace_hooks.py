"""K30_TRACE=1일 때 harness_entry.py가 설치하는 관측 훅.

알고리즘 코드(methods/*)는 고치지 않는다. 서버·클라이언트 메서드를 감싸서 값을 읽기만 하고,
읽은 값을 run.log에 한 줄짜리 JSON(`TRACE {...}`)으로 남긴다. 분석은 trace_report.py가 한다.

남기는 이벤트 (ev 필드):
  proc        프로세스마다 1회: rank, 노드, 호스트, 요청/실제 스레드 수, CPU affinity, 터보, 버전, 소스 해시
  data_split  서버 1회: 클라이언트별 데이터 개수 (data_client: 클라이언트마다 레이블 분포)
  sources     노드마다 1회: 실제 읽힌 소스 파일 해시
  upload      서버가 로컬 모델을 받은 순간: 보낸 클라이언트, 노드, 모델 버전, utility
  aggregate   집계 1회마다(제안기법 1): 참여 목록, 노드별 인원, 이전 글로벌 모델이 남는 비율
  agg_client  집계에 참여한 클라이언트마다: staleness, 감쇠 계수 0.9^s, 데이터 비율 계수,
              실제 반영 가중치, 큐에서 기다린 시간, 노드
  quota       SASAFL 라운드마다(제안기법 2): 이전/현재 global loss, 비율, C·K, 최소 쿼터, 다음 쿼터와 분기
  round       서버 라운드마다: 정확도, loss, 쿼터, 대기·집계·평가 시간, 서버 CPU 시간, 부하
  client_update  클라이언트 로컬 학습 1회마다: 계획/최종 epoch 수, 실제 돈 epoch 수, 글로벌 모델 교체 횟수,
              2 epoch 하한에 걸렸는지, 학습 시간, CPU 시간(실제로 쓴 코어 수), 모델 변화량
  proc_end    프로세스 종료 시 누적값
"""

import atexit
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import torch

REPO = Path(__file__).resolve().parents[1]
RANK = int(os.environ.get("RANK", "0"))
LOCAL_RANK = int(os.environ.get("LOCAL_RANK", "0"))
GROUP_RANK = int(os.environ.get("GROUP_RANK", "0"))
LOCAL_WORLD_SIZE = int(os.environ.get("LOCAL_WORLD_SIZE", "1"))
HOST = socket.gethostname()
DECAY = 0.9  # SASAFLServer/SemiAsyncServer.refine_received_local_model의 decay_coefficient와 같은 값

_print_lock = threading.Lock()
_counters = {"loader_iters": 0, "updates": 0, "epochs_executed": 0, "swaps": 0}


def emit(ev, **fields):
    rec = {"ev": ev, "t": round(time.time(), 6), "rank": RANK}
    rec.update(fields)
    line = "TRACE " + json.dumps(rec, ensure_ascii=False, default=_jsonable)
    with _print_lock:
        print(line, flush=True)


def _jsonable(x):
    if isinstance(x, torch.Tensor):
        return x.item() if x.numel() == 1 else x.tolist()
    return str(x)


def _f(x):
    return float(x.item()) if isinstance(x, torch.Tensor) else float(x)


def _flat(model):
    return torch.cat([v.detach().reshape(-1).float() for v in model.state_dict().values()]).clone()


def _cpu():
    t = os.times()
    return t.user + t.system


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def _arg(name):
    for a in sys.argv:
        if a.startswith(f"--{name}="):
            return a.split("=", 1)[1]
    return None


def _node_of(rank):
    """두 노드 실행에서 서버(rank 0)와 같은 노드인지. torchrun static rendezvous는 node_rank 0의 프로세스에
    rank 0..LOCAL_WORLD_SIZE-1을 준다. 클라이언트가 직접 남기는 proc 이벤트의 host로 trace_report가 다시 확인한다."""
    return "server_node" if rank < LOCAL_WORLD_SIZE else "remote_node"


def _source_hashes():
    files = ["Start.py"] + sorted(str(p.relative_to(REPO)) for d in ("methods/SASAFL", "methods/SemiAsyncFL", "methods/FedAvg",
                                                                       "methods/SAFA", "methods/SAFAfix", "utils", "model_controller")
                                  for p in (REPO / d).glob("*.py"))
    out = {f: hashlib.sha256((REPO / f).read_bytes()).hexdigest()[:12] for f in files if (REPO / f).exists()}
    src = os.environ.get("K30_SASAFL_SRC")
    if src:
        out["K30_SASAFL_SRC:" + src] = hashlib.sha256(Path(REPO / src).read_bytes()).hexdigest()[:12]
    return out


def _cpu_model():
    for line in (_read("/proc/cpuinfo") or "").splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return None


def emit_proc(role):
    threads_arg = _arg("num_threads")
    requested = int(threads_arg[LOCAL_RANK]) if threads_arg and LOCAL_RANK < len(threads_arg) else None
    try:
        git = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        git = None
    emit("proc", role=role, local_rank=LOCAL_RANK, group_rank=GROUP_RANK, local_world_size=LOCAL_WORLD_SIZE,
         world_size=int(os.environ.get("WORLD_SIZE", "1")), host=HOST, pid=os.getpid(),
         threads_requested=requested, torch_threads=torch.get_num_threads(), interop_threads=torch.get_num_interop_threads(),
         affinity=sorted(os.sched_getaffinity(0)), n_logical_cpus=os.cpu_count(),
         env={k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                                             "GLOO_SOCKET_IFNAME", "K30_SASAFL_SRC", "MASTER_ADDR", "MASTER_PORT")},
         no_turbo=_read("/sys/devices/system/cpu/intel_pstate/no_turbo"),
         governor=_read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
         cpu_model=_cpu_model(), torch_version=torch.__version__, python=platform.python_version(),
         git_head=git, argv=sys.argv[1:])
    if LOCAL_RANK == 0:
        # 노드마다 1회: 실제로 읽힌 소스 파일 해시 (두 노드 코드가 같은지 확인용)
        hashes = _source_hashes()
        items = sorted(hashes.items())
        for i in range(0, len(items), 20):
            emit("sources", host=HOST, part=i // 20, sha256=dict(items[i:i + 20]))


# ───────────────────────── 서버 쪽 ─────────────────────────

class _TimedList(list):
    """cached_client_idx 대신 넣는 리스트. append(=로컬 모델 도착) 시각을 기록한다."""

    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    def append(self, rank):
        rank = int(rank)
        srv = self._owner
        srv._trace_arrival[rank] = time.time()
        # 버전·utility는 SASAFL이 append 뒤에 채우므로 여기서는 남기지 않는다 (aggregate 이벤트에 있다)
        emit("upload", client=rank, node=_node_of(rank), cached_after=srv.num_cached_local_model + 1,
             server_round=srv.current_round)
        super().append(rank)


def _is_sasafl_server(srv):
    return type(srv).__name__ == "SASAFLServer"


def _global_round(srv):
    """이번 집계로 만들어지는 글로벌 모델 번호 (로그의 'N번째 글로벌 모델'과 같은 값).
    SASAFL은 집계 뒤에 current_round를 올리고, BSA(SemiAsync)는 라운드 시작 때 올린다."""
    return srv.current_round + 1 if _is_sasafl_server(srv) else srv.current_round


def install_server(cls):
    orig_init = cls.__init__
    orig_wait = cls.wait_until_can_update_global_model
    orig_agg = cls.average_aggregation
    orig_eval = cls.evaluate

    def __init__(self, *a, **kw):
        orig_init(self, *a, **kw)
        self._trace_arrival = {}
        self._trace_round = None
        self.cached_client_idx = _TimedList(self)

    def wait_until_can_update_global_model(self, quota):
        t0, c0 = time.time(), _cpu()
        cached0 = self.num_cached_local_model
        picked = orig_wait(self, quota)
        self._trace_round = {"global_round": _global_round(self), "quota": int(quota), "cached_at_wait_start": cached0,
                             "n_picked": len(picked), "left_in_buffer": self.num_cached_local_model,
                             "wait_sec": round(time.time() - t0, 4), "wait_cpu_sec": round(_cpu() - c0, 4)}
        return picked

    def average_aggregation(self, picked, coefficient):
        t0 = time.time()
        rows, retained = [], 1.0
        for idx in picked:
            ver = _f(self.local_model_version[idx])
            stale = self.current_round - ver  # refine_received_local_model이 실제로 쓴 값 (집계 전 current_round 기준)
            alpha = DECAY ** stale
            coef = float(coefficient[idx])
            eff = coef * alpha
            retained -= eff
            arr = self._trace_arrival.get(int(idx))
            util = self.local_utility.get(idx) if hasattr(self, "local_utility") else None
            rows.append({"client": int(idx), "node": _node_of(int(idx)), "model_version": ver, "staleness": stale,
                         "decay_alpha": alpha, "data_size": self.len_local_dataset[idx], "data_coef": coef,
                         "effective_weight": eff, "utility": _f(util) if util is not None else None,
                         "queue_wait_sec": round(t0 - arr, 4) if arr else None})
        g = _global_round(self)
        emit("aggregate", method=type(self).__name__, global_round=g, n=len(picked), picked=[int(i) for i in picked],
             old_global_retained=retained,
             n_server_node=sum(r["node"] == "server_node" for r in rows),
             n_remote_node=sum(r["node"] == "remote_node" for r in rows))
        for r in rows:  # 한 줄이 파이프 원자 단위(4KB)를 넘지 않게 클라이언트마다 따로 남긴다
            emit("agg_client", global_round=g, **r)
        out = orig_agg(self, picked, coefficient)
        if self._trace_round is not None:
            self._trace_round["aggregate_sec"] = round(time.time() - t0, 4)
        return out

    def evaluate(self):
        t0 = time.time()
        acc, loss = orig_eval(self)
        r = self._trace_round
        if r is not None:
            r.update(acc=acc, loss=loss, eval_sec=round(time.time() - t0, 4), server_cpu_total_sec=round(_cpu(), 2),
                     loadavg=os.getloadavg())
            emit("round", **r)
            self._trace_round = None
        else:
            emit("init_eval", acc=acc, loss=loss)
        return acc, loss

    cls.__init__ = __init__
    cls.wait_until_can_update_global_model = wait_until_can_update_global_model
    cls.average_aggregation = average_aggregation
    cls.evaluate = evaluate


def install_sasafl_quota(cls):
    orig = cls.get_next_round_minimum_local_model

    def get_next_round_minimum_local_model(self, cur_loss, cur_quota, min_quota):
        prev = self.last_global_loss
        nxt = orig(self, cur_loss, cur_quota, min_quota)
        ratio = cur_loss / prev if prev else None
        emit("quota", for_global_round=self.current_round + 1, prev_global_loss=prev, cur_global_loss=cur_loss,
             loss_ratio=ratio, cur_quota=int(cur_quota), raw_next=(cur_quota * ratio) if ratio is not None else None,
             C=self.selection_ratio, K=self.num_clients, CK=self.num_clients * self.selection_ratio,
             min_quota=int(min_quota), branch="loss_up→cap_K" if cur_loss > prev else "loss_down_or_same→floor_CK",
             next_quota=int(nxt), prev_equals_cur=(prev == cur_loss))
        return nxt

    cls.get_next_round_minimum_local_model = get_next_round_minimum_local_model


def install_data_split(cls):
    orig = cls.send_local_train_dataset_to_clients

    def send_local_train_dataset_to_clients(self, train_datasets):
        emit("data_split", K=self.num_clients, n_datasets_created=len(train_datasets), test_size=len(self.test_data),
             sizes=[len(ds) for ds in train_datasets[: self.num_clients]])
        for i, ds in enumerate(train_datasets[: self.num_clients]):
            labels = ds.tensors[1].long().reshape(-1)
            hist = torch.bincount(labels, minlength=10).tolist()
            emit("data_client", client=i + 1, node=_node_of(i + 1), size=len(ds), labels=hist,
                 n_labels=sum(1 for h in hist if h > 0))
        return orig(self, train_datasets)

    cls.send_local_train_dataset_to_clients = send_local_train_dataset_to_clients


# ───────────────────────── 클라이언트 쪽 ─────────────────────────

class _SwapEvent(threading.Event):
    """SASAFLClient.replace_global_model_during_local_update 대신 넣는 Event.
    train()이 글로벌 모델로 교체한 직후 clear()를 부르므로, 그때 교체된 모델을 기록한다."""

    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    def clear(self):
        c = self._owner
        st = getattr(c, "_trace_cur", None)
        if st is not None and self.is_set():
            st["swaps"] += 1
            st["swap_versions"].append(int(c.local_model_version))
            st["epochs_before_last_swap"] = _counters["loader_iters"] - st["iters0"]
            st["base"] = _flat(c.model)
            st["base_kind"] = "swapped_global"
        super().clear()


class _CountingLoader:
    """클라이언트 모듈의 DataLoader 대신 쓰는 래퍼. 한 번 순회할 때마다 epoch 1회로 센다."""

    def __init__(self, real):
        self._real = real

    def __call__(self, *a, **kw):
        loader = self._real(*a, **kw)
        return _IterCount(loader)


class _IterCount:
    def __init__(self, loader):
        self._loader = loader

    def __iter__(self):
        _counters["loader_iters"] += 1
        return iter(self._loader)

    def __len__(self):
        return len(self._loader)

    def __getattr__(self, name):
        return getattr(self._loader, name)


def install_client(cls, module, epochs_attr):
    """epochs_attr: 이번 로컬 학습의 목표 epoch 수가 들어 있는 속성 (SASAFL: current_local_epoch, BSA: local_epoch)."""
    module.DataLoader = _CountingLoader(module.DataLoader)
    orig_init = cls.__init__
    orig_train = cls.train

    def __init__(self, *a, **kw):
        orig_init(self, *a, **kw)
        if hasattr(self, "replace_global_model_during_local_update"):
            self.replace_global_model_during_local_update = _SwapEvent(self)

    def train(self, *a, **kw):
        planned = getattr(self, epochs_attr)
        st = {"iters0": _counters["loader_iters"], "swaps": 0, "swap_versions": [], "epochs_before_last_swap": 0,
              "base": _flat(self.model), "base_kind": "start"}
        start_w = st["base"]
        ver0 = int(_f(self.local_model_version))
        self._trace_cur = st
        t0, c0 = time.time(), _cpu()
        out = orig_train(self, *a, **kw)
        wall, cpu = time.time() - t0, _cpu() - c0
        self._trace_cur = None
        end_w = _flat(self.model)
        final_target = getattr(self, epochs_attr)
        executed = _counters["loader_iters"] - st["iters0"]
        _counters["updates"] += 1
        _counters["epochs_executed"] += executed
        _counters["swaps"] += st["swaps"]
        emit("client_update", client=RANK, host=HOST, node=_node_of(RANK), threads=torch.get_num_threads(),
             data_size=len(self.dataset), version_start=ver0, version_sent=int(_f(self.local_model_version)),
             epochs_planned=int(planned), epochs_final_target=int(final_target),
             epochs_final_segment=executed - st["epochs_before_last_swap"], epochs_executed_total=executed,
             swaps=st["swaps"], swap_versions=st["swap_versions"],
             hit_floor_2=bool(st["swaps"] > 0 and planned - st["swaps"] < 2),
             wall_sec=round(wall, 4), cpu_sec=round(cpu, 4), cores_used=round(cpu / wall, 3) if wall > 0 else None,
             sec_per_epoch=round(wall / executed, 4) if executed else None,
             utility=_f(out) if isinstance(out, (int, float, torch.Tensor)) else None,
             delta_norm_from_start=float((end_w - start_w).norm()),
             delta_norm_from_base=float((end_w - st["base"]).norm()), base=st["base_kind"],
             loadavg=os.getloadavg())
        return out

    cls.__init__ = __init__
    cls.train = train


def install():
    """harness_entry.py가 Start.py 실행 전에 부른다."""
    from methods.FedAvg import FedAvgServer, FedAvgClient
    from methods.SASAFL import SASAFLServer, SASAFLClient
    from methods.SemiAsyncFL import SemiAsyncServer, SemiAsyncClient

    for mod, role in ((FedAvgServer.FedAvgServer, "server"), (FedAvgClient.FedAvgClient, "client")):
        orig_setup = mod.setup

        def setup(self, *a, _orig=orig_setup, _role=role, **kw):
            out = _orig(self, *a, **kw)
            emit_proc(_role)  # Start.py가 torch.set_num_threads를 부른 뒤이므로 실제 스레드 수가 찍힌다
            return out

        mod.setup = setup

    install_data_split(FedAvgServer.FedAvgServer)
    install_server(SASAFLServer.SASAFLServer)
    install_server(SemiAsyncServer.SemiAsyncServer)
    install_sasafl_quota(SASAFLServer.SASAFLServer)
    install_client(SASAFLClient.SASAFLClient, SASAFLClient, "current_local_epoch")
    install_client(SemiAsyncClient.SemiAsyncClient, SemiAsyncClient, "local_epoch")

    atexit.register(lambda: emit("proc_end", host=HOST, cpu_total_sec=round(_cpu(), 2), **_counters))
