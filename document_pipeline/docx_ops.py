# -*- coding: utf-8 -*-
"""DOCX text, headings and tables (rows/columns preserved)."""
from __future__ import annotations

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from .common import ParseError, clean, table_blocks


def parse_docx(path) -> dict:
    try:
        doc = Document(str(path))
    except Exception as exc:
        raise ParseError(
            "E_FILE_CORRUPT",
            f"DOCX 无法打开：{str(exc)[:200]}",
            "请用 Word/WPS 打开后另存为新的 .docx；确认文件未加密或损坏。",
        ) from exc

    blocks: list[dict] = []
    table_index = 0
    para_index = 0

    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            text = clean(para.text)
            if not text:
                continue
            para_index += 1
            style = (para.style.name if para.style else "") or ""
            kind = "heading" if style.lower().startswith(("heading", "标题")) else "paragraph"
            blocks.append({
                "id": f"p{para_index:04d}",
                "type": kind,
                "text": text,
                "locator": f"docx://{path.name}#para={para_index}",
                "style": style or None,
                "source": {"file": path.name, "kind": "docx", "part": "body"},
            })
        elif tag == "tbl":
            table = Table(child, doc)
            table_index += 1
            rows = []
            for row in table.rows:
                rows.append([clean(cell.text) for cell in row.cells])
            blocks.extend(table_blocks(
                f"docxt{table_index}", table_index, rows,
                f"docx://{path.name}", part="table",
            ))

    props = doc.core_properties
    meta = {
        "title": clean(props.title) or None,
        "author": clean(props.author) or None,
        "created": props.created.isoformat(sep=" ") if props.created else None,
        "modified": props.modified.isoformat(sep=" ") if props.modified else None,
        "paragraph_count": para_index,
        "table_count": table_index,
    }
    return {"blocks": blocks, "messages": [], "meta": meta,
            "warnings": [], "errors": []}
