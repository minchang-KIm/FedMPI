#!/usr/bin/env python3
"""시뮬레이션 맵을 만든다. 모든 맵은 34개 유스케이스를 일으킬 장소·구역을 갖춘다 (mapgeo.map_coverage로 검사).

  python vehicle_sim/maps/make_maps.py
    → maps/{default,highway,port,newtown}.json   작은 맵 4종
    → maps/metro.json                            광역 도시권 (두 도시·고속도로 산악 터널·해안 순환로)
    → maps/lossantos.json                        GTA V 풍 섬 (로스 산토스 도심 + 블레인 카운티 시골·사막·호수)
    → maps/racing.json                           레이싱 서킷 (피트·서킷 터널·관람객 마을)

맵 형식
  size [W, H] (m) · lane_width (차로 폭, m) · region_border_x (권역 경계 x, 선택)
  roads    [{id, name, pts:[[x,z],...], speed(km/h)}]               양방향 2차선 (우측 통행)
  cells    [{id, name, pos:[x,z], r, region, color}]                 기지국
  zones    [{id, name, kind, rect:[x0,z0,x1,z1] | circle:[x,z,r], speed?}]
           kind: tunnel · shadow(음영) · congestion · school · wifi · weather
  places   [{id, name, kind, pos, wifi?, slots?}]  kind: home · work · gas · service · depot · server · gate
  signals  [{id, name, pos, green, yellow, offset}]                  교차로 신호 (동서·남북 두 현시)
  crosswalks [{id, name, pos, rate_per_min, dart_prob, school?}]
  routes   {id: {name, loop, kind, pts:[[x,z(,정차 종류)],...]}}     kind: commute · city · resident · visitor
  vehicle_routes [...]                                               차량 i가 쓰는 경로 (앞에서부터 K대)
  landuse  [{rect, kind: downtown · residential · industrial · park, density}]   건물·나무 자동 배치
  선택: water [{rect}] · hills [{rect, height}] · decor [{kind: grandstand · runway · startline, rect}]
        npc_routes [...] 배경 차량(학습 안 함)이 쓰는 경로 · 경로의 always(상시 운행)·label·accel·brake·a_lat
        도로의 track: true (서킷: 보도 대신 연석)
"""

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "simcore"))
from mapgeo import junctions, map_coverage, map_problems  # noqa: E402
VR = ["commute", "city", "resident", "visitor", "commute", "city", "resident", "visitor",
      "city", "commute", "resident", "city", "commute", "visitor", "city", "resident"]


def arc(cx, cz, r, a0, a1, step=10):
    """원호 위 점들 (각도는 도, x축에서 z축 쪽으로). 큰 곡선 도로·서킷용"""
    n = max(2, int(abs(a1 - a0) / step) + 1)
    return [[round(cx + r * math.cos(math.radians(a0 + (a1 - a0) * k / (n - 1))), 1),
             round(cz + r * math.sin(math.radians(a0 + (a1 - a0) * k / (n - 1))), 1)] for k in range(n)]


def chain(*parts):
    """여러 점 목록을 이어 붙인다 (겹치는 이음점은 하나만)"""
    out = []
    for part in parts:
        for p in part:
            if not out or math.dist(out[-1][:2], p[:2]) > 0.5:
                out.append(list(p))
            elif len(p) > 2:
                out[-1] = list(p)
    return out


def auto_signals(m, names=None, green=18):
    """3갈래 이상 교차로마다 신호를 단다 (이미 있는 신호는 그대로). names: {(x, z): 이름}"""
    sig = m.setdefault("signals", [])
    for j in junctions(m):
        if len(j["arms"]) < 3 or any(math.dist(s["pos"], j["pos"]) < 8 for s in sig):
            continue
        k = len(sig) + 1
        pos = [round(j["pos"][0]), round(j["pos"][1])]
        sig.append({"id": f"S{k}", "name": (names or {}).get(tuple(pos), f"교차로 {k}"), "pos": pos,
                    "green": green + (k % 3) * 2, "yellow": 3, "offset": (k * 5) % 17})
    return m


