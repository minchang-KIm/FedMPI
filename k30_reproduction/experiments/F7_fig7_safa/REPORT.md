# Fig. 7 (K=30) + SAFA 재현 실험 — 요청 사항 이행 보고서

작성: 2026-10-28. 실험 시작: 2026-10-28 10:40 (git `9c298db`).

## 1. 요청 사항별 이행 여부

| # | 요청 | 이행 | 근거 |
|---|---|---|---|
| 1 | 진행 중인 실험을 먼저 멈춤 | ✅ | 2026-10-28 09:5x에 정지했다.<br>- 175: 반복 큐(`run_rep_queue.sh`), 진행 중이던 실행 `LT_tau3_rep2`, 176 결과 동기화 루프, 상태 창<br>- 176: 반복 큐, 진행 중이던 실행 `LT_tau4_rep2`<br>- 두 노드의 crontab `@reboot` 자동 재개 줄은 주석 처리했다(백업: 175 scratchpad `crontab175.bak`, 176 `~/crontab176.bak`).<br>- 정지 후 두 노드 모두 `harness_entry`·`torch.distributed.run` 프로세스가 0개임을 확인했다.<br>- vehicle_sim 웹 서버(`serve.py`)는 학습을 돌리고 있지 않아 그대로 두었다. |
| 2 | Fig. 7의 K=30 칸을 논문 조건 그대로 | ✅ | 데이터셋은 MNIST와 FashionMNIST(논문 Fig.7 (a)(c))다. 조건(`fig7/spec.py`, 실행마다 `config.json`·`cmd.txt`에 기록):<br>- K=30, CPU 1·2·3·4·8코어 × 6명<br>- C 0.1 / 0.3 / 0.5<br>- lr: MNIST 0.01, FashionMNIST 0.001<br>- batch 32, local epoch 5, τ=9, ζ=0.9<br>- non-IID gaussian, 500라운드 |
| 3 | SAFA도 같은 그림에 | ✅ | SAFA는 파란 선이다. 논문 Fig.6의 SAFA 색을 따랐고, lag tolerance는 논문 서술대로 5다. |
| 4 | 옵티마이저 초기화 버그 수정 롤백 | ✅ | 커밋 `56edbc9`에서 `8f430a7`을 revert했다.<br>- 방법 코드(`methods/SASAFL/SASAFLClient.py`·`SASAFLServer.py`, `SemiAsyncFL`, `SAFA`, `FedAvg`, `utils`, `model_controller`)가 원저자 마지막 커밋 `c0b819b`와 바이트 단위로 같다(`git diff c0b819b` 결과 없음).<br>- 예외는 SASAFL.py 하나다(아래 5번). |
| 5 | 제안 기법 적용 / 미적용 두 버전 | ✅ | - **SASAFL_ON**: 현재 `methods/SASAFL/SASAFL.py`(f8fd198, quota 적응 동작)<br>- **SASAFL_OFF**: `original_code/SASAFL_c0b819b.py`(원저자 마지막 SASAFL.py, quota=C·K 고정)<br>- OFF 파일은 두 노드 모두에서 교체됐다. run.log에 175와 `[176]` 양쪽의 `SASAFL.py 교체 … sha256=7c4ca5fd…` 줄이 있다.<br>- 3라운드 시험에서 ON은 quota 3→5→3, OFF는 3→3→3으로 동작이 갈렸다. |
| 6 | SAFA 구현 검증 (인터넷 검색) | ✅ | 2절 참고. 원 논문과 다른 부분 6곳을 찾았다. 사용자 선택에 따라 **저장소 구현(SAFA)과 수정판(SAFAfix)을 둘 다** 돌린다. 매 실행이 두 노드를 모두 쓰므로 두 SAFA를 같은 시각에 돌릴 수는 없고, 회차마다 같은 설정(데이터셋·C)에서 BSA → SASAFL_ON → SASAFL_OFF → SAFA → SAFAfix 순으로 연달아 돈다. |
| 7 | 175·176을 같이 써서 한 실행을 돌림 | ✅ | 모든 실행이 `launch.sh … two`로 돈다.<br>- 175: 서버(rank 0) + 클라이언트 15개 (rank 1–15)<br>- 176: 클라이언트 15개 (rank 16–30)<br>- 각 노드에 카테고리별 3명씩 들어간다.<br>- run.log의 `I am client in wise-176 rank …`, `cmd.txt`의 두 노드 명령으로 확인할 수 있다. |
| 8 | git 동기화, 두 노드 모두 같은 코드 | ✅ | 코드를 바꿀 때마다 175에서 커밋·푸시하고, 176은 `git checkout -f -B main origin/main`으로 맞췄다(176 기존 파일은 `~/fedmpi176_backup_20261028.tgz`로 백업).<br>**실행마다 시작 전에 자동 검사**하고, 하나라도 어긋나면 실행하지 않고 5분마다 다시 검사한다(`run_fig7.py preflight`):<br>- 두 노드 git HEAD가 같은지<br>- 코드 경로에 미커밋 수정이 없는지<br>- 두 노드 터보가 꺼져 있는지<br>- 다른 FL 프로세스가 없는지<br>시작 시점에 추적 코드 파일 md5 합(`bcb8e378…`)이 두 노드에서 같았고, torch 1.12.1 / torchvision 0.13.1 / numpy 1.24.3도 같다. |
| 9 | 명령어 아규먼트를 텍스트로 그대로 저장 | ✅ | - 실행마다 `runs/<이름>/cmd.txt`: 두 노드에서 실제로 실행한 `torch.distributed.run` 명령 전체(스레드 배치 포함)와 환경변수<br>- `COMMANDS.md`: 공통 준비(176 git 동기화, 시작 명령)와 실행마다 wise-175 launcher·wise-175 torchrun·wise-176 torchrun 명령을 나눠 정리한 마크다운. 그림 감시 프로세스가 실행이 바뀔 때마다 자동으로 다시 만든다 |
| 10 | 반복 실험도 논문 조건대로 | ✅ | 설정당 10회다(논문 "average of ten repetitions"). 순서는 사용자 선택대로 회차 단위(1회차 30개 → 2회차 …)이고, 그림은 회차 평균 곡선이다. |
| 11 | 그림은 논문 Fig. 7처럼만 | ✅ | `fig7/plot_fig7.py`<br>- 패널: (a) MNIST with K=30, (c) FashionMNIST with K=30<br>- 색: BSA 초록, SASAFL 빨강, SAFA 파랑<br>- 선: C=0.1/0.3/0.5 = 실선/점선/파선<br>- 5라운드마다 표시, MNIST에 450–500R 확대 inset(논문과 같음)<br>- 다른 문구는 넣지 않았다.<br>그림 4장(SASAFL ON/OFF × SAFA 저장소/수정판):<br>- `fig7_SASAFL-ON_SAFA-repo.png`<br>- `fig7_SASAFL-ON_SAFA-fixed.png`<br>- `fig7_SASAFL-OFF_SAFA-repo.png`<br>- `fig7_SASAFL-OFF_SAFA-fixed.png`<br>같은 4장을 논문 원본 Fig.7의 K=30 열((a), (c))을 왼쪽에 붙여 한 장으로 만든 `compare_fig7_*.png`도 함께 갱신한다. |
| 12 | 라운드가 끝날 때마다 그림 갱신, 중간에 끊기지 않게 | ✅ (자동 재개 1곳 미완 — 3절) | - 실행기가 라운드마다 `rounds.csv`를 원자적으로 다시 쓴다.<br>- 감시 프로세스(tmux `fig7:1`)가 3초마다 변화를 확인해 다시 그린다. 그림은 임시 파일에 그린 뒤 교체하므로 깨진 그림이 남지 않는다.<br>- 그림 오류는 잡아서 기록만 하고 계속 돈다. 프로세스가 죽으면 5초 뒤 다시 뜬다.<br>- 실행기(tmux `fig7:0`)는 죽으면 1분 뒤 다시 뜨고, 완료된 실행은 건너뛴다. |
| 13 | 제대로 검증하고 시작 | ✅ | 본 실험 전에 5개 방법을 모두 두 노드로 3–4라운드 시험 실행했다(scratchpad `smoke_fig7`, `smoke2`, `smoke3`). 이 과정에서 고친 문제:<br>- SAFAfix의 도착 순서 수신 방식<br>- 저장소 SAFA가 마지막 라운드 뒤 끝나지 않는 문제를 실행기에서 처리(서버 종료 2분 뒤 정리, 완료로 판정) |

