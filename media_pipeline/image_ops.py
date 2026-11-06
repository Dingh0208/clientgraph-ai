# -*- coding: utf-8 -*-
"""Image OCR: one image, bbox + confidence + original reference."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from .ocr import OCREngineError, average_confidence

LOW_CONFIDENCE = 0.6


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_blank(path: Path) -> bool:
    with Image.open(path) as img:
        gray = img.convert("L").resize((200, 200))
        pixels = list(gray.getdata())
    light = sum(1 for p in pixels if p >= 245)
    return light / len(pixels) >= 0.999


def process_image(path: str | Path, engine) -> dict:
    path = Path(path)
    result = {
        "status": "failed",
        "pages": [],
        "blocks": [],
        "errors": [],
        "warnings": [],
        "text": "",
        "stats": {
            "page_count": 1,
            "text_layer_pages": 0,
            "ocr_pages": 0,
            "empty_pages": 0,
            "failed_pages": 0,
            "block_count": 0,
            "ocr_avg_confidence": None,
        },
    }

    try:
        with Image.open(path) as img:
            width, height = img.size
            img.verify()
    except Exception as exc:
        result["errors"].append({
            "code": "E_IMAGE_OPEN_FAILED",
            "message": f"图片无法打开：{str(exc)[:200]}",
            "hint": "确认图片未损坏；原文件已保留。",
            "recoverable": False,
        })
        return result

    page_info = {
        "page": None,
        "method": "ocr",
        "char_count": 0,
        "block_count": 0,
        "ocr_confidence": None,
        "image_ref": path.name,
        "image_sha256": _sha256(path),
        "width_px": width,
        "height_px": height,
        "blank": False,
    }

    if _is_blank(path):
        page_info["method"] = "empty"
        page_info["blank"] = True
        result["stats"]["empty_pages"] = 1
        result["warnings"].append({
            "code": "W_EMPTY_PAGE",
            "message": "图片为空白页，未识别到文字",
        })
        result["status"] = "completed"
        result["pages"].append(page_info)
        return result

    try:
        lines = engine.recognize(path)
    except OCREngineError as exc:
        result["errors"].append({
            "code": "E_OCR_FAILED",
            "message": f"图片 OCR 失败：{exc.message}",
            "hint": "可提高分辨率、纠正倾斜后重试；原图已保留。",
            "recoverable": True,
        })
        page_info["method"] = "failed"
        result["stats"]["failed_pages"] = 1
        result["pages"].append(page_info)
        return result

    blocks: list[dict] = []
    for n, line in enumerate(lines):
        x0, y0, x1, y1 = line["bbox"]
        bbox = [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)]
        blocks.append({
            "id": f"img_b{n:03d}",
            "type": "ocr",
            "text": line["text"],
            "page": None,
            "bbox": bbox,
            "bbox_px": bbox,
            "confidence": round(float(line["confidence"]), 4),
            "locator": f"img://{path.name}#bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
            "source": {
                "file": path.name,
                "kind": "image",
                "page": None,
                "method": "ocr",
                "image_ref": path.name,
                "image_sha256": page_info["image_sha256"],
            },
        })

    avg = average_confidence(lines)
    page_info["method"] = "ocr" if blocks else "ocr_empty"
    page_info["block_count"] = len(blocks)
    page_info["ocr_confidence"] = avg
    page_info["char_count"] = sum(len(b["text"]) for b in blocks)
    result["blocks"] = blocks
    result["stats"]["ocr_pages"] = 1
    result["stats"]["block_count"] = len(blocks)
    result["stats"]["ocr_avg_confidence"] = avg
    result["text"] = "\n".join(b["text"] for b in blocks)

    if not blocks:
        result["warnings"].append({
            "code": "W_OCR_NO_TEXT",
            "message": "OCR 未识别到文字，原图已保留",
        })
    elif avg is not None and avg < LOW_CONFIDENCE:
        result["warnings"].append({
            "code": "W_OCR_LOW_CONFIDENCE",
            "message": f"OCR 平均置信度 {avg:.2f}，建议核对",
            "confidence": avg,
        })

    result["pages"].append(page_info)
    result["status"] = "completed"
    return result
