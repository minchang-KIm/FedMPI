# crash_study — SASAFL은 차량 crash(연결 끊김)를 견딜 수 있는가

차량용 연합학습 클라우드(Jetson AGX Orin 32GB 클라이언트)를 설계하기 위한 검증 자료다. 두 가지를 실험으로 확인한다.

1. 현재 testbed(torch.distributed + torchrun + gloo) 위의 SASAFL 구현이 차량 1대의 장애에 어떻게 반응하는가
2. SASAFL 알고리즘 자체에 "살아있는 클라이언트 < 최소 참여 수(P_min) 또는 quota(Pᵣ)"에 대한 규칙이 있는가

**원본 코드(`Start.py`, `methods/`)는 수정하지 않았다.** 관측용 진입점(`harness/sasafl_entry.py`)과 외부 장애 주입(신호)만 사용했다.

## 폴더 구성

| 경로 | 내용 |
|---|---|
| `RESULTS_SUMMARY.md` | 실험 결과 요약과 해석 (보고서 본문용) |
| `RESEARCH_FLARE_JETSON_HEARTBEAT.md` | NVIDIA FLARE dead client 기능의 목적, Jetson Orin 시너지, heartbeat 기반 프레임워크 비교 조사 |
| `SASAFL_crash_report_draft.pptx` | PPT 초안 (그림과 표 포함, 발표자 노트에 근거 표기) |
| `figures/` | PPT용 그림 PNG와 `summary_table.{md,csv}` |
| `docs_screenshots/` | PyTorch 공식 문서 캡처 (1.12 = testbed 버전, stable = 최신). 노란 강조와 하단 캡션은 작성자가 추가한 표시 |
| `results/E*/` | 실험별 원본 로그(`run.log`), 이벤트(`events.json`), 2초 간격 샘플(`samples.csv`), 설정, rank별 PID |
| `harness/sasafl_entry.py` | `Start.py`를 감싸는 계측 진입점: PID 기록, SIGUSR1 스택 덤프, 선택적 gloo timeout 주입 |
| `experiments/run_experiment.py` | 장애 주입 오케스트레이터 (E0–E2c) |
| `experiments/code_level_proof.py` | E3: 실제 `SASAFLServer` 메서드를 직접 호출하는 코드 수준 증명 |
| `experiments/simulate_quota.py` | E4: 실제 quota 함수와 실측 loss를 쓰는 끊김률별 교착 시뮬레이션 |
| `analysis/make_figures.py` | 그림과 요약표 생성 |
| `tools/capture_docs.py`, `tools/build_pptx.py` | 문서 캡처, PPT 생성 |

## 장애 모델

| 차량 상황 | 주입 방법 | 의미 |
|---|---|---|
| 시동 OFF, 앱 강제 종료 (hard crash) | `SIGKILL` | 프로세스가 죽고 TCP 연결이 닫힌다 |
| 터널, 음영 지역 (silent drop) | `SIGSTOP` | 프로세스와 TCP 연결은 살아 있지만 상대가 응답하지 않는다 |

## 실험 목록

| ID | 설정 | 검증 대상 |
|---|---|---|
| E0 | K=10, C=0.3, 30라운드, 장애 없음 | 기준선, Pᵣ 실측 궤적 |
| E1 | 5라운드에 rank 3 SIGKILL | hard crash가 job 전체에 미치는 영향 |
| E1b | E1 + `--max_restarts=3` | torchrun 재시작이 복구가 되는가 |
| E2a | 5라운드에 rank 3 SIGSTOP | silent drop 시 서버 동작 |
| E2b | K=10, C=0.5 (P_min=5), 6대 SIGSTOP → 생존 4대 | 생존 < P_min |
| E2c | E2a + gloo timeout 90초 (기본 30분) | timeout 이후 복구되는가 |
| E3 | `wait_until_can_update_global_model`, `get_next_round_minimum_local_model` 직접 호출 | 알고리즘 코드의 crash 비고려 |
| E4 | K=100, 실측 K=100 loss, 마르코프 연결 모델, 설정당 2000회 | 끊김률과 교착 확률 |

공통 설정: MNIST non-IID(gaussian), batch 32, local epoch 2, lr 0.01, τ=9, 프로세스당 2 thread, 단일 노드(wise-175).

## 재현

```bash
cd /home/wise-175/Mando/FedMPI
PY=/home/wise-175/anaconda3/envs/FL/bin/python
$PY crash_study/experiments/run_experiment.py all          # 약 40분
$PY crash_study/experiments/code_level_proof.py
$PY crash_study/experiments/simulate_quota.py              # 약 3분
$PY crash_study/analysis/make_figures.py
# 선택: 별도 환경에서 실행 (pip install playwright python-pptx && playwright install chromium)
python crash_study/tools/capture_docs.py crash_study/docs_screenshots
python crash_study/tools/build_pptx.py
```

## 해석할 때 주의할 점

- 실측 실험(E0–E2c)은 K=10, 단일 노드다. 논문 규모(K=100, 2노드)가 아니다. 다만 검증 대상인 장애 전파 경로는 규모와 무관한 코드 경로다.
- E4의 연결 모델(p_drop, p_back)은 실측값이 아니라 sweep 변수다. 또한 "연결된 차량은 매 라운드 업로드한다"는 SASAFL에 **유리한** 가정을 썼다.
- E4의 loss 궤적은 커밋된 K=100 실행 로그에서 가져왔다. 이 실행은 quota가 고정되던 이전 코드로 돌았으므로, adaptive quota 아래의 loss와는 다를 수 있다.
- E1b 마지막의 정지는 장애 주입과 **무관하게** 일어났다. 재시작 후 클라이언트 5와 8이 첫 epoch조차 끝내지 못했는데, 원인은 확인하지 못했다(클라이언트 스택은 수집하지 않음). 정지 자체는 "Pᵣ=K인데 업로드하지 못하는 클라이언트가 있음"으로 로그에서 확인된다.
