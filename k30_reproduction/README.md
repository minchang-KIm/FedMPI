# k30_reproduction — K=30에서 SASAFL 논문 재현

K=100은 현재 장비(wise-175, wise-176: 각각 i9-14900KF, 24코어 = P 8개 + E 16개, 논리 32개)로 재현하지 못했다. 그래서 K=30으로 내려서 재현한다.

진행 순서:

1. **smoke**: 논문 그대로의 K=30 구성이 실제로 끝까지 도는지 20라운드로 확인한다.
2. **fallback**: 1단계가 실패하면 CPU 카테고리를 1·2·3코어로 줄이고, 카테고리별 인원을 같게 맞춘다(각 10명).
3. **table2**: 통과한 구성으로 논문 Table 2의 MNIST 열을 재현한다(BSA와 SASAFL, C = 0.1 / 0.3 / 0.5).

## 이 논문을 대표하는 실험

**Table 2(K=30)의 MNIST 열, 즉 BSA와 SASAFL을 C ∈ {0.1, 0.3, 0.5}에서 비교하는 실험**이다. 그중에서도 **C=0.1**이 핵심이다.

| 이유 | 설명 |
|---|---|
| 기여를 직접 분리한다 | 논문은 BSA를 "SASAFL과 같지만 글로벌 모델 수신 정책과 참여 수 조정 알고리즘만 뺀 것"으로 정의한다. 집계와 수신의 병렬 처리, Eq.2 staleness 보정은 두 방법이 공유한다. 따라서 BSA와 SASAFL의 차이가 곧 제안 기법 두 가지의 효과다 |
| 주장이 가장 강하게 드러난다 | C=0.1에서 BSA는 93.78%로 목표(95%)에 도달하지 못했다. SASAFL은 98.23%로 116라운드(53.86분) 만에 목표에 도달했다. 논문 결론("참여 비율이 작아도 SASAFL은 수렴한다")의 근거가 이 칸이다 |
| 논문 스스로 한계를 보인 칸도 있다 | C=0.5에서는 BSA가 근소하게 앞선다(98.27 vs 98.24, 96 vs 131라운드). 재현할 때 이 역전까지 나오는지가 좋은 검증 포인트다 |
| 비용이 가장 낮다 | MNIST는 500라운드다(CIFAR-10은 3000라운드). K=30은 현재 장비로 시도할 수 있는 유일한 규모다 |
| 설정이 명확하다 | lr 0.01, batch 32, E=5, 최소 epoch E/2, τ=9, ζ=0.9, non-IID(gaussian 크기, 클라이언트당 1–2개 레이블), CPU 카테고리 1·2·3·4·8코어 × 6명 |

Fig.6과 Table 1(SAFA 비교, K=100)은 대표 실험으로 보기 어렵다.

- 설정이 본 실험과 다르다(lr 0.001, batch 40, 레이블 IID).
- 논문 스스로 이후 실험에서 SAFA를 제외했다.
- K=100이라 현재 장비로는 불가능하다.

Fig.5(lag tolerance 1–10)는 τ=9를 고르기 위한 사전 실험이다.

### 논문 목표값 (Table 2, MNIST, K=30, 목표 정확도 95%)

| C | BSA 정확도 | SASAFL 정확도 | BSA 도달 라운드 | SASAFL 도달 라운드 | BSA 도달 시간(분) | SASAFL 도달 시간(분) |
|---|---:|---:|---:|---:|---:|---:|
| 0.1 | 93.78 | 98.23 | - | 116 | - | 53.86 |
| 0.3 | 97.14 | 98.07 | 211 | 132 | 101.44 | 66.71 |
| 0.5 | 98.27 | 98.24 | 96 | 131 | 60.98 | 88.77 |

논문은 설정마다 10회를 반복해 평균을 냈다. 여기서는 우선 1회씩 돌린다.

## 장비 제약

