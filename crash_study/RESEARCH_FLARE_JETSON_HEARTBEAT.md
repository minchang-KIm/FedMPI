# 차량용 연합학습 클라우드를 위한 dead client 처리 조사

**NVIDIA FLARE × Jetson AGX Orin 32GB 시너지, heartbeat 기반 프레임워크 비교**

- 작성일: 2026-10-10
- 조사 방법: 각 프레임워크의 공식 문서와 GitHub `main` 브랜치 소스를 직접 읽었다.
  - NVFlare: 2026-10-09 커밋, PyPI 최신 2.9.0
  - Flower: 2026-10-09 커밋
  - FEDn: 2026-09-23 커밋
  - FedML: 2024-05-13 커밋
  - OpenFL: 2026-08-25 커밋
  - Fed-BioMed: 2026-09-25 커밋
- 소스에서 확인한 사실은 파일과 함수 이름을 함께 적었다. 추론한 내용은 **(추론)**으로 표시했다.

---

## 0. 한눈에 보는 결론

1. **NVIDIA FLARE의 dead client 기능은 "응답 없는 클라이언트 때문에 서버가 무한히 기다리는 문제"를 막기 위한 장치다.**
   - NVIDIA는 자율주행(AV) 모델을 국가 간 연합학습으로 운영했다. 이때 클라이언트 job이 조용히 죽고 서버가 무기한 기다리는 사고를 직접 겪었다. 원인은 5~10분짜리 네트워크 단절이었다.
   - 이후 FLARE 팀이 "일시적 네트워크 단절에서 복구하고 학습을 재개하는 메커니즘"을 넣었다(NVIDIA 기술 블로그, 2024-10-24).
   - 현재 FLARE 서버는 두 가지 일을 한다.
     - 죽은 클라이언트만 기다리는 작업을 `CLIENT_DEAD` 상태로 끝낸다.
     - "살아있는 클라이언트 < `min_sites`"가 되면 무한 대기 대신 **명시적으로** job을 중단한다.
2. **SASAFL 코드에는 이 두 장치가 모두 없다.** 본 저장소의 실험(`crash_study/results`)에서 관측한 사실은 다음과 같다.
   - hard crash가 나면 1.4초 만에 job 전체가 종료된다.
   - silent drop이 나면 서버가 멈춘 차량에 대한 `dist.send`에서 블록된다. gloo timeout(기본 30분)이 끝날 때까지 정지하고, 그다음 job 전체가 종료된다.
   - 장애가 없어도 Pᵣ가 K에 도달하는 순간 업로드하지 못하는 클라이언트가 1대라도 있으면 영구 대기에 빠진다.
3. **Jetson AGX Orin 32GB와 FLARE의 시너지는 실재하지만, 바로 쓸 수 있는 형태는 아니다.**
   - FLARE 2.7부터 "Edge Device Training (Jetson / GPU)" 문서와 `EdgeFedBuffRecipe`가 있다. 이 구성은 계층형 구조, FedBuff 비동기 집계, HTTP pull 프로토콜을 쓴다. 차량처럼 **수시로 접속·이탈하는 기기**를 전제로 설계됐다.
   - 다만 저장소의 PyTorch 엣지 예제는 기기를 **시뮬레이션**한다. 실제 Jetson 연결은 in-tree Python 기기 SDK(`PTRunner` + `FegApi`)를 직접 엮어야 한다.
   - FLARE는 Python ≥ 3.10을 요구하므로 **JetPack 6(Ubuntu 22.04)**이 필요하다.
4. heartbeat나 연결 상태로 dead client를 감지하는 다른 오픈소스는 다음과 같다.
   - **Flower**: SuperNode heartbeat, 기본 30초 간격, 2회 놓치면 offline
   - **FEDn**: 클라이언트가 combiner에 heartbeat 전송
   - **FedML**: MQTT Last-Will 메시지
   - **Fed-BioMed**: 작업 요청 스트림으로 연결 상태 추적
   - OpenFL은 heartbeat 없이 straggler 정책(시간 cutoff, 비율)으로 대응한다.

