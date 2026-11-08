# -*- coding: utf-8 -*-
"""Verify clarification work-order lifecycle, filters, copy, delete and export."""
from __future__ import annotations

import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clarification.workspace import (  # noqa: E402
    STATUS_LABELS, ClarificationWorkspace, WorkspaceError,
)

EVIDENCE = ROOT / "evidence" / "clarification-records-2026-11-08.json"
OUT = ROOT / ".temp" / "exports"

MATERIALS = {
    "m1": {"source_id": "m1", "name": "微信聊天-巡检", "type": "chat",
           "locator": "chat://m1", "text": "一期先做扫码巡检与异常上报",
           "sha256": "aaa"},
    "m2": {"source_id": "m2", "name": "邮件-供应链", "type": "email",
           "locator": "mail://m2", "text": "供应链协同需要对接 ERP 接口",
           "sha256": "bbb"},
    "m3": {"source_id": "m3", "name": "会议纪要-补充", "type": "doc",
           "locator": "doc://m3", "text": "补充：报表放到二期再做",
           "sha256": "ccc"},
}


def ev(locator: str, text: str) -> dict:
    return {"text": text, "file": "微信聊天.txt", "locator": locator,
            "occurred_at": "2026-11-06"}


def question(text: str, field: str = "scope_in") -> dict:
    return {"text": text, "priority": "must_confirm", "priority_label": "必须先确认",
            "dimension": "scope", "field": field, "reason": "资料未提及",
            "evidence": [ev("chat://m1#msg=1", "一期先做扫码巡检")]}