| 구성 | 요청 thread | 가용 |
|---|---|---|
| 논문 K=30, 단일 노드 | 1 + 6×(1+2+3+4+8) = 109 | 논리 32 (물리 24) |
| 논문 K=30, 두 노드 | 노드당 54 (+서버 1) | 노드당 논리 32 |
| 대체안 1·2·3 ×10, 두 노드 | 노드당 30 (+서버 1) | 노드당 논리 32 |
| 대체안 1·2·3 ×10, 단일 노드 | 61 | 논리 32 |

논문 구성은 어느 경우든 thread를 과다 할당(oversubscription)하게 된다. 이 상태에서는 "8코어 클라이언트가 1코어 클라이언트보다 8배 빠르다"는 이질성 가정이 깨진다. 대체안(1·2·3)은 두 노드에서 과다 할당 없이 돌릴 수 있다. 다만 카테고리 구성이 논문과 다르므로 결과는 "축소 재현"으로 표기해야 한다.

## 1·2단계 결과 (2026-10-10, 20라운드, MNIST, C=0.1)

| 실험 | 노드 | 카테고리 | 방법 | 노드당 thread | 결과 |
|---|---|---|---|---|---|
| S1 | 단일 | 1·2·3·4·8 ×6 | SASAFL | 109 | 통과 (5.4분) |
| S2 | 두 노드 | 1·2·3·4·8 ×6 | SASAFL | 54 | **실패**: 15라운드, wise-176 rank 25에서 `'SASAFL' object has no attribute 'is_set'` |
| S3 | 두 노드 | 1·2·3·4·8 ×6 | BSA | 54 | 통과 (1.9분) |
| F1 | 두 노드 | 1·2·3 ×10 | SASAFL | 30 | 통과 (2.0분) |
| F2 | 두 노드 | 1·2·3 ×10 | BSA | 30 | 통과 (1.7분) |
| F3 | 단일 | 1·2·3 ×10 | SASAFL | 61 | 통과 (3.4분) |

해석:

- `is_set` 손상은 이전 기록과 마찬가지로 **wise-176에서만** 났다.
- 이번 실험에서 손상이 난 경우는 S2 하나뿐이다. S2는 세 조건이 겹친 경우다: wise-176, SASAFL(클라이언트가 수신 스레드와 학습 스레드를 동시에 돌림), 노드당 과다 할당.
- 같은 두 노드에서도 BSA(클라이언트 단일 스레드, S3)와 과다 할당이 없는 SASAFL(F1)은 정상이었다.
- 조건마다 1회씩만 돌린 결과라 원인을 확정할 수는 없다.

3단계(Table 2) 구성: **단일 노드 + 논문 카테고리(S1 구성)**. 논문 카테고리를 그대로 쓰고, BSA와 SASAFL을 같은 장비에서 돌리기 위해서다. 과다 할당 때문에 time-to-accuracy는 논문과 직접 비교하기 어렵다. 과다 할당이 없는 두 노드 + 1·2·3 카테고리(F1/F2 구성)로도 돌릴 수 있다:

```bash
$PY k30_reproduction/run_k30.py table2 --mode two --cats 1,2,3 --stall-min 15 --max-wall-min 600
```

비교표: `make_table2.py` → `table2_comparison.md`, `table2_comparison.png`

## 전체 재현 파이프라인 (`pipeline/`)

Table 2(MNIST) 작업이 끝나면 `start_pipeline_after_table2.sh`가 자동으로 이어서 실행한다(세션과 분리, `setsid nohup`).
실험마다 `experiments/<실험>/`에 논문과 같은 형식의 그래프와 표, 논문 원본과 나란히 놓은 비교 그림(`compare_*.png`), `SUMMARY.md`를 만든다.

