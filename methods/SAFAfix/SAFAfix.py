"""SAFA 프로토콜 — 원 논문(Wu et al., IEEE TC 2021)에 맞춘 수정판의 라운드 진행.

라운드 r:
  1. 충돌 trace(클라이언트별 확률 0.1, 저자 구현과 같음)로 이번 라운드에 학습하는 클라이언트(make_ids)를 정한다.
  2. 분배(식 3): up-to-date·deprecated 클라이언트는 글로벌 모델을 받고, tolerable 클라이언트는 로컬 모델을 유지한다.
     deprecated 클라이언트의 캐시는 글로벌 모델로 바꾼다 (식 6).
  3. make_ids가 학습해 업로드한다. 서버는 도착 순서를 기록한다.
  4. CFCFM(Algorithm 1)으로 도착 순서에서 quota = C·K만큼 뽑는다 (picks). 나머지 도착분은 undrafted.
  5. picks로 캐시를 갱신(사전 집계, 식 6) → 전체 K개 캐시를 n_k/n으로 집계(식 7) → undrafted로 캐시 갱신(사후 집계, 식 8).
"""
from methods.SAFA.SAFA import generate_crash_trace
from utils.utils import printLog

import torch
import torch.distributed as dist
import time
import wandb


class SAFAfix(object):
    def __init__(self, lag_tolerance):
        self.lag_tolerance = lag_tolerance

    def runClient(self, Client):
        while Client.receive_round_instruction():
            make_ids_list = torch.tensor([0 for _ in range(0, Client.num_clients)])
            dist.broadcast(tensor=make_ids_list, src=0, group=Client.FLgroup)
            if Client.id in make_ids_list:
                Client.train()
                Client.send_local_model_to_server()
        dist.barrier()

    def runServer(self, Server):
        current_FL_start = time.time()
        clients_idx = [idx for idx in range(1, Server.num_clients + 1)]
        coefficient = Server.calculate_coefficient(clients_idx)   # n_k / n, 전체 K개 합 = 1
        Server.lag_tolerance = self.lag_tolerance
        crash_trace, _ = generate_crash_trace(Server.num_clients, Server.target_rounds)

        picked_ids = []
        while True:
            current_round_start = time.time()
            if Server.current_round == 0:
                crash_ids = []
            else:
                crash_ids = crash_trace[Server.current_round]
            make_ids = [c_id for c_id in clients_idx if c_id not in crash_ids]
            printLog("SERVER", f"crashed clients: {crash_ids}")

            good_ids, deprecated_ids = Server.version_filter(clients_idx, Server.lag_tolerance)
            latest_ids, _ = Server.version_filter(good_ids, 0)
            printLog("SERVER", f"latest clients: {latest_ids}")
            printLog("SERVER", f"deprecated clients: {deprecated_ids}")
            Server.update_cloud_cache_deprecated(deprecated_ids)
            Server.update_version(deprecated_ids, Server.current_round - 1)
            Server.send_round_instructions(latest_ids + deprecated_ids)

            make_ids_list = make_ids + [-1 for _ in range(Server.num_clients - len(make_ids))]
            dist.broadcast(tensor=torch.tensor(make_ids_list), src=0, group=Server.FLgroup)
            arrival_ids = Server.receive_in_arrival_order(make_ids)
            printLog("SERVER", f"arrival order: {arrival_ids}")

            picked_ids = Server.CFCFM_by_arrival(arrival_ids, picked_ids)
            undrafted_ids = [c_id for c_id in arrival_ids if c_id not in picked_ids]
            printLog("SERVER", f"picked clients: {picked_ids}")
            printLog("SERVER", f"undrafted clients: {undrafted_ids}")

            Server.update_cloud_cache(picked_ids)
            Server.average_aggregation_all(coefficient)
            global_acc, global_loss = Server.evaluate()
            Server.update_cloud_cache(undrafted_ids)
            Server.update_version(make_ids, Server.current_round)

            Server.current_round += 1
            printLog("SERVER", f"{Server.current_round}번째 글로벌 모델 test_accuracy: {round(global_acc*100,4)}%, test_loss: {round(global_loss,4)}")
            if Server.wandb_on == "True":
                wandb.log({"test_accuracy": round(global_acc*100, 4), "test_loss": round(global_loss, 4),
                           "runtime_for_one_round": time.time() - current_round_start,
                           "wall_time(m)": (time.time() - current_FL_start) / 60})
            if global_acc >= Server.target_accuracy:
                printLog("SERVER", f"목표한 정확도에 도달했으며, 수행한 라운드 수는 {Server.current_round}회 입니다.")
                break
            elif Server.current_round == Server.target_rounds:
                printLog("SERVER", f"목표한 라운드 수에 도달했으며, 최종 정확도는 {round(global_acc*100,4)}% 입니다.")
                break
        Server.terminate_FL()
        printLog("SERVER", "FL 프로세스를 종료합니다.")
        dist.barrier()
