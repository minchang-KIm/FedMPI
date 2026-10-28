"""SAFA 클라이언트 — 수정판.

methods/SAFA의 클라이언트와 다른 점:
  1. lr·batch size를 실행 인자대로 쓴다 (저자 구현은 lr 0.001, batch 40으로 고정).
  2. 글로벌 모델을 별도 수신 스레드가 아니라 라운드 시작 지시와 함께 동기적으로 받는다.
     (저자 구현은 수신 스레드가 모델을 다 풀기 전에 학습이 시작될 수 있다)
"""
from methods.SAFA import SAFAClient
from utils.model_utils import TensorBuffer
from utils.utils import printLog

import torch.distributed as dist
import torch


class SAFAfixClient(SAFAClient.SAFAClient):
    def __init__(self, num_clients, selection_ratio, batch_size, local_epoch, lr, dataset, FLgroup):
        super().__init__(num_clients, selection_ratio, batch_size, local_epoch, lr, dataset, FLgroup)
        self.batch_size = batch_size
        self.lr = lr

    def receive_round_instruction(self):
        """반환: False = FL 종료. 지시가 1이면 글로벌 모델을 받아 로컬 모델을 교체한다."""
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
