# E8. K=10 — 논문의 K=100 칸 대신 (Fig. 7(b)(d), Fig. 8(b), Fig. 11, Table 4 K=10 행). BSA · SASAFL(현재 코드) · SASAFL(원저자 코드, quota 고정)

마지막 갱신: 2026-10-28 09:43

**재현 설정**: K=10, wise-175 단일 노드, CPU 카테고리 1·2·3·4·8코어 × 2명(논문 K=10 구성), batch 32, local epoch 5, τ=9, ζ=0.9, non-IID(gaussian), 설정당 반복 10회 목표(논문: average of ten repetitions)

## 비교 그림 (왼쪽: 논문 원본, 오른쪽: 재현)

![compare_fig7.png](compare_fig7.png)

![compare_fig8.png](compare_fig8.png)

![compare_fig11.png](compare_fig11.png)

![compare_table4.png](compare_table4.png)

![compare_fig7_err.png](compare_fig7_err.png)

![compare_fig9_err.png](compare_fig9_err.png)

## 반복 실행 상태 (그림은 완료된 반복의 평균 곡선, 표는 반복별 값의 평균)

| 설정 (1회차 이름) | 방법 | C | 완료 반복 | 최고 정확도 평균 ± 표준편차 | 소요 평균(분) |
|---|---|---:|---:|---:|---:|
| `K10_MNIST_BSA_C0.1` | BSA | 0.1 | 2/10 | 94.64 ± 0.05 | 33 |
| `K10_MNIST_SASAFL_C0.1` | SASAFL | 0.1 | 2/10 | 98.69 ± 0.09 | 163 |
| `K10_MNIST_SASAFLorig_C0.1` | SASAFLorig | 0.1 | 2/10 | 92.50 ± 1.91 | 76 |
| `K10_MNIST_BSA_C0.3` | BSA | 0.3 | 2/10 | 97.90 ± 0.01 | 100 |
| `K10_MNIST_SASAFL_C0.3` | SASAFL | 0.3 | 2/10 | 98.85 ± 0.02 | 217 |
| `K10_MNIST_SASAFLorig_C0.3` | SASAFLorig | 0.3 | 2/10 | 96.41 ± 0.25 | 117 |
| `K10_MNIST_BSA_C0.5` | BSA | 0.5 | 2/10 | 98.81 ± 0.11 | 151 |
| `K10_MNIST_SASAFL_C0.5` | SASAFL | 0.5 | 2/10 | 98.91 ± 0.07 | 265 |
| `K10_MNIST_SASAFLorig_C0.5` | SASAFLorig | 0.5 | 2/10 | 98.18 ± 0.23 | 183 |
| `K10_FMNIST_BSA_C0.1` | BSA | 0.1 | 2/10 | 58.35 ± 2.87 | 35 |
| `K10_FMNIST_SASAFL_C0.1` | SASAFL | 0.1 | 2/10 | 65.63 ± 3.96 | 79 |
| `K10_FMNIST_SASAFLorig_C0.1` | SASAFLorig | 0.1 | 2/10 | 66.70 ± 11.11 | 76 |
| `K10_FMNIST_BSA_C0.3` | BSA | 0.3 | 2/10 | 74.72 ± 0.20 | 81 |
| `K10_FMNIST_SASAFL_C0.3` | SASAFL | 0.3 | 2/10 | 81.06 ± 1.96 | 199 |
| `K10_FMNIST_SASAFLorig_C0.3` | SASAFLorig | 0.3 | 2/10 | 69.49 ± 0.63 | 112 |
| `K10_FMNIST_BSA_C0.5` | BSA | 0.5 | 2/10 | 79.36 ± 0.48 | 140 |
| `K10_FMNIST_SASAFL_C0.5` | SASAFL | 0.5 | 2/10 | 82.66 ± 2.21 | 295 |
| `K10_FMNIST_SASAFLorig_C0.5` | SASAFLorig | 0.5 | 2/10 | 79.66 ± 0.68 | 168 |
| `K10_CIFAR10_BSA_C0.1` | BSA | 0.1 | 2/10 | 41.31 ± 2.28 | 44 |
| `K10_CIFAR10_SASAFL_C0.1` | SASAFL | 0.1 | 2/10 | 44.00 ± 8.08 | 103 |
| `K10_CIFAR10_SASAFLorig_C0.1` | SASAFLorig | 0.1 | 2/10 | 46.06 ± 0.98 | 84 |
| `K10_CIFAR10_BSA_C0.3` | BSA | 0.3 | 2/10 | 46.93 ± 1.57 | 117 |
| `K10_CIFAR10_SASAFL_C0.3` | SASAFL | 0.3 | 2/10 | 48.83 ± 0.07 | 160 |
| `K10_CIFAR10_SASAFLorig_C0.3` | SASAFLorig | 0.3 | 2/10 | 51.67 ± 4.56 | 159 |
| `K10_CIFAR10_BSA_C0.5` | BSA | 0.5 | 2/10 | 48.92 ± 3.07 | 179 |
| `K10_CIFAR10_SASAFL_C0.5` | SASAFL | 0.5 | 2/10 | 51.51 ± 0.43 | 217 |
| `K10_CIFAR10_SASAFLorig_C0.5` | SASAFLorig | 0.5 | 2/10 | 51.02 ± 2.55 | 216 |

