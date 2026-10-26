"""SASAFL 원본 파일을 고치지 않고, 서브클래스로 '차량 환경'과 '학습 방식 전환'을 끼워 넣는다.

원본 메서드의 동작은 그대로 옮겨 두고(장애가 없으면 원본과 같은 순서·같은 통신), 사이사이에 다음을 넣었다.
  - 주행 환경(world.json)과 설정(config.json)을 읽어 학습 중단·불참·지연·전송 끊김·보관 후 일괄 전송을 결정
  - 차량 상태(client_<id>.json), 서버 상태(server.json), 사건(events.jsonl), 체크포인트(checkpoint.pt)를 기록
  - 학습 방식(설정 fl.method): SASAFL / SASAFL 원저자 코드 / BSA / FedAsync / 동기식. 같은 하네스에서
    적응형 quota·staleness 감쇄·학습 중 교체·epoch 축소·quota 크기만 바꾸므로 나머지 조건은 그대로다 (ablation).
원본과 다른 점
  - 원본 runClient/wait_until_can_update_global_model의 busy-wait → 짧게 sleep (동작 동일)
  - 'rejoin'(fl.rejoin): 원본은 한 번 빠진 차량이 다시 선택되지 못한다. 켜면 복귀한 차량이 스스로 다시 학습한다.
    해당 라운드 미참여(패턴 3)는 복귀할 때 마지막으로 받은 최신 글로벌 모델로 시작한다.
  - 학습 중 글로벌 모델 교체 뒤 optimizer를 다시 만든다 (main 8f430a7 버그 수정과 같음)
  - 업로드: 실제 dist.send는 원본처럼 한 번. 전송 시간(모델 크기/대역폭)을 n등분해 기다리며 연결을 확인하고,
    끊기면 보내지 않는다 (서버는 아무것도 받지 못함 — SASAFL에는 조각 개념이 없어 패턴 2가 패턴 1처럼 보인다).
"""

import copy
import fcntl
import os
import random
import threading
import time
from collections import Counter, deque
from pathlib import Path

import torch
import torch.distributed as dist
from torch.nn import CrossEntropyLoss
from torch.optim import SGD
from torch.utils.data import DataLoader, RandomSampler

import common as C
from methods.SASAFL import SASAFL as M_SASAFL
from methods.SASAFL import SASAFLClient as M_CLIENT
from methods.SASAFL import SASAFLServer as M_SERVER
from utils.model_utils import TensorBuffer
from utils.utils import printLog

RUN = Path(os.environ["SIM_RUN_DIR"])
RESUME = Path(os.environ["SIM_RESUME_DIR"]) if os.environ.get("SIM_RESUME_DIR") else None
ABORT = "ABORT"
MAX_ARRIVALS, MAX_HISTORY = 200, 1500           # 메모리가 실행 시간에 비례해 늘지 않게


class Env:
    """world.json / config.json / server_ctl.json 읽기 캐시 (프로세스마다 하나)"""

    def __init__(self):
        self._w_t, self._w = 0.0, {}
        self._c_t, self._c, self._c_m = 0.0, None, -1
        self._s_t, self._s = 0.0, {}

    def world(self, vid):
        if time.time() - self._w_t > 0.1:
            self._w = C.read_json(RUN / "world.json", self._w) or self._w
            self._w_t = time.time()
        return (self._w.get("vehicles") or {}).get(str(vid), {})

    def world_all(self):
        self.world(0)
        return self._w.get("vehicles") or {}

    def cfg(self):
        if time.time() - self._c_t > 1.0 or self._c is None:
            try:
                m = (RUN / "config.json").stat().st_mtime
            except FileNotFoundError:
                m = 0
            if m != self._c_m or self._c is None:
                self._c = C.read_json(RUN / "config.json", self._c or C.DEFAULT_CONFIG)
                self._c_m = m
            self._c_t = time.time()
        return self._c

    def tod(self):
        """하루 시계 (world.json의 시각, 0–24)"""
        self.world(0)
        return float(self._w.get("tod", 12.0))

    def server_down(self):
        """8-1 집계 서버 장애(일시 중단) 여부: serve.py가 server_ctl.json에 down_until을 쓴다"""
        if time.time() - self._s_t > 0.3:
            self._s = C.read_json(RUN / "server_ctl.json", {}) or {}
            self._s_t = time.time()
        return time.time() < float(self._s.get("down_until", 0))


ENV = Env()


def link_reason(w):
    """연결이 없는 이유 → 유스케이스 id"""
    if not w.get("present", True):
        return None, "맵 밖"
    if w.get("zones", {}).get("tunnel"):
        return "2-5", "터널"
    if w.get("engine_off"):
        return "1-5", "시동 꺼짐"
    if w.get("ota"):
        return "1-2", "OTA 설치 중"
    if not w.get("gilbert_good", True):
        return "2-1", "음영지역 단절"
    return "2-1", "기지국 범위 밖"


