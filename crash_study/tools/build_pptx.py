#!/usr/bin/env python3
"""crash_study 결과로 PPT 초안(16:9)을 만든다.

실행: pip install python-pptx && python build_pptx.py
입력: ../figures/*.png, ../figures/summary_table.csv, ../docs_screenshots/*.png
출력: ../SASAFL_crash_report_draft.pptx
"""

import csv
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Inches, Pt

STUDY = Path(__file__).resolve().parents[1]
FIGS = STUDY / "figures"
SHOTS = STUDY / "docs_screenshots"
OUT = STUDY / "SASAFL_crash_report_draft.pptx"

INK = RGBColor(0x0B, 0x0B, 0x0B)
INK_2 = RGBColor(0x52, 0x51, 0x4E)
ACCENT = RGBColor(0xD0, 0x3B, 0x3B)
FONT = "NanumGothic"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
W, H = prs.slide_width, prs.slide_height
MARGIN = Inches(0.5)


def text_box(slide, x, y, w, h, lines, size=18, color=INK, bold_first=False):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    for i, line in enumerate(lines):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        bold = False
        if isinstance(line, tuple):
            line, bold = line
        run = para.add_run()
        run.text = line
        run.font.size = Pt(size)
        run.font.name = FONT
        run.font.bold = bold or (bold_first and i == 0)
        run.font.color.rgb = ACCENT if line.startswith("→") else color
        para.space_after = Pt(6)
    return box


def title(slide, text, sub=None):
    text_box(slide, MARGIN, Inches(0.3), W - 2 * MARGIN, Inches(0.8), [(text, True)], size=28)
    if sub:
        text_box(slide, MARGIN, Inches(0.95), W - 2 * MARGIN, Inches(0.5), [sub], size=14, color=INK_2)


def picture(slide, path, x, y, max_w, max_h):
    with Image.open(path) as img:
        iw, ih = img.size
    scale = min(max_w / iw, max_h / ih)
    w, h = int(iw * scale), int(ih * scale)
    slide.shapes.add_picture(str(path), x + (max_w - w) // 2, y + (max_h - h) // 2, Emu(w), Emu(h))


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def figure_slide(head, sub, fig, note, bullets=None):
    slide = prs.slides.add_slide(BLANK)
    title(slide, head, sub)
    top = Inches(1.45)
    if bullets:
        picture(slide, fig, MARGIN, top, int(W * 0.66), H - top - Inches(0.3))
        text_box(slide, int(W * 0.69), top, int(W * 0.29), H - top - Inches(0.3), bullets, size=15)
    else:
        picture(slide, fig, MARGIN, top, W - 2 * MARGIN, H - top - Inches(0.3))
    notes(slide, note)
    return slide


def table_slide(head, sub, header, rows, col_w, size=12):
    slide = prs.slides.add_slide(BLANK)
    title(slide, head, sub)
    top = Inches(1.5)
    shape = slide.shapes.add_table(len(rows) + 1, len(header), MARGIN, top, W - 2 * MARGIN,
                                   Inches(0.4) * (len(rows) + 1))
    table = shape.table
    for j, wdt in enumerate(col_w):
        table.columns[j].width = Inches(wdt)
    for j, h in enumerate(header):
        cell = table.cell(0, j)
        cell.text = h
    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row):
            table.cell(i, j).text = str(val)
    for i in range(len(rows) + 1):
        for j in range(len(header)):
            for para in table.cell(i, j).text_frame.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(size)
                    run.font.name = FONT
                    run.font.bold = i == 0
    return slide


# 1. 표지
slide = prs.slides.add_slide(BLANK)
text_box(slide, MARGIN, Inches(2.2), W - 2 * MARGIN, Inches(1.5),
         [("SASAFL은 차량 crash를 견딜 수 있는가?", True)], size=40)
text_box(slide, MARGIN, Inches(3.4), W - 2 * MARGIN, Inches(1.5),
         ["torchrun/gloo testbed 장애 주입 실험 · 코드 수준 증명 · 시뮬레이션 · 프레임워크 조사",
          "차량용 연합학습 클라우드 (Jetson AGX Orin 32GB 클라이언트) 설계 검토"], size=20, color=INK_2)

# 2. 문제 정의
slide = prs.slides.add_slide(BLANK)
title(slide, "문제 정의", "차량 FL에서는 연결 끊김(crashed client)이 일상이다")
text_box(slide, MARGIN, Inches(1.6), W - 2 * MARGIN, Inches(5.5), [
    "• 차량 클라이언트: 시동 OFF, 터널·음영 지역, 핸드오버 → 수시로 이탈·복귀",
    "• SASAFL 논문(Yu et al., JPDC 2024) 스스로 명시:",
    "   \"Unlike SASAFL, SAFA considers crashed clients\" (p.8)",
    "• SASAFL의 quota: P_min = C·K (최소 참여 수), P_r = Eq.(1)로 loss 변화에 따라 증감, 상한 K",
    "• 질문 1) 현재 testbed(torch.distributed + torchrun)는 차량 1대 장애에 어떻게 반응하는가?",
    "• 질문 2) 알고리즘 자체에 '살아있는 차량 수 < P_r'에 대한 규칙이 있는가?",
    ("→ 결론: 둘 다 없다. 코드 수정은 임시방편이며 알고리즘·통신 구조 모두 crash-aware여야 한다", True),
], size=20)
notes(slide, "논문 인용은 paper/ 폴더의 PDF 8쪽, Table 1 설명 문단.")

