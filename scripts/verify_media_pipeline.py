# -*- coding: utf-8 -*-
"""Verify video/PDF/image media pipeline.

Run: python scripts/verify_media_pipeline.py
Requires: pymupdf, pillow, rapidocr-onnxruntime (installed under .temp/pylibs).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".temp" / "pylibs"))

import pymupdf  # noqa: E402
from PIL import Image, ImageDraw, ImageFont, ImageFilter  # noqa: E402

from audio_pipeline import PipelineConfig, MockASR, probe  # noqa: E402
from media_pipeline import OCREngineError, RapidOCREngine, process, search  # noqa: E402

TMP = ROOT / ".temp" / "media-verify"
EVIDENCE = ROOT / "evidence" / "media-pipeline-2026-11-06.json"
FONT = str(Path(os.environ["WINDIR"]) / "Fonts" / "msyh.ttc")


def sh(cmd: list[str], timeout: int = 300) -> None:
    cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or "").strip()[:500])


def draw(path: Path, size: tuple[int, int], lines: list[tuple[str, int]], rotate: float = 0.0):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    y = 60
    for text, size_px in lines:
        font = ImageFont.truetype(FONT, size_px)
        d.text((70, y), text, font=font, fill=(20, 20, 20))
        y += int(size_px * 1.9)
    if rotate:
        img = img.rotate(rotate, expand=True, fillcolor="white", resample=Image.BICUBIC)
    img.save(path)
    return path


def make_fixtures() -> dict:
    if TMP.exists():
        shutil.rmtree(TMP)
    src = TMP / "source"
    src.mkdir(parents=True)

    # 1) PDF with a real text layer (Chinese + English + numbers)
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((72, 100), "设备巡检报告", fontsize=26, fontname="msyh", fontfile=FONT)
    p1.insert_text((72, 145), "Inspection Report 2026", fontsize=18, fontname="msyh", fontfile=FONT)
    p2 = doc.new_page()
    p2.insert_text((72, 100), "报价单：100,000 元", fontsize=24, fontname="msyh", fontfile=FONT)
    p2.insert_text((72, 145), "Quotation: CNY 100,000", fontsize=18, fontname="msyh", fontfile=FONT)
    doc.save(src / "text_layer.pdf")
    doc.close()

    # 2) Skewed scanned page (image only)
    skew_img = src / "skew_page.png"
    draw(skew_img, (1240, 1754), [
        ("设备巡检记录", 54),
        ("Inspection Record 2026", 38),
        ("车间：一车间  设备：EQ-001", 34),
    ], rotate=2.5)
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, filename=str(skew_img))
    doc.save(src / "scan_skew.pdf")
    doc.close()

    # 3) Blank page
    doc = pymupdf.open()
    doc.new_page()
    doc.save(src / "scan_blank.pdf")
    doc.close()

    # 4) Low-resolution, heavily blurred image
    small = Image.new("RGB", (320, 200), "white")
    d = ImageDraw.Draw(small)
    f = ImageFont.truetype(FONT, 16)
    d.text((20, 40), "设备巡检报告", font=f, fill=(30, 30, 30))
    d.text((20, 90), "LOW RES 2026", font=f, fill=(30, 30, 30))
    small.filter(ImageFilter.GaussianBlur(3.0)).save(src / "lowres.png")

    # 5) Mixed Chinese/English image (clear)
    draw(src / "mixed.png", (1200, 520), [
        ("设备巡检报告", 64),
        ("Inspection Report 2026", 44),
    ])

    # 6) Scanned PDF with 2 pages, for OCR failure isolation
    page1 = src / "fail_page1.png"
    page2 = src / "fail_page2.png"
    draw(page1, (1240, 1754), [("第一页：可识别内容", 54), ("Page One", 38)])
    draw(page2, (1240, 1754), [("第二页：模拟识别失败", 54), ("Page Two", 38)])
    doc = pymupdf.open()
    for img in (page1, page2):
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, filename=str(img))
    doc.save(src / "ocr_fail.pdf")
    doc.close()

    # 7) Video with audio + video without audio
    sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=navy:s=640x360:d=6",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(src / "video_6s.mp4")])
    sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=gray:s=640x360:d=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
        str(src / "video_no_audio.mp4")])

    return {
        "dir": src,
        "text_pdf": src / "text_layer.pdf",
        "skew_pdf": src / "scan_skew.pdf",
        "blank_pdf": src / "scan_blank.pdf",
        "lowres": src / "lowres.png",
        "mixed": src / "mixed.png",
        "fail_pdf": src / "ocr_fail.pdf",
        "video": src / "video_6s.mp4",
        "video_no_audio": src / "video_no_audio.mp4",
    }


class CountingOCR(RapidOCREngine):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def recognize(self, image_path):
        self.calls += 1
        raise AssertionError("文本层页面不应调用 OCR")


class FailSecondPageOCR(RapidOCREngine):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def recognize(self, image_path):
        self.calls += 1
        if Path(image_path).name == "page_002.png":
            raise OCREngineError("模拟 OCR 引擎异常")
        return super().recognize(image_path)


def summarize(r: dict) -> dict:
    return {
        "status": r["status"],
        "kind": r["source"]["kind"],
        "text_chars": len(r.get("text") or ""),
        "blocks": len(r.get("blocks") or []),
        "pages": len(r.get("pages") or []),
        "errors": r.get("errors"),
        "warnings": r.get("warnings"),
        "stats": r.get("stats"),
        "source_unchanged": r.get("source", {}).get("unchanged"),
    }


def main() -> int:
    fx = make_fixtures()
    engine = RapidOCREngine()
    scenarios = []

    def record(name, result, checks, details=None):
        scenarios.append({
            "name": name,
            "summary": summarize(result),
            "checks": checks,
            "details": details or {},
            "passed": all(checks.values()),
        })

    def ensure(checks, key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    # S1: video -> audio track -> ASR
    checks, details = {}, {}
    r = process(fx["video"], TMP / "out-video",
                asr_provider=MockASR(delay_ms=2),
                audio_cfg=PipelineConfig(chunk_seconds=300, concurrency=2, timeout_s=5))
    blocks = r["blocks"]
    ensure(checks, "status_completed", r["status"] == "completed", r["status"])
    ensure(checks, "kind_video", r["source"]["kind"] == "video")
    ensure(checks, "has_audio", r["stats"]["has_audio"] is True)
    ensure(checks, "audio_16k_mono",
           r["stats"]["audio_sample_rate"] == 16000 and r["stats"]["audio_channels"] == 1)
    ensure(checks, "three_segments", len(blocks) == 3, len(blocks))
    ensure(checks, "segment_times_video", all(b["start_ms"] < b["end_ms"] for b in blocks))
    ensure(checks, "video_locator", all(b["locator"].startswith("video://") for b in blocks))
    ensure(checks, "no_frame_ocr", r["stats"]["frame_ocr"] is False)
    ensure(checks, "diarization_not_claimed", r.get("diarization", {}).get("supported") is False)
    ensure(checks, "source_unchanged", r["source"]["unchanged"] is True)
    audio_info = probe(TMP / "out-video" / "audio.wav")
    ensure(checks, "extracted_audio_valid",
           audio_info.sample_rate == 16000 and audio_info.channels == 1)
    ensure(checks, "search_finds_text", len(search(r, "设备巡检")) >= 1, len(search(r, "设备巡检")))
    details["block_times"] = [(b["start_ms"], b["end_ms"]) for b in blocks]
    record("视频只提取音轨转写", r, checks, details)

    # S2: PDF text layer first, no OCR calls
    checks = {}
    txt_engine = CountingOCR()
    r = process(fx["text_pdf"], TMP / "out-text", ocr_engine=txt_engine)
    ensure(checks, "status_completed", r["status"] == "completed", r["status"])
    ensure(checks, "two_text_pages", r["stats"]["text_layer_pages"] == 2,
           r["stats"]["text_layer_pages"])
    ensure(checks, "zero_ocr_pages", r["stats"]["ocr_pages"] == 0, r["stats"]["ocr_pages"])
    ensure(checks, "no_ocr_calls", txt_engine.calls == 0, txt_engine.calls)
    ensure(checks, "chinese_and_english",
           "设备巡检报告" in r["text"] and "Inspection Report 2026" in r["text"])
    ensure(checks, "page_numbers", sorted({b["page"] for b in r["blocks"]}) == [1, 2])
    ensure(checks, "bbox_present", all(len(b["bbox"]) == 4 for b in r["blocks"]))
    ensure(checks, "text_confidence_none", all(b["confidence"] is None for b in r["blocks"]))
    ensure(checks, "source_unchanged", r["source"]["unchanged"] is True)
    ensure(checks, "search_english", len(search(r, "Quotation")) >= 1)
    record("PDF 文本层优先（中英混排）", r, checks)

    # S3: skewed scan -> OCR, preserve page/bbox/image/confidence
    checks, details = {}, {}
    r = process(fx["skew_pdf"], TMP / "out-skew", ocr_engine=engine)
    blocks = r["blocks"]
    ensure(checks, "status_completed", r["status"] == "completed", r["status"])
    ensure(checks, "ocr_page", r["stats"]["ocr_pages"] == 1, r["stats"]["ocr_pages"])
    ensure(checks, "has_blocks", len(blocks) >= 1, len(blocks))
    ensure(checks, "page_number", all(b["page"] == 1 for b in blocks))
    ensure(checks, "confidence_present",
           all(isinstance(b["confidence"], float) and 0 <= b["confidence"] <= 1 for b in blocks))
    ensure(checks, "bbox_px_present", all(len(b.get("bbox_px", [])) == 4 for b in blocks))
    ensure(checks, "image_ref_exists",
           all((TMP / "out-skew" / b["source"]["image_ref"]).exists() for b in blocks))
    ensure(checks, "image_sha_recorded",
           all(len(b["source"].get("image_sha256", "")) == 64 for b in blocks))
    ensure(checks, "text_readable", ("巡检" in r["text"]) or ("Inspection" in r["text"]), r["text"][:100])
    ensure(checks, "no_text_layer_warning",
           any(w["code"] == "W_PDF_NO_TEXT_LAYER" for w in r["warnings"]))
    details["avg_confidence"] = r["stats"]["ocr_avg_confidence"]
    details["text"] = r["text"][:120]
    record("扫描件倾斜（2.5°）", r, checks, details)

    # S4: low-resolution image
    checks, details = {}, {}
    r = process(fx["lowres"], TMP / "out-lowres", ocr_engine=engine)
    warns = [w["code"] for w in r["warnings"]]
    ensure(checks, "status_completed", r["status"] == "completed", r["status"])
    ensure(checks, "low_quality_flagged",
           ("W_OCR_LOW_CONFIDENCE" in warns) or ("W_OCR_NO_TEXT" in warns), warns)
    ensure(checks, "no_crash", r["status"] != "failed")
    details["blocks"] = len(r["blocks"])
    details["avg_confidence"] = r["stats"]["ocr_avg_confidence"]
    record("低清图片", r, checks, details)

    # S5: blank page, no OCR
    checks = {}
    blank_engine = CountingOCR()
    r = process(fx["blank_pdf"], TMP / "out-blank", ocr_engine=blank_engine)
    ensure(checks, "status_completed", r["status"] == "completed", r["status"])
    ensure(checks, "blank_page", r["stats"]["empty_pages"] == 1, r["stats"]["empty_pages"])
    ensure(checks, "no_blocks", len(r["blocks"]) == 0, len(r["blocks"]))
    ensure(checks, "no_ocr_calls", blank_engine.calls == 0, blank_engine.calls)
    ensure(checks, "empty_warning", any(w["code"] == "W_EMPTY_PAGE" for w in r["warnings"]))
    ensure(checks, "empty_searchable_text", r["text"] == "")
    record("空白页", r, checks)

    # S6: mixed Chinese/English OCR image
    checks, details = {}, {}
    r = process(fx["mixed"], TMP / "out-mixed", ocr_engine=engine)
    ensure(checks, "status_completed", r["status"] == "completed", r["status"])
    ensure(checks, "has_blocks", len(r["blocks"]) >= 1, len(r["blocks"]))
    ensure(checks, "chinese_present", bool(re.search(r"[\u4e00-\u9fa5]", r["text"])), r["text"][:80])
    ensure(checks, "english_present", bool(re.search(r"[A-Za-z]", r["text"])), r["text"][:80])
    ensure(checks, "confidence_present",
           all(isinstance(b["confidence"], float) for b in r["blocks"]))
    details["avg_confidence"] = r["stats"]["ocr_avg_confidence"]
    record("混合中英文 OCR", r, checks, details)

    # S7: OCR failure on page 2, page 1 preserved
    checks, details = {}, {}
    fail_engine = FailSecondPageOCR()
    r = process(fx["fail_pdf"], TMP / "out-fail", ocr_engine=fail_engine)
    ensure(checks, "status_partial", r["status"] == "partial", r["status"])
    ensure(checks, "one_error", len(r["errors"]) == 1, r["errors"])
    ensure(checks, "ocr_failed_code", r["errors"][0]["code"] == "E_OCR_FAILED", r["errors"][0])
    ensure(checks, "error_page_2", r["errors"][0].get("page") == 2, r["errors"][0].get("page"))
    ensure(checks, "error_explained",
           ("模拟 OCR 引擎异常" in r["errors"][0]["message"]) and bool(r["errors"][0].get("hint")))
    ensure(checks, "page1_kept", any(b["page"] == 1 for b in r["blocks"]))
    ensure(checks, "page2_no_blocks", not any(b["page"] == 2 for b in r["blocks"]))
    ensure(checks, "partial_warning", any(w["code"] == "W_PARTIAL" for w in r["warnings"]))
    details["error"] = r["errors"][0]
    record("OCR 失败隔离", r, checks, details)

    # S8: video without audio
    checks = {}
    r = process(fx["video_no_audio"], TMP / "out-noaudio",
                asr_provider=MockASR(delay_ms=1),
                audio_cfg=PipelineConfig(chunk_seconds=300, concurrency=2))
    ensure(checks, "status_failed", r["status"] == "failed", r["status"])
    ensure(checks, "no_audio_code", r["errors"][0]["code"] == "E_VIDEO_NO_AUDIO", r["errors"][0])
    ensure(checks, "no_blocks", len(r["blocks"]) == 0)
    ensure(checks, "has_audio_false", r["stats"]["has_audio"] is False)
    record("视频无音轨", r, checks)

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "pymupdf": pymupdf.__version__,
            "ocr_engine": engine.info().name,
            "ocr_version": engine.info().version,
            "platform": sys.platform,
        },
        "fixtures": {k: {"name": v.name, "size": v.stat().st_size} for k, v in fx.items() if k != "dir"},
        "scenarios": scenarios,
        "all_passed": all(s["passed"] for s in scenarios),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    for s in scenarios:
        print(("PASS " if s["passed"] else "FAIL ") + s["name"] +
              f" | status={s['summary']['status']} blocks={s['summary']['blocks']} "
              f"pages={s['summary']['pages']}")
        for k, v in s["checks"].items():
            if not v:
                print("   failed check:", k)
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)

