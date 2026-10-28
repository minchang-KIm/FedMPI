from methods.FedAvg import FedAvgClient
from utils.utils import *

from utils.model_utils import TensorBuffer
import torch.distributed as dist

import torch
import time
import copy
import threading

from torch.utils.data import DataLoader
from torch.optim import SGD
from torch.nn import CrossEntropyLoss

class SAFAClient(FedAvgClient.FedAvgClient):
    def __init__(self, num_clients, selection_ratio, batch_size, local_epoch, lr, dataset, FLgroup):
        super().__init__(int(num_clients * selection_ratio), 40, local_epoch, 0.001, dataset, FLgroup)
        self.num_clients = num_clients
        self.local_model_version=0
        self.len_local_dataset = len(dataset)


    def setup(self, cluster_type):
        super().setup(cluster_type)
        
        profiling_group = dist.new_group([idx for idx in range(0,self.num_selected_clients+1)])
        flatten_model = TensorBuffer(list(self.model.state_dict().values()))
        profiling_model_state_dict = self.model.state_dict()
        dist.broadcast(tensor=flatten_model.buffer, src=0, group=profiling_group)

        dist.broadcast(tensor=flatten_model.buffer, src=0, group=self.FLgroup)

        flatten_model.unpack(profiling_model_state_dict.values())
        self.model.load_state_dict(profiling_model_state_dict)

        self.train()

        T_train_k = self.total_train_time

        self.total_train_time=0

        dist.send(tensor=torch.tensor(T_train_k), dst=0)
    
    def receive_round_instruction(self):
        """라운드 지시를 받는다 (SAFAServer.send_round_instructions). 반환: False = FL 종료.
        지시가 1이면 글로벌 모델을 받아 로컬 모델을 교체한다 (latest·deprecated 클라이언트의 동기화, SAFA 식 (3)).

        [버그 수정 2026-10-28] 원래 코드(수신 스레드의 receive_global_model_from_server)의 두 문제를 고쳤다.
        1) unpack만 하고 load_state_dict를 하지 않아 글로벌 모델이 모델에 적용되지 않았다. TensorBuffer.unpack은
           `tensor.data = entry.clone()`으로 state_dict 사본만 바꾼다. 다른 클라이언트들은 모두 load_state_dict를 부른다.
           이 때문에 클라이언트는 자기 모델만 계속 학습했다 (F7_MNIST_SAFA_C0.1_rep1, b9f353a: 최고 37.77%, 마지막 11.39%).
        2) 별도 스레드가 받아서, 모델 적용과 학습 시작 사이에 순서 보장이 없었다. 이제 학습 전에 같은 스레드에서 받는다.
        """
        flag = torch.tensor([0])
        dist.recv(tensor=flag, src=0)
        if flag.item() == -1:
            return False
        if flag.item() == 1:
            model_state_dict = self.model.state_dict()
            flatten_model = TensorBuffer(list(model_state_dict.values()))
            dist.recv(tensor=flatten_model.buffer, src=0)
            flatten_model.unpack(model_state_dict.values())
            self.model.load_state_dict(model_state_dict)
        return True

    def train(self, terminate_flag=None):
        printLog(f"CLIENT {self.id}", "로컬 학습을 시작합니다.")
            

        start=time.time()

        self.model.train()
        optimizer = SGD(self.model.parameters(), lr=self.lr, momentum=0.9)
        
        dataloader = DataLoader(self.dataset, self.batch_size, shuffle=True)

        loss_function = CrossEntropyLoss()

        for e in range(self.local_epoch):
            for data, labels in dataloader:
                optimizer.zero_grad()
                outputs = self.model.forward(data)
                loss = loss_function(outputs, labels)
                loss.backward()
                optimizer.step()
            printLog(f"CLIENT {self.id}", f"{e+1} epoch을 수행했습니다.")
        self.total_train_time += time.time()-start

    def send_local_model_to_server(self):

        flatten_model=TensorBuffer(list(self.model.state_dict().values()))
        dist.send(tensor=flatten_model.buffer, dst=0)