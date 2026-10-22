# E8. K=10 — 논문의 K=100 칸 대신 (Fig. 7(b)(d), Fig. 8(b), Fig. 11, Table 4 K=10 행). BSA · SASAFL(현재 코드) · SASAFL(원저자 코드, quota 고정)

마지막 갱신: 2026-10-21 17:35

**재현 설정**: K=10, wise-175 단일 노드, CPU 카테고리 1·2·3·4·8코어 × 2명(논문 K=10 구성), batch 32, local epoch 5, τ=9, ζ=0.9, non-IID(gaussian), 1회 실행

## 비교 그림 (왼쪽: 논문 원본, 오른쪽: 재현)

![compare_fig7.png](compare_fig7.png)

![compare_fig8.png](compare_fig8.png)

![compare_fig11.png](compare_fig11.png)

![compare_table4.png](compare_table4.png)

![compare_fig7_err.png](compare_fig7_err.png)

![compare_fig9_err.png](compare_fig9_err.png)

## 실행 상태

| 실행 | 방법 | C | 상태 | 소요(분) |
|---|---|---:|---|---:|
| `K10_MNIST_BSA_C0.1` | BSA | 0.1 | 완료: 500/500라운드 | 37.1 |
| `K10_MNIST_SASAFL_C0.1` | SASAFL | 0.1 | 완료: 500/500라운드 | 143.1 |
| `K10_MNIST_SASAFLorig_C0.1` | SASAFLorig | 0.1 | 완료: 500/500라운드 | 71.7 |
| `K10_MNIST_BSA_C0.3` | BSA | 0.3 | 완료: 500/500라운드 | 87.4 |
| `K10_MNIST_SASAFL_C0.3` | SASAFL | 0.3 | 완료: 500/500라운드 | 196.9 |
| `K10_MNIST_SASAFLorig_C0.3` | SASAFLorig | 0.3 | 완료: 500/500라운드 | 116.4 |
| `K10_MNIST_BSA_C0.5` | BSA | 0.5 | 완료: 500/500라운드 | 150.2 |
| `K10_MNIST_SASAFL_C0.5` | SASAFL | 0.5 | 완료: 500/500라운드 | 220.6 |
| `K10_MNIST_SASAFLorig_C0.5` | SASAFLorig | 0.5 | 완료: 500/500라운드 | 180.4 |
| `K10_FMNIST_BSA_C0.1` | BSA | 0.1 | 완료: 500/500라운드 | 28.2 |
| `K10_FMNIST_SASAFL_C0.1` | SASAFL | 0.1 | 완료: 500/500라운드 | 72.8 |
| `K10_FMNIST_SASAFLorig_C0.1` | SASAFLorig | 0.1 | 완료: 500/500라운드 | 74.4 |
| `K10_FMNIST_BSA_C0.3` | BSA | 0.3 | 완료: 500/500라운드 | 76.1 |
| `K10_FMNIST_SASAFL_C0.3` | SASAFL | 0.3 | 완료: 500/500라운드 | 162.0 |
| `K10_FMNIST_SASAFLorig_C0.3` | SASAFLorig | 0.3 | 완료: 500/500라운드 | 106.0 |
| `K10_FMNIST_BSA_C0.5` | BSA | 0.5 | 완료: 500/500라운드 | 127.6 |
| `K10_FMNIST_SASAFL_C0.5` | SASAFL | 0.5 | 완료: 500/500라운드 | 292.3 |
| `K10_FMNIST_SASAFLorig_C0.5` | SASAFLorig | 0.5 | 완료: 500/500라운드 | 155.5 |
| `K10_CIFAR10_BSA_C0.1` | BSA | 0.1 | 완료: 500/500라운드 | 34.6 |
| `K10_CIFAR10_SASAFL_C0.1` | SASAFL | 0.1 | 완료: 500/500라운드 | 82.6 |
| `K10_CIFAR10_SASAFLorig_C0.1` | SASAFLorig | 0.1 | 완료: 500/500라운드 | 73.4 |
| `K10_CIFAR10_BSA_C0.3` | BSA | 0.3 | 완료: 500/500라운드 | 87.3 |
| `K10_CIFAR10_SASAFL_C0.3` | SASAFL | 0.3 | 완료: 500/500라운드 | 158.8 |
| `K10_CIFAR10_SASAFLorig_C0.3` | SASAFLorig | 0.3 | 완료: 500/500라운드 | 116.5 |
| `K10_CIFAR10_BSA_C0.5` | BSA | 0.5 | 완료: 500/500라운드 | 177.8 |
| `K10_CIFAR10_SASAFL_C0.5` | SASAFL | 0.5 | 완료: 500/500라운드 | 194.2 |
| `K10_CIFAR10_SASAFLorig_C0.5` | SASAFLorig | 0.5 | 완료: 500/500라운드 | 215.9 |

## 무엇을 돌렸나

- 논문은 K=30과 K=100을 비교했지만 이 장비에서 K=100은 돌릴 수 없어 K=10으로 대신한다. 그림·표에서 논문의 K=100 칸 자리에 K=10을 넣었다(왼쪽 논문 원본은 K=100 그대로).
- K=10 클라이언트는 K=30과 같은 CPU 카테고리(1·2·3·4·8코어)를 2명씩 쓴다. 나머지 설정은 K=30과 같다.
- SASAFL은 현재 코드(quota 적응 동작)와 원저자 코드(c0b819b, quota 고정) 둘 다 돌렸다.

