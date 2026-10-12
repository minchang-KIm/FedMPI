# E4. CIFAR-10 — Table 2(CIFAR-10 열), Fig. 8(a), Fig. 9, Table 4(CIFAR-10)

마지막 갱신: 2026-10-10 19:31

**재현 설정**: K=30, wise-175 단일 노드, CPU 카테고리 1·2·3·4·8코어 × 6명(논문 K=30 구성), batch 32, local epoch 5, τ=9, ζ=0.9, non-IID(gaussian), 1회 실행

## 실행 상태

| 실행 | 방법 | C | 상태 | 소요(분) |
|---|---|---:|---|---:|
| `CIFAR10_BSA_C0.1` | BSA | 0.1 | 미실행 | - |
| `CIFAR10_BSA_C0.3` | BSA | 0.3 | 미실행 | - |
| `CIFAR10_BSA_C0.5` | BSA | 0.5 | 미실행 | - |
| `CIFAR10_SASAFL_C0.1` | SASAFL | 0.1 | 미실행 | - |
| `CIFAR10_SASAFL_C0.3` | SASAFL | 0.3 | 미실행 | - |
| `CIFAR10_SASAFL_C0.5` | SASAFL | 0.5 | 미실행 | - |

## Table 2 비교

| CIFAR10 (목표 55%) | 논문 BSA | 논문 SASAFL | 재현 BSA | 재현 SASAFL |
|---|---:|---:|---:|---:|
| **C = 0.1** | | | | |
| Accuracy | 42.50 | **58.59** | - | - |
| Round-to-accuracy | - | **1,490** | - | - |
| Time-to-accuracy | - | **1,104.42** | - | - |
| **C = 0.3** | | | | |
| Accuracy | 51.08 | **58.25** | - | - |
| Round-to-accuracy | - | **1,728** | - | - |
| Time-to-accuracy | - | **1,281.03** | - | - |
| **C = 0.5** | | | | |
| Accuracy | **56.82** | 56.77 | - | - |
| Round-to-accuracy | 2,348 | **2,140** | - | - |
| Time-to-accuracy | 1,809.73 | **1,680.49** | - | - |

주의:
- CIFAR10_BSA_C0.1: 미실행
- CIFAR10_BSA_C0.3: 미실행
- CIFAR10_BSA_C0.5: 미실행
- CIFAR10_SASAFL_C0.1: 미실행
- CIFAR10_SASAFL_C0.3: 미실행
- CIFAR10_SASAFL_C0.5: 미실행

![Table 2 비교](table2_comparison.png)

- Accuracy = 최고 test 정확도, Round-to-accuracy = 목표 첫 도달 라운드, Time-to-accuracy = 서버 setup 시작부터 목표 도달까지(분). `-` = 도달 못 함/미실행
- Time-to-accuracy는 단일 노드 과다 할당(thread 109개 / 논리 CPU 32개) 환경이라 논문과 절대값 비교가 어렵다.

**라운드 축소**: 논문은 CIFAR-10을 3000라운드 돌렸지만 여기서는 500라운드로 고정했다. 논문 SASAFL은 목표 55%에 1,490~2,140라운드에 도달하므로, Round/Time-to-accuracy는 대부분 `-`(미도달)로 나올 수 있다. 논문 그림과는 0~500라운드 구간만 비교할 수 있다.

## Fig. 8(a) — CIFAR-10, K=30 (10라운드 간격, 0~500라운드)

![Fig8a](fig8a_cifar10_k30.png)

논문과 같은 배치:

![Fig8 layout](fig8_layout_as_paper.png)

![Fig. 8 비교 ((b) K=100은 재현 불가)](compare_fig8.png)

## Fig. 9 — CIFAR-10 SASAFL, K=30, C별

![Fig9](fig9_cifar10_sasafl_k30.png)

![Fig. 9 비교](compare_fig9.png)

## Table 4 (K=30 행)

SASAFL로 500라운드를 마치는 데 걸린 시간(분). **주의: 논문은 1000라운드 기준, 재현은 500라운드 기준이라 직접 비교 불가 (라운드당 시간 비교용: 논문 1000R 값을 500/1000배 하면 대략적인 기준이 된다).**

|  | C=0.1 | C=0.3 | C=0.5 |
|---|---:|---:|---:|
| 논문 K=30 (1000R) | 741 | 742 | 787 |
| 재현 K=30 (500R) | - | - | - |

![Table 4](table4_k30.png)