반복 값 파일: `repeats/runs_index.csv`(실행별), `repeats/summary_by_setting.csv`(설정별 평균·표준편차), `repeats/curves/<설정>.csv`(라운드별 회차 값과 평균)

## 무엇을 돌렸나

- 논문은 K=30과 K=100을 비교했지만 이 장비에서 K=100은 돌릴 수 없어 K=10으로 대신한다. 그림·표에서 논문의 K=100 칸 자리에 K=10을 넣었다(왼쪽 논문 원본은 K=100 그대로).
- K=10 클라이언트는 K=30과 같은 CPU 카테고리(1·2·3·4·8코어)를 2명씩 쓴다. 나머지 설정은 K=30과 같다.
- SASAFL은 현재 코드(quota 적응 동작)와 원저자 코드(c0b819b, quota 고정) 둘 다 돌렸다.

## 실행 상태

| 설정 (1회차 이름) | 방법 | C | 완료 반복 | 최고 정확도 평균 ± 표준편차 | 소요 평균(분) |
|---|---|---:|---:|---:|---:|
| `K10_MNIST_BSA_C0.1` | BSA | 0.1 | 2/10 | 94.64 ± 0.05 | 33 |
| `K10_MNIST_SASAFL_C0.1` | SASAFL | 0.1 | 2/10 | 98.69 ± 0.09 | 163 |
| `K10_MNIST_SASAFLorig_C0.1` | SASAFLorig | 0.1 | 2/10 | 92.50 ± 1.91 | 76 |
| `K10_MNIST_BSA_C0.3` | BSA | 0.3 | 2/10 | 97.90 ± 0.01 | 100 |
| `K10_MNIST_SASAFL_C0.3` | SASAFL | 0.3 | 2/10 | 98.85 ± 0.02 | 217 |
| `K10_MNIST_SASAFLorig_C0.3` | SASAFLorig | 0.3 | 2/10 | 96.41 ± 0.25 | 117 |
| `K10_MNIST_BSA_C0.5` | BSA | 0.5 | 2/10 | 98.81 ± 0.11 | 151 |
| `K10_MNIST_SASAFL_C0.5` | SASAFL | 0.5 | 2/10 | 98.91 ± 0.07 | 265 |
| `K10_MNIST_SASAFLorig_C0.5` | SASAFLorig | 0.5 | 2/10 | 98.18 ± 0.23 | 183 |
| `K10_FMNIST_BSA_C0.1` | BSA | 0.1 | 2/10 | 58.35 ± 2.87 | 35 |
| `K10_FMNIST_SASAFL_C0.1` | SASAFL | 0.1 | 2/10 | 65.63 ± 3.96 | 79 |
| `K10_FMNIST_SASAFLorig_C0.1` | SASAFLorig | 0.1 | 2/10 | 66.70 ± 11.11 | 76 |
| `K10_FMNIST_BSA_C0.3` | BSA | 0.3 | 2/10 | 74.72 ± 0.20 | 81 |
| `K10_FMNIST_SASAFL_C0.3` | SASAFL | 0.3 | 2/10 | 81.06 ± 1.96 | 199 |
| `K10_FMNIST_SASAFLorig_C0.3` | SASAFLorig | 0.3 | 2/10 | 69.49 ± 0.63 | 112 |
| `K10_FMNIST_BSA_C0.5` | BSA | 0.5 | 2/10 | 79.36 ± 0.48 | 140 |
| `K10_FMNIST_SASAFL_C0.5` | SASAFL | 0.5 | 2/10 | 82.66 ± 2.21 | 295 |
| `K10_FMNIST_SASAFLorig_C0.5` | SASAFLorig | 0.5 | 2/10 | 79.66 ± 0.68 | 168 |
| `K10_CIFAR10_BSA_C0.1` | BSA | 0.1 | 2/10 | 41.31 ± 2.28 | 44 |
| `K10_CIFAR10_SASAFL_C0.1` | SASAFL | 0.1 | 2/10 | 44.00 ± 8.08 | 103 |
| `K10_CIFAR10_SASAFLorig_C0.1` | SASAFLorig | 0.1 | 2/10 | 46.06 ± 0.98 | 84 |
| `K10_CIFAR10_BSA_C0.3` | BSA | 0.3 | 2/10 | 46.93 ± 1.57 | 117 |
| `K10_CIFAR10_SASAFL_C0.3` | SASAFL | 0.3 | 2/10 | 48.83 ± 0.07 | 160 |
| `K10_CIFAR10_SASAFLorig_C0.3` | SASAFLorig | 0.3 | 2/10 | 51.67 ± 4.56 | 159 |
| `K10_CIFAR10_BSA_C0.5` | BSA | 0.5 | 2/10 | 48.92 ± 3.07 | 179 |
| `K10_CIFAR10_SASAFL_C0.5` | SASAFL | 0.5 | 2/10 | 51.51 ± 0.43 | 217 |
| `K10_CIFAR10_SASAFLorig_C0.5` | SASAFLorig | 0.5 | 2/10 | 51.02 ± 2.55 | 216 |

