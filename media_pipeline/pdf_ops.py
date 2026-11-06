# -*- coding: utf-8 -*-
"""PDF processing: text layer first, scanned pages rendered and OCR'd."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pymupdf

from .ocr import OCREngineError, average_confidence


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_blank(pix) -> bool:
    """A page is blank when almost every pixel is near-white."""
    samples = pix.samples
    step = pix.n
    total = pix.width * pix.height
    if total <= 0:
        return True
    light = 0
    # Sample every 4th pixel for speed; still stable for blank detection.
    for i in range(0, len(samples), step * 4):
        if samples[i] >= 245:
            light += 1
    sampled = len(range(0, len(samples), step * 4))
    return sampled > 0 and (light / sampled) >= 0.999


def _text_blocks(page, page_no: int, file_name: str) -> list[dict]:
    blocks: list[dict] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            text = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
            if not text:
                continue
            bbox = [round(float(v), 2) for v in line.get("bbox", [0, 0, 0, 0])]
            blocks.append({
                "id": f"p{page_no:03d}b{len(blocks):03d}",
                "type": "text",
                "text": text,
                "page": page_no,
                "bbox": bbox,
                "confidence": None,
                "locator": f"pdf://{file_name}#page={page_no}&bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",
                "source": {
                    "file": file_name,
                    "kind": "pdf",
                    "page": page_no,
                    "method": "text",
                    "image_ref": None,
                },
            })
    # Reading order inside a page: top-to-bottom, then left-to-right.
    blocks.sort(key=lambda b: (round(b["bbox"][1] / 4), b["bbox"][0]))
    return blocks


def process_pdf(path: str | Path, out_dir: str | Path, engine,
                min_text_chars: int = 20, dpi: int = 200) -> dict:
    path = Path(path)
    out_dir = Path(out_dir)
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "status": "failed",
        "pages": [],
        "blocks": [],
        "errors": [],
        "warnings": [],
        "text": "",
        "stats": {
            "page_count": 0,
            "text_layer_pages": 0,
            "ocr_pages": 0,
            "empty_pages": 0,
            "failed_pages": 0,
            "block_count": 0,
            "ocr_avg_confidence": None,
        },
    }

    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        result["errors"].append({
            "code": "E_PDF_OPEN_FAILED",
            "message": f"PDF 无法打开：{str(exc)[:200]}",
            "hint": "确认文件未损坏；原文件已保留。",
            "recoverable": False,
        })
        return result

    if doc.needs_pass:
        result["errors"].append({
            "code": "E_PDF_ENCRYPTED",
            "message": "PDF 已加密，无法读取页面",
            "hint": "提供密码后重新导入。",
            "recoverable": True,
        })
        doc.close()
        return result

    page_texts: list[str] = []
    confidences: list[float] = []

    for index in range(doc.page_count):
        page_no = index + 1
        page = doc.load_page(index)
        raw_text = page.get_text("text").strip()
        page_info = {
            "page": page_no,
            "method": "text",
            "char_count": len(raw_text),
            "block_count": 0,
            "ocr_confidence": None,
            "image_ref": None,
            "image_sha256": None,
            "width_pt": round(page.rect.width, 2),
            "height_pt": round(page.rect.height, 2),
            "blank": False,
        }

        if len(raw_text) >= min_text_chars:
            blocks = _text_blocks(page, page_no, path.name)
            result["blocks"].extend(blocks)
            page_info["block_count"] = len(blocks)
            result["stats"]["text_layer_pages"] += 1
            page_texts.append("\n".join(b["text"] for b in blocks))
            result["pages"].append(page_info)
            continue

        # No usable text layer: render the page and try OCR.
        image_name = f"page_{page_no:03d}.png"
        image_path = image_dir / image_name
        try:
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
            pix.save(str(image_path))
        except Exception as exc:
            result["errors"].append({
                "code": "E_PAGE_RENDER_FAILED",
                "message": f"第 {page_no} 页渲染失败：{str(exc)[:200]}",
                "page": page_no,
                "hint": "原 PDF 已保留，可尝试降低渲染 DPI 或修复页面。",
                "recoverable": True,
            })
            page_info["method"] = "failed"
            result["stats"]["failed_pages"] += 1
            result["pages"].append(page_info)
            continue

        image_sha = _sha256(image_path)
        page_info["image_ref"] = f"images/{image_name}"
        page_info["image_sha256"] = image_sha

        if _is_blank(pix):
            page_info["method"] = "empty"
            page_info["blank"] = True
            result["stats"]["empty_pages"] += 1
            result["warnings"].append({
                "code": "W_EMPTY_PAGE",
                "message": f"第 {page_no} 页为空白页，未识别到文字",
                "page": page_no,
            })
            result["pages"].append(page_info)
            continue

        result["warnings"].append({
            "code": "W_PDF_NO_TEXT_LAYER",
            "message": f"第 {page_no} 页无可用文本层，已转 OCR",
            "page": page_no,
        })

        try:
            lines = engine.recognize(image_path)
        except OCREngineError as exc:
            result["errors"].append({
                "code": "E_OCR_FAILED",
                "message": f"第 {page_no} 页 OCR 失败：{exc.message}",
                "page": page_no,
                "hint": "可提高扫描分辨率、纠正倾斜后重试；原图已保留。",
                "recoverable": True,
            })
            page_info["method"] = "failed"
            result["stats"]["failed_pages"] += 1
            result["pages"].append(page_info)
            continue

        page_blocks: list[dict] = []
        scale = 72.0 / dpi
        for n, line in enumerate(lines):
            x0, y0, x1, y1 = line["bbox"]
            bbox_pt = [round(x0 * scale, 2), round(y0 * scale, 2),
                       round(x1 * scale, 2), round(y1 * scale, 2)]
            page_blocks.append({
                "id": f"p{page_no:03d}o{n:03d}",
                "type": "ocr",
                "text": line["text"],
                "page": page_no,
                "bbox": bbox_pt,
                "bbox_px": [round(v, 2) for v in line["bbox"]],
                "confidence": round(float(line["confidence"]), 4),
                "locator": (f"pdf://{path.name}#page={page_no}"
                            f"&bbox={bbox_pt[0]},{bbox_pt[1]},{bbox_pt[2]},{bbox_pt[3]}&ocr=1"),
                "source": {
                    "file": path.name,
                    "kind": "pdf",
                    "page": page_no,
                    "method": "ocr",
                    "image_ref": page_info["image_ref"],
                    "image_sha256": image_sha,
                },
            })

        avg = average_confidence(lines)
        page_info["method"] = "ocr" if page_blocks else "ocr_empty"
        page_info["block_count"] = len(page_blocks)
        page_info["ocr_confidence"] = avg
        result["stats"]["ocr_pages"] += 1
        result["blocks"].extend(page_blocks)

        if not page_blocks:
            result["warnings"].append({
                "code": "W_OCR_NO_TEXT",
                "message": f"第 {page_no} 页 OCR 未识别到文字",
                "page": page_no,
            })
        else:
            confidences.append(avg or 0.0)
            if avg is not None and avg < 0.6:
                result["warnings"].append({
                    "code": "W_OCR_LOW_CONFIDENCE",
                    "message": f"第 {page_no} 页 OCR 平均置信度 {avg:.2f}，建议核对",
                    "page": page_no,
                    "confidence": avg,
                })

        page_texts.append("\n".join(b["text"] for b in page_blocks))
        result["pages"].append(page_info)

    doc.close()

    result["text"] = "\n\n".join(t for t in page_texts if t).strip()
    result["stats"]["page_count"] = len(result["pages"])
    result["stats"]["block_count"] = len(result["blocks"])
    result["stats"]["ocr_avg_confidence"] = (
        round(sum(confidences) / len(confidences), 4) if confidences else None
    )

    failed = result["stats"]["failed_pages"]
    if failed and not result["blocks"]:
        result["status"] = "failed"
    elif failed:
        result["status"] = "partial"
        result["warnings"].append({
            "code": "W_PARTIAL",
            "message": f"{failed} 页处理失败，已保留其余页面结果",
        })
    else:
        result["status"] = "completed"

    return result
