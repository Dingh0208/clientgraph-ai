# -*- coding: utf-8 -*-
"""Legacy XLS parsing (xlrd), rows/columns preserved."""
from __future__ import annotations

from .common import ParseError, cell_text, sheet_quote, table_blocks

MAX_ROWS = 5000
MAX_COLS = 100


def parse_xls(path) -> dict:
    try:
        import xlrd
    except ImportError as exc:
        raise ParseError(
            "E_LEGACY_FORMAT",
            "缺少 .xls 解析组件 xlrd",
            "安装 xlrd 后重试，或用 Excel/WPS 另存为 .xlsx。",
        ) from exc

    try:
        wb = xlrd.open_workbook(str(path))
    except Exception as exc:
        raise ParseError(
            "E_FILE_CORRUPT",
            f"XLS 无法打开：{str(exc)[:200]}",
            "请用 Excel/WPS 打开后另存为新的 .xls 或 .xlsx；确认文件未加密或损坏。",
        ) from exc

    blocks: list[dict] = []
    sheets_meta: list[dict] = []
    warnings: list[dict] = []

    for sheet_index, sheet in enumerate(wb.sheets(), 1):
        total_rows = sheet.nrows
        total_cols = sheet.ncols
        if total_rows > MAX_ROWS or total_cols > MAX_COLS:
            warnings.append({
                "code": "W_SHEET_TRUNCATED",
                "message": f"工作表「{sheet.name}」超过 {MAX_ROWS} 行或 {MAX_COLS} 列，已截断",
                "sheet": sheet.name,
            })

        rows: list[list[str]] = []
        for r in range(min(total_rows, MAX_ROWS)):
            cells = []
            for c in range(min(total_cols, MAX_COLS)):
                cell = sheet.cell(r, c)
                value = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        value = xlrd.xldate_as_datetime(cell.value, wb.datemode)
                    except Exception:
                        value = cell.value
                elif cell.ctype == xlrd.XL_CELL_ERROR:
                    value = ""
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    value = bool(cell.value)
                cells.append(cell_text(value))
            if any(cells):
                rows.append(cells)

        sheets_meta.append({
            "name": sheet.name,
            "row_count": len(rows),
            "col_count": max((len(r) for r in rows), default=0),
        })
        if not rows:
            warnings.append({
                "code": "W_EMPTY_SHEET",
                "message": f"工作表「{sheet.name}」没有可提取的内容",
                "sheet": sheet.name,
            })
            continue

        prefix = f"xls://{path.name}?sheet={sheet_quote(sheet.name)}"
        blocks.extend(table_blocks(
            f"l{sheet_index}", sheet_index, rows, prefix, sheet=sheet.name,
        ))

    return {
        "blocks": blocks,
        "messages": [],
        "meta": {"sheet_count": len(wb.sheets()), "sheets": sheets_meta, "format": "xls"},
        "warnings": warnings,
        "errors": [],
    }