## 최고 정확도 (500라운드)

| 데이터셋 | C | BSA | SASAFL 현재 코드 | SASAFL 원저자 코드 | 원저자 코드 quota: 범위 / 서로 다른 값 수 / int(C·K) 비율 |
|---|---:|---:|---:|---:|---|
| MNIST | 0.1 | 94.64 | 98.69 | 92.50 | 1–1 / 1 / 100% |
| MNIST | 0.3 | 97.90 | 98.85 | 96.41 | 3–3 / 1 / 100% |
| MNIST | 0.5 | 98.81 | 98.91 | 98.18 | 5–5 / 1 / 100% |
| FashionMNIST | 0.1 | 58.35 | 65.63 | 66.70 | 1–1 / 1 / 100% |
| FashionMNIST | 0.3 | 74.72 | 81.06 | 69.49 | 3–3 / 1 / 100% |
| FashionMNIST | 0.5 | 79.36 | 82.66 | 79.66 | 5–5 / 1 / 100% |
| CIFAR10 | 0.1 | 41.31 | 44.00 | 46.06 | 1–1 / 1 / 100% |
| CIFAR10 | 0.3 | 46.93 | 48.83 | 51.67 | 3–3 / 1 / 100% |
| CIFAR10 | 0.5 | 48.92 | 51.51 | 51.02 | 5–5 / 1 / 100% |