---

## 1. NVIDIA FLARE의 dead client 기능

### 1.1 무엇을 하는가 (소스 기준)

FLARE는 **시스템 수준**과 **job 수준**의 2계층으로 생존 여부를 관리한다.

| 계층 | 메커니즘 | 소스 위치 | 기본값 |
|---|---|---|---|
| 시스템 | 클라이언트가 주기적으로 heartbeat를 보낸다. 서버는 `last_connect_time`이 `heart_beat_timeout`보다 오래된 클라이언트를 로그아웃시키고 `notify_dead_client()`를 호출한다 | `nvflare/private/fed/server/fed_server.py` `remove_dead_clients()`, `logout_client()` | 생성자 기본 600초. 설정 파서 기본 60초(`server_json_config.py`). 배포 설정에 따라 다르다 |
| job | 클라이언트 job 프로세스가 job heartbeat를 보낸다 | `client_runner.py` `JOB_HEARTBEAT_INTERVAL` | 10초 |
| job | 서버와 클라이언트가 job 목록을 동기화하다가, 클라이언트에 job이 없어졌으면 **dead job report**를 보낸다 | `fed_server.py` `_notify_dead_job()` → `server_runner.handle_dead_job()` | `sync_client_jobs_require_previous_report=true`(오탐 방지) |
| 컨트롤러 | dead job report를 받은 클라이언트를 **watch list**에 올린다. **유예 시간** 동안 다시 활동하지 않으면 disconnected로 확정하고 `CLIENT_DISCONNECTED` 이벤트를 발생시킨다 | `nvflare/apis/impl/wf_comm_server.py` `process_dead_client_report()`, `_check_dead_clients()` | `dead_client_grace_period` 60초 |
| 컨트롤러 | 어떤 작업이 **죽은 클라이언트의 응답만** 기다리고 있으면, 그 작업을 `TaskCompletionStatus.CLIENT_DEAD`로 끝낸다. 살아있는 대상이 하나라도 남아 있으면 계속 기다린다 | `wf_comm_server.py` `_get_task_dead_clients()`, `_do_check_tasks()` | 작업 시작 후 `dead_client_check_lead_time` 30초가 지나야 검사 |
| 컨트롤러 | **배포 정책 검사**: 살아있는 클라이언트 < `min_sites`, 필수 사이트(`required_sites`) 사망, 전원 사망 중 하나면 job을 중단한다 | `wf_comm_server.py` `_job_policy_violated()` | job meta의 `min_sites`, `required_sites` |
| 컨트롤러 | 죽었다고 판정된 클라이언트가 다시 활동하면 watch list에서 빼고 `CLIENT_RECONNECTED` 이벤트를 발생시킨다 | `wf_comm_server.py` `client_is_active()` | - |
| Job API | `fail_fast=True`로 설정하면 유예 시간을 0으로 바꿔 약 0.2초 안에 판정한다 | `nvflare/job_config/api.py` `_apply_fail_fast()` | 기본값 False |
| 수집 계열 워크플로 | `min_clients`만큼 응답이 오면 `wait_time_after_min_received`만큼 더 기다린 뒤 집계한다. 그 뒤에 도착한 결과는 버린다 | `scatter_and_gather.py` | `train_timeout`, `wait_time_after_min_received` |

`_job_policy_violated()`의 핵심부(원문 그대로):

```python
if not alive_clients:
    self.log_error(fl_ctx, f"All clients are dead: {dead_clients}")
    return True
...
if len(alive_clients) < job.min_sites:
    self.log_error(fl_ctx, f"Alive clients {len(alive_clients)} < required min {job.min_sites}")
    return True
```

