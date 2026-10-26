#!/usr/bin/env python3
"""시뮬레이션 맵 4종을 만든다. 모든 맵은 34개 유스케이스를 일으킬 장소·구역을 갖춘다 (common.map_coverage로 검사).

  python vehicle_sim/maps/make_maps.py      → maps/{default,highway,port,newtown}.json

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
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "simcore"))
from common import map_coverage, map_problems  # noqa: E402
VR = ["commute", "city", "resident", "visitor", "commute", "city", "resident", "visitor",
      "city", "commute", "resident", "city", "commute", "visitor", "city", "resident"]


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
