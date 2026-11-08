# -*- coding: utf-8 -*-
"""Split selected materials into model-sized batches."""
from __future__ import annotations


class PlanningError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _split_text(text: str, limit: int) -> list[str]:
    text = text or ""
    if len(text) <= limit:
        return [text]
    parts = []
    pos = 0
    while pos < len(text):
        end = min(len(text), pos + limit)
        if end < len(text):
            cut = text.rfind("\n", pos, end)
            if cut > pos + limit // 2:
                end = cut
        parts.append(text[pos:end])
        pos = end
    return parts


def plan(materials: list[dict], max_input_chars: int = 2000) -> list[dict]:
    if max_input_chars <= 0:
        raise PlanningError("E_MODEL_LIMIT", "模型输入上限必须大于 0")
    parts = []
    for material in materials:
        if material.get("readable") is False:
            raise PlanningError("E_UNREADABLE", f"资料不可读：{material.get('material_id')}")
        text = material.get("text") or ""
        chunks = _split_text(text, max_input_chars)
        for i, chunk in enumerate(chunks):
            parts.append({
                "material_id": material["material_id"],
                "name": material.get("name") or material["material_id"],
                "type": material.get("type"),
                "locator": material.get("locator"),
                "part_index": i,
                "text": chunk,
                "chars": len(chunk),
            })

    batches, current = [], []
    current_chars = 0
    for part in parts:
        if current and current_chars + part["chars"] > max_input_chars:
            batches.append(_batch(len(batches), current, current_chars))
            current, current_chars = [], 0
        current.append(part)
        current_chars += part["chars"]
    if current:
        batches.append(_batch(len(batches), current, current_chars))
    return batches


def _batch(index: int, parts: list[dict], chars: int) -> dict:
    return {
        "batch_id": f"B{index + 1}",
        "index": index,
        "status": "pending",
        "input_chars": chars,
        "parts": parts,
        "material_ids": list(dict.fromkeys(p["material_id"] for p in parts)),
        "attempts": 0,
        "error": None,
        "questions": [],
    }