def save(name, m):
    m.setdefault("lane_width", 3.5)
    m.setdefault("vehicle_routes", VR)
    probs = map_problems(m)
    cov = map_coverage(m)
    miss = [c["id"] for c in cov if not c["ok"]]
    print(f"[+] {name:8s} {m['name']:10s} 유스케이스 {34 - len(miss)}/34" + (f"  없음: {miss}" if miss else "")
          + (f"\n    문제: {probs}" if probs else ""))
    if probs or miss:
        raise SystemExit(f"{name}: 조건을 만족하지 않음")
    (HERE / f"{name}.json").write_text(json.dumps(m, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ 1. 도심 격자 (기본)
save("default", {
    "name": "도심 격자", "desc": "고속도로·도심 순환로·교외 순환로. 셀 4개, 터널, 빌딩 숲, 어린이 보호구역",
    "size": [2000, 1400], "region_border_x": 1400,
    "roads": [
        {"id": "highway", "name": "고속도로", "pts": [[0, 300], [2000, 300]], "speed": 100},
        {"id": "conn_w", "name": "서측 진입로", "pts": [[300, 300], [300, 600]], "speed": 50},
        {"id": "conn_e", "name": "동측 진입로", "pts": [[1700, 300], [1700, 700]], "speed": 50},
        {"id": "ring", "name": "도심 순환로", "pts": [[300, 600], [1100, 600], [1100, 1200], [300, 1200], [300, 600]], "speed": 45},
        {"id": "suburb", "name": "교외 순환로", "pts": [[1100, 700], [1800, 700], [1800, 1200], [1100, 1200]], "speed": 55},
    ],
    "cells": [
        {"id": "A", "name": "도심 기지국 A", "pos": [650, 900], "r": 480, "region": "W", "color": "#2563eb"},
        {"id": "H1", "name": "고속도로 서측 H1", "pos": [300, 330], "r": 360, "region": "W", "color": "#0891b2"},
        {"id": "H2", "name": "고속도로 동측 H2", "pos": [1600, 330], "r": 360, "region": "E", "color": "#9333ea"},
        {"id": "C", "name": "교외 기지국 C", "pos": [1450, 950], "r": 430, "region": "E", "color": "#ea580c"},
    ],
    "zones": [
        {"id": "tunnel", "name": "터널", "kind": "tunnel", "rect": [850, 285, 1150, 315], "speed": 80},
        {"id": "shadow", "name": "빌딩 숲(음영지역)", "kind": "shadow", "rect": [450, 1150, 800, 1250]},
        {"id": "congest", "name": "혼잡 교차로", "kind": "congestion", "rect": [270, 850, 330, 1050], "speed": 15},
        {"id": "school", "name": "어린이 보호구역", "kind": "school", "rect": [1080, 820, 1120, 980], "speed": 30},
        {"id": "wifi_pub", "name": "공영 Wi-Fi 구역(비과금망)", "kind": "wifi", "rect": [1760, 850, 1840, 1050]},
        {"id": "weather", "name": "강우 구역", "kind": "weather", "circle": [1450, 850, 250]},
    ],
    "places": [
        {"id": "home", "name": "주거단지 주차장", "kind": "home", "pos": [1500, 1200], "wifi": True, "slots": 10},
        {"id": "work", "name": "오피스 주차장", "kind": "work", "pos": [520, 600], "slots": 10},
        {"id": "gas", "name": "충전소", "kind": "gas", "pos": [300, 750], "wifi": True, "slots": 6},
        {"id": "service", "name": "서비스센터(OTA·정비)", "kind": "service", "pos": [760, 600], "wifi": True, "slots": 6},
        {"id": "depot", "name": "택시 차고지", "kind": "depot", "pos": [300, 1120], "slots": 8},
        {"id": "datacenter", "name": "FL 집계 서버", "kind": "server", "pos": [1000, 1330]},
        {"id": "gate_in", "name": "진입 게이트", "kind": "gate", "pos": [0, 300]},
        {"id": "gate_out", "name": "이탈 게이트", "kind": "gate", "pos": [2000, 300]},
    ],
    "signals": [
        {"id": "S1", "name": "서측 교차로", "pos": [300, 600], "green": 18, "yellow": 3, "offset": 0},
        {"id": "S2", "name": "도심·교외 교차로", "pos": [1100, 700], "green": 16, "yellow": 3, "offset": 7},
        {"id": "S3", "name": "남측 교차로", "pos": [1100, 1200], "green": 18, "yellow": 3, "offset": 12},
        {"id": "S4", "name": "동측 교차로", "pos": [1700, 700], "green": 20, "yellow": 3, "offset": 4},
        {"id": "S5", "name": "고속도로 서측 IC", "pos": [300, 300], "green": 25, "yellow": 3, "offset": 2},
        {"id": "S6", "name": "고속도로 동측 IC", "pos": [1700, 300], "green": 25, "yellow": 3, "offset": 9},
    ],
    "crosswalks": [
        {"id": "X1", "name": "어린이 보호구역 횡단보도", "pos": [1100, 900], "rate_per_min": 6, "dart_prob": 0.25, "school": True},
        {"id": "X2", "name": "도심 횡단보도", "pos": [650, 1200], "rate_per_min": 4, "dart_prob": 0.05},
        {"id": "X3", "name": "오피스 앞 횡단보도", "pos": [900, 600], "rate_per_min": 4, "dart_prob": 0.05},
        {"id": "X4", "name": "주택가 횡단보도", "pos": [1350, 1200], "rate_per_min": 3, "dart_prob": 0.08},
    ],
    "routes": {
        "commute": {"name": "고속도로 통근", "loop": True, "kind": "commute",
                    "pts": [[300, 600], [300, 300], [1700, 300], [1700, 700], [1800, 700], [1800, 1200],
                            [1500, 1200, "home"], [1100, 1200], [1100, 600], [520, 600, "work"], [300, 600]]},
        "city": {"name": "도심 택시", "loop": True, "kind": "city",
                 "pts": [[300, 600], [760, 600, "service"], [1100, 600], [1100, 1200], [300, 1200],
                         [300, 1120, "depot"], [300, 750, "gas"], [300, 600]]},
        "resident": {"name": "교외 주민", "loop": True, "kind": "resident",
                     "pts": [[1100, 700], [1800, 700], [1800, 1200], [1500, 1200, "home"], [1100, 1200], [1100, 700]]},
        "visitor": {"name": "통과 차량", "loop": False, "kind": "visitor", "pts": [[0, 300], [2000, 300]]},
    },
    "landuse": [
        {"rect": [330, 630, 1070, 1170], "kind": "downtown", "density": 0.75},
        {"rect": [1130, 730, 1770, 1170], "kind": "residential", "density": 0.5},
        {"rect": [0, 0, 2000, 270], "kind": "park", "density": 0.35},
        {"rect": [330, 330, 1670, 570], "kind": "residential", "density": 0.35},
        {"rect": [0, 1230, 2000, 1400], "kind": "residential", "density": 0.45},
    ],
})

# ------------------------------------------------------------------ 2. 고속도로 회랑
save("highway", {
    "name": "고속도로 회랑", "desc": "두 도시를 잇는 고속도로. 산을 뚫은 1 km 터널(80 km/h ≈ 45초 단절), 톨게이트 권역 경계",
    "size": [3200, 1200], "region_border_x": 2250,
    "roads": [
        {"id": "hw", "name": "고속도로", "pts": [[0, 600], [3200, 600]], "speed": 100},
        {"id": "w_loop", "name": "서부 도시 순환로", "pts": [[200, 300], [800, 300], [800, 900], [200, 900], [200, 300]], "speed": 45},
        {"id": "e_loop", "name": "동부 도시 순환로", "pts": [[2400, 300], [3000, 300], [3000, 900], [2400, 900], [2400, 300]], "speed": 45},
    ],
    "cells": [
        {"id": "W1", "name": "서부 북 W1", "pos": [500, 420], "r": 400, "region": "W", "color": "#2563eb"},
        {"id": "W2", "name": "서부 남 W2", "pos": [500, 820], "r": 360, "region": "W", "color": "#0891b2"},
        {"id": "H", "name": "터널 앞 H", "pos": [950, 600], "r": 260, "region": "W", "color": "#9333ea"},
        {"id": "T", "name": "톨게이트 T", "pos": [2250, 600], "r": 260, "region": "E", "color": "#db2777"},
        {"id": "E1", "name": "동부 북 E1", "pos": [2700, 420], "r": 400, "region": "E", "color": "#ea580c"},
        {"id": "E2", "name": "동부 남 E2", "pos": [2700, 820], "r": 360, "region": "E", "color": "#16a34a"},
    ],
    "zones": [
        {"id": "tunnel", "name": "산악 터널 1 km", "kind": "tunnel", "rect": [1100, 585, 2100, 615], "speed": 80},
        {"id": "shadow", "name": "도심 빌딩 숲(음영지역)", "kind": "shadow", "rect": [300, 860, 700, 940]},
        {"id": "congest", "name": "동부 교차로 혼잡", "kind": "congestion", "rect": [2360, 560, 2440, 640], "speed": 15},
        {"id": "school", "name": "어린이 보호구역", "kind": "school", "rect": [540, 280, 660, 320], "speed": 30},
        {"id": "wifi_pub", "name": "공원 Wi-Fi(비과금망)", "kind": "wifi", "rect": [2820, 880, 3000, 920]},
        {"id": "weather", "name": "산간 강우 구역", "kind": "weather", "circle": [2700, 700, 280]},
    ],
    "places": [
        {"id": "home", "name": "서부 주거단지", "kind": "home", "pos": [350, 900], "wifi": True, "slots": 10},
        {"id": "home2", "name": "동부 주거단지", "kind": "home", "pos": [2700, 900], "wifi": True, "slots": 8},
        {"id": "work", "name": "동부 산업단지 오피스", "kind": "work", "pos": [2700, 300], "slots": 10},
        {"id": "gas", "name": "서부 충전소", "kind": "gas", "pos": [800, 450], "wifi": True, "slots": 6},
        {"id": "service", "name": "동부 서비스센터", "kind": "service", "pos": [2400, 760], "wifi": True, "slots": 6},
        {"id": "depot", "name": "서부 택시 차고지", "kind": "depot", "pos": [200, 450], "slots": 8},
        {"id": "datacenter", "name": "FL 집계 서버", "kind": "server", "pos": [1600, 1050]},
        {"id": "gate_in", "name": "서쪽 진입", "kind": "gate", "pos": [0, 600]},
        {"id": "gate_out", "name": "동쪽 이탈", "kind": "gate", "pos": [3200, 600]},
    ],
    "signals": [
        {"id": "S1", "name": "서부 IC 서", "pos": [200, 600], "green": 20, "yellow": 3, "offset": 0},
        {"id": "S2", "name": "서부 IC 동", "pos": [800, 600], "green": 20, "yellow": 3, "offset": 8},
        {"id": "S3", "name": "동부 IC 서", "pos": [2400, 600], "green": 20, "yellow": 3, "offset": 4},
        {"id": "S4", "name": "동부 IC 동", "pos": [3000, 600], "green": 20, "yellow": 3, "offset": 12},
    ],
    "crosswalks": [
        {"id": "X1", "name": "학교 앞 횡단보도", "pos": [600, 300], "rate_per_min": 6, "dart_prob": 0.25, "school": True},
        {"id": "X2", "name": "서부 상가 횡단보도", "pos": [500, 900], "rate_per_min": 4, "dart_prob": 0.05},
        {"id": "X3", "name": "산업단지 횡단보도", "pos": [2550, 300], "rate_per_min": 3, "dart_prob": 0.05},
        {"id": "X4", "name": "동부 주거 횡단보도", "pos": [2850, 900], "rate_per_min": 3, "dart_prob": 0.08},
    ],
    "routes": {
        "commute": {"name": "도시 간 통근", "loop": True, "kind": "commute",
                    "pts": [[350, 900, "home"], [200, 900], [200, 600], [2400, 600], [2400, 300], [2700, 300, "work"],
                            [3000, 300], [3000, 600], [800, 600], [800, 900], [350, 900]]},
        "city": {"name": "서부 택시", "loop": True, "kind": "city",
                 "pts": [[200, 300], [800, 300], [800, 450, "gas"], [800, 900], [200, 900], [200, 450, "depot"], [200, 300]]},
        "resident": {"name": "동부 주민", "loop": True, "kind": "resident",
                     "pts": [[2400, 300], [3000, 300], [3000, 900], [2700, 900, "home"], [2400, 900], [2400, 760, "service"], [2400, 300]]},
        "visitor": {"name": "고속도로 통과", "loop": False, "kind": "visitor", "pts": [[0, 600], [3200, 600]]},
    },
    "landuse": [
        {"rect": [230, 330, 770, 570], "kind": "downtown", "density": 0.6},
        {"rect": [230, 630, 770, 870], "kind": "residential", "density": 0.6},
        {"rect": [2430, 330, 2970, 570], "kind": "industrial", "density": 0.6},
        {"rect": [2430, 630, 2970, 870], "kind": "residential", "density": 0.55},
        {"rect": [1000, 0, 2200, 1200], "kind": "park", "density": 0.5},
    ],
    "hills": [{"rect": [1060, 380, 2140, 820], "height": 140}],
})

# ------------------------------------------------------------------ 3. 항만·산업단지
save("port", {
    "name": "항만·산업단지", "desc": "간선도로 지하차도, 컨테이너 야적장(음영), 해무(강우), 항만 게이트 혼잡",
    "size": [2400, 1600], "region_border_x": 1500,
    "roads": [
        {"id": "art", "name": "간선도로", "pts": [[0, 400], [2400, 400]], "speed": 90},
        {"id": "c_w", "name": "서측 연결로", "pts": [[600, 400], [600, 800]], "speed": 50},
        {"id": "c_e", "name": "동측 연결로", "pts": [[1800, 400], [1800, 800]], "speed": 50},
        {"id": "loop", "name": "항만 순환로", "pts": [[400, 800], [2000, 800], [2000, 1300], [400, 1300], [400, 800]], "speed": 40},
        {"id": "mid", "name": "부두 중앙로", "pts": [[1200, 800], [1200, 1300]], "speed": 40},
        {"id": "w_conn", "name": "숙소 연결로", "pts": [[400, 400], [400, 800]], "speed": 50},
    ],
    "cells": [
        {"id": "P1", "name": "물류 P1", "pos": [600, 580], "r": 420, "region": "W", "color": "#2563eb"},
        {"id": "P2", "name": "산단 P2", "pos": [1800, 580], "r": 420, "region": "E", "color": "#9333ea"},
        {"id": "P3", "name": "서부두 P3", "pos": [800, 1100], "r": 380, "region": "W", "color": "#0891b2"},
        {"id": "P4", "name": "동부두 P4", "pos": [1600, 1100], "r": 380, "region": "E", "color": "#ea580c"},
    ],
    "zones": [
        {"id": "tunnel", "name": "지하차도", "kind": "tunnel", "rect": [1000, 385, 1300, 415], "speed": 70},
        {"id": "shadow", "name": "컨테이너 야적장(음영)", "kind": "shadow", "rect": [1300, 1240, 1900, 1360]},
        {"id": "congest", "name": "항만 게이트 혼잡", "kind": "congestion", "rect": [1970, 1050, 2030, 1150], "speed": 10},
        {"id": "school", "name": "통학로 보호구역", "kind": "school", "rect": [580, 540, 620, 660], "speed": 30},
        {"id": "wifi_pub", "name": "물류센터 Wi-Fi(비과금망)", "kind": "wifi", "rect": [700, 780, 900, 820]},
        {"id": "weather", "name": "해무 구역", "kind": "weather", "circle": [1200, 1450, 420]},
    ],
    "places": [
        {"id": "home", "name": "근로자 숙소", "kind": "home", "pos": [480, 400], "wifi": True, "slots": 10},
        {"id": "home2", "name": "항만 사택", "kind": "home", "pos": [800, 1300], "wifi": True, "slots": 8},
        {"id": "work", "name": "물류센터 오피스", "kind": "work", "pos": [950, 800], "slots": 10},
        {"id": "gas", "name": "트럭 충전소", "kind": "gas", "pos": [2000, 1000], "wifi": True, "slots": 6},
        {"id": "service", "name": "정비소", "kind": "service", "pos": [1500, 800], "wifi": True, "slots": 6},
        {"id": "depot", "name": "트럭 차고지", "kind": "depot", "pos": [500, 1300], "slots": 8},
        {"id": "datacenter", "name": "FL 집계 서버", "kind": "server", "pos": [1200, 200]},
        {"id": "gate_in", "name": "서쪽 진입", "kind": "gate", "pos": [0, 400]},
        {"id": "gate_out", "name": "동쪽 이탈", "kind": "gate", "pos": [2400, 400]},
    ],
    "signals": [
        {"id": "S1", "name": "서측 교차로", "pos": [600, 400], "green": 22, "yellow": 3, "offset": 0},
        {"id": "S2", "name": "동측 교차로", "pos": [1800, 400], "green": 22, "yellow": 3, "offset": 9},
        {"id": "S3", "name": "부두 북 교차로", "pos": [1200, 800], "green": 16, "yellow": 3, "offset": 5},
        {"id": "S4", "name": "부두 남 교차로", "pos": [1200, 1300], "green": 16, "yellow": 3, "offset": 11},
        {"id": "S5", "name": "물류센터 서측", "pos": [600, 800], "green": 16, "yellow": 3, "offset": 2},
        {"id": "S6", "name": "정비단지 동측", "pos": [1800, 800], "green": 16, "yellow": 3, "offset": 7},
        {"id": "S7", "name": "숙소 교차로", "pos": [400, 400], "green": 22, "yellow": 3, "offset": 13},
        {"id": "S8", "name": "항만 서북 교차로", "pos": [400, 800], "green": 16, "yellow": 3, "offset": 4},
    ],
    "crosswalks": [
        {"id": "X1", "name": "통학로 횡단보도", "pos": [600, 600], "rate_per_min": 6, "dart_prob": 0.25, "school": True},
        {"id": "X2", "name": "사택 앞 횡단보도", "pos": [900, 1300], "rate_per_min": 3, "dart_prob": 0.08},
        {"id": "X3", "name": "정비소 앞 횡단보도", "pos": [1400, 800], "rate_per_min": 3, "dart_prob": 0.05},
        {"id": "X4", "name": "숙소 앞 횡단보도", "pos": [540, 400], "rate_per_min": 3, "dart_prob": 0.05},
    ],
    "routes": {
        "commute": {"name": "숙소→물류센터 통근", "loop": True, "kind": "commute",
                    "pts": [[400, 400], [480, 400, "home"], [600, 400], [600, 800], [950, 800, "work"], [1200, 800],
                            [1200, 1300], [400, 1300], [400, 800], [400, 400]]},
        "city": {"name": "항만 트럭", "loop": True, "kind": "city",
                 "pts": [[400, 800], [1200, 800], [1500, 800, "service"], [2000, 800], [2000, 1000, "gas"], [2000, 1300],
                         [500, 1300, "depot"], [400, 1300], [400, 800]]},
        "resident": {"name": "사택 주민", "loop": True, "kind": "resident",
                     "pts": [[1200, 800], [1200, 1300], [800, 1300, "home"], [400, 1300], [400, 800], [1200, 800]]},
        "visitor": {"name": "간선도로 통과", "loop": False, "kind": "visitor", "pts": [[0, 400], [2400, 400]]},
    },
    "landuse": [
        {"rect": [0, 0, 2400, 370], "kind": "industrial", "density": 0.45},
        {"rect": [630, 430, 1770, 770], "kind": "industrial", "density": 0.6},
        {"rect": [430, 830, 1170, 1270], "kind": "residential", "density": 0.5},
        {"rect": [1230, 830, 1970, 1230], "kind": "industrial", "density": 0.6},
        {"rect": [0, 430, 570, 1600], "kind": "park", "density": 0.3},
    ],
    "water": [{"rect": [0, 1380, 2400, 1600]}],
})

# ------------------------------------------------------------------ 4. 신도시 순환
save("newtown", {
    "name": "신도시 순환", "desc": "외곽 순환대로(70 km/h)·내부 순환로·방사형 도로, 지하차도, 업무지구 빌딩 숲, 학교·공원",
    "size": [2200, 1600], "region_border_x": 900,
    "roads": [
        {"id": "outer", "name": "외곽 순환대로", "pts": [[200, 200], [2000, 200], [2000, 1400], [200, 1400], [200, 200]], "speed": 70},
        {"id": "inner", "name": "내부 순환로", "pts": [[700, 600], [1500, 600], [1500, 1000], [700, 1000], [700, 600]], "speed": 40},
        {"id": "rad_n", "name": "북측 방사로", "pts": [[1100, 200], [1100, 600]], "speed": 50},
        {"id": "rad_s", "name": "남측 방사로", "pts": [[1100, 1000], [1100, 1400]], "speed": 50},
        {"id": "rad_w", "name": "서측 방사로", "pts": [[0, 800], [700, 800]], "speed": 60},
        {"id": "rad_e", "name": "동측 방사로", "pts": [[1500, 800], [2200, 800]], "speed": 60},
    ],
    "cells": [
        {"id": "NW", "name": "북서 NW", "pos": [550, 450], "r": 450, "region": "W", "color": "#2563eb"},
        {"id": "NE", "name": "북동 NE", "pos": [1650, 450], "r": 400, "region": "E", "color": "#9333ea"},
        {"id": "SW", "name": "남서 SW", "pos": [550, 1150], "r": 450, "region": "W", "color": "#0891b2"},
        {"id": "SE", "name": "남동 SE", "pos": [1650, 1150], "r": 450, "region": "E", "color": "#ea580c"},
        {"id": "CT", "name": "도심 CT", "pos": [1100, 800], "r": 300, "region": "E", "color": "#16a34a"},
    ],
    "zones": [
        {"id": "tunnel", "name": "외곽 지하차도", "kind": "tunnel", "rect": [1300, 185, 1700, 215], "speed": 70},
        {"id": "shadow", "name": "업무지구 빌딩 숲(음영)", "kind": "shadow", "rect": [750, 960, 1050, 1040]},
        {"id": "congest", "name": "도심 교차로 혼잡", "kind": "congestion", "rect": [1050, 560, 1150, 640], "speed": 15},
        {"id": "school", "name": "초등학교 보호구역", "kind": "school", "rect": [180, 1000, 220, 1200], "speed": 30},
        {"id": "wifi_pub", "name": "중앙공원 Wi-Fi(비과금망)", "kind": "wifi", "rect": [1400, 1380, 1650, 1420]},
        {"id": "weather", "name": "강우 구역", "kind": "weather", "circle": [1700, 1100, 300]},
    ],
    "places": [
        {"id": "home", "name": "아파트 단지", "kind": "home", "pos": [600, 1400], "wifi": True, "slots": 12},
        {"id": "work", "name": "업무지구 오피스", "kind": "work", "pos": [1300, 600], "slots": 10},
        {"id": "gas", "name": "충전소", "kind": "gas", "pos": [2000, 500], "wifi": True, "slots": 6},
        {"id": "service", "name": "서비스센터", "kind": "service", "pos": [700, 700], "wifi": True, "slots": 6},
        {"id": "depot", "name": "택시 차고지", "kind": "depot", "pos": [1500, 900], "slots": 8},
        {"id": "datacenter", "name": "FL 집계 서버", "kind": "server", "pos": [1100, 1520]},
        {"id": "gate_in", "name": "서쪽 진입", "kind": "gate", "pos": [0, 800]},
        {"id": "gate_out", "name": "동쪽 이탈", "kind": "gate", "pos": [2200, 800]},
    ],
    "signals": [
        {"id": "S1", "name": "서측 교차로", "pos": [200, 800], "green": 20, "yellow": 3, "offset": 0},
        {"id": "S2", "name": "내부 서측", "pos": [700, 800], "green": 16, "yellow": 3, "offset": 6},
        {"id": "S3", "name": "도심 북측", "pos": [1100, 600], "green": 16, "yellow": 3, "offset": 3},
        {"id": "S4", "name": "도심 남측", "pos": [1100, 1000], "green": 16, "yellow": 3, "offset": 10},
        {"id": "S5", "name": "내부 동측", "pos": [1500, 800], "green": 16, "yellow": 3, "offset": 13},
        {"id": "S6", "name": "동측 교차로", "pos": [2000, 800], "green": 20, "yellow": 3, "offset": 5},
        {"id": "S7", "name": "북측 교차로", "pos": [1100, 200], "green": 20, "yellow": 3, "offset": 8},
        {"id": "S8", "name": "남측 교차로", "pos": [1100, 1400], "green": 20, "yellow": 3, "offset": 15},
    ],
    "crosswalks": [
        {"id": "X1", "name": "초등학교 횡단보도", "pos": [200, 1100], "rate_per_min": 7, "dart_prob": 0.3, "school": True},
        {"id": "X2", "name": "업무지구 횡단보도", "pos": [900, 1000], "rate_per_min": 5, "dart_prob": 0.05},
        {"id": "X3", "name": "오피스 앞 횡단보도", "pos": [1250, 600], "rate_per_min": 4, "dart_prob": 0.05},
        {"id": "X4", "name": "아파트 앞 횡단보도", "pos": [800, 1400], "rate_per_min": 4, "dart_prob": 0.08},
    ],
    "routes": {
        "commute": {"name": "아파트→업무지구 통근", "loop": True, "kind": "commute",
                    "pts": [[600, 1400, "home"], [200, 1400], [200, 200], [1100, 200], [1100, 600], [1300, 600, "work"],
                            [1500, 600], [1500, 1000], [1100, 1000], [1100, 1400], [600, 1400]]},
        "city": {"name": "도심 택시", "loop": True, "kind": "city",
                 "pts": [[700, 600], [1500, 600], [1500, 900, "depot"], [1500, 1000], [700, 1000], [700, 700, "service"], [700, 600]]},
        "resident": {"name": "외곽 주민", "loop": True, "kind": "resident",
                     "pts": [[200, 200], [2000, 200], [2000, 500, "gas"], [2000, 1400], [600, 1400, "home"], [200, 1400], [200, 200]]},
        "visitor": {"name": "동서 통과", "loop": False, "kind": "visitor",
                    "pts": [[0, 800], [200, 800], [700, 800], [700, 600], [1500, 600], [1500, 800], [2000, 800], [2200, 800]]},
    },
    "landuse": [
        {"rect": [730, 630, 1470, 970], "kind": "downtown", "density": 0.8},
        {"rect": [230, 1030, 1070, 1370], "kind": "residential", "density": 0.6},
        {"rect": [1130, 1030, 1970, 1370], "kind": "park", "density": 0.45},
        {"rect": [230, 230, 1070, 570], "kind": "residential", "density": 0.5},
        {"rect": [1130, 230, 1970, 570], "kind": "industrial", "density": 0.45},
    ],
})

# ------------------------------------------------------------------ 5. 광역 도시권 (넓은 맵: 켜 두고 보기)
save("metro", auto_signals({
    "name": "광역 도시권", "desc": "6 × 4 km. 서부·동부 두 도시를 고속도로(산악 터널 1 km)와 해안 순환로가 잇는다. 도심 빌딩 숲, 해변 Wi-Fi, 중앙 숲 공원",
    "size": [6000, 4000], "region_border_x": 3000,
    "roads": [
        {"id": "hw", "name": "도시 간 고속도로", "pts": [[0, 800], [6000, 800]], "speed": 110},
        {"id": "w1", "name": "서부 1로", "pts": [[500, 1500], [500, 3400]], "speed": 50},
        {"id": "w2", "name": "서부 중앙로", "pts": [[1300, 800], [1300, 3400]], "speed": 60},
        {"id": "w3", "name": "서부 3로", "pts": [[2100, 1500], [2100, 3400]], "speed": 50},
        {"id": "wa", "name": "서부 업무로", "pts": [[500, 1500], [2100, 1500]], "speed": 50},
        {"id": "wb", "name": "서부 상가로", "pts": [[500, 2300], [2100, 2300]], "speed": 50},
        {"id": "e1", "name": "동부 1로", "pts": [[3900, 1600], [3900, 3400]], "speed": 50},
        {"id": "e2", "name": "동부 중앙로", "pts": [[4700, 800], [4700, 3400]], "speed": 60},
        {"id": "e3", "name": "동부 3로", "pts": [[5500, 1600], [5500, 3400]], "speed": 50},
        {"id": "ea", "name": "테크노밸리로", "pts": [[3900, 1600], [5500, 1600]], "speed": 50},
        {"id": "eb", "name": "동부 주거로", "pts": [[3900, 2500], [5500, 2500]], "speed": 50},
        {"id": "sc", "name": "해안 순환로", "pts": [[500, 3400], [5500, 3400]], "speed": 80},
    ],
    "cells": [
        {"id": "W1", "name": "서부 도심 W1", "pos": [1000, 1900], "r": 700, "region": "W", "color": "#2563eb"},
        {"id": "W2", "name": "서부 주거 W2", "pos": [1500, 2950], "r": 560, "region": "W", "color": "#0891b2"},
        {"id": "HW", "name": "고속도로 서측 HW", "pos": [1300, 820], "r": 620, "region": "W", "color": "#9333ea"},
        {"id": "HE", "name": "고속도로 동측 HE", "pos": [4700, 820], "r": 620, "region": "E", "color": "#db2777"},
        {"id": "E1", "name": "동부 도심 E1", "pos": [4700, 2100], "r": 760, "region": "E", "color": "#ea580c"},
        {"id": "CS", "name": "해변 CS", "pos": [3000, 3420], "r": 460, "region": "E", "color": "#16a34a"},
    ],
    "zones": [
        {"id": "tunnel", "name": "산악 터널 1 km", "kind": "tunnel", "rect": [2500, 785, 3500, 815], "speed": 80},
        {"id": "shadow", "name": "서부 도심 빌딩 숲(음영)", "kind": "shadow", "rect": [1270, 1600, 1330, 2200]},
        {"id": "shadow2", "name": "동부 업무지구 빌딩 숲(음영)", "kind": "shadow", "rect": [4670, 1700, 4730, 2400]},
        {"id": "congest", "name": "서부 중앙 교차로 혼잡", "kind": "congestion", "rect": [1250, 2250, 1350, 2350], "speed": 15},
        {"id": "school", "name": "동부 초등학교 보호구역", "kind": "school", "rect": [3880, 1900, 3920, 2200], "speed": 30},
        {"id": "wifi_pub", "name": "해변 공영 Wi-Fi(비과금망)", "kind": "wifi", "rect": [2600, 3380, 3400, 3420]},
        {"id": "weather", "name": "동부 강우 구역", "kind": "weather", "circle": [5000, 2900, 450]},
    ],
    "places": [
        {"id": "home", "name": "서부 해안 아파트", "kind": "home", "pos": [900, 3400], "wifi": True, "slots": 12},
        {"id": "home2", "name": "동부 주거단지", "kind": "home", "pos": [5100, 3400], "wifi": True, "slots": 12},
        {"id": "work", "name": "서부 업무지구 오피스", "kind": "work", "pos": [1700, 1500], "slots": 12},
        {"id": "work2", "name": "동부 테크노밸리", "kind": "work", "pos": [4300, 1600], "slots": 12},
        {"id": "gas", "name": "서부 충전소", "kind": "gas", "pos": [2100, 1900], "wifi": True, "slots": 6},
        {"id": "gas2", "name": "동부 충전소", "kind": "gas", "pos": [5500, 2000], "wifi": True, "slots": 6},
        {"id": "service", "name": "서부 서비스센터", "kind": "service", "pos": [500, 1900], "wifi": True, "slots": 6},
        {"id": "service2", "name": "동부 서비스센터", "kind": "service", "pos": [4700, 2900], "wifi": True, "slots": 6},
        {"id": "depot", "name": "서부 택시 차고지", "kind": "depot", "pos": [1300, 3000], "slots": 8},
        {"id": "depot2", "name": "동부 택시 차고지", "kind": "depot", "pos": [3900, 2900], "slots": 8},
        {"id": "datacenter", "name": "FL 집계 서버", "kind": "server", "pos": [3000, 1350]},
        {"id": "gate_in", "name": "서쪽 진입", "kind": "gate", "pos": [0, 800]},
        {"id": "gate_out", "name": "동쪽 이탈", "kind": "gate", "pos": [6000, 800]},
    ],
    "crosswalks": [
        {"id": "X1", "name": "동부 초등학교 횡단보도", "pos": [3900, 2050], "rate_per_min": 6, "dart_prob": 0.25, "school": True},
        {"id": "X2", "name": "서부 상가 횡단보도", "pos": [900, 2300], "rate_per_min": 5, "dart_prob": 0.05},
        {"id": "X3", "name": "서부 업무로 횡단보도", "pos": [1000, 1500], "rate_per_min": 4, "dart_prob": 0.05},
        {"id": "X4", "name": "동부 주거 횡단보도", "pos": [5100, 2500], "rate_per_min": 3, "dart_prob": 0.08},
        {"id": "X5", "name": "해변 횡단보도", "pos": [3000, 3400], "rate_per_min": 5, "dart_prob": 0.08},
        {"id": "X6", "name": "테크노밸리 횡단보도", "pos": [5100, 1600], "rate_per_min": 3, "dart_prob": 0.05},
    ],
    "routes": {
        "commute": {"name": "서부→동부 통근 (고속도로)", "loop": True, "kind": "commute",
                    "pts": [[900, 3400, "home"], [1300, 3400], [1300, 800], [4700, 800], [4700, 1600], [4300, 1600, "work"],
                            [3900, 1600], [3900, 3400], [900, 3400]]},
        "commute2": {"name": "동부→서부 통근", "loop": True, "kind": "commute",
                     "pts": [[5100, 3400, "home"], [4700, 3400], [4700, 800], [1300, 800], [1300, 1500], [1700, 1500, "work"],
                             [2100, 1500], [2100, 3400], [5100, 3400]]},
        "city": {"name": "서부 택시", "loop": True, "kind": "city",
                 "pts": [[500, 1500], [1300, 1500], [2100, 1500], [2100, 1900, "gas"], [2100, 2300], [1300, 2300],
                         [1300, 3000, "depot"], [1300, 3400], [500, 3400], [500, 1900, "service"], [500, 1500]]},
        "city2": {"name": "동부 택시", "loop": True, "kind": "city",
                  "pts": [[3900, 1600], [5500, 1600], [5500, 2000, "gas"], [5500, 2500], [4700, 2500], [4700, 2900, "service"],
                          [4700, 3400], [3900, 3400], [3900, 2900, "depot"], [3900, 1600]]},
        "resident": {"name": "서부 주민", "loop": True, "kind": "resident",
                     "pts": [[500, 2300], [1300, 2300], [1300, 3400], [900, 3400, "home"], [500, 3400], [500, 2300]]},
        "resident2": {"name": "동부 주민", "loop": True, "kind": "resident",
                      "pts": [[4700, 2500], [5500, 2500], [5500, 3400], [5100, 3400, "home"], [4700, 3400], [4700, 2500]]},
        "visitor": {"name": "고속도로 통과", "loop": False, "kind": "visitor", "pts": [[0, 800], [6000, 800]]},
        "coast": {"name": "해안 드라이브", "loop": True, "kind": "city", "always": True, "label": "드라이브",
                  "pts": [[500, 3400], [5500, 3400], [5500, 1600], [4700, 1600], [4700, 800], [1300, 800], [1300, 1500],
                          [500, 1500], [500, 3400]]},
    },
    "vehicle_routes": ["commute", "city", "resident", "visitor", "commute2", "city2", "resident2", "visitor",
                       "city", "commute", "resident2", "city2", "commute2", "visitor", "city", "resident"],
    "npc_routes": ["coast", "city", "city2", "commute", "commute2", "visitor", "coast", "resident", "resident2", "visitor"],
    "landuse": [
        {"rect": [530, 1530, 2070, 2270], "kind": "downtown", "density": 0.8},
        {"rect": [530, 2330, 2070, 3370], "kind": "residential", "density": 0.55},
        {"rect": [3930, 1630, 5470, 2470], "kind": "downtown", "density": 0.7},
        {"rect": [3930, 2530, 5470, 3370], "kind": "residential", "density": 0.55},
        {"rect": [0, 0, 2400, 770], "kind": "park", "density": 0.45},
        {"rect": [3600, 0, 6000, 770], "kind": "industrial", "density": 0.4},
        {"rect": [2150, 1150, 3850, 3350], "kind": "park", "density": 0.5},
        {"rect": [530, 830, 1270, 1470], "kind": "residential", "density": 0.4},
        {"rect": [1330, 830, 2400, 1470], "kind": "residential", "density": 0.4},
        {"rect": [3600, 830, 4670, 1570], "kind": "industrial", "density": 0.5},
        {"rect": [4730, 830, 5470, 1570], "kind": "industrial", "density": 0.5},
        {"rect": [0, 830, 470, 3370], "kind": "park", "density": 0.3},
        {"rect": [5530, 830, 6000, 3370], "kind": "residential", "density": 0.3},
    ],
    "water": [{"rect": [0, 3560, 6000, 4000]}],
    "hills": [{"rect": [2400, 420, 3600, 1180], "height": 170}],
}, {(1300, 800): "서부 IC", (4700, 800): "동부 IC"}))

# ------------------------------------------------------------------ 6. GTA V 풍 섬: 로스 산토스 + 블레인 카운티
# 실제 게임 지도의 배치를 본뜸 (북쪽이 위, 화면 z가 아래로 커짐):
#   남쪽 대도시 로스 산토스(다운타운·베스푸치 해변·공항·항만) · 북쪽 비너스 언덕 · 가운데 알라모 호수와 샌디 쇼어스(남쪽 호숫가)
#   · 그랜드 세노라 사막 · 호수 동쪽 그레이프시드 농장 · 북서 칠리아드 산 · 북쪽 끝 팔레토 베이 · 서쪽 해안 그레이트 오션 하이웨이
#   · 동쪽 세노라 프리웨이 · 사막을 가로지르는 68번 국도 · 북동 브래독 터널 · 서쪽 군 기지
save("lossantos", auto_signals({
    "name": "로스 산토스 섬 (GTA V 풍)", "desc": "6 × 8.8 km 섬. 남쪽 대도시·북쪽 시골. 해안 하이웨이·프리웨이·사막 국도로 한 바퀴 약 25 km, 공항→페리 통과 차량",
    "size": [6000, 8800], "region_border_x": 3000,
    "roads": [
        {"id": "goh", "name": "그레이트 오션 하이웨이", "speed": 100,
         "pts": [[1800, 6400], [700, 6400], [700, 1200], [1400, 500], [4600, 500], [5500, 1400], [5500, 3200]]},
        {"id": "senora", "name": "세노라 프리웨이", "speed": 110, "pts": [[5500, 3200], [5500, 5200], [4800, 6000], [4800, 6400]]},
        {"id": "r68", "name": "68번 국도 (사막)", "speed": 80, "pts": [[700, 4300], [5500, 4300]]},
        {"id": "sandy_rd", "name": "샌디 쇼어스 진입로", "speed": 50, "pts": [[3200, 3900], [3200, 4300]]},
        {"id": "sandy", "name": "샌디 쇼어스 호숫가길", "speed": 40, "pts": [[2700, 3900], [4000, 3900]]},
        {"id": "grape", "name": "그레이프시드 길", "speed": 60, "pts": [[4200, 2400], [5500, 2400]]},
        {"id": "farm", "name": "그레이프시드 농장길", "speed": 40, "pts": [[4200, 2400], [4200, 3000], [4800, 3000], [4800, 2400]]},
        {"id": "paleto", "name": "팔레토 베이 마을길", "speed": 40, "pts": [[2600, 500], [2600, 1000], [3400, 1000], [3400, 500]]},
        {"id": "pier", "name": "팔레토 페리 부두", "speed": 40, "pts": [[3000, 500], [3000, 0]]},
        {"id": "airport", "name": "공항로", "speed": 60, "pts": [[3000, 8800], [3000, 8200]]},
        {"id": "ls_ring", "name": "로스 산토스 순환 고속도로", "speed": 90,
         "pts": [[1800, 6400], [4800, 6400], [4800, 8200], [1800, 8200], [1800, 6400]]},
        {"id": "ls_v1", "name": "베스푸치 대로", "speed": 50, "pts": [[2600, 6400], [2600, 8200]]},
        {"id": "ls_v2", "name": "다운타운 중앙로", "speed": 50, "pts": [[3400, 6400], [3400, 8200]]},
        {"id": "ls_v3", "name": "이스트 로스 산토스로", "speed": 50, "pts": [[4100, 6400], [4100, 8200]]},
        {"id": "ls_h1", "name": "다운타운 1번가", "speed": 50, "pts": [[1800, 7000], [4800, 7000]]},
        {"id": "ls_h2", "name": "사우스 로스 산토스 거리", "speed": 50, "pts": [[1800, 7600], [4800, 7600]]},
    ],
    "cells": [
        {"id": "PB", "name": "팔레토 베이 PB", "pos": [3000, 800], "r": 620, "region": "E", "color": "#0891b2"},
        {"id": "GS", "name": "그레이프시드 GS", "pos": [4700, 2700], "r": 640, "region": "E", "color": "#16a34a"},
        {"id": "SS", "name": "샌디 쇼어스 SS", "pos": [3200, 4100], "r": 720, "region": "E", "color": "#ea580c"},
        {"id": "FZ", "name": "서해안 군 기지 FZ", "pos": [900, 3700], "r": 520, "region": "W", "color": "#64748b"},
        {"id": "DT", "name": "다운타운 DT", "pos": [3400, 7300], "r": 900, "region": "E", "color": "#2563eb"},
        {"id": "VB", "name": "베스푸치 VB", "pos": [2200, 7000], "r": 520, "region": "W", "color": "#9333ea"},
        {"id": "PT", "name": "항만 PT", "pos": [4500, 7900], "r": 520, "region": "E", "color": "#db2777"},
        {"id": "SF", "name": "세노라 프리웨이 SF", "pos": [5400, 5300], "r": 560, "region": "E", "color": "#ca8a04"},
    ],
    "zones": [
        {"id": "tunnel", "name": "브래독 터널", "kind": "tunnel", "rect": [3800, 485, 4500, 515], "speed": 80},
        {"id": "shadow", "name": "다운타운 마천루(음영)", "kind": "shadow", "rect": [3380, 7020, 3420, 7580]},
        {"id": "congest", "name": "다운타운 교차로 혼잡", "kind": "congestion", "rect": [3350, 7550, 3450, 7650], "speed": 15},
        {"id": "school", "name": "샌디 쇼어스 학교 앞", "kind": "school", "rect": [2900, 3880, 3150, 3920], "speed": 30},
        {"id": "wifi_pub", "name": "베스푸치 해변 Wi-Fi(비과금망)", "kind": "wifi", "rect": [1780, 6800, 1820, 7600]},
        {"id": "weather", "name": "사막 모래바람(대역폭↓)", "kind": "weather", "circle": [2600, 4500, 520]},
    ],
    "places": [
        {"id": "home", "name": "샌디 쇼어스 트레일러 단지", "kind": "home", "pos": [3600, 3900], "slots": 10},
        {"id": "home2", "name": "베스푸치 아파트", "kind": "home", "pos": [1800, 7300], "wifi": True, "slots": 12},
        {"id": "home3", "name": "팔레토 베이 주택가", "kind": "home", "pos": [3000, 1000], "wifi": True, "slots": 10},
        {"id": "work", "name": "다운타운 오피스", "kind": "work", "pos": [3000, 7000], "slots": 14},
        {"id": "work2", "name": "그레이프시드 농장", "kind": "work", "pos": [4500, 3000], "slots": 8},
        {"id": "gas", "name": "샌디 쇼어스 충전소", "kind": "gas", "pos": [3200, 4100], "wifi": True, "slots": 6},
        {"id": "gas2", "name": "로스 산토스 충전소", "kind": "gas", "pos": [4100, 6800], "wifi": True, "slots": 8},
        {"id": "service", "name": "로스 산토스 정비소(OTA)", "kind": "service", "pos": [2600, 7900], "wifi": True, "slots": 8},
        {"id": "service2", "name": "팔레토 정비소", "kind": "service", "pos": [3400, 750], "wifi": True, "slots": 6},
        {"id": "depot", "name": "다운타운 택시 차고지", "kind": "depot", "pos": [4100, 7900], "slots": 10},
        {"id": "datacenter", "name": "FL 집계 서버", "kind": "server", "pos": [2000, 6000]},
        {"id": "gate_in", "name": "공항 (진입)", "kind": "gate", "pos": [3000, 8800]},
        {"id": "gate_out", "name": "팔레토 페리 (이탈)", "kind": "gate", "pos": [3000, 0]},
    ],
    "crosswalks": [
        {"id": "X1", "name": "샌디 쇼어스 학교 횡단보도", "pos": [3000, 3900], "rate_per_min": 6, "dart_prob": 0.25, "school": True},
        {"id": "X2", "name": "다운타운 횡단보도", "pos": [3000, 7600], "rate_per_min": 6, "dart_prob": 0.05},
        {"id": "X3", "name": "베스푸치 횡단보도", "pos": [2200, 7000], "rate_per_min": 5, "dart_prob": 0.06},
        {"id": "X4", "name": "이스트 LS 횡단보도", "pos": [4100, 7300], "rate_per_min": 4, "dart_prob": 0.08},
        {"id": "X5", "name": "팔레토 횡단보도", "pos": [3000, 1000], "rate_per_min": 2, "dart_prob": 0.05},
        {"id": "X6", "name": "항만 횡단보도", "pos": [4450, 7600], "rate_per_min": 3, "dart_prob": 0.05},
    ],
    "routes": {
        "commute": {"name": "샌디 쇼어스→다운타운 통근", "loop": True, "kind": "commute",
                    "pts": [[3600, 3900, "home"], [3200, 3900], [3200, 4300], [5500, 4300], [5500, 5200], [4800, 6000],
                            [4800, 6400], [4100, 6400], [4100, 7000], [3000, 7000, "work"], [2600, 7000], [2600, 6400],
                            [1800, 6400], [700, 6400], [700, 4300], [3200, 4300], [3200, 3900], [3600, 3900]]},
        "commute2": {"name": "팔레토 베이→그레이프시드 농장", "loop": True, "kind": "commute",
                     "pts": [[3000, 1000, "home"], [3400, 1000], [3400, 500], [4600, 500], [5500, 1400], [5500, 2400],
                             [4800, 2400], [4800, 3000], [4500, 3000, "work"], [4200, 3000], [4200, 2400], [5500, 2400],
                             [5500, 1400], [4600, 500], [2600, 500], [2600, 1000], [3000, 1000]]},
        "city": {"name": "로스 산토스 택시", "loop": True, "kind": "city",
                 "pts": [[1800, 7000], [4100, 7000], [4100, 6800, "gas"], [4100, 6400], [4800, 6400], [4800, 8200],
                         [4100, 8200], [4100, 7900, "depot"], [4100, 7600], [2600, 7600], [2600, 7900, "service"],
                         [2600, 8200], [1800, 8200], [1800, 7000]]},
        "city2": {"name": "블레인 카운티 버스", "loop": True, "kind": "city", "always": True, "label": "버스",
                  "pts": [[3200, 4300], [700, 4300], [700, 1200], [1400, 500], [3400, 500], [3400, 750, "service"],
                          [3400, 1000], [2600, 1000], [2600, 500], [4600, 500], [5500, 1400], [5500, 4300], [3200, 4300]]},
        "resident": {"name": "베스푸치 주민", "loop": True, "kind": "resident",
                     "pts": [[1800, 7600], [2600, 7600], [2600, 7000], [1800, 7000], [1800, 7300, "home"], [1800, 7600]]},
        "visitor": {"name": "공항→팔레토 페리 (섬 종단)", "loop": False, "kind": "visitor",
                    "pts": [[3000, 8800], [3000, 8200], [1800, 8200], [1800, 6400], [700, 6400], [700, 1200], [1400, 500],
                            [3000, 500], [3000, 0]]},
        "island": {"name": "섬 일주 드라이브", "loop": True, "kind": "city", "always": True, "label": "드라이브",
                   "pts": [[1800, 6400], [700, 6400], [700, 1200], [1400, 500], [4600, 500], [5500, 1400], [5500, 5200],
                           [4800, 6000], [4800, 6400], [1800, 6400]]},
    },
    "vehicle_routes": ["commute", "city", "resident", "visitor", "commute2", "city2", "city", "commute",
                       "resident", "visitor", "city2", "commute2", "city", "resident", "commute", "visitor"],
    "npc_routes": ["island", "city", "city", "commute", "visitor", "city2", "island", "resident", "city", "commute2"],
    "landuse": [
        {"rect": [2630, 6430, 4070, 6970], "kind": "downtown", "density": 0.85},
        {"rect": [2630, 7030, 4070, 7570], "kind": "downtown", "density": 0.8},
        {"rect": [1830, 6430, 2570, 7570], "kind": "residential", "density": 0.55},
        {"rect": [1830, 7630, 4070, 8170], "kind": "residential", "density": 0.6},
        {"rect": [4130, 6430, 4770, 7570], "kind": "residential", "density": 0.55},
        {"rect": [4130, 7630, 4770, 8170], "kind": "industrial", "density": 0.7},
        {"rect": [1700, 5300, 4600, 6340], "kind": "residential", "density": 0.18},
        {"rect": [2700, 3930, 4000, 4270], "kind": "residential", "density": 0.25},
        {"rect": [4230, 2430, 4770, 2970], "kind": "park", "density": 0.12},
        {"rect": [2630, 530, 3370, 970], "kind": "residential", "density": 0.45},
        {"rect": [800, 3300, 1800, 4100], "kind": "industrial", "density": 0.3},
        {"rect": [800, 4400, 5400, 5200], "kind": "park", "density": 0.04},
        {"rect": [750, 600, 2500, 2500], "kind": "park", "density": 0.55},
        {"rect": [4700, 600, 5450, 2300], "kind": "park", "density": 0.45},
        {"rect": [750, 4350, 1800, 6350], "kind": "park", "density": 0.25},
        {"rect": [3700, 2500, 4150, 3850], "kind": "park", "density": 0.15},
    ],
    "water": [{"rect": [0, 0, 450, 8800]}, {"rect": [450, 0, 6000, 230]}, {"rect": [5800, 230, 6000, 8800]},
              {"rect": [450, 8650, 5800, 8800]}, {"rect": [450, 6700, 1550, 8650]}, {"rect": [1900, 2600, 3700, 3600]}],
    "hills": [{"rect": [950, 850, 2450, 2350], "height": 480}, {"rect": [3600, 150, 4700, 900], "height": 180},
              {"rect": [4950, 3350, 5800, 4100], "height": 230}, {"rect": [2200, 5250, 4500, 6200], "height": 200}],
    "decor": [{"kind": "runway", "rect": [2000, 8300, 3400, 8380]}, {"kind": "runway", "rect": [1950, 8450, 3300, 8520]},
              {"kind": "runway", "rect": [900, 3500, 1700, 3560]}],
}, {(1800, 6400): "베스푸치 IC", (4800, 6400): "프리웨이 남쪽 끝", (700, 4300): "68번 국도 서쪽",
    (5500, 4300): "68번 국도 동쪽", (3200, 4300): "샌디 쇼어스 입구", (5500, 2400): "그레이프시드 입구",
    (3000, 500): "팔레토 부두 입구", (3000, 8200): "공항 입구"}))

# ------------------------------------------------------------------ 7. 레이싱 서킷
# 시계 방향 약 8 km 서킷: 피트 직선(충전·OTA 개러지·팀 개러지) → 1번 코너 → 안쪽 S자 → 남쪽 직선(관중석 밑 터널) → 서쪽 직선
TRACK = chain([[1000, 600], [1500, 600, "gas"], [1900, 600, "service"], [2300, 600, "depot"], [3000, 600]],
              arc(3000, 800, 200, -90, 0), [[3200, 1000]], arc(3000, 1000, 200, 0, 90), [[2600, 1200]],
              arc(2600, 1400, 200, -90, -180), [[2400, 1500]], arc(2600, 1500, 200, 180, 90), [[3000, 1700]],
              arc(3000, 1900, 200, -90, 0), [[3200, 2000]], arc(3000, 2000, 200, 0, 90), [[1000, 2200]],
              arc(1000, 2000, 200, 90, 180), [[800, 800]], arc(1000, 800, 200, 180, 270))
save("racing", auto_signals({
    "name": "레이싱 서킷", "desc": "8 km 서킷(최고 220 km/h)과 피트 개러지. 서킷 터널·관중석 음영·국지성 소나기, 바깥에 관람객 마을·호텔·고속도로",
    "size": [4000, 3000], "region_border_x": 2200, "lane_width": 5.0,
    "roads": [
        {"id": "track", "name": "서킷", "pts": [p[:2] for p in TRACK], "speed": 220, "track": True},
        {"id": "perim", "name": "서킷 외곽도로", "pts": [[400, 300], [3600, 300], [3600, 2500], [400, 2500], [400, 300]], "speed": 50},
        {"id": "hw", "name": "고속도로", "pts": [[0, 120], [4000, 120]], "speed": 100},
        {"id": "conn", "name": "서킷 진입로", "pts": [[2000, 120], [2000, 300]], "speed": 50},
        {"id": "village", "name": "관람객 마을길", "pts": [[400, 2500], [400, 2850], [3600, 2850], [3600, 2500]], "speed": 40},
        {"id": "vmid", "name": "마을 중앙길", "pts": [[2000, 2500], [2000, 2850]], "speed": 30},
    ],
    "cells": [
        {"id": "T1", "name": "피트 직선 T1", "pos": [1800, 620], "r": 620, "region": "W", "color": "#2563eb"},
        {"id": "T2", "name": "안쪽 S자 T2", "pos": [2900, 1450], "r": 460, "region": "E", "color": "#9333ea"},
        {"id": "T3", "name": "남쪽 직선 T3", "pos": [1300, 2250], "r": 520, "region": "W", "color": "#0891b2"},
        {"id": "VL", "name": "관람객 마을 VL", "pos": [2400, 2700], "r": 560, "region": "E", "color": "#ea580c"},
        {"id": "HW", "name": "고속도로 HW", "pos": [2000, 150], "r": 520, "region": "W", "color": "#16a34a"},
    ],
    "zones": [
        {"id": "tunnel", "name": "관중석 밑 터널", "kind": "tunnel", "rect": [1700, 2180, 2300, 2220], "speed": 220},
        {"id": "shadow", "name": "메인 관중석 지붕 밑(음영)", "kind": "shadow", "rect": [2400, 570, 2950, 630]},
        {"id": "congest", "name": "관람객 혼잡", "kind": "congestion", "rect": [1950, 2800, 2050, 2900], "speed": 10},
        {"id": "school", "name": "어린이 관람 구역", "kind": "school", "rect": [800, 2830, 1200, 2870], "speed": 30},
        {"id": "wifi_pub", "name": "패독 Wi-Fi(비과금망)", "kind": "wifi", "rect": [1000, 280, 1800, 320]},
        {"id": "weather", "name": "국지성 소나기", "kind": "weather", "circle": [2900, 1450, 380]},
    ],
    "places": [
        {"id": "gas", "name": "피트 충전", "kind": "gas", "pos": [1500, 600], "wifi": True, "slots": 6},
        {"id": "service", "name": "피트 개러지(OTA)", "kind": "service", "pos": [1900, 600], "wifi": True, "slots": 6},
        {"id": "depot", "name": "팀 개러지", "kind": "depot", "pos": [2300, 600], "slots": 8},
        {"id": "home", "name": "관람객 호텔", "kind": "home", "pos": [2800, 2850], "wifi": True, "slots": 12},
        {"id": "home2", "name": "스태프 숙소", "kind": "home", "pos": [3600, 1500], "slots": 10},
        {"id": "work", "name": "서킷 운영 사무실", "kind": "work", "pos": [1200, 300], "slots": 10},
        {"id": "datacenter", "name": "FL 집계 서버 (관제탑)", "kind": "server", "pos": [1800, 1400]},
        {"id": "gate_in", "name": "서쪽 진입", "kind": "gate", "pos": [0, 120]},
        {"id": "gate_out", "name": "동쪽 이탈", "kind": "gate", "pos": [4000, 120]},
    ],
    "crosswalks": [
        {"id": "X1", "name": "어린이 관람 구역 횡단보도", "pos": [1000, 2850], "rate_per_min": 6, "dart_prob": 0.25, "school": True},
        {"id": "X2", "name": "관람객 횡단보도", "pos": [2700, 2500], "rate_per_min": 6, "dart_prob": 0.06},
        {"id": "X3", "name": "호텔 앞 횡단보도", "pos": [3100, 2850], "rate_per_min": 4, "dart_prob": 0.06},
        {"id": "X4", "name": "패독 횡단보도", "pos": [2600, 300], "rate_per_min": 3, "dart_prob": 0.05},
    ],
    "routes": {
        "race": {"name": "레이스", "loop": True, "kind": "city", "always": True, "label": "레이싱 카",
                 "accel": 7.0, "brake": 9.0, "a_lat": 12.0, "pts": TRACK},
        "commute": {"name": "호텔→운영 사무실 통근", "loop": True, "kind": "commute",
                    "pts": [[2800, 2850, "home"], [2000, 2850], [2000, 2500], [400, 2500], [400, 300], [1200, 300, "work"],
                            [3600, 300], [3600, 2850], [2800, 2850]]},
        "commute2": {"name": "스태프 숙소→사무실", "loop": True, "kind": "commute",
                     "pts": [[3600, 1500, "home"], [3600, 300], [1200, 300, "work"], [400, 300], [400, 2500], [3600, 2500],
                             [3600, 1500]]},
        "resident": {"name": "관람객 마을 주민", "loop": True, "kind": "resident",
                     "pts": [[2000, 2500], [3600, 2500], [3600, 2850], [2800, 2850, "home"], [2000, 2850], [2000, 2500]]},
        "visitor": {"name": "고속도로 통과", "loop": False, "kind": "visitor", "pts": [[0, 120], [4000, 120]]},
        "shuttle": {"name": "외곽 셔틀", "loop": True, "kind": "city", "always": True, "label": "셔틀",
                    "pts": [[400, 300], [3600, 300], [3600, 2500], [400, 2500], [400, 300]]},
    },
    "vehicle_routes": ["race", "race", "commute", "race", "resident", "race", "visitor", "commute2",
                       "race", "race", "commute", "race", "resident", "race", "visitor", "race"],
    "npc_routes": ["race", "race", "race", "race", "shuttle", "commute", "visitor", "resident", "race", "shuttle"],
    "landuse": [
        {"rect": [850, 650, 3150, 2150], "kind": "park", "density": 0.2},
        {"rect": [0, 330, 370, 2470], "kind": "park", "density": 0.5},
        {"rect": [3630, 330, 4000, 2470], "kind": "park", "density": 0.45},
        {"rect": [430, 2530, 3570, 2820], "kind": "residential", "density": 0.6},
        {"rect": [0, 2880, 4000, 3000], "kind": "residential", "density": 0.4},
        {"rect": [430, 150, 3570, 270], "kind": "industrial", "density": 0.5},
    ],
    "decor": [{"kind": "grandstand", "rect": [1100, 520, 2900, 548]}, {"kind": "grandstand", "rect": [1100, 2232, 1650, 2262]},
              {"kind": "grandstand", "rect": [2350, 2232, 2900, 2262]}, {"kind": "startline", "rect": [1196, 594, 1204, 606]}],
}, {(2000, 120): "고속도로 IC", (2000, 300): "서킷 정문", (2000, 2500): "마을 입구", (2000, 2850): "마을 광장"}))
