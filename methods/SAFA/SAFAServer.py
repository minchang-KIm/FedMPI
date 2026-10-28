from methods.FedAvg import FedAvgServer
from utils.model_utils import TensorBuffer
from utils.utils import printLog

import torch.distributed as dist
import torch
import copy
import threading
import gc
import time

from collections import OrderedDict
from torch.nn import CrossEntropyLoss
from torch.utils.data import DataLoader

class SAFAServer(FedAvgServer.FedAvgServer):
    def __init__(self, num_clients, selection_ratio, batch_size, target_rounds, target_accuracy, wandb_on, FLgroup):
        super().__init__(num_clients, selection_ratio, batch_size, target_rounds, target_accuracy, wandb_on, FLgroup)
        self.local_model_version = [-1 for idx in range(0,self.num_clients+1)]

        self.picked_history_per_client={}
        for idx in range(1, self.num_clients+1):
            self.picked_history_per_client[idx]=-1

        self.T_lim = 5000 # WISE
        # self.T_lim = 
        self.Quota=int(self.num_clients*self.selection_ratio) # 한 라운드 동안 수신할 local model 최대 개수
        self.flatten_client_models={} #로컬 모델 받는용도
        self.cache={} #aggregation에 사용하는 로컬 모델

        self.idle_clients=[]

        self.lag_tolerance=5

    def setup(self, dataset, iid, split, cluster_type, comm_hetero):
        super().setup(dataset, iid, split, cluster_type, comm_hetero)

        profiling_group = dist.new_group([idx for idx in range(0,self.Quota+1)])
        
        T_dist=time.time()
        dist.broadcast(tensor=TensorBuffer(list(self.model.state_dict().values())).buffer, src=0, group=profiling_group)
        T_dist = time.time() - T_dist

        dist.broadcast(tensor=TensorBuffer(list(self.model.state_dict().values())).buffer, src=0, group=self.FLgroup)

        T_train_k=torch.zeros(1)

        self.clients_est_round_T_train={}

        for idx in range(1, self.num_clients+1):
            req = dist.irecv(tensor=T_train_k)
            req.wait()
            # [버그 수정 2026-10-28] 받은 값을 float로 저장한다. 원래 코드는 같은 텐서 객체 T_train_k를 모든 클라이언트에
            # 넣어서, 마지막에 받은 값 하나로 전부 같아졌다(→ CFCFM 정렬이 rank 번호 순, cross-rounder 판정 무의미).
            # 저자 구현(wingter562/SAFA semiAysnc_FedAvg.py)의 clients_est_round_T_train은 클라이언트별 값이다.
            self.clients_est_round_T_train[req.source_rank()] = T_train_k.item()
        
        T_max_train_k = max(self.clients_est_round_T_train.values())

        self.T = min(self.T_lim, T_dist + T_max_train_k)

        printLog(f"SERVER", f"한 라운드의 deadline은 {self.T}입니다.")

        self.cross_rounders=[]
        # [버그 수정 2026-10-28] 마지막 클라이언트(num_clients)도 검사한다 (원래 range(1, num_clients)로 하나 빠짐).
        # 저자 구현 get_cross_rounders는 모든 클라이언트를 검사한다.
        for c_id in range(1, self.num_clients+1):
            if self.clients_est_round_T_train[c_id] > self.T:
                self.cross_rounders.append(c_id)
        

        for idx in range(1, self.num_clients+1):
            self.cache[idx] = copy.deepcopy(self.model.state_dict())
    
    def sort_ids_by_perf_desc(self, id_list):
        cp_map={}
        for id in id_list:
            cp_map[id] = self.clients_est_round_T_train[id]

        # [버그 수정 2026-10-28] 빠른 클라이언트(추정 학습 시간이 짧은 쪽)가 앞에 오도록 오름차순으로 정렬한다.
        # 저자 구현 sort_ids_by_perf_desc는 성능(초당 처리 배치 수, clients_perf_vec)을 내림차순으로 정렬한다
        # = 먼저 끝나는 클라이언트 우선(First-Come-First-Merge). 이 저장소는 성능 대신 학습 시간을 저장하므로
        # 같은 순서를 얻으려면 시간 오름차순이어야 한다 (원래 코드는 reverse=True로 가장 느린 클라이언트부터 뽑았다).
        sorted_map = sorted(cp_map.items(), key=lambda x: x[1])
        sorted_id_list = [sorted_map[i][0] for i in range(len(id_list))]

        return sorted_id_list
    
    def CFCFM(self, make_ids, last_round_pick_ids):

        picks=[]
        in_time_make_ids = [m_id for m_id in make_ids if m_id not in self.cross_rounders]  # in-time make ids
        high_priority_ids = [h_id for h_id in in_time_make_ids if h_id not in last_round_pick_ids]  # compensatory priority
        low_priority_ids = [l_id for l_id in in_time_make_ids if l_id in last_round_pick_ids]
        printLog("SERVER", f"high_priority_ids: {high_priority_ids}")
        printLog("SERVER", f"low_priority_ids: {low_priority_ids}")
        # case 0: clients finishing in time not enough for fraction C, just gather them all
        if len(in_time_make_ids) <= self.Quota:  # if not enough well-progress clients to meet the quota
            return copy.deepcopy(in_time_make_ids)
        # case 1: # of priority ids > quota
        if len(high_priority_ids) >= self.Quota:
            sorted_priority_ids = self.sort_ids_by_perf_desc(high_priority_ids)
            picks = sorted_priority_ids[0:int(self.Quota)]
        # case 2: # of priority ids <= quota
        # the rest are picked by order of performance ("FCFM"), lowest batch overhead first
        else:
            picks += high_priority_ids  # they have priority
            # FCFM
            sorted_low_priority_ids =self. sort_ids_by_perf_desc(low_priority_ids)
            for i in range(min(self.Quota - len(picks), len(sorted_low_priority_ids))):
                picks.append(sorted_low_priority_ids[i])

        return picks


    def version_filter(self, ids, lag_tolerance):
        base_v = self.current_round-1
        good_ids=[]
        deprecated_ids=[]
        for id in ids:
            if base_v - self.local_model_version[id] <= lag_tolerance:
                good_ids.append(id)
            else:
                deprecated_ids.append(id)
        return good_ids, deprecated_ids
    
    def average_aggregation(self, ids, coefficient):
        printLog("SERVER", "global aggregation을 진행합니다.")
        """
        averaged_weights = OrderedDict()
        
        for idx, client_idx in enumerate(ids):
            model = self.model_controller.Model()
            model.load_state_dict(self.cache[client_idx])
            for key in self.cache[client_idx].keys():
                if idx==0:
                    averaged_weights[key] = coefficient[client_idx] * self.cache[client_idx][key]
                else:
                    averaged_weights[key] += coefficient[client_idx] * self.cache[client_idx][key]

        self.model.load_state_dict(averaged_weights)
        """
        global_model_params = self.model.state_dict()
        for pname, param in global_model_params.items():
            global_model_params[pname]=0.0

        agg_coefficient={}
        agg_coefficient_sum=0
        for id in ids:
            if id==-1:
                continue
            agg_coefficient_sum+=coefficient[id]
        
        for id in ids:
            if id==-1:
                continue
            agg_coefficient[id]=coefficient[id]/agg_coefficient_sum

        # [버그 수정 2026-10-28] 집계에 정규화된 가중치 agg_coefficient를 쓴다 (원래 코드는 coefficient[id]를 썼다).
        #
        # 1) 원래 코드의 가중치 합은 1보다 작다.
        #    coefficient는 SAFA.runServer에서 calculate_coefficient(clients_idx)로 "전체 K명" 기준으로 만든 값이다:
        #    coefficient[k] = n_k / (n_1 + … + n_K)  (n_k = 클라이언트 k의 데이터 수), 전체 K명의 합이 1.
        #    그런데 여기서는 ids(= 이번 라운드에 충돌하지 않은 클라이언트, 충돌한 자리는 -1)만 더한다.
        #    그러므로 가중치 합 = (비충돌 클라이언트 데이터 수의 합) / (전체 데이터 수의 합) 이고,
        #    한 명이라도 충돌하면(generate_crash_trace: 클라이언트마다 매 라운드 확률 0.1) 반드시 1보다 작다.
        #
        # 2) 가중치 합이 1이 아니면 결과는 평균이 아니다.
        #    결과 = (가중치 합) × (비충돌 클라이언트 모델의 가중 평균) 이므로, 모든 파라미터가 매 라운드 (가중치 합)배로 줄어든다.
        #    예: 데이터 수가 같은 3명 중 1명 충돌, 파라미터 값 1.0, 1.2 → (1/3)·1.0 + (1/3)·1.2 = 0.733.
        #    두 모델 값(1.0, 1.2)의 어느 쪽보다도 작아서 평균일 수 없다.
        #    실측(F7_MNIST_SAFA_C0.1_rep1, 수정 전 83라운드): 라운드별 가중치 합 평균 0.910, 최소 0.737.
        #    그 결과 test loss가 83라운드 내내 2.19–2.49(무작위 추측 수준 ln 10 ≈ 2.30)에 머물러 학습이 되지 않았다.
        #
        # 3) 바로 위 코드가 정규화된 가중치 agg_coefficient(= coefficient / 비충돌 합, 합 1)를 계산해 두고
        #    한 번도 쓰지 않는다. 의도한 가중치는 agg_coefficient였다.
        #
        # 4) SAFA 원 논문(Wu et al., IEEE TC 70(5), 2021, arXiv:1910.01355) 식 (7)
        #    w(t) = Σ_k (n_k / n) · w*_k(t) 와 FedAvg(McMahan et al., 2017)의 집계도
        #    모두 가중치 합이 1인 가중 평균이다.
        #
        # 집계 대상(ids)과 나머지 동작은 바꾸지 않았다. 가중치만 의도대로 정규화한 최소 수정이다.
        for id in ids:
            if id==-1:
                continue
            for pname, param in self.cache[id].items():
                global_model_params[pname] += param.data * agg_coefficient[id]

        self.model.load_state_dict(global_model_params)

    def receive_local_model_from_selected_clients(self, selected_client_idx):
        # [버그 수정 2026-10-28] 클라이언트마다 보낸 쪽(src)을 지정해 받는다.
        # 상속한 FedAvgServer 구현은 irecv에 src를 주지 않아(아무 쪽에서나 받음) 먼저 도착한 모델이
        # selected_client_idx 앞 번호의 버퍼에 들어갔다. 그러면 cache[k]에 다른 클라이언트의 모델이 들어가
        # 데이터 비율 가중치(n_k/n)와 picks/undrafted 구분이 엉뚱한 모델에 적용된다.
        # 받는 대상과 나머지 동작은 그대로다.
        reqs=[]
        for idx in selected_client_idx:
            if idx==-1:
                continue
            reqs.append(dist.irecv(tensor=self.flatten_client_models[idx].buffer, src=idx))
        for req in reqs:
            req.wait()

    def update_cloud_cache(self, ids):
        model = self.model_controller.Model()
        model_state_dict = model.state_dict()
        for id in ids:
            self.flatten_client_models[id].unpack(model_state_dict.values())
            self.cache[id] = copy.deepcopy(model_state_dict)

    
    def update_cloud_cache_deprecated(self, ids):
        for id in ids:
            self.cache[id] = copy.deepcopy(self.model.state_dict())


    def update_version(self, ids, version):
        for id in ids:
            self.local_model_version[id] = version

    def send_round_instructions(self, model_ids):
        # [버그 수정 2026-10-28] 라운드마다 모든 클라이언트에게 지시를 먼저 보낸다: 1 = 글로벌 모델이 뒤따름(동기화), 0 = 로컬 모델 유지.
        # 원래 코드는 model_ids에게만 글로벌 모델을 보내고, 클라이언트는 별도 수신 스레드에서 받았다. 그 스레드가 모델을
        # 적용하는 시점과 학습 시작(다른 통신 그룹의 broadcast 뒤) 사이에 순서 보장이 없어, 학습 도중에 파라미터가 바뀔 수 있었다.
        # 이제 클라이언트는 지시(와 모델)를 받아 적용한 뒤에 학습을 시작한다. 받는 대상(latest·deprecated)은 원래와 같다.
        flatten_model = TensorBuffer(list(self.model.state_dict().values()))
        for c_id in range(1, self.num_clients+1):
            flag = 1 if c_id in model_ids else 0
            dist.send(tensor=torch.tensor([flag]), dst=c_id)
            if flag:
                dist.send(tensor=flatten_model.buffer, dst=c_id)

    def terminate_FL(self):
        # 종료 지시 -1 (send_round_instructions와 같은 형식). 클라이언트가 루프를 빠져나와 barrier에 도달한다.
        for idx in range(1, self.num_clients+1):
            dist.send(tensor=torch.tensor([-1]), dst=idx)