> SASAFL과의 대비: SASAFL에도 "최소 참여 수"(P_min = C·K)와 동적 quota Pᵣ가 있다. 하지만 **"살아있는 클라이언트가 이보다 적어졌을 때 무엇을 할지"를 정한 코드가 없다.** `wait_until_can_update_global_model()`은 timeout도 생존 확인도 없이 busy-wait한다(실험 E3-T1: 15초 동안 반환하지 않고 CPU 100% 사용).
> FLARE는 같은 상황을 "검사하고, 판정하고, 정책에 따라 중단하거나 계속하는" 흐름으로 처리한다.

### 1.2 왜 만들었는가

| 목적 | 근거 |
|---|---|
| **응답 없는 클라이언트 때문에 서버가 무기한 기다리는 문제 방지** | NVIDIA 기술 블로그 *Federated Learning in Autonomous Vehicles Using Cross-Border Training* (2024-10-24, Hanson Xu 외)에 다음 문장들이 있다. "certain client training jobs would terminate without any apparent reason … causing the server to wait indefinitely for their return." 원인으로는 "prolonged network outages lasting 5 to 10 minutes"를 들었다. 해결책으로 "The NVFLARE team implemented a mechanism to recover from temporary network outages and resume training"이라고 적었고, 이후 "no unexplained job failures"였다고 한다. **(추론)** 블로그는 구체 기능 이름을 밝히지 않는다. 다만 소스의 dead client watch list, 유예 시간, `CLIENT_RECONNECTED` 처리가 바로 이 "일시 단절 후 복구" 요구에 해당한다 |
| **job 생명주기와 사이트 건강 관리** | FLARE 2.4 릴리스 노트에 "Server controller manages the job lifecycle (eg. health of client sites, monitoring of job status)"라고 되어 있다. 이 설명은 client-side 워크플로에도 똑같이 적용된다 |
| **무기한 정지 대신 명시적 정책 결정** | `_job_policy_violated()`가 `min_sites`, `required_sites`, 전원 사망 여부로 중단을 결정한다. `fail_fast` 문서는 "The job then aborts only when the normal deployment policy is violated"라고 설명한다 |
| **일시 단절과 실제 사망의 구분 (오탐 방지)** | 장치가 여럿 있다. 기본 60초 유예(`dead_client_grace_period`), 작업 시작 후 30초 lead time, `sync_client_jobs_require_previous_report`(공식 timeout 가이드: "to avoid false dead-job reports caused by transient startup or sync races"), 그리고 최근 릴리스의 "startup grace period prevents premature dead-client detection during initialization"이다 |
| **엣지 기기의 상시 접속·이탈 수용** | Edge 문서는 "edge devices can connect and disconnect at any time. This requires the training strategy to accommodate dynamic participation"이라고 쓴다. 이 요구는 dead-client 판정이 아니라 비동기 FedBuff와 pull 프로토콜로 해결한다(2절) |
| **관측성** | `CLIENT_DISCONNECTED`와 `CLIENT_RECONNECTED` 이벤트는 `system_metrics_collector.py`와 `job_stats_reporter.py`가 수집한다. StatsD, Prometheus, Grafana 모니터링(2.6)과 연결된다 |

---

## 2. Jetson AGX Orin 32GB를 차량 클라이언트로 쓸 때 FLARE의 시너지

### 2.1 하드웨어 요약 (NVIDIA 데이터시트 기준)

| 항목 | Jetson AGX Orin 32GB |
|---|---|
| AI 성능 | 200 TOPS (INT8, sparse) |
| GPU | Ampere, CUDA 코어 1792개, Tensor 코어 56개 |
| CPU | Arm Cortex-A78AE 8코어 (최대 2.2GHz) |
| 메모리 | 32GB LPDDR5, 204.8 GB/s (CPU와 GPU가 공유) |
| 가속기 | NVDLA v2.0 ×2, PVA v2.0 |
| 전력 | 15–40 W |
| 소프트웨어 | JetPack 6.x = Jetson Linux r36, Ubuntu 22.04, Python 3.10. JetPack 5.x = Ubuntu 20.04, Python 3.8 |

