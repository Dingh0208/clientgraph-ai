# -*- coding: utf-8 -*-
"""XLSX parsing: sheets, rows and columns preserved."""
from __future__ import annotations

from openpyxl import load_workbook

from .common import ParseError, cell_text, sheet_quote, table_blocks

MAX_ROWS = 5000
MAX_COLS = 100


def parse_xlsx(path) -> dict:
    try:
        wb = load_workbook(str(path), data_only=True, read_only=False)
    except Exception as exc:
        raise ParseError(
            "E_FILE_CORRUPT",
            f"XLSX 无法打开：{str(exc)[:200]}",
            "请用 Excel/WPS 打开后另存为新的 .xlsx；确认文件未加密或损坏。",
        ) from exc

    blocks: list[dict] = []
    sheets_meta: list[dict] = []
    warnings: list[dict] = []

    for sheet_index, sheet in enumerate(wb.worksheets, 1):
        total_rows = sheet.max_row or 0
        total_cols = sheet.max_column or 0
        limit_rows = min(total_rows, MAX_ROWS)
        limit_cols = min(total_cols, MAX_COLS)
        if total_rows > MAX_ROWS or total_cols > MAX_COLS:
            warnings.append({
                "code": "W_SHEET_TRUNCATED",
                "message": f"工作表「{sheet.title}」超过 {MAX_ROWS} 行或 {MAX_COLS} 列，已截断",
                "sheet": sheet.title,
            })

        rows: list[list[str]] = []
        for row in sheet.iter_rows(min_row=1, max_row=limit_rows,
                                   max_col=limit_cols, values_only=True):
            cells = [cell_text(v) for v in row]
            if not any(cells):
                continue
            rows.append(cells)

        sheets_meta.append({
            "name": sheet.title,
            "row_count": len(rows),
            "col_count": max((len(r) for r in rows), default=0),
            "merged": [str(r) for r in sheet.merged_cells.ranges][:50],
        })

        if not rows:
            warnings.append({
                "code": "W_EMPTY_SHEET",
                "message": f"工作表「{sheet.title}」没有可提取的内容",
                "sheet": sheet.title,
            })
            continue

        prefix = f"xlsx://{path.name}?sheet={sheet_quote(sheet.title)}"
        blocks.extend(table_blocks(
            f"x{sheet_index}", sheet_index, rows, prefix, sheet=sheet.title,
        ))

    meta = {
        "sheet_count": len(wb.worksheets),
        "sheets": sheets_meta,
        "formula_mode": "cached_values",
    }
    return {"blocks": blocks, "messages": [], "meta": meta,
            "warnings": warnings, "errors": []}
