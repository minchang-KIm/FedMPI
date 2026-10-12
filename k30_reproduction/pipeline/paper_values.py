"""논문(Yu et al., JPDC 2024)에서 옮겨 온 비교 기준값.

표 값은 본문 표에서 그대로 옮겼다. '근사'로 표시한 값은 그림에서 눈으로 읽은 값이다.
"""

TARGET_ACC = {"MNIST": 95.0, "FashionMNIST": 70.0, "CIFAR10": 55.0}

# Table 2 (K=30): dataset -> C -> method -> (accuracy, round-to-accuracy, time-to-accuracy[min])
TABLE2 = {
    "MNIST": {
        0.1: {"BSA": (93.78, None, None), "SASAFL": (98.23, 116, 53.86)},
        0.3: {"BSA": (97.14, 211, 101.44), "SASAFL": (98.07, 132, 66.71)},
        0.5: {"BSA": (98.27, 96, 60.98), "SASAFL": (98.24, 131, 88.77)},
    },
    "FashionMNIST": {
        0.1: {"BSA": (54.72, None, None), "SASAFL": (74.09, 248, 105.24)},
        0.3: {"BSA": (66.0, None, None), "SASAFL": (71.59, 420, 178.8)},
        0.5: {"BSA": (73.834, 376, 185.34), "SASAFL": (73.94, 283, 142.21)},
    },
    "CIFAR10": {
        0.1: {"BSA": (42.5, None, None), "SASAFL": (58.59, 1490, 1104.42)},
        0.3: {"BSA": (51.08, None, None), "SASAFL": (58.25, 1728, 1281.03)},
        0.5: {"BSA": (56.82, 2348, 1809.73), "SASAFL": (56.77, 2140, 1680.49)},
    },
}

# Table 3 (K=100) — 이 장비로는 재현 불가, 결론 수치 출처 확인용
TABLE3 = {
    "MNIST": {
        0.1: {"BSA": (92.47, None, None), "SASAFL": (98.56, 119, 65.99)},
        0.3: {"BSA": (97.31, 244, 131.37), "SASAFL": (98.52, 105, 58.5)},
        0.5: {"BSA": (98.27, 131, 82.65), "SASAFL": (98.36, 133, 74.81)},
    },
    "CIFAR10": {
        0.1: {"BSA": (38.26, None, None), "SASAFL": (57.95, 2418, 2384.51)},
    },
}

# Table 4, K=30 행: SASAFL wall clock time(분), MNIST 300 / FashionMNIST 500 / CIFAR-10 1000 라운드
TABLE4_K30 = {
    "MNIST": {"rounds": 300, 0.1: 139, 0.3: 151, 0.5: 204},
    "FashionMNIST": {"rounds": 500, 0.1: 212, 0.3: 213, 0.5: 251},
    "CIFAR10": {"rounds": 1000, 0.1: 741, 0.3: 742, 0.5: 787},
}

# Fig. 11 (FashionMNIST 500라운드 wall clock, K=30). SASAFL은 Table 4와 같고, BSA는 그림에서 읽은 근사값
FIG11_K30 = {
    "BSA": {0.1: 190, 0.3: 200, 0.5: 245},
    "SASAFL": {0.1: 212, 0.3: 213, 0.5: 251},
}

# Fig. 2 본문 수치 (MNIST, 500라운드)
FIG2_TEXT = {
    "semi_final_acc": 91.6,
    "sync_final_acc_approx": 97.6,      # "semi가 sync보다 6%p 낮다"
    "time_to_90_semi_min": 143,
    "time_to_90_sync_min": 177,
}

# 결론의 수치와 출처
CONCLUSION_CLAIMS = [
    ("최대 19.69%p 높은 정확도", "Table 3 (K=100) CIFAR-10, C=0.1: 57.95 - 38.26"),
    ("round-to-accuracy 2.32배", "Table 3 (K=100) MNIST, C=0.3: 244 / 105"),
    ("time-to-accuracy 2.24배", "Table 3 (K=100) MNIST, C=0.3: 131.37 / 58.5"),
]