### 2.2 시너지가 있는 지점

| 차량 FL 요구 | FLARE가 제공하는 것 | 근거 |
|---|---|---|
| 차량이 수시로 끊기고 다시 붙음 | Edge 모드는 **라운드 개념 없이** FedBuff 비동기 집계를 쓴다. 기기가 보고하면 선택 풀에서 빠지고, 빈자리("hole")를 다른 기기로 채운다 | `docs/user_guide/edge_development/edge_devices.rst` |
| 오래된(stale) 업데이트 처리 | `max_model_history`보다 오래된 버전의 업데이트는 버린다. 여러 버전을 동시에 학습할 수 있다 | 같은 문서 `ModelManagerConfig` |
| 집계 시점 제어 | `num_updates_for_model`(새 글로벌 모델을 만드는 데 필요한 업데이트 수), `device_selection_size`, `min_hole_to_fill` | 같은 문서 |
| 단절에 강한 통신 | 기기는 HTTP **pull** 방식(EDIP)으로 통신한다: `getJob` → `getTask` → `reportResult`. `RETRY`, `NO_TASK`, `NO_JOB` 응답에 따라 재시도한다. 서버가 기기에 blocking send를 하지 않는다 | 같은 문서 EDIP 절 |
| 대규모 차량 | 계층형 FLARE(서버 → relay → leaf client → 기기). 문서는 "수백만 기기"까지 확장을 목표로 한다 | `docs/release_notes/flare_270.rst` |
| Jetson 명시 지원 | `EdgeFedBuffRecipe`: "for training with standard PyTorch on other edge devices (e.g., NVIDIA Jetson devices)" | `edge_devices.rst` |
| 기기 측 코드 | `nvflare.edge.device.pt.PTRunner`(PyTorch 학습기)와 `nvflare.edge.simulation.feg_api.FegApi`(HTTP 클라이언트: `get_job`, `get_task`, `report_result`) | 소스 |
| 클라이언트 생존 관리 | 1절의 heartbeat, dead client, 정책 장치 (leaf client 계층) | 소스 |
| 운영과 보안 | provisioning으로 인증서와 TLS를 발급한다. StatsD, Prometheus, Grafana 모니터링(2.6) | 릴리스 노트 |
| AV 도메인 경험 | NVIDIA 자체 AV 모델(PathNet, RadarNet 등)을 FLARE로 국가 간 연합학습한 운영 사례가 있다 | NVIDIA 블로그 2024-10 |

**SASAFL 아이디어를 FLARE Edge에 옮길 때의 대응 (추론, 설계 제안)**

| SASAFL 요소 | FLARE Edge에서의 대응 지점 |
|---|---|
| 버퍼가 Pᵣ개 차면 집계 | `ModelManagerConfig.num_updates_for_model` (현재는 고정값이다. loss 기반 동적 조정은 ModelManager를 직접 구현해야 함) |
| staleness 기반 보간 (Eq.2) | `max_model_history` + 사용자 정의 aggregator 또는 updater |
| 글로벌 모델 수신 정책 (Alg.1) | 기기 측 `PTRunner` 또는 executor에서 `getTask` 응답을 처리할 때 구현 |
| (SASAFL에 없음) 생존 기기 < quota | `device_selection_size`와 hole 채우기, `min_sites` 정책, `CLIENT_DEAD` 작업 종료 |

### 2.3 주의할 점과 공백

1. **Python 버전**: NVFlare `setup.cfg`가 `python_requires = >= 3.10`이다. 따라서 Orin에는 **JetPack 6.x**가 필요하다. JetPack 5.x(Python 3.8)에서는 최신 FLARE를 설치할 수 없다.
2. **실기기 예제의 범위**: 엣지 예제 README는 두 경로를 둔다. "ExecuTorch-based FL (real devices …)" 경로는 Android/iOS SDK용이다. "Pure PyTorch Simulated … (no real devices)" 경로는 실기기 없이 시뮬레이션한다.
   - 즉 Jetson 실기기는 `PTRunner`와 `FegApi`를 엮어 EDIP 클라이언트를 직접 구성해야 한다(엔지니어링 비용).
   - 또는 Jetson을 **일반 FLARE 클라이언트**로 등록할 수 있다. 이 방식은 heartbeat와 dead client 처리를 그대로 받는다. 하지만 cross-silo 가정(안정적 연결)에 맞춰져 있다.
