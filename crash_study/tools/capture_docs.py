#!/usr/bin/env python3
"""PyTorch 공식 문서의 crash/timeout 관련 문단을 캡처한다.

노란 배경 강조와 하단 캡션(URL, 캡처 시각)은 이 스크립트가 덧붙인 표시이며 원문에는 없다.
실행: pip install playwright pillow && playwright install chromium
      python capture_docs.py <출력 디렉터리>
"""

import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

FONT = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"

# (파일명, URL, 강조할 문장 일부, 캡션 설명)
TARGETS = [
    ("01_torchrun_failure_modes_v1.12.png",
     "https://docs.pytorch.org/docs/1.12/elastic/run.html",
     "if k<=n workers fail all workers are stopped",
     "torchrun(1.12): worker k개(k≤n)가 실패하면 모든 worker를 중지·재시작 (max_restarts 기본값 0 → 즉시 job 실패)"),
    ("02_torchrun_all_surviving_killed_v1.12.png",
     "https://docs.pytorch.org/docs/1.12/elastic/run.html",
     "ALL surviving workers are killed immediately",
     "torchrun(1.12): 실패 또는 membership 변경 시 살아있는 worker도 전부 즉시 kill"),
    ("03_gloo_timeout_30min_v1.12.png",
     "https://docs.pytorch.org/docs/1.12/distributed.html",
     "Default value equals 30 minutes. This is applicable for the gloo backend",
     "init_process_group(1.12): gloo 연산 timeout 기본 30분 (응답 없는 rank를 30분간 기다림)"),
    ("04_irecv_any_source_v1.12.png",
     "https://docs.pytorch.org/docs/1.12/distributed.html",
     "Receives a tensor asynchronously",
     "irecv(1.12): src 미지정 시 아무 rank에서나 수신 — SASAFL 서버 listening thread가 사용하는 방식"),
    ("05_monitored_barrier_v1.12.png",
     "https://docs.pytorch.org/docs/1.12/distributed.html",
     "As of v1.10, torch.distributed.monitored_barrier() exists",
     "monitored_barrier(1.12): 실패 rank를 '보고'만 함 — 복구·제외 기능 아님"),
    ("06_torchrun_failure_modes_stable.png",
     "https://docs.pytorch.org/docs/stable/elastic/run.html",
     "if k<=n workers fail all workers are stopped",
     "torchrun(최신 stable): 동일한 gang 실패 semantics 유지"),
    ("07_reconfigure_experimental_stable.png",
     "https://docs.pytorch.org/docs/stable/distributed.html",
     "Reconfigure group with a new set of peers for fault tolerance",
     "torch.distributed(최신 stable): peer 재구성 기반 fault tolerance API는 아직 experimental"),
]

HIGHLIGHT_JS = """
(snippet) => {
  // snippet을 포함하는 가장 깊은 블록 요소를 찾는다
  const all = Array.from(document.querySelectorAll('p, dd, li, dt, div.highlight, td'));
  let best = null;
  for (const el of all) {
    if (el.innerText && el.innerText.includes(snippet)) {
      if (!best || best.contains(el)) best = el;
    }
  }
  if (!best) return null;
  best.style.background = '#fff3a3';
  best.style.outline = '3px solid #e0a800';
  best.scrollIntoView({block: 'center'});
  const r = best.getBoundingClientRect();
  return {x: r.left + window.scrollX, y: r.top + window.scrollY, w: r.width, h: r.height};
}
"""


def add_caption(path, url, desc):
    img = Image.open(path).convert("RGB")
    font = ImageFont.truetype(FONT, 22)
    small = ImageFont.truetype(FONT, 17)
    bar_h = 78
    out = Image.new("RGB", (img.width, img.height + bar_h), "white")
    out.paste(img, (0, 0))
    draw = ImageDraw.Draw(out)
    draw.rectangle([0, img.height, img.width, img.height + bar_h], fill="#1f2937")
    draw.text((16, img.height + 10), desc, fill="white", font=font)
    stamp = time.strftime("%Y-%m-%d")
    draw.text((16, img.height + 46),
              f"출처: {url}  (캡처 {stamp}, 노란 강조는 작성자 표시)", fill="#cbd5e1", font=small)
    out.save(path)


def main(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1.5)
        for name, url, snippet, desc in TARGETS:
            page.goto(url, wait_until="networkidle", timeout=120000)
            box = page.evaluate(HIGHLIGHT_JS, snippet)
            if box is None:
                print(f"[!] 문장을 찾지 못함: {name}")
                continue
            page.wait_for_timeout(500)
            margin = 160
            clip = {
                "x": 0,
                "y": max(box["y"] - margin, 0),
                "width": 1280,
                "height": min(box["h"] + 2 * margin, 1400),
            }
            path = out_dir / name
            page.screenshot(path=str(path), full_page=True, clip=clip)
            add_caption(path, url, desc)
            print(f"[+] {path}")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs_screenshots")