# 3. 실험 설계
table_slide("실험 설계", "원본 코드 무수정 · 계측 진입점(harness)과 외부 장애 주입만 사용",
            ["ID", "종류", "설정", "검증하려는 것"],
            [["E0", "실측", "K=10, C=0.3, 30라운드, 장애 없음", "기준선 · P_r 실측 궤적"],
             ["E1", "실측", "5라운드에 차량 1대 SIGKILL", "hard crash 시 job 전체 영향"],
             ["E1b", "실측", "E1 + torchrun --max_restarts=3", "재시작이 복구가 되는가"],
             ["E2a", "실측", "5라운드에 차량 1대 SIGSTOP", "silent drop(음영) 시 서버 동작"],
             ["E2b", "실측", "K=10, C=0.5(P_min=5), 6대 SIGSTOP", "생존 4대 < P_min 5"],
             ["E2c", "실측", "E2a + gloo timeout 90초", "timeout 이후 복구되는가"],
             ["E3", "코드", "SASAFLServer 메서드 직접 호출", "대기 함수·quota 함수의 crash 비고려"],
             ["E4", "시뮬레이션", "K=100, 실측 loss, 마르코프 연결 모델 2000회", "끊김률 vs 교착 확률"]],
            [0.8, 1.3, 5.0, 5.2], size=13)

# 4~5. 공식 문서 근거
slide = prs.slides.add_slide(BLANK)
title(slide, "공식 문서 근거 ① torchrun의 실패 semantics", "PyTorch 1.12 (testbed 버전) 공식 문서")
picture(slide, SHOTS / "01_torchrun_failure_modes_v1.12.png", MARGIN, Inches(1.4), W - 2 * MARGIN, Inches(2.95))
picture(slide, SHOTS / "02_torchrun_all_surviving_killed_v1.12.png", MARGIN, Inches(4.4), W - 2 * MARGIN, Inches(2.95))
notes(slide, "k<=n개 worker가 실패하면 모든 worker를 중지하고 재시작. max_restarts 기본값은 0(torch/distributed/run.py).")
slide = prs.slides.add_slide(BLANK)
title(slide, "공식 문서 근거 ② timeout과 fault tolerance의 현주소", "gloo 기본 30분 · peer 재구성 API는 최신 버전에서도 experimental")
picture(slide, SHOTS / "03_gloo_timeout_30min_v1.12.png", MARGIN, Inches(1.4), W - 2 * MARGIN, Inches(2.95))
picture(slide, SHOTS / "07_reconfigure_experimental_stable.png", MARGIN, Inches(4.4), W - 2 * MARGIN, Inches(2.95))

# 6~11. 결과 그림
figure_slide("장애 전파 경로", "hard crash와 silent drop 모두 testbed 전체 정지로 이어진다",
             FIGS / "fig6_failure_propagation.png", "각 상자는 E1/E2 로그와 서버 스택 덤프로 확인한 경로.")
figure_slide("실험 결과 ① 장애 주입 타임라인", "K=10, 차량 1대 장애로 전체 학습이 멈추거나 종료",
             FIGS / "fig1_fault_timeline.png", "세부 수치는 figures/summary_table.md.")
with (FIGS / "summary_table.csv").open() as f:
    summary = list(csv.DictReader(f))
table_slide("실측 결과 요약", "K=10 단일 노드 · 정지 시간 = 마지막 라운드 이후 관측 종료까지",
            ["시나리오", "완료 라운드", "결과", "정지(초)", "종료 시 서버 위치"],
            [[r["description"], r["rounds_completed"], r["outcome"], r["sec_without_progress_at_end"] or "-",
              (r["server_stack_at_end"].split(" / [main] ")[-1] if r["server_stack_at_end"] else "예외로 종료 / 정상")]
             for r in summary],
            [3.6, 1.2, 2.6, 1.0, 3.9], size=11)
figure_slide("실험 결과 ② 정지 구간의 서버 상태", "라운드 진행 0 · 서버 스택은 send 또는 대기 루프",
             FIGS / "fig2_server_state_during_stall.png", "SIGUSR1로 받은 서버 스레드 스택(faulthandler).")
figure_slide("실험 결과 ③ 장애가 없어도 P_r = K", "E0 실측 — K에 도달한 라운드에 1대만 빠져도 영구 대기",
             FIGS / "fig3_e0_measured_quota.png", "E1b의 24라운드 정지가 실제 사례.")
figure_slide("코드 수준 증명", "대기 함수에 timeout·생존 확인 없음 / quota 함수에 연결 상태 입력 없음",
             FIGS / "fig4_code_level_proof.png", "experiments/code_level_proof.py")