3. **SimEnv 미지원**: README는 "SimEnv (simulator) is not supported for edge examples"라고 명시한다. 계층형 시스템을 provisioning해서 `ProdEnv`로 실행해야 한다.
4. **PyTorch on Jetson**: Jetson용 PyTorch는 NVIDIA가 배포하는 aarch64 wheel이나 컨테이너를 써야 한다. 버전 조합을 사전에 검증해야 한다.
5. **통합 메모리 32GB**: CPU와 GPU가 메모리를 공유한다. 주행 중 인지 스택과 동시에 학습하면 메모리와 전력 예산이 충돌한다. 학습 시간대 제어(정차, 충전 중)가 필요하다. **(추론)**
6. **차량 네트워크**: 차량은 NAT나 이동통신망 뒤에 있다. 따라서 서버가 차량에 연결을 여는 push 방식보다, 차량이 서버로 요청하는 **pull 방식이 필수적**이다. FLARE Edge의 HTTP pull과 Flower의 SuperNode pull은 이 조건을 만족한다. 현재 torch.distributed 기반 SASAFL testbed는 서버→클라이언트 blocking send를 하므로 만족하지 못한다.

---

## 3. heartbeat나 연결 상태 기반 dead client 감지가 있는 오픈소스 프레임워크

| 프레임워크 | 감지 방식 | 감지 후 동작 | 소스 근거 | 차량 FL 적합성 메모 |
|---|---|---|---|---|
| **NVIDIA FLARE** | 시스템 heartbeat + job heartbeat(10초) + dead job report + 유예 60초 | 작업 `CLIENT_DEAD` 종료, `min_sites`/`required_sites` 정책으로 중단 여부 결정, 재접속 이벤트 | 1절 | Edge 모드(FedBuff, pull)가 차량 시나리오에 가장 가깝다 |
| **Flower** | SuperNode가 SuperLink에 `SendNodeHeartbeat` 전송. 기본 간격 30초, `HEARTBEAT_PATIENCE=2` → `online_until = 마지막 heartbeat + 2×간격` | 시간이 지나면 노드를 offline으로 표시. offline 노드로 가는 메시지에는 **`NODE_UNAVAILABLE` 오류 응답**("failed to report a heartbeat within 2 × its expected interval")을 생성해 무한 대기를 막는다. 전략 쪽 `accept_failures`(기본 True)로 실패를 제외하고 집계 | `flwr/common/constant.py`, `server/superlink/linkstate/in_memory_linkstate.py`, `linkstate/utils.py` `check_node_availability_for_in_message()` | SuperNode가 pull하는 구조라 NAT 뒤 차량에 적합하다. 노드 재활성화(`activate_node`)를 지원한다 |
| **FEDn (Scaleout)** | 클라이언트가 combiner로 `Heartbeat` gRPC 메시지 전송. edge runtime에서 `with_heartbeat` 옵션 | 서버(combiner) 측 처리는 이번 조사에서 확인하지 않았다 | `scaleout-client-python/scaleout/client/grpc_handler.py` `heartbeat()`, `grpc_edge_client_runtime.py` `_send_heartbeats()` | edge client 런타임이 따로 있다 |
| **FedML** | MQTT keepalive(10초) + **Last-Will 메시지**. 연결이 끊기면 브로커가 `{"status": OFFLINE}`를 대신 발행 | `client_active_list`에서 제거한다. 단, cross-silo 기본 aggregator는 `check_whether_all_receive()`로 **전원 업로드를 기다린다**. 감지 결과가 집계 대기에는 반영되지 않는다(소스 기준) | `core/distributed/communication/mqtt_s3/mqtt_s3_multi_clients_comm_manager.py`, `cross_silo/server/fedml_aggregator.py` | 마지막 커밋이 2024-05로 유지보수가 정체돼 있다 |
| **Fed-BioMed** | 노드가 gRPC로 작업을 요청(long-poll)하는 스트림의 상태로 `NodeActiveStatus`(WAITING, ACTIVE, DISCONNECTED)를 추적. 전용 heartbeat는 아님 | 요청 정책 `DiscardOnTimeout`, `StopOnTimeout`, `StopOnDisconnect`, `StopOnError`를 선택할 수 있다 | `transport/node_agent.py`, `researcher/requests/_policies.py` | 의료 cross-silo 지향 |
| **OpenFL** (비교용) | heartbeat는 없다 | `StragglerPolicy`: `WaitForAllPolicy`, `CutoffTimePolicy`(cutoff 시간과 `minimum_reporting`), `PercentagePolicy` | `component/aggregator/straggler_handling.py` | 늦게 오는 클라이언트를 정책으로 끊을 수 있다 |
| **torch.distributed / torchrun** (참고) | 없음. 연산 timeout만 있다(gloo 기본 30분) | worker k개(k≤n)가 실패하면 **모든 worker 중지·재시작**(`max_restarts` 기본 0 → job 실패). 최신 버전의 peer 재구성 API(`_reconfigure`)는 experimental | `docs_screenshots/01–07` | FL용 장애 모델이 아니다 |

