# -*- coding: utf-8 -*-
"""Shared helpers for document parsers."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from urllib.parse import quote


class ParseError(Exception):
    def __init__(self, code: str, message: str, hint: str, recoverable: bool = True):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.recoverable = recoverable


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean(text: str) -> str:
    if text is None:
        return ""
    s = str(text).replace("\xa0", " ").replace("\r", "")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return clean(str(value))


def table_blocks(table_id: str, table_index: int, rows: list[list[str]],
                 locator_prefix: str, **extra) -> list[dict]:
    blocks = []
    for ri, cols in enumerate(rows, 1):
        cells = [clean(c) for c in cols]
        blocks.append({
            "id": f"{table_id}r{ri:03d}",
            "type": "table_row",
            "text": " | ".join(c for c in cells if c),
            "table_id": table_id,
            "table_index": table_index,
            "row": ri,
            "cols": cells,
            "locator": f"{locator_prefix}#table={table_index}&row={ri}",
            **extra,
        })
    return blocks


def sheet_quote(name: str) -> str:
    return quote(name or "Sheet", safe="")


def finish(result: dict) -> dict:
    """Compute searchable text and stats, and set completed/failed status."""
    messages = result.get("messages") or []
    blocks = result.get("blocks") or []
    parts = []
    if messages:
        parts.append("\n".join(f"{m.get('sender', '')}: {m.get('text', '')}".strip()
                                for m in messages if m.get("text")))
    if blocks and not messages:
        parts.append("\n".join(b.get("text", "") for b in blocks if b.get("text")))
    elif blocks:
        table_text = "\n".join(b.get("text", "") for b in blocks
                               if b.get("type") == "table_row" and b.get("text"))
        if table_text:
            parts.append(table_text)
    result["text"] = "\n".join(p for p in parts if p).strip()

    table_ids = {b.get("table_id") for b in blocks if b.get("type") == "table_row"}
    result["stats"] = {
        **(result.get("stats") or {}),
        "block_count": len(blocks),
        "table_count": len(table_ids),
        "table_row_count": sum(1 for b in blocks if b.get("type") == "table_row"),
        "message_count": len(messages),
        "char_count": len(result.get("text") or ""),
    }
    if not blocks and not messages and not result.get("errors"):
        result.setdefault("warnings", []).append({
            "code": "W_EMPTY_DOCUMENT",
            "message": "文件可打开，但没有可提取的文字或表格",
        })
    if result.get("errors") and not blocks and not messages:
        result["status"] = "failed"
    elif result.get("errors"):
        result["status"] = "partial"
    else:
        result["status"] = "completed"
    return result