## 실행 상태

| 실행 | 방법 | C | 상태 | 소요(분) |
|---|---|---:|---|---:|
| `K10_MNIST_BSA_C0.1` | BSA | 0.1 | 완료: 500/500라운드 | 37.1 |
| `K10_MNIST_SASAFL_C0.1` | SASAFL | 0.1 | 완료: 500/500라운드 | 143.1 |
| `K10_MNIST_SASAFLorig_C0.1` | SASAFLorig | 0.1 | 완료: 500/500라운드 | 71.7 |
| `K10_MNIST_BSA_C0.3` | BSA | 0.3 | 완료: 500/500라운드 | 87.4 |
| `K10_MNIST_SASAFL_C0.3` | SASAFL | 0.3 | 완료: 500/500라운드 | 196.9 |
| `K10_MNIST_SASAFLorig_C0.3` | SASAFLorig | 0.3 | 완료: 500/500라운드 | 116.4 |
| `K10_MNIST_BSA_C0.5` | BSA | 0.5 | 완료: 500/500라운드 | 150.2 |
| `K10_MNIST_SASAFL_C0.5` | SASAFL | 0.5 | 완료: 500/500라운드 | 220.6 |
| `K10_MNIST_SASAFLorig_C0.5` | SASAFLorig | 0.5 | 완료: 500/500라운드 | 180.4 |
| `K10_FMNIST_BSA_C0.1` | BSA | 0.1 | 완료: 500/500라운드 | 28.2 |
| `K10_FMNIST_SASAFL_C0.1` | SASAFL | 0.1 | 완료: 500/500라운드 | 72.8 |
| `K10_FMNIST_SASAFLorig_C0.1` | SASAFLorig | 0.1 | 완료: 500/500라운드 | 74.4 |
| `K10_FMNIST_BSA_C0.3` | BSA | 0.3 | 완료: 500/500라운드 | 76.1 |
| `K10_FMNIST_SASAFL_C0.3` | SASAFL | 0.3 | 완료: 500/500라운드 | 162.0 |
| `K10_FMNIST_SASAFLorig_C0.3` | SASAFLorig | 0.3 | 완료: 500/500라운드 | 106.0 |
| `K10_FMNIST_BSA_C0.5` | BSA | 0.5 | 완료: 500/500라운드 | 127.6 |
| `K10_FMNIST_SASAFL_C0.5` | SASAFL | 0.5 | 완료: 500/500라운드 | 292.3 |
| `K10_FMNIST_SASAFLorig_C0.5` | SASAFLorig | 0.5 | 완료: 500/500라운드 | 155.5 |
| `K10_CIFAR10_BSA_C0.1` | BSA | 0.1 | 완료: 500/500라운드 | 34.6 |
| `K10_CIFAR10_SASAFL_C0.1` | SASAFL | 0.1 | 완료: 500/500라운드 | 82.6 |
| `K10_CIFAR10_SASAFLorig_C0.1` | SASAFLorig | 0.1 | 완료: 500/500라운드 | 73.4 |
| `K10_CIFAR10_BSA_C0.3` | BSA | 0.3 | 완료: 500/500라운드 | 87.3 |
| `K10_CIFAR10_SASAFL_C0.3` | SASAFL | 0.3 | 완료: 500/500라운드 | 158.8 |
| `K10_CIFAR10_SASAFLorig_C0.3` | SASAFLorig | 0.3 | 완료: 500/500라운드 | 116.5 |
| `K10_CIFAR10_BSA_C0.5` | BSA | 0.5 | 완료: 500/500라운드 | 177.8 |
| `K10_CIFAR10_SASAFL_C0.5` | SASAFL | 0.5 | 완료: 500/500라운드 | 194.2 |
| `K10_CIFAR10_SASAFLorig_C0.5` | SASAFLorig | 0.5 | 완료: 500/500라운드 | 215.9 |

## 최고 정확도 (500라운드)

| 데이터셋 | C | BSA | SASAFL 현재 코드 | SASAFL 원저자 코드 | 원저자 코드 quota: 범위 / 서로 다른 값 수 / int(C·K) 비율 |
|---|---:|---:|---:|---:|---|
| MNIST | 0.1 | 94.69 | 98.60 | 94.40 | 1–1 / 1 / 100% |
| MNIST | 0.3 | 97.90 | 98.88 | 96.66 | 3–3 / 1 / 100% |
| MNIST | 0.5 | 98.71 | 98.85 | 98.40 | 5–5 / 1 / 100% |
| FashionMNIST | 0.1 | 55.48 | 69.59 | 55.59 | 1–1 / 1 / 100% |
| FashionMNIST | 0.3 | 74.91 | 79.10 | 70.12 | 3–3 / 1 / 100% |
| FashionMNIST | 0.5 | 78.88 | 84.87 | 80.34 | 5–5 / 1 / 100% |
| CIFAR10 | 0.1 | 43.59 | 35.92 | 47.04 | 1–1 / 1 / 100% |
| CIFAR10 | 0.3 | 45.36 | 48.76 | 47.11 | 3–3 / 1 / 100% |
| CIFAR10 | 0.5 | 51.99 | 51.94 | 48.46 | 5–5 / 1 / 100% |