## 2. SAFA 구현 검증 (원 논문: Wu et al., "SAFA: a Semi-Asynchronous Protocol for Fast Federated Learning with Low Overhead", IEEE TC 70(5), 2021, arXiv:1910.01355)

| 원 논문 | 저장소 구현 (`methods/SAFA`, SASAFL 저자) | 수정판 (`methods/SAFAfix`) |
|---|---|---|
| CFCFM(Alg.1): **먼저 도착한** 업데이트부터, 직전 라운드에 안 뽑힌 클라이언트 우선으로 quota=C·K만큼 뽑음 | ① 도착 순서가 아니라 학습 시간 추정치 **내림차순**(느린 쪽부터)으로 뽑음<br>② 게다가 추정치 dict가 모든 클라이언트에 **같은 텐서 객체**를 저장해 값이 전부 같음 → 결과적으로 **rank 번호 순**으로 뽑힘. 시험 로그: 라운드마다 `[1,2,3]`, `[4,5,6]` … | 실제 도착 순서(any-source recv)로 뽑음. 시험 로그: 도착 `[16, 9, 25, 6, 28, …]`에서 직전에 뽑힌 16·9·28을 건너뛰고 `[25, 6, 13]` |
| 식 (7): 전체 K개 캐시를 n_k/n(합 1)으로 집계 | ③ 이번 라운드 비충돌 클라이언트만 더하고, 정규화 값(`agg_coefficient`)은 계산만 하고 쓰지 않음 → 가중치 합 ≈ 0.9(충돌 확률 0.1)라 **매 라운드 모델 파라미터가 줄어듦**<br>④ 충돌 클라이언트의 캐시를 집계에서 뺌 | 전체 K개 캐시, n_k/n 가중치(합 1) |
| 라운드 종료: quota를 채우거나 마감(T_lim) | ⑤ 비충돌 클라이언트 전원을 기다림 | 같음 (전원 업로드 후 도착 순서로 picks/undrafted를 나눔). 정확도-라운드 곡선에는 영향이 없고 벽시계 시간만 다르다. **미구현으로 남김** |
| 학습 하이퍼파라미터는 실험 조건대로 | ⑥ 클라이언트가 lr 0.001, batch 40으로 **고정**(SASAFL 논문 Fig.6 조건, 실행 인자 무시) → 이번 실험에서도 저장소 SAFA는 MNIST에서 lr 0.001, batch 40으로 학습함 | 실행 인자대로(MNIST lr 0.01, FMNIST 0.001, batch 32) |
| 분배(식 3)·lag tolerance·deprecated 강제 동기화·사전/사후 캐시 갱신(식 6, 8) | 원 논문과 같음 | 같음 (저장소 코드 재사용) |
| 충돌 모델 | 클라이언트별 매 라운드 확률 0.1 | 같음 |
| 기타 | cross-rounder 판정에서 마지막 클라이언트 누락(off-by-one), 수신 스레드가 모델을 다 풀기 전에 학습이 시작될 수 있는 경쟁 상태, 마지막 라운드 뒤 클라이언트가 broadcast에서 멈춰 프로세스가 끝나지 않음 | off-by-one 수정, 라운드 시작 지시와 함께 동기적으로 모델 수신, 정상 종료 |

