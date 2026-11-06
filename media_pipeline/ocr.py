# -*- coding: utf-8 -*-
"""OCR engine abstraction.

RapidOCR is used as the local engine (Chinese + English, ONNX, no network).
The interface is intentionally small so tests can inject failures.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class OCREngineError(Exception):
    def __init__(self, message: str, page: int | None = None):
        super().__init__(message)
        self.message = message
        self.page = page


@dataclass
class OCREngineInfo:
    name: str
    version: str
    languages: list[str]


class RapidOCREngine:
    name = "rapidocr"
    languages = ["ch", "en"]

    def __init__(self):
        self._model = None
        self._version = "unknown"

    def info(self) -> OCREngineInfo:
        if self._model is None:
            self._ensure()
        return OCREngineInfo(self.name, self._version, self.languages)

    def _ensure(self):
        if self._model is not None:
            return
        try:
            from rapidocr_onnxruntime import RapidOCR
            import rapidocr_onnxruntime
        except ImportError as exc:
            raise OCREngineError("未安装 rapidocr-onnxruntime，无法执行 OCR") from exc
        self._model = RapidOCR()
        self._version = getattr(rapidocr_onnxruntime, "__version__", "unknown")

    def recognize(self, image_path: str | Path) -> list[dict]:
        path = Path(image_path)
        if not path.exists() or path.stat().st_size == 0:
            raise OCREngineError(f"OCR 输入不存在或为空：{path.name}")
        self._ensure()
        try:
            result, _elapse = self._model(str(path))
        except Exception as exc:  # engine-level failure, keep message for the report
            raise OCREngineError(f"OCR 引擎执行失败：{str(exc)[:200]}") from exc

        lines: list[dict] = []
        for item in result or []:
            try:
                box, text, score = item[0], str(item[1]).strip(), float(item[2])
            except (IndexError, TypeError, ValueError):
                continue
            if not text:
                continue
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            lines.append({
                "text": text,
                "confidence": max(0.0, min(1.0, score)),
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
                "polygon": [[float(p[0]), float(p[1])] for p in box],
            })

        # Reading order: top-to-bottom, then left-to-right within a line band.
        lines.sort(key=lambda ln: (round(ln["bbox"][1] / 12), ln["bbox"][0]))
        return lines


def average_confidence(lines: list[dict]) -> float | None:
    values = [ln["confidence"] for ln in lines if isinstance(ln.get("confidence"), (int, float))]
    if not values:
        return None
    return round(sum(values) / len(values), 4)
