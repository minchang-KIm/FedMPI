# E2. FashionMNIST — Table 2(FashionMNIST 열), Fig. 7(c), Fig. 11(K=30), Table 4(FashionMNIST)

마지막 갱신: 2026-10-19 11:50

**재현 설정**: K=30, wise-175 단일 노드, CPU 카테고리 1·2·3·4·8코어 × 6명(논문 K=30 구성), batch 32, local epoch 5, τ=9, ζ=0.9, non-IID(gaussian), 1회 실행

## 비교 그림 (왼쪽: 논문 원본, 오른쪽: 재현)

![compare_fig7.png](compare_fig7.png)

![compare_fig11.png](compare_fig11.png)

![compare_table2.png](compare_table2.png)

![compare_table4.png](compare_table4.png)

## 실행 상태

| 실행 | 방법 | C | 상태 | 소요(분) |
|---|---|---:|---|---:|
| `FMNIST_BSA_C0.1` | BSA | 0.1 | 완료: 500/500라운드 | 31.7 |
| `FMNIST_BSA_C0.3` | BSA | 0.3 | 완료: 500/500라운드 | 192.0 |
| `FMNIST_BSA_C0.5` | BSA | 0.5 | 완료: 500/500라운드 | 303.9 |
| `FMNIST_SASAFL_C0.1` | SASAFL | 0.1 | 완료: 500/500라운드 | 148.5 |
| `FMNIST_SASAFL_C0.3` | SASAFL | 0.3 | 완료: 500/500라운드 | 353.3 |
| `FMNIST_SASAFL_C0.5` | SASAFL | 0.5 | 완료: 500/500라운드 | 737.6 |

## Table 2 비교

| FashionMNIST (목표 70%) | 논문 BSA | 논문 SASAFL | 재현 BSA | 재현 SASAFL |
|---|---:|---:|---:|---:|
| **C = 0.1** | | | | |
| Accuracy | 54.72 | **74.09** | **63.64** | 59.72 |
| Round-to-accuracy | - | **248** | - | - |
| Time-to-accuracy | - | **105.24** | - | - |
| **C = 0.3** | | | | |
| Accuracy | 66.00 | **71.59** | **74.50** | 69.93 |
| Round-to-accuracy | - | **420** | **354** | - |
| Time-to-accuracy | - | **178.80** | **136.50** | - |
| **C = 0.5** | | | | |
| Accuracy | 73.83 | **73.94** | 79.57 | **81.36** |
| Round-to-accuracy | 376 | **283** | 118 | **98** |
| Time-to-accuracy | 185.34 | **142.21** | **73.10** | 137.88 |

- Accuracy = 최고 test 정확도, Round-to-accuracy = 목표 첫 도달 라운드, Time-to-accuracy = 서버 setup 시작부터 목표 도달까지(분). `-` = 도달 못 함/미실행
- Time-to-accuracy는 단일 노드 과다 할당(thread 109개 / 논리 CPU 32개) 환경이라 논문과 절대값 비교가 어렵다.

### 관찰

- C=0.1: 정확도 차이(SASAFL−BSA) 논문 +19.37%p, 재현 -3.92%p → **논문과 반대 방향**
- C=0.3: 정확도 차이(SASAFL−BSA) 논문 +5.59%p, 재현 -4.57%p → **논문과 반대 방향**
- C=0.5: 정확도 차이(SASAFL−BSA) 논문 +0.11%p, 재현 +1.79%p → 논문과 같은 방향
  - round-to-accuracy BSA/SASAFL = 1.20배 (논문 1.33배) → 1보다 크면 SASAFL이 더 빨리 도달

## Table 4 (K=30 행)

SASAFL로 500라운드를 마치는 데 걸린 시간(분).

|  | C=0.1 | C=0.3 | C=0.5 |
|---|---:|---:|---:|
| 논문 K=30 (500R) | 212 | 213 | 251 |
| 재현 K=30 (500R) | 149 | 353 | 738 |

<!-- /table4 -->

