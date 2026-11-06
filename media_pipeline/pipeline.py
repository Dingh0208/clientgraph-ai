# -*- coding: utf-8 -*-
"""Unified media entry point: video audio-track ASR, PDF text/OCR, image OCR."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from audio_pipeline import PipelineConfig, build_provider

from .image_ops import process_image
from .ocr import RapidOCREngine
from .pdf_ops import process_pdf
from .video_ops import process_video

VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in VIDEO_EXT:
        return "video"
    if suffix in IMAGE_EXT:
        return "image"
    return "unsupported"


def process(path: str | Path, out_dir: str | Path, ocr_engine=None,
            asr_provider=None, audio_cfg: PipelineConfig | None = None) -> dict:
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    kind = _kind(path)

    result = {
        "schema": "clientgraph.media.run.v1",
        "source": {
            "name": path.name,
            "kind": kind,
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "sha256": _sha256(path) if path.exists() else None,
            "unchanged": None,
        },
        "status": "failed",
        "text": "",
        "blocks": [],
        "pages": [],
        "errors": [],
        "warnings": [],
        "stats": {"processing_ms": 0},
    }

    if not path.exists():
        result["errors"].append({
            "code": "E_INPUT_MISSING",
            "message": f"文件不存在：{path.name}",
            "hint": "确认路径后重试。",
            "recoverable": False,
        })
        return result

    if kind == "unsupported":
        result["errors"].append({
            "code": "E_UNSUPPORTED_MEDIA",
            "message": f"不支持的文件类型：{path.suffix or '无扩展名'}",
            "hint": "支持视频、PDF、常见图片格式。",
            "recoverable": False,
        })
        return result

    try:
        if kind == "video":
            provider = asr_provider or build_provider("mock", {})
            child = process_video(path, out_dir, provider, audio_cfg or PipelineConfig())
        else:
            engine = ocr_engine or RapidOCREngine()
            if kind == "pdf":
                child = process_pdf(path, out_dir, engine)
            else:
                child = process_image(path, engine)
    except Exception as exc:
        result["errors"].append({
            "code": "E_PROCESS_FAILED",
            "message": f"处理失败：{str(exc)[:300]}",
            "hint": "原始文件已保留；可重试或转为人工处理。",
            "recoverable": True,
        })
        result["source"]["unchanged"] = (_sha256(path) == result["source"]["sha256"])
        result["stats"] = {"processing_ms": int((time.perf_counter() - started) * 1000)}
        return result

    for key in ("status", "text", "blocks", "pages", "errors", "warnings"):
        result[key] = child.get(key, result[key])
    result["stats"] = {**child.get("stats", {}), "processing_ms": int((time.perf_counter() - started) * 1000)}
    if child.get("diarization"):
        result["diarization"] = child["diarization"]
    result["source"]["unchanged"] = (_sha256(path) == result["source"]["sha256"])
    if not result["source"]["unchanged"]:
        result["status"] = "failed"
        result["errors"].append({
            "code": "E_ORIGINAL_MODIFIED",
            "message": "原始文件在运行期间被修改",
            "hint": "停止写入该文件后重试。",
            "recoverable": False,
        })
    return result


def search(result: dict, query: str) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return []
    return [b for b in result.get("blocks") or [] if q in (b.get("text") or "").lower()]
