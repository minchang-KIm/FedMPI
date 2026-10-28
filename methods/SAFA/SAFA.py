from utils.utils import *

import wandb
import time
import threading
import copy
import random

def generate_crash_trace(num_clients, num_rounds):
    clients_crash_prob_vec = [0.1 for _ in range(0, num_clients+1)]
    crash_trace=[]
    progress_trace=[]
    for r in range(num_rounds):
        crash_ids=[]
        progress = [1.0 for _ in range(0,num_clients+1)]
        for c_id in range(1, num_clients+1):
            rand=random.random()
            if rand <= clients_crash_prob_vec[c_id]:
                crash_ids.append(c_id)
                progress[c_id] = rand / clients_crash_prob_vec[c_id]
        crash_trace.append(crash_ids)
        progress_trace.append(progress)
    
    return crash_trace, progress_trace




class SAFA(object):
    def __init__(self, lag_tolerance):
        self.lag_tolerance = lag_tolerance
    
    def runClient(self, Client):
        # [버그 수정 2026-10-28] 라운드 지시(와 글로벌 모델)를 학습 전에 받는다 (SAFAClient.receive_round_instruction 참고).
        while Client.receive_round_instruction():
            make_ids_list=torch.tensor([0 for _ in range(0,Client.num_clients)])
            dist.broadcast(tensor=make_ids_list, src=0, group=Client.FLgroup)
            if Client.id in make_ids_list:
                Client.train()
                Client.send_local_model_to_server()


        dist.barrier()
            
    def runServer(self, Server):
        current_FL_start = time.time()
        clients_idx = [idx for idx in range(1,Server.num_clients+1)]
        coefficient = Server.calculate_coefficient(clients_idx)

        Server.lag_tolerance = self.lag_tolerance

        crash_trace, progress_trace = generate_crash_trace(Server.num_clients, Server.target_rounds)

        picked_ids = []
        # FL 프로세스 시작
        while True:
            
            current_round_start=time.time()

            # [버그 수정 2026-10-28] 0라운드는 모든 클라이언트가 학습한다(아래 make_ids_list = clients_idx). 원래 코드는
            # 0라운드에도 충돌 목록을 빼서 picks/undrafted/버전을 정했기 때문에, 학습하고 모델을 보낸 클라이언트의 캐시·버전이
            # 갱신되지 않았다. 저자 구현도 0라운드 첫 epoch은 전원이 학습하고 그 모델로 캐시를 시작한다.
            crash_ids = [] if Server.current_round == 0 else crash_trace[Server.current_round]
            printLog("SERVER", f"crashed clients: {crash_ids}")
            make_ids = [c_id for c_id in range(1, Server.num_clients+1) if c_id not in crash_ids]
            printLog("SERVER", f"make clients: {make_ids}")

            # compensatory first-come-first-merge selection, last-round picks are considered low priority
            picked_ids = Server.CFCFM(make_ids, picked_ids)
            printLog("SERVER", f"picked clients: {picked_ids}")
            
            undrafted_ids = [c_id for c_id in make_ids if c_id not in picked_ids]
            printLog("SERVER", f"undrafted clients: {undrafted_ids}")

            # distributing step
            # distribute the global model to the edge in a discriminative manner
            good_ids, deprecated_ids = Server.version_filter(clients_idx, Server.lag_tolerance)
            printLog("SERVER", f"good clients: {good_ids}")
            printLog("SERVER", f"deprecated clients: {deprecated_ids}")

            latest_ids, straggler_ids = Server.version_filter(good_ids, 0)
            printLog("SERVER", f"latest clients: {latest_ids}")

            # case 1: deprecated clients
            Server.update_cloud_cache_deprecated(deprecated_ids)
            Server.update_version(deprecated_ids, Server.current_round-1)
            # case 1·2: deprecated·latest clients에게 글로벌 모델, 나머지에게는 "로컬 모델 유지" 지시
            Server.send_round_instructions(deprecated_ids + latest_ids)
            # case 3: non-deprecated stragglers
            # Moderately straggling clients remain unsync.

            # Local Update            
            if Server.current_round==0:
                make_ids_list = clients_idx
            else:
                make_ids_list = make_ids+[-1 for _ in range(Server.num_clients-len(make_ids))]
            dist.broadcast(tensor=torch.tensor(make_ids_list), src=0, group=Server.FLgroup)
            Server.receive_local_model_from_selected_clients(make_ids_list)



            # Aggregation step
            # discriminative update of cloud cache and aggregate
            # pre-aggregation: update cache from picked clients
            Server.update_cloud_cache(picked_ids)        
            # SAFA aggregation
            # [버그 수정 2026-10-28] 전체 K개 캐시를 n_k/n으로 집계한다 (SAFA 식 (7), 저자 구현 safa_aggregate(cache, ...)).
            # 원래 코드는 이번 라운드 비충돌 클라이언트의 캐시만 집계했다.
            Server.average_aggregation(clients_idx, coefficient)
            global_acc, global_loss = Server.evaluate()
            # post=aggregation
            Server.update_cloud_cache(undrafted_ids)

            # update_version
            Server.update_version(make_ids, Server.current_round)

            printLog("SERVER", f"Version updated: {Server.local_model_version}")
            Server.current_round+=1

            printLog("SERVER", f"{Server.current_round}번째 글로벌 모델 test_accuracy: {round(global_acc*100,4)}%, test_loss: {round(global_loss,4)}")

            if Server.wandb_on=="True":
                wandb.log({"test_accuracy": round(global_acc*100,4), "test_loss":round(global_loss,4), "runtime_for_one_round":time.time()-current_round_start, "wall_time(m)":(time.time()-current_FL_start)/60})
            
            if global_acc>=Server.target_accuracy:
                printLog("SERVER", f"목표한 정확도에 도달했으며, 수행한 라운드 수는 {Server.current_round}회 입니다.")
                
                break
            
            elif Server.current_round == Server.target_rounds:
                printLog(f"SERVER", f"목표한 라운드 수에 도달했으며, 최종 정확도는 {round(global_acc*100,4)}% 입니다.")
                break
        Server.terminate_FL()
        printLog(f"SERVER", "FL 프로세스를 종료합니다.")
        dist.barrier()