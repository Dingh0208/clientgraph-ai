# -*- coding: utf-8 -*-
"""Verify document parsers.

Run: python scripts/verify_document_pipeline.py
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".temp" / "pylibs"))

from docx import Document  # noqa: E402
from docx.shared import Pt  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Inches  # noqa: E402
from email.message import EmailMessage  # noqa: E402
import xlwt  # noqa: E402

from document_pipeline import process, search  # noqa: E402

TMP = ROOT / ".temp" / "document-verify"
EVIDENCE = ROOT / "evidence" / "document-pipeline-2026-11-06.json"


def make_fixtures() -> dict:
    if TMP.exists():
        shutil.rmtree(TMP)
    src = TMP / "source"
    src.mkdir(parents=True)

    # DOCX: heading, paragraphs, table
    doc = Document()
    doc.core_properties.title = "设备巡检需求说明"
    doc.core_properties.author = "王工"
    doc.add_heading("设备巡检小程序 需求说明", level=0)
    doc.add_paragraph("本项目覆盖设备台账、巡检计划与异常上报。")
    doc.add_paragraph("Inspection scope: 118 devices across five workshops.")
    table = doc.add_table(rows=2, cols=3)
    table.style = "Table Grid"
    values = [["模块", "优先级", "说明"],
              ["设备台账", "P0", "含二维码"]]
    for r, row in enumerate(values):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    doc.save(src / "req.docx")

    # XLSX: two sheets, merged cells
    wb = Workbook()
    ws = wb.active
    ws.title = "设备清单"
    ws.append(["设备编号", "名称", "车间", "状态"])
    for row in [["EQ-001", "数控车床", "一车间", "在用"],
                ["EQ-002", "加工中心", "二车间", "备用"]]:
        ws.append(row)
    ws.merge_cells("A5:B5")
    ws["A5"] = "合计 2 台"
    ws2 = wb.create_sheet("汇总")
    ws2.append(["指标", "数值"])
    ws2.append(["设备总数", 2])
    wb.save(src / "devices.xlsx")

    # XLS (legacy)
    book = xlwt.Workbook()
    sh = book.add_sheet("旧版清单")
    for r, row in enumerate([["设备", "数量"], ["空压机", 3]]):
        for c, value in enumerate(row):
            sh.write(r, c, value)
    book.save(str(src / "legacy.xls"))

    # PPTX: 3 slides, table, notes
    prs = Presentation()
    blank = prs.slide_layouts[6]
    s1 = prs.slides.add_slide(blank)
    box = s1.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(8), Inches(1))
    box.text_frame.text = "设备巡检方案"
    s2 = prs.slides.add_slide(blank)
    tb = s2.shapes.add_table(2, 3, Inches(0.8), Inches(1.2), Inches(8), Inches(2)).table
    for r, row in enumerate([["阶段", "周期", "交付"], ["一期", "4 周", "小程序"]]):
        for c, value in enumerate(row):
            tb.cell(r, c).text = value
    s3 = prs.slides.add_slide(blank)
    s3.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(8), Inches(1)).text_frame.text = "下一步"
    s3.notes_slide.notes_text_frame.text = "备注：审批流二期再评估。"
    prs.save(src / "proposal.pptx")

    # EML
    msg = EmailMessage()
    msg["From"] = "陈晓岚 <chen.xiaolan@example.com>"
    msg["To"] = "王工 <wang.gong@example.com>"
    msg["Cc"] = "李副总 <li.fu@example.com>"
    msg["Subject"] = "需求文档 v1.0 请确认"
    msg["Date"] = "Tue, 29 Sep 2026 10:12:00 +0800"
    msg["Message-ID"] = "<demo-001@example.com>"
    msg.set_content("王工：\n请确认一期范围与上线时间。\n谢谢。")
    msg.add_attachment("巡检说明".encode("utf-8"), maintype="text", subtype="plain",
                       filename="巡检说明.txt")
    (src / "mail.eml").write_bytes(msg.as_bytes())

    # TXT chat export (WeChat style, two lines per message)
    chat_lines = [
        "2026-09-22 09:14:02 陈晓岚",
        "上次电话后我们内部过了一版",
        "2026-09-22 09:16:10 陈晓岚",
        "领导提了个审批，巡检异常要走审批",
        "2026-09-22 09:18:02 我",
        "我先记成待确认，范围以评审会为准",
        "2026-09-22 09:19:15 陈晓岚",
        "预算还是 8 万左右",
    ]
    (src / "chat.txt").write_text("\n".join(chat_lines), encoding="utf-8")

    # Plain TXT
    (src / "notes.txt").write_text(
        "项目背景\n客户现有 118 台设备，台账用 Excel 维护。\n本期范围包括台账、巡检计划与异常上报。",
        encoding="utf-8",
    )

    # HTML chat + table
    html = """<!doctype html><html><head><meta charset="utf-8"><title>聊天记录</title></head>