figure_slide("시뮬레이션: 차량 끊김률과 교착", "정상상태 연결 비율 p_back/(p_back+p_drop)이 C 아래면 SASAFL 정지",
             FIGS / "fig5_simulation_deadlock_probability.png",
             "P_r은 실제 SASAFL 코드 + 커밋된 K=100 실행의 실측 loss로 계산. 연결 모델은 sweep 변수(실측 아님). "
             "연결된 차량은 매 라운드 업로드한다는 SASAFL에 유리한 가정.")

# 12. 결론
slide = prs.slides.add_slide(BLANK)
title(slide, "결론", "코드 패치는 임시방편 — 알고리즘과 통신 구조 모두 crash-aware여야 한다")
text_box(slide, MARGIN, Inches(1.6), W - 2 * MARGIN, Inches(5.5), [
    "• 통신 계층: torchrun은 1대 실패 시 전체 worker 종료(gang), gloo p2p는 재접속 불가, timeout 기본 30분",
    "• 애플리케이션: 서버가 매 라운드 전체 차량에 blocking send, 예외 처리 없음",
    "• 알고리즘: P_r(Eq.1)은 loss만 보고 K까지 증가, 대기 조건 len(B) ≥ P_r에 생존 차량 수가 없음",
    "• 재시작(max_restarts)은 복구가 아님: 라운드 0부터 다시 시작, 끊긴 실제 차량은 서버가 재기동할 수 없음",
    ("→ 필요한 것: heartbeat 기반 생존 판정 + 유예시간, pull 기반 재접속, P_eff=min(P_r, alive) + deadline, 서버 상태 영속화", True),
    ("→ 후보: NVIDIA FLARE Edge(FedBuff, Jetson 지원, dead client 정책) 위에 SASAFL 아이디어 이식", True),
], size=19)

# 13. 프레임워크 비교
table_slide("오픈소스 프레임워크의 dead client 처리", "소스 코드 확인 기준 (2026-10-10)",
            ["프레임워크", "감지", "감지 후 동작"],
            [["NVIDIA FLARE", "heartbeat + dead job report, 유예 60초", "작업 CLIENT_DEAD 종료, alive<min_sites면 중단, 재접속 이벤트"],
             ["Flower", "SuperNode heartbeat 30초 × patience 2", "offline 노드 메시지에 NODE_UNAVAILABLE 응답, accept_failures"],
             ["FEDn", "클라이언트→combiner heartbeat", "(서버 측 미확인)"],
             ["FedML", "MQTT keepalive + Last-Will", "active list에서 제거, 단 cross-silo 집계는 전원 대기"],
             ["Fed-BioMed", "gRPC 작업 요청 스트림 상태", "DiscardOnTimeout / StopOnDisconnect 정책"],
             ["OpenFL", "없음", "CutoffTime / Percentage straggler 정책"],
             ["torchrun+gloo", "없음 (연산 timeout 30분)", "전체 worker 종료·재시작"]],
            [2.2, 4.3, 5.8], size=13)

# 14. FLARE × Jetson
slide = prs.slides.add_slide(BLANK)
title(slide, "NVIDIA FLARE × Jetson AGX Orin 32GB", "상세: RESEARCH_FLARE_JETSON_HEARTBEAT.md")
text_box(slide, MARGIN, Inches(1.6), W - 2 * MARGIN, Inches(5.5), [
    "• Orin 32GB: Ampere 1792 CUDA / 56 Tensor 코어, 8코어 A78AE, 32GB LPDDR5(공유), 200 TOPS, 15–40W",
    "• FLARE 2.7+ Edge: 계층형(서버→relay→leaf→기기), FedBuff 비동기, HTTP pull 프로토콜(EDIP)",
    "• 문서 명시: 'Edge Device Training (Jetson / GPU)', EdgeFedBuffRecipe 'e.g., NVIDIA Jetson devices'",
    "• NVIDIA AV 운영 사례: 5–10분 단절로 서버 무기한 대기 → FLARE에 복구·재개 기능 추가 (NVIDIA blog 2024-10)",
    "• 주의: FLARE는 Python ≥ 3.10 → JetPack 6 필요 / PyTorch 엣지 예제는 기기 시뮬레이션 →",
    "   실기기는 PTRunner + FegApi(HTTP)로 직접 연동 / SimEnv 미지원(ProdEnv provisioning 필요)",
], size=19)

# 15. 재현 방법
slide = prs.slides.add_slide(BLANK)
title(slide, "재현 방법", "crash_study/README.md")
text_box(slide, MARGIN, Inches(1.6), W - 2 * MARGIN, Inches(5.5), [
    "python crash_study/experiments/run_experiment.py all",
    "python crash_study/experiments/code_level_proof.py",
    "python crash_study/experiments/simulate_quota.py",
    "python crash_study/analysis/make_figures.py",
    "python crash_study/tools/capture_docs.py crash_study/docs_screenshots   (playwright 필요)",
    "python crash_study/tools/build_pptx.py   (python-pptx 필요)",
], size=18)

prs.save(OUT)
print(f"[+] {OUT}")