| 순서 | 폴더 | 실행 | 논문 대응 |
|---|---|---|---|
| E1 | `experiments/E1_MNIST_table2` | BSA·SASAFL × C 3개, MNIST 500R (지금 돌고 있는 Table 2 실행을 그대로 씀) | Table 2 MNIST, Fig.7(a), Table 4 MNIST |
| E2 | `experiments/E2_FashionMNIST_table2` | BSA·SASAFL × C 3개, FashionMNIST 500R, lr 0.001 | Table 2 FashionMNIST, Fig.7(c), Fig.11(K=30), Table 4 FashionMNIST |
| E4 | `experiments/E4_CIFAR10_table2` | BSA·SASAFL × C 3개, CIFAR-10 500R (논문 3000R에서 축소), lr 0.001 | Table 2 CIFAR-10, Fig.8((a)+(b) 배치), Fig.9, Table 4 CIFAR-10 |
| E5 | `experiments/E5_Fig5_lag_tolerance` | SASAFL τ=1–10 × 1회, MNIST C=0.3 500R | Fig.5 |
| E6 | `experiments/E6_final_summary` | (실행 없음) | 논문과 같은 배치의 Table 2(3개 데이터셋, 논문/재현 위아래), Table 4(K=30, 9칸), Fig.7 2×2 배치, 결론 수치 점검 |

- 재개 가능: 완료된 실행은 건너뛴다. 중단되면 같은 명령으로 다시 시작하면 된다.
- 실행 하나가 끝날 때마다 해당 실험의 `SUMMARY.md`와 그림을 다시 만든다. 진행 기록은 `PROGRESS.md`에 남는다.
- 실패한 실행은 1회 재시도하고, 그래도 실패하면 기록을 남긴 뒤 다음 실행으로 넘어간다.
- 제외: Fig.2(동기·비동기·반비동기 비교)와 Fig.3(BSA만의 C별 곡선)은 SASAFL을 검증하는 실험이 아니어서 뺐다(2026-10-10).
- 라운드 상한: 500라운드를 넘는 실험(CIFAR-10, 논문 3000R)은 500R로 고정했다. Table 4의 CIFAR-10 칸은 논문 1000R 기준이라 직접 비교할 수 없다.
- 그림 글꼴: 논문과 같은 Times 계열(Liberation Serif), 한글만 나눔고딕. K=100 패널은 '재현 불가'로 비워 둔다.
- 반복 축소: 논문은 설정마다 10회 평균이지만, 여기서는 모두 1회만 실행한다(Fig.5도 τ마다 1회).
- 가정: Fig.5의 데이터셋과 C는 논문에 없어서 MNIST, C=0.3으로 가정했다.
- 재현 불가(K=100): Table 3, Fig.6, Table 1, Fig.7(b)(d), Fig.8(b), Fig.10, Table 4의 K≥100 행. 결론의 수치(19.69%p, 2.32배, 2.24배)도 모두 K=100 결과다(Table 3). E6에서 K=30의 같은 지표와 비교한다.

확인:

```bash
cat  k30_reproduction/PROGRESS.md            # 실행별 시작/종료 기록
tail k30_reproduction/pipeline_console.log   # PIPELINE_DONE이 찍히면 전체 종료
ls   k30_reproduction/experiments/*/SUMMARY.md
```

다시 시작(중단 후) — tmux 사용, 자세한 접속법은 `HOW_TO_ACCESS.md`:

```bash
cd ~/Mando/FedMPI && bash k30_reproduction/start_in_tmux.sh
tmux attach -t k30      # 빠져나오기: Ctrl+b 누른 뒤 d
```

## 실행

```bash
cd /home/wise-175/Mando/FedMPI
PY=/home/wise-175/anaconda3/envs/FL/bin/python
$PY k30_reproduction/run_k30.py smoke
$PY k30_reproduction/run_k30.py fallback
$PY k30_reproduction/run_k30.py table2 --mode two --cats 1,2,3 --stall-min 15 --max-wall-min 600
```

결과는 `runs/<이름>/`에 남는다: `run.log`, `result.json`, `rounds.csv`, `config.json`, `pids/`.
- E5의 τ=9 실행은 E1의 `T2_MNIST_SASAFL_C0.3_single_cats12348`과 설정이 같아 재실행하지 않고 링크로 재사용한다(`experiments/E5_Fig5_lag_tolerance/runs/LT_tau9_rep1`).