<body>
<div>2026-09-22 09:14:02 陈晓岚</div><div>上次电话后我们内部过了一版</div>
<div>2026-09-22 09:16:10 陈晓岚</div><div>审批这块要加</div>
<div>2026-09-22 09:18:02 我</div><div>我先记成待确认</div>
<table><tr><th>项目</th><th>金额</th></tr><tr><td>巡检</td><td>100000</td></tr></table>
</body></html>"""
    (src / "chat.html").write_text(html, encoding="utf-8")

    # JSON chat
    (src / "chat.json").write_text(json.dumps({
        "messages": [
            {"time": "2026-09-22 09:14:02", "sender": "陈晓岚", "content": "上次电话后过了一版"},
            {"time": "2026-09-22 09:16:10", "sender": "陈晓岚", "content": "审批要加"},
            {"time": "2026-09-22 09:18:02", "sender": "我", "content": "先记成待确认"},
        ]
    }, ensure_ascii=False), encoding="utf-8")

    # Corrupt / legacy
    (src / "broken.docx").write_bytes(b"PK\x03\x04" + b"\x00" * 2048)
    (src / "broken.xlsx").write_bytes(b"PK\x03\x04" + b"\x11" * 2048)
    (src / "legacy.doc").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 512)
    (src / "legacy.ppt").write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 512)

    return {
        "dir": src,
        "docx": src / "req.docx",
        "xlsx": src / "devices.xlsx",
        "xls": src / "legacy.xls",
        "pptx": src / "proposal.pptx",
        "eml": src / "mail.eml",
        "chat_txt": src / "chat.txt",
        "plain_txt": src / "notes.txt",
        "chat_html": src / "chat.html",
        "chat_json": src / "chat.json",
        "broken_docx": src / "broken.docx",
        "broken_xlsx": src / "broken.xlsx",
        "legacy_doc": src / "legacy.doc",
        "legacy_ppt": src / "legacy.ppt",
    }


def summarize(r: dict) -> dict:
    return {
        "status": r["status"],
        "kind": r["source"]["kind"],
        "blocks": len(r.get("blocks") or []),
        "messages": len(r.get("messages") or []),
        "tables": r["stats"].get("table_count"),
        "chars": r["stats"].get("char_count"),
        "errors": r.get("errors"),
        "warnings": r.get("warnings"),
        "meta": r.get("meta"),
        "source_unchanged": r["source"].get("unchanged"),
    }


def main() -> int:
    fx = make_fixtures()
    scenario_results = []

    def run(name, path, checks_fn):
        checks = {}
        try:
            r = process(path, TMP / f"out-{len(scenario_results)}")
            checks_fn(r, checks)
            ok = all(checks.values())
            err = None
        except Exception as exc:
            r = {"status": "error", "source": {"kind": "error"}, "stats": {},
                 "blocks": [], "messages": [], "errors": [], "warnings": [], "meta": {}}
            checks["no_exception"] = False
            ok = False
            err = str(exc)
        scenario_results.append({
            "name": name,
            "summary": summarize(r),
            "checks": checks,
            "passed": ok,
            "error": err,
        })
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            for k, v in checks.items():
                if not v:
                    print("   failed:", k)
            if err:
                print("   exception:", err)

    def ensure(checks, key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    # 1 DOCX
    def c_docx(r, checks):
        ensure(checks, "completed", r["status"] == "completed", r["status"])
        ensure(checks, "text", "设备巡检小程序 需求说明" in r["text"] and "Inspection scope" in r["text"])
        tables = [b for b in r["blocks"] if b["type"] == "table_row"]
        ensure(checks, "table_rows", len(tables) == 2, len(tables))
        ensure(checks, "table_cols", len(tables[0]["cols"]) == 3, tables[0]["cols"])
        ensure(checks, "table_cell", tables[1]["cols"][0] == "设备台账", tables[1]["cols"])
        ensure(checks, "locator", "table=1" in tables[0]["locator"])
        ensure(checks, "unchanged", r["source"]["unchanged"] is True)
        ensure(checks, "search", len(search(r, "二维码")) >= 1)
    run("DOCX 文本与表格", fx["docx"], c_docx)

    # 2 XLSX
    def c_xlsx(r, checks):
        ensure(checks, "completed", r["status"] == "completed", r["status"])
        ensure(checks, "sheets", r["meta"]["sheet_count"] == 2, r["meta"]["sheet_count"])
        rows = [b for b in r["blocks"] if b.get("sheet") == "设备清单"]
        ensure(checks, "rows", len(rows) >= 3, len(rows))
        ensure(checks, "cols", rows[0]["cols"][:4] == ["设备编号", "名称", "车间", "状态"], rows[0]["cols"])
        ensure(checks, "cell_value", rows[2]["cols"][0] == "EQ-002", rows[2]["cols"])
        ensure(checks, "sheet_locator", "sheet=" in rows[0]["locator"])
        ensure(checks, "merged", any("A5:B5" in m for m in r["meta"]["sheets"][0]["merged"]))
    run("XLSX 多工作表与行列", fx["xlsx"], c_xlsx)

    # 3 XLS legacy
    def c_xls(r, checks):
        ensure(checks, "completed", r["status"] == "completed", r["status"])
        ensure(checks, "kind", r["source"]["kind"] == "xls")
        rows = [b for b in r["blocks"] if b["type"] == "table_row"]
        ensure(checks, "rows", len(rows) == 2, len(rows))
        ensure(checks, "cell", rows[1]["cols"][0] == "空压机", rows[1]["cols"])
    run("XLS 旧版表格", fx["xls"], c_xls)

    # 4 PPTX
    def c_pptx(r, checks):
        ensure(checks, "completed", r["status"] == "completed", r["status"])
        ensure(checks, "slides", r["meta"]["slide_count"] == 3, r["meta"]["slide_count"])
        ensure(checks, "slide_numbers", {b["slide"] for b in r["blocks"] if "slide" in b} == {1, 2, 3})
        tables = [b for b in r["blocks"] if b["type"] == "table_row"]
        ensure(checks, "table", len(tables) == 2 and tables[0]["slide"] == 2, len(tables))
        ensure(checks, "table_cols", len(tables[0]["cols"]) == 3, tables[0]["cols"])
        ensure(checks, "notes", any(b["type"] == "slide_note" and "审批流" in b["text"] for b in r["blocks"]))
    run("PPTX 页码与表格", fx["pptx"], c_pptx)

    # 5 EML
    def c_eml(r, checks):
        email_meta = r["meta"]["email"]
        ensure(checks, "completed", r["status"] == "completed", r["status"])
        ensure(checks, "from", any("chen.xiaolan@example.com" in x for x in email_meta["from"]), email_meta["from"])
        ensure(checks, "to", any("wang.gong@example.com" in x for x in email_meta["to"]), email_meta["to"])
        ensure(checks, "date", email_meta["date"].startswith("2026-09-29"), email_meta["date"])
        ensure(checks, "subject", "需求文档" in email_meta["subject"], email_meta["subject"])
        ensure(checks, "body", "一期范围" in r["text"], r["text"][:80])
        ensure(checks, "attachment", any(a["filename"] == "巡检说明.txt" for a in email_meta["attachments"]))
    run("EML 邮件头与正文", fx["eml"], c_eml)

    # 6 TXT chat
    def c_chat_txt(r, checks):
        ensure(checks, "completed", r["status"] == "completed", r["status"])
        ensure(checks, "messages", len(r["messages"]) == 4, len(r["messages"]))
        ensure(checks, "times", all(m["ts"].startswith("2026-09-22") for m in r["messages"]))
        ensure(checks, "senders", {m["sender"] for m in r["messages"]} == {"陈晓岚", "我"})
        ensure(checks, "chat_meta", r["meta"]["chat"]["message_count"] == 4)
        ensure(checks, "locator", all(m["locator"].startswith("chat://") for m in r["messages"]))
    run("TXT 微信聊天导出", fx["chat_txt"], c_chat_txt)

    # 7 HTML chat + table
    def c_html(r, checks):
        ensure(checks, "completed", r["status"] == "completed", r["status"])
        ensure(checks, "messages", len(r["messages"]) == 3, len(r["messages"]))
        ensure(checks, "times_senders", all(m["ts"] and m["sender"] for m in r["messages"]))
        tables = [b for b in r["blocks"] if b["type"] == "table_row"]
        ensure(checks, "table_rows", len(tables) == 2, len(tables))
        ensure(checks, "table_cols", tables[0]["cols"] == ["项目", "金额"], tables[0]["cols"])
    run("HTML 聊天导出与表格", fx["chat_html"], c_html)

    # 8 JSON chat
    def c_json(r, checks):
        ensure(checks, "completed", r["status"] == "completed", r["status"])
        ensure(checks, "messages", len(r["messages"]) == 3, len(r["messages"]))
        ensure(checks, "sender", r["messages"][0]["sender"] == "陈晓岚")
        ensure(checks, "ts", r["messages"][0]["ts"].startswith("2026-09-22"))
    run("JSON 聊天导出", fx["chat_json"], c_json)

    # 9 plain TXT
    def c_plain(r, checks):
        ensure(checks, "completed", r["status"] == "completed", r["status"])
        ensure(checks, "no_chat", len(r["messages"]) == 0)
        ensure(checks, "blocks", len(r["blocks"]) == 3, len(r["blocks"]))
    run("TXT 普通文本", fx["plain_txt"], c_plain)

    # 10 corrupt docx
    def c_broken(r, checks):
        ensure(checks, "failed", r["status"] == "failed", r["status"])
        ensure(checks, "code", r["errors"][0]["code"] == "E_FILE_CORRUPT", r["errors"])
        ensure(checks, "hint", bool(r["errors"][0].get("hint")))
    run("损坏 DOCX", fx["broken_docx"], c_broken)

    # 11 corrupt xlsx
    def c_broken_xlsx(r, checks):
        ensure(checks, "failed", r["status"] == "failed", r["status"])
        ensure(checks, "code", r["errors"][0]["code"] == "E_FILE_CORRUPT", r["errors"])
        ensure(checks, "hint", bool(r["errors"][0].get("hint")))
    run("损坏 XLSX", fx["broken_xlsx"], c_broken_xlsx)

    # 12 legacy doc / ppt
    def c_legacy(r, checks):
        ensure(checks, "failed", r["status"] == "failed", r["status"])
        ensure(checks, "code", r["errors"][0]["code"] == "E_LEGACY_FORMAT", r["errors"])
        ensure(checks, "hint", "另存为" in r["errors"][0]["hint"], r["errors"][0]["hint"])
    run("旧版 DOC", fx["legacy_doc"], c_legacy)
    run("旧版 PPT", fx["legacy_ppt"], c_legacy)

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
        "fixtures": {k: {"name": v.name, "size": v.stat().st_size}
                     for k, v in fx.items() if k != "dir"},
        "scenarios": scenario_results,
        "all_passed": all(s["passed"] for s in scenario_results),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