def main() -> int:
    checks = {}

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    def raises(code, fn, *args, **kwargs):
        try:
            fn(*args, **kwargs)
        except WorkspaceError as exc:
            return exc.code == code
        return False

    ws = ClarificationWorkspace(now=datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc))
    scope1 = {"customers": [{"id": "c1", "name": "青岚能装备（虚构）"}],
              "projects": [{"id": "p1", "name": "设备巡检小程序（一期）"}]}
    scope2 = {"customers": [{"id": "c2", "name": "恒晟精工（虚构）"}],
              "projects": [{"id": "p3", "name": "供应链协同平台（预研）"}]}

    ensure("scope_required", raises("E_SCOPE_REQUIRED", ws.create_record, {}))

    cr1 = ws.create_record(scope1, [MATERIALS["m1"]],
                           created_at="2026-11-06T09:00:00+08:00")
    cr2 = ws.create_record(scope2, [MATERIALS["m2"]],
                           created_at="2026-11-07T09:00:00+08:00")
    ensure("draft_status", cr1["status"] == "draft" and cr1["status_label"] == "草稿")
    ensure("default_name", "2026-11-06" in cr1["name"] and "青岚" in cr1["name"])

    # Full lifecycle to completed.
    ensure("scope_confirm_required", raises("E_SCOPE_NOT_CONFIRMED",
                                            ws.start_analysis, cr1["id"]))
    ws.confirm_scope(cr1["id"], at="2026-11-06T09:05:00+08:00")
    started = ws.start_analysis(cr1["id"], at="2026-11-06T09:06:00+08:00")
    ensure("analyzing_status", cr1["status"] == "analyzing"
           and cr1["status_label"] == "分析中")
    ensure("batch_created", len(started["batches"]) == 1
           and started["batches"][0]["batch_id"] == "R1-B1")
    ws.complete_batch(cr1["id"], "R1-B1", questions=[
        question("请问一期必须包含哪些功能？"),
        question("请问本期不包含哪些功能？", "scope_out"),
        question("请问上线日期是哪一天？", "schedule"),
    ], at="2026-11-06T09:10:00+08:00")
    ensure("incomplete_after_analysis", cr1["status"] == "incomplete"
           and cr1["status_label"] == "未完成")
    ensure("three_questions", len(ws.ledger(cr1["id"]).questions) == 3)

    ws.ask(cr1["id"], "Q1", at="2026-11-06T10:00:00+08:00")
    ensure("asked_still_incomplete", cr1["status"] == "incomplete")
    ws.answer(cr1["id"], "Q1", "扫码巡检、异常上报", [ev("chat://m1#msg=2", "扫码巡检")],
              answered_at="2026-11-06T11:00:00+08:00")
    ensure("partial_after_one_answer", cr1["status"] == "partial"
           and cr1["status_label"] == "部分完成")
    ws.mark_not_applicable(cr1["id"], "Q2", "客户确认本期不做报表",
                           at="2026-11-06T11:10:00+08:00")
    ensure("still_partial", cr1["status"] == "partial")
    ws.ask(cr1["id"], "Q3", at="2026-11-06T11:20:00+08:00")
    ws.answer(cr1["id"], "Q3", "2026-12-15", [ev("chat://m1#msg=3", "12月15日上线")],
              answered_at="2026-11-06T11:30:00+08:00")
    ensure("completed_status", cr1["status"] == "completed"
           and cr1["status_label"] == "已完成")

    # Second record stays open after asking.
    ws.confirm_scope(cr2["id"], at="2026-11-07T09:05:00+08:00")
    ws.start_analysis(cr2["id"], at="2026-11-07T09:06:00+08:00")
    ws.complete_batch(cr2["id"], "R1-B1", questions=[question("请问需要对接哪些外部系统？", "interfaces")],
                      at="2026-11-07T09:10:00+08:00")
    ws.ask(cr2["id"], "Q1", at="2026-11-07T09:20:00+08:00")
    ensure("asked_unanswered_incomplete", cr2["status"] == "incomplete"
           and ws.summary(cr2["id"])["open"] == 1)

    # Filters: customer, project, date, unanswered / completed.
    ids = lambda rows: {r["id"] for r in rows}
    ensure("filter_customer", ids(ws.list_records(customer_id="c1")) == {"CR1"})
    ensure("filter_project", ids(ws.list_records(project_id="p3")) == {"CR2"})
    ensure("filter_date", ids(ws.list_records(date_from="2026-11-06",
                                              date_to="2026-11-06")) == {"CR1"})
    ensure("filter_unanswered", ids(ws.list_records(view="unanswered")) == {"CR2"})
    ensure("filter_completed", ids(ws.list_records(view="completed")) == {"CR1"})

    # Copy as a new draft: questions reset, answers not copied.
    cr3 = ws.copy_as_draft(cr2["id"], at="2026-11-08T09:00:00+08:00")
    ensure("copy_draft", cr3["status"] == "draft" and cr3["copy_of"] == cr2["id"])
    ensure("copy_name", cr3["name"].endswith("（副本）"))
    ensure("copy_questions_pending",
           len(ws.ledger(cr3["id"]).questions) == 1
           and ws.ledger(cr3["id"]).questions[0]["status"] == "pending")
    ensure("copy_sources", len(ws.sources_for(cr3["id"])) == 1)
    ensure("copy_no_effect_on_source", ws.summary(cr2["id"])["open"] == 1)

    # Archive hides by default and restores to the previous status.
    ws.archive(cr1["id"], at="2026-11-08T09:10:00+08:00")
    ensure("archived_status", cr1["status"] == "archived"
           and cr1["status_label"] == "已归档")
    ensure("archived_hidden", ids(ws.list_records()) == {"CR2", "CR3"})
    ensure("archived_visible", ids(ws.list_records(include_archived=True)) ==
           {"CR1", "CR2", "CR3"})
    ws.restore(cr1["id"], at="2026-11-08T09:15:00+08:00")
    ensure("restored_status", cr1["status"] == "completed"
           and cr1["status_label"] == "已完成")

    # Append materials: status does not auto-revive; next analysis only new data.
    dup = ws.append_materials(cr1["id"], [MATERIALS["m1"]])
    added = ws.append_materials(cr1["id"], [MATERIALS["m3"]], at="2026-11-08T09:20:00+08:00")
    ensure("append_dedupe", dup["duplicates"] == 1 and dup["added"] == [])
    ensure("append_added", len(added["added"]) == 1 and added["duplicates"] == 0)
    ensure("append_no_auto_status", cr1["status"] == "completed"
           and cr1["incremental_pending"] is True)
    inc = ws.start_analysis(cr1["id"], at="2026-11-08T09:25:00+08:00")
    ensure("incremental_round", inc["round"] == 2 and len(inc["batches"]) == 1)
    ensure("incremental_only_new",
           inc["batches"][0]["material_ids"] == [added["added"][0]["id"]])
    ws.complete_batch(cr1["id"], inc["batches"][0]["batch_id"],
                      questions=[question("请问报表是否放到二期？", "scope_out")],
                      at="2026-11-08T09:30:00+08:00")
    ensure("incremental_partial", cr1["status"] == "partial")
    ws.ask(cr1["id"], "Q4", at="2026-11-08T09:35:00+08:00")
    ws.answer(cr1["id"], "Q4", "报表放二期", [ev("doc://m3#p1", "报表放二期")],
              answered_at="2026-11-08T09:40:00+08:00")
    ensure("incremental_completed", cr1["status"] == "completed")

    # Empty / repeated analysis.
    ensure("copy_unconfirmed", raises("E_SCOPE_NOT_CONFIRMED",
                                      ws.start_analysis, cr3["id"]))
    ws.confirm_scope(cr3["id"], at="2026-11-08T09:45:00+08:00")
    ws.start_analysis(cr3["id"], at="2026-11-08T09:46:00+08:00")
    ensure("copy_analyzing", cr3["status"] == "analyzing")
    ensure("nothing_to_analyze", raises("E_NOTHING_TO_ANALYZE",
                                        ws.start_analysis, cr3["id"]))

    # Delete keeps original materials and hides the work order.
    ensure("delete_confirm", raises("E_CONFIRM_REQUIRED", ws.delete_record, cr2["id"]))
    before_sources = len(ws.sources)
    ws.delete_record(cr2["id"], confirm=True, at="2026-11-08T10:00:00+08:00")
    ensure("deleted_hidden", "CR2" not in ids(ws.list_records()))
    ensure("deleted_visible", "CR2" in ids(ws.list_records(include_deleted=True)))
    ensure("sources_kept", len(ws.sources) == before_sources
           and len(ws.sources_for(cr2["id"])) == 1)
    kept = next(s for s in ws.all_sources() if s["record_id"] == cr2["id"])
    ensure("source_marked_deleted", kept["record_deleted"] is True)
    ensure("deleted_cannot_archive", raises("E_DELETED", ws.archive, cr2["id"]))

    # Internal vs external text.
    internal = ws.render_text(cr1["id"])
    external = ws.render_text(cr1["id"], external=True)
    ensure("internal_has_reason", "提问理由" in internal and "资料未提及" in internal)
    ensure("internal_has_evidence", "证据" in internal and "chat://m1" in internal)
    ensure("external_hides_reason", "提问理由" not in external
           and "资料未提及" not in external)
    ensure("external_hides_evidence", "证据" not in external
           and "chat://m1" not in external and "doc://m3" not in external)
    ensure("external_keeps_content", "扫码巡检" in external and "报表放二期" in external)
    ensure("group_by_customer", "客户：青岚能装备（虚构）" in external)
    by_project = ws.render_text(cr1["id"], group_by="project", external=True)
    ensure("group_by_project", "项目：设备巡检小程序（一期）" in by_project)

    # Word export (zero dependency) and external hiding.
    OUT.mkdir(parents=True, exist_ok=True)
    word_in = ws.export_docx(cr1["id"], OUT / "巡检澄清单-内部.docx")
    word_out = ws.export_docx(cr1["id"], OUT / "巡检澄清单-对外.docx", external=True)
    with zipfile.ZipFile(word_in) as zf:
        xml_in = zf.read("word/document.xml").decode("utf-8")
        has_doc = "word/document.xml" in zf.namelist()
    with zipfile.ZipFile(word_out) as zf:
        xml_out = zf.read("word/document.xml").decode("utf-8")
    ensure("docx_structure", has_doc and word_in.stat().st_size > 1000)
    ensure("docx_internal", "提问理由" in xml_in and "证据" in xml_in
           and "扫码巡检" in xml_in)
    ensure("docx_external", "提问理由" not in xml_out and "证据" not in xml_out
           and "扫码巡检" in xml_out)

    # PDF export through a local headless browser.
    pdf = ws.export_pdf(cr1["id"], OUT / "巡检澄清单-对外.pdf", external=True)
    head = pdf.read_bytes()[:5]
    ensure("pdf_created", pdf.exists() and pdf.stat().st_size > 1500)
    ensure("pdf_header", head == b"%PDF-")

    ensure("status_labels", STATUS_LABELS == {
        "draft": "草稿", "analyzing": "分析中", "partial": "部分完成",
        "incomplete": "未完成", "completed": "已完成", "archived": "已归档"})

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema": "clientgraph.clarification_records.evidence.v1",
        "records": [ws.summary(r["id"]) for r in ws.records],
        "sources": ws.all_sources(),
        "internal_text": internal,
        "external_text": external,
        "exports": {"docx_internal": str(word_in), "docx_external": str(word_out),
                    "pdf_external": str(pdf)},
        "checks": checks,
        "all_passed": all(checks.values()),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("checks:", len(checks), "records:", len(ws.records), "sources:", len(ws.sources))
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
