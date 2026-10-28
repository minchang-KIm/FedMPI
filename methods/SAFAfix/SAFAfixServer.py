"""SAFA 서버 — 원 논문(Wu et al., IEEE TC 2021, arXiv 1910.01355)에 맞춘 수정판.

methods/SAFA(SASAFL 저자 구현)과 다른 점:
  1. CFCFM: 학습 시간 추정치 내림차순(가장 느린 클라이언트 우선)이 아니라 실제 도착 순서(first-come)로 뽑는다.
     직전 라운드에 뽑히지 않은 클라이언트가 우선이고(P), 직전에 뽑힌 클라이언트는 quota가 모자랄 때만 도착 순으로 채운다(Q). (Algorithm 1)
  2. 집계: 비충돌 클라이언트만 정규화되지 않은 가중치로 더하던 것을, 식 (7)대로 전체 K개 캐시를 n_k/n 가중치(합 1)로 더한다.
  3. cross-rounder 판정의 off-by-one(마지막 클라이언트 누락)을 고쳤다.
나머지(버전 필터·lag tolerance, deprecated 강제 동기화, 사전/사후 캐시 갱신, 충돌 trace)는 저자 구현과 같다.
"""
from methods.SAFA import SAFAServer
from utils.model_utils import TensorBuffer
from utils.utils import printLog

import torch.distributed as dist
import torch
import time


class SAFAfixServer(SAFAServer.SAFAServer):
    def setup(self, dataset, iid, split, cluster_type, comm_hetero):
        super().setup(dataset, iid, split, cluster_type, comm_hetero)
        self.cross_rounders = [c_id for c_id in range(1, self.num_clients + 1)
                               if self.clients_est_round_T_train[c_id] > self.T]

    def CFCFM_by_arrival(self, arrival_ids, last_round_pick_ids):
        in_time_ids = [c_id for c_id in arrival_ids if c_id not in self.cross_rounders]
        if len(in_time_ids) <= self.Quota:
            return list(in_time_ids)
        high_priority_ids = [c_id for c_id in in_time_ids if c_id not in last_round_pick_ids]
        low_priority_ids = [c_id for c_id in in_time_ids if c_id in last_round_pick_ids]
        picks = high_priority_ids[:self.Quota]
        picks += low_priority_ids[:self.Quota - len(picks)]
        return picks

    def send_round_instructions(self, model_ids):
        """모든 클라이언트에게 이번 라운드 지시를 보낸다: 1 = 글로벌 모델이 뒤따름, 0 = 자기 로컬 모델 유지."""
        flatten_model = TensorBuffer(list(self.model.state_dict().values()))
        for c_id in range(1, self.num_clients + 1):
            flag = 1 if c_id in model_ids else 0
            dist.send(tensor=torch.tensor([flag]), dst=c_id)
            if flag:
                dist.send(tensor=flatten_model.buffer, dst=c_id)

    def receive_in_arrival_order(self, make_ids):
        reqs = {c_id: dist.irecv(tensor=self.flatten_client_models[c_id].buffer, src=c_id) for c_id in make_ids}
        arrival = []
        while len(arrival) < len(make_ids):
            for c_id, req in reqs.items():
                if c_id not in arrival and req.is_completed():
                    arrival.append(c_id)
            time.sleep(0.005)
        for req in reqs.values():
            req.wait()
        return arrival

    def average_aggregation_all(self, coefficient):
        printLog("SERVER", "global aggregation을 진행합니다.")
        global_model_params = self.model.state_dict()
        for pname in global_model_params:
            global_model_params[pname] = 0.0
        for c_id in range(1, self.num_clients + 1):
            for pname, param in self.cache[c_id].items():
                global_model_params[pname] += param.data * coefficient[c_id]
        self.model.load_state_dict(global_model_params)

    def terminate_FL(self):
        for c_id in range(1, self.num_clients + 1):
            dist.send(tensor=torch.tensor([-1]), dst=c_id)
