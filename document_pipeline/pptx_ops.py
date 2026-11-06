# -*- coding: utf-8 -*-
"""PPTX text, slide numbers and tables."""
from __future__ import annotations

from pptx import Presentation

from .common import ParseError, clean, table_blocks


def parse_pptx(path) -> dict:
    try:
        prs = Presentation(str(path))
    except Exception as exc:
        raise ParseError(
            "E_FILE_CORRUPT",
            f"PPTX 无法打开：{str(exc)[:200]}",
            "请用 PowerPoint/WPS 打开后另存为新的 .pptx；确认文件未加密或损坏。",
        ) from exc

    blocks: list[dict] = []
    slides_meta: list[dict] = []

    for slide_no, slide in enumerate(prs.slides, 1):
        slide_blocks = 0
        table_index = 0
        for shape_no, shape in enumerate(slide.shapes, 1):
            if getattr(shape, "has_table", False):
                table_index += 1
                rows = []
                for row in shape.table.rows:
                    rows.append([clean(cell.text) for cell in row.cells])
                blocks.extend(table_blocks(
                    f"pt{slide_no}_{table_index}", table_index, rows,
                    f"pptx://{path.name}?slide={slide_no}",
                    slide=slide_no, part="table",
                ))
                slide_blocks += len(rows)
                continue

            if getattr(shape, "has_text_frame", False):
                for para_no, para in enumerate(shape.text_frame.paragraphs, 1):
                    text = clean(para.text)
                    if not text:
                        continue
                    blocks.append({
                        "id": f"s{slide_no:03d}p{shape_no:03d}_{para_no:02d}",
                        "type": "slide_text",
                        "text": text,
                        "slide": slide_no,
                        "shape": shape_no,
                        "locator": f"pptx://{path.name}#slide={slide_no}&shape={shape_no}",
                        "source": {"file": path.name, "kind": "pptx", "part": "slide"},
                    })
                    slide_blocks += 1

        notes = ""
        try:
            if slide.has_notes_slide:
                notes = clean(slide.notes_slide.notes_text_frame.text)
        except Exception:
            notes = ""
        if notes:
            blocks.append({
                "id": f"s{slide_no:03d}notes",
                "type": "slide_note",
                "text": notes,
                "slide": slide_no,
                "locator": f"pptx://{path.name}#slide={slide_no}&notes=1",
                "source": {"file": path.name, "kind": "pptx", "part": "notes"},
            })
            slide_blocks += 1

        slides_meta.append({"slide": slide_no, "block_count": slide_blocks})

    return {
        "blocks": blocks,
        "messages": [],
        "meta": {
            "slide_count": len(prs.slides),
            "slides": slides_meta,
            "title": clean(prs.core_properties.title) or None,
            "author": clean(prs.core_properties.author) or None,
        },
        "warnings": [],
        "errors": [],
    }