## 3. 남은 일 / 주의

- **재부팅 시 자동 재개(crontab @reboot)는 등록하지 못했다.** 권한 확인에서 막혔다. 175가 다시 멈추면(이전 3회 모두 실행 전환 시점) 수동으로 `bash k30_reproduction/fig7/start_fig7.sh`를 실행하거나, 아래 줄을 175 crontab에 직접 추가해야 한다.
  `@reboot sleep 120 && bash /home/wise-175/Mando/FedMPI/k30_reproduction/fig7/start_fig7.sh >> /home/wise-175/Mando/FedMPI/k30_reproduction/experiments/F7_fig7_safa/reboot_console.log 2>&1`
- **규모**: 2 데이터셋 × 3 C × 5 방법 × 10회 = 300회다. 매 실행이 두 노드를 함께 쓰므로 한 번에 하나씩만 돈다. 시험 실행의 라운드 시간은 BSA 약 5–8초, SASAFL 수 초–수십 초, 저장소 SAFA 약 33초, SAFAfix 약 90–110초였다. 저장소 SAFA와 SAFAfix는 실행 하나에 각각 약 4.5시간, 약 14시간이 걸릴 것으로 보인다. 전체 10회는 수 주가 걸린다.
- 175는 하드웨어 문제로 이전에 실행 전환 시점에 세 번 멈췄다. 두 노드 모두 터보는 꺼져 있고, 실행기가 매번 확인한다.
- 실행 전 검사는 git HEAD 일치를 요구한다. 175에서 커밋하면 176도 즉시 맞춰야 다음 실행이 시작된다.