# ================================================================== 차량 (클라이언트)
class SimClient(M_CLIENT.SASAFLClient):

    def ev(self, example, msg, **kw):
        C.emit(RUN, "fl", vid=self.id, example=example, msg=msg, **kw)

    def vcfg(self):
        return C.merged_vehicle(ENV.cfg(), self.id)

    def w(self):
        return ENV.world(self.id)

    def setup(self, cluster_type):
        super().setup(cluster_type)
        cfg, v = ENV.cfg(), self.vcfg()
        _, self.method = C.method_of(cfg)
        self.energy = self.budget()
        self.new_data = float(v.get("min_data", 32)) * 2
        if RESUME:                                            # 불러오기: 에너지·데이터 이어받기
            old = C.read_json(RESUME / f"client_{self.id}.json", {}) or {}
            self.energy = float(old.get("energy", self.energy))
            self.new_data = float(old.get("new_data", self.new_data))
        self.vtype = v["vtype"]
        self.ecu = float(v["ecu_factor"])
        self.status, self.detail = "idle", ""
        self.queue = []                                       # 보관 후 전송(5-x): [텐서, 버전, 만든 시각]
        self.queue_cause = None
        self.need_rejoin = False
        self.server_version = 0
        self.latest_info = None                               # 마지막으로 받은 글로벌 모델 (패턴 3 복귀용)
        self.keep_streak = 0                                  # 새 글로벌 모델을 연속으로 거부한 횟수 (8-3)
        self.emerg_seen = 0
        self.counters = {k: 0 for k in ("trained", "sent", "dropped", "aborted", "skipped", "queued", "burst")}
        self.wasted_mb = 0.0
        self.skip_active = None
        labels = self.dataset.tensors[1].clone()
        # 6-2 센서 고장: 지정한 라벨의 데이터 일부가 계속 오염 (라벨이 무작위로 바뀜)
        fault = [int(c) for c in str(v.get("sensor_fault_classes", "")).replace(" ", "").split(",") if c != ""]
        lvl = float(v.get("sensor_fault_level", 0.0))
        self.sensor_fault = (fault, lvl) if fault and lvl > 0 else None
        if self.sensor_fault:
            mask = torch.zeros(len(labels), dtype=torch.bool)
            for c in fault:
                mask |= labels == c
            idx = torch.nonzero(mask).flatten()
            idx = idx[torch.rand(len(idx)) < lvl]
            labels[idx] = torch.randint(0, 10, (len(idx),))
            self.dataset.tensors = (self.dataset.tensors[0], labels)
        hist = torch.bincount(labels.long(), minlength=10).tolist()
        self.label_hist = hist
        self.label_skew = max(hist) / max(1, sum(hist))
        self.model_mb = sum(t.numel() for t in self.model.state_dict().values()) * 4 / 1e6
        self.last_train = {}
        self.was_present = True
        threading.Thread(target=self._status_loop, daemon=True).start()

    def budget(self):
        """차량 배터리 예산 = 전체 예산 × 차량 배터리 배수 (작은 배터리 → 1-3·2-6)"""
        return float(ENV.cfg()["energy"]["budget_j"]) * float(self.vcfg().get("battery_scale", 1.0) or 1.0)

    def payload_mb(self):
        """전송 시간 계산에 쓰는 업데이트 크기: net.payload_mb(실차 모델 크기 가정), 0이면 실제 모델 크기"""
        p = float(ENV.cfg()["net"].get("payload_mb", 0) or 0)
        return p if p > 0 else self.model_mb

    def data_mult(self):
        """학습에 쓰는 데이터 배수 (4-6). 비우면 택시(운행이 긴 차량)는 2배, 나머지 1배"""
        m = self.vcfg().get("data_mult")
        if m:
            return float(m)
        return 2.0 if self.w().get("kind") == "city" else 1.0

    def _status_loop(self):
        last = time.time()
        while True:
            now = time.time()
            dt, last = now - last, now
            try:
                cfg, w, v = ENV.cfg(), self.w(), self.vcfg()
                rate = float(cfg["energy"]["charge_rate_jps"])
                if w.get("charging"):                          # 충전소 (급속)
                    self.energy = min(self.budget(), self.energy + rate * dt)
                elif w.get("home_charging"):                   # 집 주차 중 완속 충전 (시동 꺼짐)
                    self.energy = min(self.budget(), self.energy + rate * 0.25 * dt)
                if w.get("kind") == "visitor" and w.get("present") and not self.was_present:
                    self.energy = self.budget()                # 새로 들어온 통과 차량 = 다른 차 (배터리·데이터 새로)
                    self.new_data = float(v.get("min_data", 32)) * 2
                self.was_present = bool(w.get("present", True))
                if w.get("moving"):                            # 새 데이터는 주행 중에만 쌓인다 (3-2)
                    self.new_data += float(v.get("data_rate_per_s", 5)) * dt
                C.write_json(RUN / f"client_{self.id}.json", {
                    "vid": self.id, "t": now, "status": self.status, "detail": self.detail, "vtype": self.vtype,
                    "version": self.local_model_version, "server_version": self.server_version,
                    "energy": round(self.energy, 1), "energy_frac": round(self.energy / max(1e-6, self.budget()), 3),
                    "budget": round(self.budget()), "new_data": int(self.new_data), "ecu": round(self.ecu, 2),
                    "data_mult": self.data_mult(), "last_train": self.last_train,
                    "queue": len(self.queue), "need_rejoin": self.need_rejoin, "counters": self.counters,
                    "wasted_mb": round(self.wasted_mb, 2), "label_hist": self.label_hist,
                    "label_skew": round(self.label_skew, 2), "n_data": len(self.dataset),
                    "model_mb": round(self.payload_mb(), 2), "lr": v.get("lr_override") or self.lr,
                    "keep_streak": self.keep_streak})
            except Exception as e:
                printLog(f"CLIENT {self.id}", f"status error {e}")
            time.sleep(0.3)

    def set_status(self, status, detail=""):
        self.status, self.detail = status, detail

    # ---------------------------------------------------------------- 글로벌 모델 수신 (원본 + 수신 실패·강제 갱신 기록)
    def receive_global_model_from_server(self, is_ongoing_local_update_flag, terminate_FL_flag, lag_tolerance):
        self.received_global_model = self.model_controller.Model()
        model_state_dict = self.model.state_dict()
        flatten_model = TensorBuffer(list(model_state_dict.values()))
        self.global_model_info = torch.zeros(len(flatten_model.buffer) + 3)
        while True:
            dist.recv(tensor=self.global_model_info, src=0)
            global_model_version = int(self.global_model_info[-3].item())
            if global_model_version == -1:
                terminate_FL_flag.set()
                break
            am_i_picked = self.global_model_info[-1].item()
            global_loss = self.global_model_info[-2].item()
            self.server_version = global_model_version
            w = self.w()
            if not (w.get("link_up") and w.get("server_ok")):
                # 서버는 모든 차량에 보내지만 이 차량은 받지 못함 (프로세스는 메시지를 비워 서버가 멈추지 않게 한다)
                if am_i_picked == 1 and not is_ongoing_local_update_flag.is_set() and w.get("present", True) \
                        and not w.get("engine_off") and not w.get("ota"):
                    _, why = link_reason(w)
                    self.ev("4-8", f"새 모델 v{global_model_version} 수신 실패({why}) → 이전 v{self.local_model_version}로 "
                                   f"학습해 늦은 값을 보냄")
                    is_ongoing_local_update_flag.set()           # 받은 줄 모르고 가진 모델로 학습 시작
                elif am_i_picked == 1:
                    self.need_rejoin = True
                continue
            self.latest_info = self.global_model_info.clone()     # 최신 글로벌 모델 보관 (덮어쓰기라 메모리 일정)
            flatten_model.buffer = self.global_model_info[:-3]
            flatten_model.unpack(model_state_dict.values())
            if is_ongoing_local_update_flag.is_set() and global_model_version >= 1:
                if not self.method["mid_swap"]:                  # BSA·FedAsync·동기식: 학습 중에는 교체하지 않음
                    continue
                lag = global_model_version - self.local_model_version
                if lag >= lag_tolerance:
                    self.ev("8-3", f"새 글로벌 모델을 {self.keep_streak}번 연속 거부(성능이 더 나쁨)하다 lag {lag} ≥ τ={lag_tolerance}"
                                   f" → 강제 갱신" if self.keep_streak else f"lag {lag} ≥ τ={lag_tolerance} → 강제 갱신")
                    self.keep_streak = 0
                    self.received_global_model.load_state_dict(model_state_dict)
                    self.replace_global_model_during_local_update.set()
                elif global_loss < self.last_global_loss:
                    self.keep_streak = 0
                    self.received_global_model.load_state_dict(model_state_dict)
                    self.replace_global_model_during_local_update.set()
                else:
                    self.keep_streak += 1
                    continue
            elif am_i_picked == 1:
                self.model.load_state_dict(model_state_dict)
                self.local_model_version = global_model_version
                self.last_global_loss = global_loss
                self.need_rejoin = False
                is_ongoing_local_update_flag.set()

    def load_latest_global(self, why):
        """패턴 3 서버 대응: 복귀할 때 마지막으로 받은 최신 글로벌 모델로 시작"""
        info = self.latest_info
        if info is None or int(info[-3].item()) <= self.local_model_version:
            return False
        sd = self.model.state_dict()
        fm = TensorBuffer(list(sd.values()))
        fm.buffer = info[:-3]
        fm.unpack(sd.values())
        self.model.load_state_dict(sd)
        old = self.local_model_version
        self.local_model_version = int(info[-3].item())
        self.last_global_loss = info[-2].item()
        self.ev(None, f"복귀({why}): 최신 글로벌 모델 v{self.local_model_version}을 받아 다시 참여 (이전 v{old})")
        return True

    # ---------------------------------------------------------------- 참여 조건: 미달이면 학습을 시작하지 않는다
    def gate(self):
        cfg, w, v = ENV.cfg(), self.w(), self.vcfg()
        if not w.get("present", True) or v.get("leave"):
            return None, "맵 밖"
        if not w.get("available", True):
            return None, "운행 시간대 아님"
        if w.get("engine_off"):
            return "1-5", "시동 꺼짐"
        if w.get("ota"):
            return "1-2", "OTA 설치 중"
        if self.energy <= 0:
            return "1-3", "배터리 방전 (충전 필요)"
        if v.get("energy_gate", True) and self.energy < float(cfg["energy"]["min_energy_j"]):
            return "3-1", f"잔여 배터리 {self.energy:.0f} J < 안전 기준 {cfg['energy']['min_energy_j']} J"
        if self.new_data < float(v.get("min_data", 32)):
            why = "충전 중" if w.get("charging") else ("시동 켠 채 정차" if w.get("idle_parked") else "주행 데이터 부족")
            return "3-2", f"새 데이터 {self.new_data:.0f}개 < {v.get('min_data')} ({why})"
        if v.get("wifi_only") and not w.get("wifi"):
            return "3-3", "비과금망(Wi-Fi)이 아님"
        return None

    # ---------------------------------------------------------------- 로컬 학습 (원본 + 중단·지연·오염)
    def train(self, terminate_flag):
        cfg, v = ENV.cfg(), self.vcfg()
        self.set_status("training", f"v{self.local_model_version}")
        start = time.time()
        self.model.train()
        lr = float(v["lr_override"]) if v.get("lr_override") else self.lr
        optimizer = SGD(self.model.parameters(), lr=lr, momentum=0.9)
        loss_function = CrossEntropyLoss()
        mult = self.data_mult()
        n_used = max(self.batch_size, int(len(self.dataset) * mult))
        if abs(mult - 1.0) < 1e-6:
            dataloader = DataLoader(self.dataset, self.batch_size, shuffle=True)
        else:                                    # 4-6 데이터 양: 수집한 데이터가 많은 차량은 더 많은 표본으로 학습
            dataloader = DataLoader(self.dataset, self.batch_size,
                                    sampler=RandomSampler(self.dataset, replacement=mult > 1, num_samples=n_used))
        start_weights = copy.deepcopy(self.model.state_dict())
        crash_batch = random.randint(0, max(0, len(dataloader) * self.current_local_epoch - 1)) \
            if random.random() < float(v.get("crash_prob", 0.0)) else -1                 # 1-1
        e_cfg = cfg["energy"]
        per_batch_j = random.uniform(float(e_cfg["round_j_min"]), float(e_cfg["round_j_max"])) / \
            max(1, len(dataloader) * self.current_local_epoch)
        slow_ecu = slow_adas = 0.0
        batch_no = 0
        epoch_train_loss = 0.0
        e = 0
        while e < self.current_local_epoch:
            if self.replace_global_model_during_local_update.is_set():
                e = 0
                epoch_train_loss = 0.0
                if self.method["epoch_reduce"]:
                    self.current_local_epoch -= 1
                    if self.current_local_epoch < 2:
                        self.current_local_epoch = 2
                self.local_model_version = int(self.global_model_info[-3].item())
                self.last_global_loss = self.global_model_info[-2].item()
                self.model = copy.deepcopy(self.received_global_model)
                optimizer = SGD(self.model.parameters(), lr=lr, momentum=0.9)     # main 8f430a7 수정과 같음
                self.replace_global_model_during_local_update.clear()
                start_weights = copy.deepcopy(self.model.state_dict())
                continue
            for data, labels in dataloader:
                t_b = time.time()
                w = self.w()
                if w.get("engine_off") or not w.get("present", True):
                    return self._abort("1-5", "주차·시동 꺼짐으로 학습 중단")
                if w.get("ota"):
                    return self._abort("1-2", "OTA 설치·재부팅으로 학습 중단")
                if batch_no == crash_batch:
                    return self._abort("1-1", "계산 도중 돌발 중단")
                if self.energy <= 0:
                    return self._abort("1-3", "학습 중 배터리 방전")
                adas = float(w.get("emergency", 0)) > 0
                if adas and int(w.get("emergency_id", 0)) > self.emerg_seen:   # 새 긴급제동
                    self.emerg_seen = int(w["emergency_id"])
                    cause = w.get("emergency_cause", "")
                    if random.random() < float(v.get("safety_preempt_prob", 0.0)):
                        return self._abort("1-4", f"긴급제동({cause})이 연산을 선점해 FL 프로세스 종료")
                    self.ev("4-5", f"긴급제동({cause}) — ADAS가 {w['emergency']:.0f}초간 연산 점유, 학습 지연")
                optimizer.zero_grad()
                outputs = self.model.forward(data)
                loss = loss_function(outputs, labels)
                if e == 0:
                    epoch_train_loss += loss.detach().item()
                loss.backward()
                optimizer.step()
                batch_no += 1
                self.energy -= per_batch_j
                spent = time.time() - t_b
                if self.ecu > 1.0:                                              # 4-1 구형 EV
                    time.sleep(spent * (self.ecu - 1.0))
                    slow_ecu += spent * (self.ecu - 1.0)
                if adas:                                                         # 4-5 ADAS 연산 점유
                    time.sleep(spent * float(v.get("adas_slowdown", 1.5)))
                    slow_adas += spent * float(v.get("adas_slowdown", 1.5))
            e += 1
            self.set_status("training", f"v{self.local_model_version} · {e}/{self.current_local_epoch} epoch")
            if terminate_flag.is_set():
                return -1
        self.total_train_time += time.time() - start
        self.counters["trained"] += 1
        self.new_data = max(0.0, self.new_data - float(v.get("min_data", 32)))
        self._corrupt(start_weights, v, lr)
        took = time.time() - start
        if slow_ecu > 1.0:
            self.ev("4-1", f"{C.VTYPES[self.vtype]['name']} (연산 ×{self.ecu:.1f}) — 학습 {took:.1f}초, "
                           f"{slow_ecu:.1f}초 늦어짐")
        self.last_train = {"n": n_used, "s": round(took, 1), "mult": mult}
        avg = len(self.dataset) / max(1e-6, mult) if mult else len(self.dataset)
        sizes = [int(c.get("last_train", {}).get("n", 0)) for c in
                 (C.read_json(RUN / f"client_{i}.json", {}) or {} for i in range(1, int(cfg["fl"]["K"]) + 1))]
        sizes = sorted(x for x in sizes if x > 0) or [int(avg)]
        med = sizes[len(sizes) // 2]
        if n_used > 1.3 * med and took > 2:
            self.ev("4-6", f"데이터 {n_used}개(다른 차량 중앙값 {med}개의 {n_used / med:.1f}배)로 학습 {took:.1f}초 "
                           f"→ 늦게 도착 (운행이 길어 수집량이 많음)")
        return epoch_train_loss / len(dataloader)

    def _abort(self, example, msg):
        self.counters["aborted"] += 1
        self.need_rejoin = True
        self.set_status("dead", msg)
        self.ev(example, msg + " → 서버는 아무 응답도 받지 못함")
        return ABORT

    def _corrupt(self, start_weights, v, lr):
        """패턴 6: 제시간·정상 형식이지만 오류가 있는 값을 계속 보냄"""
        if float(v.get("backdoor_boost", 0)) > 0:                       # 6-1 악의적 조작
            sd = self.model.state_dict()
            for k in sd:
                sd[k] = start_weights[k] + (1 + float(v["backdoor_boost"])) * (sd[k] - start_weights[k])
            self.model.load_state_dict(sd)
            self.ev("6-1", f"조작한 값 전송 (업데이트 {1 + float(v['backdoor_boost']):.1f}배 증폭)")
        if self.sensor_fault:                                            # 6-2 센서 고장
            cls, lvl = self.sensor_fault
            self.ev("6-2", f"센서 고장: 라벨 {cls} 데이터의 {lvl:.0%}가 오염된 채 학습한 값 전송")
        if v.get("lr_override"):                                         # 6-3 학습 설정 오류
            self.ev("6-3", f"학습률 {lr} (정상 {self.lr})로 학습한 값 전송")

    # ---------------------------------------------------------------- 업로드
    def build_update(self, utility):
        flatten_model = TensorBuffer(list(self.model.state_dict().values()))
        info = flatten_model.buffer.tolist()
        info.append(utility)
        info.append(self.local_model_version)
        return torch.tensor(info), self.local_model_version

    def send_local_model_to_server(self, utility):
        self.current_local_epoch = self.local_epoch
        tensor, version = self.build_update(utility)
        result = self.upload(tensor, version)
        if result == "queued":
            self.queue.append((tensor, version, time.time()))
            del self.queue[:-3]                       # 보관은 최대 3개 (메모리 상한)
            self.counters["queued"] += 1
        return result

    def _cell_slot(self, cell, capacity):
        """기지국 동시 업로드 수 제한 (4-2): 셀마다 capacity개의 잠금 파일 중 하나를 잡는다"""
        for k in range(capacity):
            f = open(RUN / f".cell_{cell}_{k}.lock", "w")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return f
            except BlockingIOError:
                f.close()
        return None

    def upload(self, tensor, version):
        cfg, v = ENV.cfg(), self.vcfg()
        n = cfg["net"]
        frags = max(1, int(n["fragments"]))
        t0 = time.time()
        if ENV.server_down():                                             # 8-1 서버 장애 중: 보관 (5-3)
            return self._queue("5-3", "집계 서버 장애 — 복구될 때까지 보관")
        G = int(n.get("tdma_groups", 1))                                  # 4-7 TDMA 순서 대기
        if G > 1:
            slot, grp = float(n["tdma_slot_s"]), self.id % G
            self.set_status("waiting", f"TDMA 그룹 {grp}/{G} 순서 대기")
            while int(time.time() / slot) % G != grp:
                time.sleep(0.05)
            waited = time.time() - t0
            if waited > slot * 0.5:
                self.ev("4-7", f"TDMA 송신 순서 대기 {waited:.1f}초 (그룹 {grp}/{G})")
        w = self.w()
        if not (w.get("link_up") and w.get("server_ok")):
            return self._link_fail(w, 0, frags, v, "전송 시작 전")
        t_slot, lock = time.time(), None
        while lock is None:
            w = self.w()
            if not (w.get("link_up") and w.get("server_ok")):
                return self._link_fail(w, 0, frags, v, "기지국 대기 중")
            lock = self._cell_slot(w["cell"], int(n["cell_capacity"]))
            if lock is None:
                self.set_status("waiting", f"기지국 {w['cell']} 혼잡 — 빈 슬롯 대기")
                time.sleep(0.2)
        if time.time() - t_slot > 1.0:
            self.ev("4-2", f"기지국 {w['cell']} 혼잡으로 {time.time() - t_slot:.1f}초 대기")
        try:
            cell0, region0 = w["cell"], w["region"]
            q = w.get("quality", 1)
            if v.get("store_forward") and (q < float(n.get("edge_quality", 0.15)) or (w.get("zones", {}).get("weather") and q < 0.4)):
                why = "셀 가장자리" if q < float(n.get("edge_quality", 0.15)) else "강우 구역"
                return self._queue("5-2", f"{why}: 통신 품질 {q:.2f}로 낮아 전송 보류")
            retx = 0.0
            retx_seen = set()
            i = 0
            while i < frags:
                w = self.w()
                bw = float(n["bandwidth_mbps"]) * (float(n["weather_bw_mult"]) if w.get("zones", {}).get("weather") else 1.0)
                self.set_status("uploading", f"{i}/{frags} 조각 · {bw:.0f} Mbps")
                time.sleep(self.payload_mb() * 8 / frags / max(0.1, bw))
                w = self.w()
                fail = None
                if ENV.server_down():
                    return self._queue("5-3", "전송 중 집계 서버 장애 — 복구될 때까지 보관")
                if not (w.get("link_up") and w.get("server_ok")):
                    fail = link_reason(w)
                elif w.get("cell") != cell0 and n.get("handover_drops", True):
                    fail = ("2-1", f"기지국 {cell0}→{w.get('cell')} 핸드오버로 범위 이탈")
                elif w.get("region") != region0 and random.random() < float(n["region_instability"]):
                    fail = ("2-4", f"권역 경계 {region0}→{w.get('region')} 망 불안정")
                elif self.energy <= 0:
                    fail = ("2-6", "전송 중 배터리 방전")
                elif w.get("speed_kmh", 0) > float(n["doppler_kmh"]) and random.random() < float(n["doppler_fail"]):
                    fail = ("2-2", f"{w['speed_kmh']:.0f} km/h 도플러로 채널 추정 실패")
                elif random.random() < float(n["frag_fail"]):
                    fail = ("2-3", "무선 패킷 오류")
                if fail is None:
                    self.energy -= float(cfg["energy"]["upload_j"]) / frags
                    i += 1
                    continue
                if fail[0] in ("2-2", "2-3") and v.get("retransmit", True) and \
                        retx + float(n["retx_timeout_s"]) <= float(n["retx_total_s"]):
                    if fail[0] not in retx_seen:                 # 조각 손실 자체는 패턴 2, 재전송으로 늦게 도착하면 4-3
                        retx_seen.add(fail[0])
                        self.ev(fail[0], f"{fail[1]}: {i}/{frags} 조각에서 손실 → 재전송 시도 (복구되면 4-3 지연)")
                    self.set_status("waiting", f"재전송 대기 {n['retx_timeout_s']}초 ({fail[1]})")
                    time.sleep(float(n["retx_timeout_s"]))
                    retx += float(n["retx_timeout_s"])
                    continue
                return self._link_fail(w, i, frags, v, fail[1], forced=fail[0])
            dist.send(tensor=tensor, dst=0)                       # 원본과 같은 한 번의 dist.send
            total = time.time() - t0
            self.counters["sent"] += 1
            self.need_rejoin = False
            if retx > 0:
                self.ev("4-3", f"패킷 오류·도플러로 재전송 대기 {retx:.0f}초 후 도착")
            if total > self.payload_mb() * 8 / float(n["bandwidth_mbps"]) * 2 and total > 2:
                self.ev("4-4", f"업로드 {total:.1f}초 (대역폭 {n['bandwidth_mbps']} Mbps·강우·혼잡 포함)")
            C.emit(RUN, "upload", vid=self.id, msg=f"v{version} 업로드 완료 {total:.1f}초", version=version)
            self.set_status("idle", "업로드 완료, 다음 선택 대기")
            return "sent"
        finally:
            if lock is not None:
                fcntl.flock(lock, fcntl.LOCK_UN)
                lock.close()

    def _queue(self, example, why):
        self.queue_cause = self.queue_cause or example
        self.set_status("queued", why)
        self.ev(None, f"{why} (보관 {len(self.queue) + 1}개)")
        return "queued"

    def _link_fail(self, w, sent_frags, frags, v, where, forced=None):
        ex, why = (forced, where) if forced else link_reason(w)
        if v.get("store_forward") and ex and ex.startswith("2"):        # 5-1 수신 영역 밖: 보관 후 일괄 송신
            return self._queue("5-1", f"{why} → 보관, 수신 영역에 들어오면 일괄 송신")
        wasted = self.payload_mb() * sent_frags / frags
        self.counters["dropped"] += 1
        self.wasted_mb += wasted
        self.need_rejoin = True
        self.set_status("dead", f"{why} → 업데이트 폐기")
        if ex and ex.startswith("2"):
            self.ev(ex, f"{why}: {sent_frags}/{frags} 조각 전송 중 끊김, {wasted:.1f} MB 낭비 "
                        f"(SASAFL 서버에는 조각이 없어 '아무것도 안 옴'으로 보임)", wasted_mb=round(wasted, 2))
        else:
            self.ev(ex, f"{why}: 업로드 못 함 → 서버는 아무것도 받지 못함")
        return "dropped"

    def flush_queue(self):
        """보관한 업데이트를 연결·서버가 돌아오면 한꺼번에 보낸다 (패턴 5). 원본 서버는 차량당 버퍼 1칸이라 덮어씀"""
        w = self.w()
        if not self.queue or ENV.server_down() or not (w.get("link_up") and w.get("server_ok")):
            return
        items, self.queue = self.queue, []
        cause, self.queue_cause = self.queue_cause or "5-1", None
        sent = 0
        for tensor, version, made in items:
            if self.upload(tensor, version) == "sent":
                sent += 1
        if sent:
            self.counters["burst"] += 1
            self.ev(cause, f"보관한 값 {sent}개를 한꺼번에 전송 (버전 {[it[1] for it in items]})", n=sent)


# ================================================================== 실행 루프
class SimSASAFL(M_SASAFL.SASAFL):

    def runClient(self, Client):
        is_ongoing = threading.Event()
        terminate = threading.Event()
        listen = threading.Thread(target=Client.receive_global_model_from_server,
                                  args=(is_ongoing, terminate, self.lag_tolerance), daemon=True)
        listen.start()
        while True:
            if terminate.is_set():
                break
            cfg = ENV.cfg()
            if Client.queue:
                Client.flush_queue()
            if is_ongoing.is_set():
                g = Client.gate()
                if g:
                    prev = Client.skip_active
                    Client.skip_active = g
                    if not prev or prev[0] != g[0] or (g[0] is None and prev[1] != g[1]):   # 사유가 바뀔 때만 기록
                        Client.counters["skipped"] += 1
                        Client.ev(g[0], f"{g[1]} → 이번 라운드 미참여")
                    Client.set_status("skipped" if g[0] else "absent", g[1])
                    time.sleep(0.3)
                    continue
                if Client.skip_active:                          # 패턴 3 복귀: 최신 글로벌 모델로 시작
                    if Client.skip_active[0] and Client.skip_active[0].startswith("3"):
                        Client.load_latest_global(Client.skip_active[1])
                    Client.skip_active = None
                utility = Client.train(terminate)
                if terminate.is_set() or utility == -1:
                    break
                if utility == ABORT:
                    is_ongoing.clear()
                    continue
                r = Client.send_local_model_to_server(utility)
                is_ongoing.clear()
                if r == "queued" and len(Client.queue) < 3:
                    Client.need_rejoin = True                   # 끊긴 동안 같은 버전 모델로 계속 학습해 쌓는다
            elif Client.need_rejoin and cfg["fl"].get("rejoin", True):
                w = Client.w()
                g = Client.gate()
                can_store = Client.vcfg().get("store_forward") and Client.queue and len(Client.queue) < 3
                if not g and ((w.get("link_up") and w.get("server_ok") and not ENV.server_down()) or can_store):
                    if not can_store:
                        Client.load_latest_global("연결 회복")
                    Client.need_rejoin = False
                    is_ongoing.set()
                else:
                    why = g[1] if g else link_reason(w)[1]
                    Client.set_status("dead" if not Client.queue else "queued", f"복귀 대기: {why}")
            elif Client.need_rejoin:
                Client.set_status("excluded", "원본 SASAFL: 다시 선택되지 않음 (복귀 허용 꺼짐)")
            time.sleep(0.05)
        printLog(f"CLIENT {Client.id}", "FL 프로세스를 종료합니다.")
        dist.barrier()

    def runServer(self, Server):
        cfg = ENV.cfg()
        mname, method = C.method_of(cfg)
        K = Server.num_clients
        clients_idx = list(range(1, K + 1))
        picked_client_idx = clients_idx
        if method["quota"] == "one":
            minimum = 1
        elif method["quota"] == "all":
            minimum = K
        else:
            minimum = max(1, int(K * Server.selection_ratio))
        current = minimum
        Server.method = method
        listen_local_update = threading.Thread(target=Server.receive_local_model_from_any_clients, daemon=True)
        global_acc, global_loss = Server.evaluate()
        Server.last_global_loss = global_loss
        Server.history = [{"round": 0, "acc": round(global_acc * 100, 2), "loss": round(global_loss, 4),
                           "t": time.time(), "quota": current, "picked": []}]
        Server.part_total = Counter()
        Server.part_period = {}
        Server.q_sum, Server.q_n, Server.link_up_n = Counter(), Counter(), Counter()
        threading.Thread(target=Server.sample_comm, daemon=True).start()
        Server.window = deque(maxlen=int(cfg["server"].get("p7_window", 12)))
        Server.p7_last = {}
        if RESUME and (RESUME / "checkpoint.pt").exists():
            ck = torch.load(RESUME / "checkpoint.pt")
            Server.model.load_state_dict(ck["model"])
            Server.current_round = ck["round"]
            Server.last_global_loss = global_loss = ck["last_loss"]
            current = ck.get("quota", current)
            Server.history = ck.get("history", Server.history)
            Server.part_total = Counter({int(k): v for k, v in ck.get("part_total", {}).items()})
            Server.part_period = {p: Counter({int(k): v for k, v in c.items()}) for p, c in ck.get("part_period", {}).items()}
            C.emit(RUN, "control", msg=f"저장된 글로벌 모델 {Server.current_round}라운드에서 이어서 학습")
        C.emit(RUN, "control", msg=f"학습 방식: {method['name']} (quota 최소 {minimum}, 적응형 "
                                   f"{'켬' if method['adaptive_quota'] else '끔'}, 감쇄 {'켬' if method['decay'] else '끔'}, "
                                   f"학습 중 교체 {'켬' if method['mid_swap'] else '끔'})")
        Server.publish(current, "start")
        start = time.time()
        listen_local_update.start()
        while True:
            Server.wait_while_down(current)
            round_start = time.time()
            Server.send_global_model_to_clients(clients_idx, picked_client_idx, global_loss)
            picked_client_idx = Server.wait_until_can_update_global_model(current)
            stal = {i: Server.current_round - int(Server.local_model_version[i]) for i in picked_client_idx}
            Server.refine_received_local_model(picked_client_idx)
            coefficient = Server.calculate_coefficient(picked_client_idx)
            Server.average_aggregation(picked_client_idx, coefficient)
            global_acc, global_loss = Server.evaluate()
            Server.current_round += 1
            used = current
            if Server.current_round == Server.target_rounds or global_acc >= Server.target_accuracy:
                break
            if method["adaptive_quota"]:
                current = Server.get_next_round_minimum_local_model(global_loss, current, minimum)
            else:
                Server.last_global_loss = global_loss
            dups = sorted({i for i in picked_client_idx if picked_client_idx.count(i) > 1})
            rec = {"round": Server.current_round, "acc": round(global_acc * 100, 2), "loss": round(global_loss, 4),
                   "t": time.time(), "dur": round(time.time() - round_start, 2), "quota": used, "next_quota": current,
                   "picked": [{"vid": i, "staleness": stal[i], "version": int(Server.local_model_version[i]),
                               "weight": round(float(coefficient[i]), 3)} for i in picked_client_idx],
                   "dups": dups, "elapsed": round(time.time() - start, 1), "method": mname,
                   "tod": round(ENV.tod(), 2)}
            Server.history.append(rec)
            del Server.history[:-MAX_HISTORY]
            C.emit(RUN, "round", msg=f"{Server.current_round}라운드 집계: 차량 {picked_client_idx} 정확도 {rec['acc']}%",
                   round=rec)
            if dups:
                wsum = sum(float(coefficient[i]) for i in picked_client_idx)
                C.emit(RUN, "fl", vid=dups[0], msg=f"차량 {dups}: 같은 라운드에 두 번 집계 — 버퍼가 차량당 1칸이라 최신 것만 "
                                                   f"남고, 원본 calculate_coefficient가 비중을 두 번 나눠 비중 합 {wsum:.4f}")
            Server.track_participation(picked_client_idx)
            Server.publish(current, "aggregated")
            torch.save({"model": Server.model.state_dict(), "round": Server.current_round, "last_loss": global_loss,
                        "quota": current, "history": Server.history, "part_total": dict(Server.part_total),
                        "part_period": {p: dict(c) for p, c in Server.part_period.items()}},
                       RUN / "checkpoint.pt.tmp")
            os.replace(RUN / "checkpoint.pt.tmp", RUN / "checkpoint.pt")
        Server.terminate(clients_idx)
        dist.barrier()


# ================================================================== 서버
class SimServer(M_SERVER.SASAFLServer):

    def publish(self, quota, phase, waiting_s=0.0):
        K = self.num_clients
        win = Counter(i for r in getattr(self, "window", []) for i in r)
        C.write_json(RUN / "server.json", {
            "t": time.time(), "phase": phase, "round": self.current_round, "quota": quota,
            "cached": self.num_cached_local_model, "cached_ids": list(self.cached_client_idx),
            "waiting_s": round(waiting_s, 1), "history": self.history[-300:],
            "last_arrivals": getattr(self, "arrivals", [])[-30:],
            "participation": {"total": {str(i): self.part_total.get(i, 0) for i in range(1, K + 1)},
                              "window": {str(i): win.get(i, 0) for i in range(1, K + 1)},
                              "window_rounds": len(getattr(self, "window", [])),
                              "period": {p: {str(i): c.get(i, 0) for i in range(1, K + 1)}
                                         for p, c in getattr(self, "part_period", {}).items()}}})

    def refine_received_local_model(self, picked_client_idx):
        if getattr(self, "method", {}).get("decay", True):
            super().refine_received_local_model(picked_client_idx)

    def check_down(self):
        """8-1 장애 시작·복구를 한 번씩 기록. 반환: 지금 장애 중인지"""
        down = ENV.server_down()
        if down and not getattr(self, "_down_since", None):
            self._down_since = time.time()
            C.emit(RUN, "fl", example="8-1", msg="집계 서버 장애 — 배포·수신·집계 중단 (차량은 값을 보관)")
        elif not down and getattr(self, "_down_since", None):
            C.emit(RUN, "fl", example="8-1", msg=f"집계 서버 복구 ({time.time() - self._down_since:.0f}초 중단) — "
                                                 f"학습 재개, 보관된 값이 한꺼번에 도착")
            self._down_since = None
        return down

    def wait_while_down(self, quota):
        """8-1: 장애 중에는 배포·집계를 멈춘다. 복구되면 이어서 학습"""
        t0 = time.time()
        while self.check_down():
            self.publish(quota, "down", time.time() - t0)
            time.sleep(0.3)

    def receive_local_model_from_any_clients(self):
        self.arrivals = []
        while not self.terminate_FL.is_set() or len(self.idle_clients) + self.num_cached_local_model < self.num_clients:
            while ENV.server_down():                       # 장애 중에는 수신하지 않는다
                time.sleep(0.2)
            temp_local_model = TensorBuffer(list(self.model.state_dict().values()))
            local_model_info = torch.zeros(len(temp_local_model.buffer) + 2)
            req = dist.irecv(tensor=local_model_info)
            req.wait()
            with self.cached_client_idx_lock and self.num_cached_local_model_lock:
                src = req.source_rank()
                dup = src in self.cached_client_idx
                self.cached_client_idx.append(src)
                self.num_cached_local_model += 1
                temp_local_model.buffer = local_model_info[:-2]
                self.flatten_client_models[src] = copy.deepcopy(temp_local_model)
                self.local_utility[src] = local_model_info[-2]
                self.local_model_version[src] = local_model_info[-1]
            ver = int(local_model_info[-1].item())
            q = ENV.world(src).get("quality", 0)
            arr = {"t": time.time(), "vid": src, "version": ver, "staleness": self.current_round - ver,
                   "overwrite": dup, "quality": q}
            self.arrivals.append(arr)
            del self.arrivals[:-MAX_ARRIVALS]
            C.emit(RUN, "arrive", vid=src, msg=f"값 도착 v{ver} (staleness {self.current_round - ver})"
                   + (" — 같은 차량 값이 버퍼에 이미 있어 덮어씀" if dup else ""),
                   version=ver, staleness=arr["staleness"], overwrite=dup)

    def wait_until_can_update_global_model(self, num_local_model_limit):
        t0 = time.time()
        warned = False
        last_pub = 0
        while True:
            down = self.check_down()
            if down:
                t0 = time.time()                      # 장애 시간은 무한 대기(8-2) 판단에서 뺀다
            with self.cached_client_idx_lock and self.num_cached_local_model_lock:
                if self.num_cached_local_model >= num_local_model_limit and not down:
                    picked = [self.cached_client_idx.pop(0) for _ in range(self.num_cached_local_model)]
                    self.num_cached_local_model = 0
                    return picked
            waited = time.time() - t0
            if time.time() - last_pub > 0.5:
                self.publish(num_local_model_limit, "down" if down else "waiting", waited)
                last_pub = time.time()
            if waited > 60 and not warned and not down:
                warned = True
                alive = sum(1 for i in range(1, self.num_clients + 1)
                            if (C.read_json(RUN / f"client_{i}.json", {}) or {}).get("status") in
                            ("training", "uploading", "waiting", "queued"))
                C.emit(RUN, "fl", example="8-2",
                       msg=f"버퍼 {self.num_cached_local_model}/{num_local_model_limit}로 {waited:.0f}초째 대기 "
                           f"(학습·전송 중인 차량 {alive}대) — SASAFL에는 라운드 시간 제한이 없음")
            time.sleep(0.01)

    def sample_comm(self):
        """7-2용: 2초마다 주행 중(시동 켬) 차량의 연결 여부·신호 품질을 누적"""
        while not self.terminate_FL.is_set():
            for k, s in ENV.world_all().items():
                if s.get("present") and not s.get("engine_off"):
                    i = int(k)
                    self.q_n[i] += 1
                    self.link_up_n[i] += bool(s.get("link_up"))
                    self.q_sum[i] += s.get("quality", 0) if s.get("link_up") else 0.0
            time.sleep(2.0)

    def track_participation(self, picked):
        """패턴 7: 여러 라운드를 봐야 보이는 편중을 감시 (신형 EV / 통신 품질 / 운행 시간대)"""
        cfg = ENV.cfg()
        self.part_total.update(picked)
        self.part_period.setdefault(C.period_of(ENV.tod())[0], Counter()).update(picked)
        self.window.append(list(picked))
        W = self.window.maxlen
        if len(self.window) < W:
            return
        ratio = float(cfg["server"].get("p7_ratio", 1.4))
        allw = [i for r in self.window for i in r]
        K = self.num_clients
        vtype = {i: C.merged_vehicle(cfg, i)["vtype"] for i in range(1, K + 1)}
        rnd = self.current_round

        def fire(key, ex, msg):
            if rnd - self.p7_last.get(key, -10 ** 9) >= W:
                self.p7_last[key] = rnd
                C.emit(RUN, "fl", example=ex, msg=msg)
        n_new = sum(1 for i in vtype if vtype[i] == "new")
        exp = n_new / K
        got = sum(1 for i in allw if vtype[i] == "new") / max(1, len(allw))
        if n_new and exp < 1 and got > exp * ratio:
            fire("7-1", "7-1", f"최근 {W}라운드 집계의 {got:.0%}가 신형 EV (차량 비율 {exp:.0%}) — 연산이 빠른 차량 편중")
        # 7-2 통신 상태 편중: 주행 중 연결 유지율(같으면 신호 품질) 상위 절반 차량의 참여 비중
        wa = ENV.world_all()
        score = {i: (self.link_up_n[i] + 0.01 * self.q_sum[i]) / self.q_n[i] if self.q_n[i] else -1 for i in range(1, K + 1)}
        top = set(sorted(score, key=lambda i: -score[i])[:K // 2])
        g = sum(1 for i in allw if i in top) / max(1, len(allw))
        e = len(top) / K
        if top and g > min(0.95, e * ratio):
            up = ", ".join(f"V{i} {self.link_up_n[i] / max(1, self.q_n[i]):.0%}" for i in sorted(top))
            fire("7-2", "7-2", f"최근 {W}라운드 집계의 {g:.0%}가 연결 유지율 상위 절반 차량({up}) (차량 비율 {e:.0%}) "
                               f"— 통신 상태 좋은 차량 편중")
        # 7-3 운행 시간대 편중: 지금 시간대에 집계된 차량 종류(통근·택시·주민·통과)가 전체 차량 구성과 다름
        _, pname = C.period_of(ENV.tod())
        kinds = {i: wa.get(str(i), {}).get("kind", "?") for i in range(1, K + 1)}
        for kd, label in (("commute", "통근 차량"), ("city", "택시"), ("resident", "주민 차량")):
            ids = [i for i in kinds if kinds[i] == kd]
            if not ids:
                continue
            e2 = len(ids) / K
            g2 = sum(1 for i in allw if i in ids) / max(1, len(allw))
            if g2 > min(0.95, e2 * ratio) or g2 < e2 / ratio:
                fire("7-3:" + kd, "7-3", f"{pname} 시간대({C.fmt_hour(ENV.tod())}) 최근 {W}라운드 집계 중 {label} {g2:.0%} "
                                         f"(차량 비율 {e2:.0%}) — {'이 시간대에 몰림' if g2 > e2 else '이 시간대에 거의 없음'}")
                break


def install():
    """Start.py가 쓰는 클래스 이름을 시뮬레이션 클래스로 바꾼다 (원본 파일은 그대로)."""
    M_SASAFL.SASAFL = SimSASAFL
    M_CLIENT.SASAFLClient = SimClient
    M_SERVER.SASAFLServer = SimServer