---

## 4. 차량 FL 클라우드 설계에 대한 시사점

1. **전송 계층**: 차량이 서버로 요청하는 pull, 메시지 지향 구조(gRPC, HTTP, MQTT)여야 한다. 서버가 모든 클라이언트에게 blocking send를 하는 collective 스타일(torch.distributed)은 차량 1대만 멈춰도 서버 전체가 멈춘다(실험 E2).
2. **생존 판정**: heartbeat와 유예 시간으로 "일시 단절"과 "이탈"을 구분해야 한다. FLARE의 기본값(60초 유예, 30초 lead time)과 Flower의 기본값(30초 간격 ×2)이 출발점이 될 수 있다. 터널 같은 짧은 음영은 유예 시간 안에 흡수하는 것이 맞다.
3. **알고리즘의 하한 처리**: quota(Pᵣ, P_min)는 **현재 살아있는 차량 수에 따라 조정**되어야 한다. 예를 들면 `P_eff = min(Pᵣ, alive)`에 deadline을 더한다. 살아있는 차량이 정책 하한 아래로 떨어졌을 때의 행동도 명시해야 한다(대기 상한, 부분 집계, 중단).
   - 시뮬레이션(E4)에서 정상 상태 연결 비율 `p_back/(p_back+p_drop)`이 C 아래로 내려가면 SASAFL 규칙은 사실상 정지했다. 같은 조건에서 crash-aware 규칙은 정지하지 않았다.
4. **상태 보존**: torchrun 재시작은 모든 상태를 잃고 라운드 0부터 다시 시작한다(실험 E1b). 글로벌 모델 버전, 버퍼, 클라이언트별 staleness를 서버 쪽에 영속화해야 한다.

---

## 출처

**공식 문서와 블로그**
- NVIDIA FLARE Timeout Troubleshooting Guide: https://nvflare.readthedocs.io/en/main/user_guide/timeout_troubleshooting.html
- NVIDIA FLARE FAQ: https://nvflare.readthedocs.io/en/main/faq.html
- NVIDIA FLARE ScatterAndGather API (2.3): https://nvflare.readthedocs.io/en/2.3/apidocs/nvflare.app_common.workflows.scatter_and_gather.html
- NVIDIA FLARE 2.3 릴리스 노트: https://nvflare.readthedocs.io/en/main/release_notes/flare_230.html
- NVIDIA FLARE FlareAgent (heartbeat_timeout): https://nvflare.readthedocs.io/en/2.6/apidocs/nvflare.client.flare_agent.html
- NVIDIA FLARE Controller API (`handle_dead_job`): https://nvflare.readthedocs.io/en/2.4.2/apidocs/nvflare.apis.impl.controller.html
- NVIDIA FLARE Edge 예제: https://github.com/NVIDIA/NVFlare/tree/main/examples/advanced/edge
- NVIDIA 기술 블로그, *Federated Learning in Autonomous Vehicles Using Cross-Border Training* (2024-10-24): https://developer.nvidia.com/blog/federated-learning-in-autonomous-vehicles-using-cross-border-training/
- Jetson AGX Orin Series Technical Brief: https://www.nvidia.com/content/dam/en-zz/Solutions/gtcf21/jetson-orin/nvidia-jetson-agx-orin-technical-brief.pdf
- Jetson AGX Orin 데이터시트: https://openzeka.com/en/wp-content/uploads/2022/08/Jetson-AGX-Orin-Module-Series-Datasheet.pdf
- JetPack 6.0: https://developer.nvidia.com/embedded/jetpack-sdk-60
- JetPack 6.2: https://developer.nvidia.com/embedded/jetpack-sdk-62
- JetPack 버전 대응표 (서드파티, 일부 오류 있음): https://proventusnova.com/blog/jetpack-versions-l4t-compatibility-table/
- Flower FedAvg API: https://flower.ai/docs/framework/ref-api/flwr.server.strategy.FedAvg.html
- PyTorch 1.12 torchrun: https://docs.pytorch.org/docs/1.12/elastic/run.html
- PyTorch 1.12 torch.distributed: https://docs.pytorch.org/docs/1.12/distributed.html
- PyTorch stable torch.distributed: https://docs.pytorch.org/docs/stable/distributed.html

**소스 코드 (2026-10-10 시점 clone)**
- NVFlare: https://github.com/NVIDIA/NVFlare
  - `nvflare/apis/impl/wf_comm_server.py`
  - `nvflare/private/fed/server/fed_server.py`
  - `nvflare/private/fed/server/server_runner.py`
  - `nvflare/job_config/api.py`
  - `nvflare/private/fed/client/client_runner.py`
  - `nvflare/edge/device/pt/runner.py`
  - `nvflare/edge/simulation/feg_api.py`
  - `docs/user_guide/edge_development/edge_devices.rst`
  - `docs/release_notes/flare_240.rst`, `docs/release_notes/flare_270.rst`
  - `setup.cfg`
- Flower: https://github.com/adap/flower
  - `framework/py/flwr/common/constant.py`
  - `framework/py/flwr/server/superlink/linkstate/in_memory_linkstate.py`
  - `framework/py/flwr/server/superlink/linkstate/utils.py`
  - `framework/py/flwr/server/strategy/fedavg.py`
  - `framework/py/flwr/server/server.py`
- FEDn: https://github.com/scaleoutsystems/fedn
  - `scaleout-client-python/scaleout/client/grpc_handler.py`
  - `scaleout-client-python/scaleout/client/grpc_edge_client_runtime.py`
- FedML: https://github.com/FedML-AI/FedML
  - `python/fedml/core/distributed/communication/mqtt_s3/mqtt_s3_multi_clients_comm_manager.py`
  - `python/fedml/cross_silo/server/fedml_server_manager.py`
  - `python/fedml/cross_silo/server/fedml_aggregator.py`
- Fed-BioMed: https://github.com/fedbiomed/fedbiomed
  - `fedbiomed/transport/node_agent.py`
  - `fedbiomed/researcher/requests/_policies.py`
  - `fedbiomed/researcher/requests/_requests.py`
- OpenFL: https://github.com/securefederatedai/openfl
  - `openfl/component/aggregator/straggler_handling.py`
