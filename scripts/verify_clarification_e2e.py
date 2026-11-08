# -*- coding: utf-8 -*-
"""End-to-end regression for the clarification assistant (v0.4.0).

Covers: material selection, batching, evidence questions, conflicts, answers,
manual follow-up, write-back preview, history, incremental analysis, failure
retry and external export. Every step is recorded in order; expected failures
are kept in the run record and in a separate failure-case file.
"""
from __future__ import annotations

import json
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clarification.workspace import ClarificationWorkspace, WorkspaceError  # noqa: E402
from writeback.converter import WritebackError, apply_preview, build_preview  # noqa: E402

RUN_EVIDENCE = ROOT / "evidence" / "clarification-e2e-2026-11-08.json"
FAIL_EVIDENCE = ROOT / "evidence" / "clarification-failures-2026-11-08.json"
OUT = ROOT / ".temp" / "e2e-exports"
BASE = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)


def ts(minutes: int) -> str:
    return (BASE + timedelta(minutes=minutes)).isoformat()


def aev(locator: str, text: str) -> dict:
    return {"text": text, "file": "微信聊天-2026-11-07.txt", "source_type": "chat",
            "locator": locator, "occurred_at": "2026-11-07"}


def question(text, cid, pid, priority="important", evidence=None,
             reason="资料未提及", field="scope_in", label="本期包含",
             conclusion="fact", confidence=0.9, low=False, conflict=None) -> dict:
    return {
        "text": text, "customer_id": cid, "project_id": pid,
        "priority": priority, "dimension": "scope", "field": field,
        "field_label": label, "reason": reason,
        "conclusion_type": conclusion, "confidence": confidence,
        "low_confidence": low, "evidence": evidence or [],
        "conflict_evidence": conflict,
    }


def main() -> int:
    checks = {}
    steps, failures = [], []

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    def log(phase, action, status="pass", detail=None):
        steps.append({"seq": len(steps) + 1, "at": ts(len(steps)), "phase": phase,
                      "action": action, "status": status, "detail": detail})

    def expect(code, phase, action, fn, recovered_by, *args, **kwargs):
        actual = None
        try:
            fn(*args, **kwargs)
        except (WorkspaceError, WritebackError) as exc:
            actual = exc.code
        except Exception as exc:  # noqa: BLE001
            actual = getattr(exc, "code", type(exc).__name__)
        ok = actual == code
        log(phase, action, "pass" if ok else "fail",
            {"expected": code, "actual": actual})
        ensure(f"failure_case_{len(failures) + 1}", ok, actual)
        failures.append({
            "id": f"F{len(failures) + 1}",
            "phase": phase,
            "action": action,
            "expected_code": code,
            "observed_code": actual,
            "recovered_by": recovered_by,
            "step": len(steps),
            "retained": True,
            "at": ts(len(steps)),
        })
        return actual

    ws = ClarificationWorkspace(now=BASE)
    c1 = {"id": "c1", "name": "青岚能装备（虚构）"}
    c2 = {"id": "c2", "name": "恒晟精工（虚构）"}
    p1 = {"id": "p1", "name": "设备巡检小程序（一期）"}
    p3 = {"id": "p3", "name": "供应链协同平台（预研）"}

    materials = [
        {"source_id": "m1", "name": "微信聊天-巡检", "type": "chat",
         "locator": "chat://m1#msg=1", "text": "一期先做扫码巡检", "sha256": "a1",
         "customer_id": "c1", "project_id": "p1"},
        {"source_id": "m2", "name": "需求确认单-2026-10-20.docx", "type": "doc",
         "locator": "doc://m2#p3", "text": "上线日期 2026-11-15", "sha256": "a2",
         "customer_id": "c1", "project_id": "p1"},
        {"source_id": "m3", "name": "邮件-供应链", "type": "email",
         "locator": "mail://m3#text", "text": "对接 ERP 接口", "sha256": "a3",
         "customer_id": "c2", "project_id": "p3"},
    ]

    # 1. Selection and scope confirmation.
    record = ws.create_record(
        {"customers": [c1, c2], "projects": [p1, p3]}, materials,
        name="巡检与供应链澄清（虚构演示）", model={"max_input_chars": 20},
        created_at=ts(0))
    rid = record["id"]
    log("选材确认", "选择 2 个客户 / 2 个项目 / 3 份资料，建单", detail={
        "record_id": rid, "sources": len(ws.sources_for(rid))})
    ensure("selection_sources", len(ws.sources_for(rid)) == 3)
    ensure("initial_draft", record["status"] == "draft")

    ws.confirm_scope(rid, at=ts(1))
    log("选材确认", "确认发送范围，记录 confirmed_scope_at",
        detail={"confirmed_scope_at": record["confirmed_scope_at"]})
    ensure("scope_confirmed", bool(record["confirmed_scope_at"]))

    # 2. Batch analysis.
    started = ws.start_analysis(rid, at=ts(2))
    ensure("batch_split", len(started["batches"]) == 3,
           [b["batch_id"] for b in started["batches"]])
    ensure("analyzing", record["status"] == "analyzing")
    log("分批分析", "按 20 字上限拆成 3 批，只分析本轮资料", detail={
        "batches": [b["batch_id"] for b in started["batches"]],
        "status": record["status"]})

    conf = [{
        "id": "K1", "dimension": "timeline", "value_a": {
            "raw": "2026-11-15", "file": "需求确认单-2026-10-20.docx",
            "locator": "第 3 页", "occurred_at": "2026-10-20"},
        "value_b": {"raw": "2026-12-01", "file": "微信聊天-2026-11-02.txt",
                    "locator": "msg 120", "occurred_at": "2026-11-02"},
        "resolution": None, "write_blocked": True,
    }]

    ws.complete_batch(rid, "R1-B1", questions=[
        question("请问一期必须包含哪些功能？", "c1", "p1", "must_confirm",
                 [aev("chat://m1#msg=1", "一期先做扫码巡检")],
                 field="scope_in", label="本期包含"),
        question("请问对审计和脱敏有什么要求？", "c1", "p1", "important",
                 [{"text": "要能看到谁改过记录", "file": "会议录音.m4a",
                   "source_type": "asr", "locator": "file://m4a#t=1200-1800",
                   "occurred_at": "2026-10-30", "confidence": 0.42}],
                 field="security", label="安全要求", confidence=0.55, low=True),
    ], at=ts(3))

    ws.complete_batch(rid, "R1-B2", questions=[
        question("请问一期上线日期是哪一天？", "c1", "p1", "must_confirm",
                 [aev("doc://m2#p3", "上线日期 2026-11-15")],
                 reason="资料存在冲突，需人工确认", field="schedule",
                 label="上线日期", conclusion="unknown", confidence=0.3,
                 low=True, conflict=conf),
        question("请问需要对接哪些外部系统？", "c2", "p3", "must_confirm",
                 [aev("mail://m3#text", "对接 ERP 接口")],
                 field="interfaces", label="外部接口"),
    ], at=ts(4))

    ws.complete_batch(rid, "R1-B3", questions=[
        question("请问以哪些条件作为验收标准？", "c1", "p1", "important",
                 [], field="acceptance", label="验收标准",
                 conclusion="unknown", confidence=0.2, low=True),
    ], at=ts(5))

    ensure("incomplete_after_batches", record["status"] == "incomplete")
    ensure("question_count_5", len(ws.ledger(rid).questions) == 5)
    log("证据问题", "3 批共生成 5 个问题，含 ASR 低置信度与工期冲突", detail={
        "questions": [q["id"] for q in ws.ledger(rid).questions],
        "status": record["status"]})

    # 3. Answers, not applicable, conflict retained.
    for qid in ("Q1", "Q2", "Q3", "Q4", "Q5"):
        ws.ask(rid, qid, at=ts(6))
    log("回答", "5 个问题全部标记已问", detail={"status": record["status"]})

    ws.answer(rid, "Q1", "扫码巡检与异常上报", [aev("chat://m1#msg=2", "扫码巡检")],
              answered_at=ts(7))
    ws.mark_not_applicable(rid, "Q2", "本期不涉及个人数据审计", at=ts(8))
    ws.answer(rid, "Q3", "以 2026-12-01 为准，11-15 是旧口径",
              [aev("chat://m1#msg=120", "以 12-01 为准")], answered_at=ts(9))
    ws.answer(rid, "Q4", "对接 ERP 与钉钉", [aev("mail://m3#reply", "ERP 与钉钉")],
              answered_at=ts(10))
    ensure("partial_with_open_q5", record["status"] == "partial"
           and ws.summary(rid)["open"] == 1)
    conflict_q = ws.ledger(rid).questions[2]
    ensure("conflict_kept", conflict_q["conflict_evidence"][0]["value_a"]["raw"] == "2026-11-15"
           and conflict_q["conflict_evidence"][0]["value_b"]["raw"] == "2026-12-01"
           and conflict_q["conflict_evidence"][0]["resolution"] is None)
    log("冲突", "工期冲突双方证据保留，回答后仍未自动裁定", detail={
        "question": conflict_q["id"], "status": record["status"]})

    # 4. Manual follow-up only.
    ensure("no_auto_followup", ws.ledger(rid).questions[0]["child_question_ids"] == [])
    child = ws.generate_followup(rid, "Q1", text="请问扫码巡检是否需要拍照留痕？",
                                 operator="老板", at=ts(11))
    ensure("followup_pending", child["status"] == "pending"
           and child["parent_question_id"] == "Q1")
    log("手动追问", "老板点击后生成 1 个待问子问题", detail={
        "child": child["id"], "parent": "Q1"})
    ws.ask(rid, "Q6", at=ts(12))
    ws.answer(rid, "Q6", "需要拍照留痕", [aev("chat://m1#msg=130", "拍照留痕")],
              answered_at=ts(13))

    # 5. Write-back preview and history.
    store = {
        "customers": [c1, c2],
        "projects": [{**p1, "customer_id": "c1", "budget": {"amount": 80000, "raw": "8 万"},
                      "schedule": "2026-11-30", "platform": "微信小程序",
                      "scope_in": [], "scope_out": []},
                     {**p3, "customer_id": "c2"}],
        "requirements": [], "versions": [], "operations": [], "applied_previews": [],
    }
    catalog = {k: store[k] for k in ("customers", "projects", "requirements")}
    answer1 = ws.ledger(rid).questions[0]["answers"][-1]
    preview = build_preview(answer1, {"kind": "requirement", "customer_id": "c1",
                                      "project_id": "p1"}, catalog, at=ts(14))
    ensure("preview_supported_only",
           set(f["field"] for f in preview["fields"]) == {"title", "description"},
           [f["field"] for f in preview["fields"]])
    ensure("preview_pending_status", preview["new_requirement"]["status"] == "待确认")
    ensure("preview_priority", preview["suggested_priority"]["value"] == "P1")
    log("回写预览", "展示标题/描述两项变更与证据，状态待确认", detail={
        "fields": [f["field"] for f in preview["fields"]],
        "priority": preview["suggested_priority"]["value"]})

    saved = apply_preview(preview, store, "老板", confirm=True,
                          token=preview["token"], at=ts(15))
    ensure("requirement_created", saved["requirement"]["status"] == "待确认"
           and saved["requirement"]["current_version"] == 1)
    log("回写保存", "人工确认后创建需求 R1 与版本 V1", detail={
        "requirement": saved["requirement"]["id"],
        "version": saved["version"]["version"]})

    answer3 = ws.ledger(rid).questions[2]["answers"][-1]
    upd = build_preview(answer3, {"kind": "requirement", "customer_id": "c1",
                                  "project_id": "p1", "requirement_id": "R1"},
                         {k: store[k] for k in ("customers", "projects", "requirements")},
                         at=ts(16))
    ensure("update_only_due", [f["field"] for f in upd["fields"]] == ["due_text"],
           [f["field"] for f in upd["fields"]])
    upd_saved = apply_preview(upd, store, "老板", confirm=True,
                              token=upd["token"], at=ts(17))
    ensure("version_appended", upd_saved["version"]["version"] == 2
           and store["versions"][0]["content_json"]["due_text"] is None)
    log("历史", "同一需求追加版本 V2，V1 内容保持不变", detail={
        "version": upd_saved["version"]["version"]})

    proj = build_preview(answer3, {"kind": "project", "customer_id": "c1",
                                   "project_id": "p1"},
                          {k: store[k] for k in ("customers", "projects", "requirements")},
                          at=ts(18))
    ensure("project_schedule_only", [f["field"] for f in proj["fields"]] == ["schedule"])
    proj_saved = apply_preview(proj, store, "老板", confirm=True,
                               token=proj["token"], at=ts(19))
    ensure("project_updated", proj_saved["project"]["schedule"] == "2026-12-01"
           and proj_saved["project"]["budget"]["amount"] == 80000)
    log("回写保存", "更新项目工期，预算等其他字段保持原值", detail={
        "project": proj_saved["project"]["id"]})

    # 6. Incremental analysis.
    appended = ws.append_materials(rid, [{
        "source_id": "m4", "name": "会议纪要-补充", "type": "doc",
        "locator": "doc://m4#p1", "text": "报表放到二期", "sha256": "a4",
        "customer_id": "c1", "project_id": "p1"}], at=ts(20))
    ensure("incremental_added", len(appended["added"]) == 1)
    ensure("status_not_revived", record["status"] == "partial")
    inc = ws.start_analysis(rid, at=ts(21))
    ensure("incremental_only_new", inc["round"] == 2
           and inc["batches"][0]["material_ids"] == [appended["added"][0]["id"]])
    ws.complete_batch(rid, inc["batches"][0]["batch_id"], questions=[
        question("请问报表是否确定放到二期？", "c1", "p1", "important",
                 [aev("doc://m4#p1", "报表放到二期")],
                 field="scope_out", label="本期不包含"),
    ], at=ts(22))
    ws.ask(rid, "Q7", at=ts(22))
    ws.answer(rid, "Q7", "报表放二期", [aev("doc://m4#p1", "报表放到二期")],
              answered_at=ts(23))
    ensure("still_open_q5", record["status"] == "partial")
    log("增量分析", "追加资料只分析新增 1 份，Q5 仍待回答，状态保持部分完成", detail={
        "round": inc["round"], "status": record["status"]})

    # 7. Failure cases kept, then recovered.
    bad = ws.create_record({"customers": [c1], "projects": [p1]},
                           [{"source_id": "m9", "name": "损坏的合同.pdf", "type": "pdf",
                             "locator": "file://m9", "text": "", "readable": False,
                             "sha256": "bad"}], created_at=ts(25))
    ws.confirm_scope(bad["id"], at=ts(26))
    expect("E_UNREADABLE", "选材确认", "不可读资料阻止发送",
           ws.start_analysis, "保留工作单作为失败样本，不删除", bad["id"])
    ensure("bad_record_kept", bad["status"] == "draft"
           and "E_UNREADABLE" in (bad["error_message"] or ""))

    retry = ws.create_record({"customers": [c1], "projects": [p1]},
                             [{"source_id": "m5", "name": "聊天-异常上报", "type": "chat",
                               "locator": "chat://m5", "text": "需要异常上报",
                               "sha256": "a5"}], created_at=ts(27))
    ws.confirm_scope(retry["id"], at=ts(28))
    retry_batch = ws.start_analysis(retry["id"], at=ts(29))["batches"][0]["batch_id"]
    ws.fail_batch(retry["id"], retry_batch, "E_MODEL_TIMEOUT", "批次超时",
                  at=ts(30))
    ensure("failed_status", retry["status"] == "incomplete"
           and retry["error_message"].startswith("E_MODEL_TIMEOUT"))
    log("失败重试", "模型批次超时，工作单保留失败原因", status="fail", detail={
        "batch": retry_batch, "code": "E_MODEL_TIMEOUT"})
    failures.append({
        "id": f"F{len(failures) + 1}",
        "phase": "失败重试",
        "action": "模型批次超时",
        "expected_code": "E_MODEL_TIMEOUT",
        "observed_code": "E_MODEL_TIMEOUT",
        "recovered_by": "retry_failed 重置失败批次后重新完成",
        "step": len(steps),
        "retained": True,
        "at": ts(len(steps)),
    })
    expect("E_NOT_ANSWERED", "手动追问", "未回答不能生成追问",
           ws.generate_followup, "先完成回答再生成追问", rid, "Q5")
    retried = ws.retry_failed(retry["id"], at=ts(31))
    ensure("retry_pending", retried == [retry_batch]
           and retry["status"] == "analyzing")
    log("失败重试", "失败批次重置为待执行，保留错误历史", detail={
        "batch": retry_batch, "batch_errors": len(retry["batch_errors"])})
    ws.complete_batch(retry["id"], retry_batch,
                      questions=[question("请问异常上报需要哪些字段？", "c1", "p1")],
                      at=ts(32))
    ws.ask(retry["id"], "Q1", at=ts(33))
    ws.answer(retry["id"], "Q1", "设备编号、照片、描述",
              [aev("chat://m5#1", "设备编号、照片、描述")], answered_at=ts(34))
    ensure("retry_completed", retry["status"] == "completed")

    answer_retry = ws.ledger(retry["id"]).questions[0]["answers"][-1]
    retry_preview = build_preview(
        answer_retry, {"kind": "requirement", "customer_id": "c1", "project_id": "p1"},
        {k: store[k] for k in ("customers", "projects", "requirements")}, at=ts(35))
    ops_before = len(store["operations"])
    expect("E_CONFIRM_REQUIRED", "回写预览", "未确认不能保存",
           apply_preview, "演示环境拒绝写入，数据零变化",
           retry_preview, store, "老板", confirm=False)
    ensure("no_write_without_confirm", len(store["operations"]) == ops_before)

    tampered = json.loads(json.dumps(retry_preview, ensure_ascii=False))
    tampered["fields"][0]["after"] = "被篡改的标题"
    expect("E_PREVIEW_TAMPERED", "回写预览", "预览被修改后拒绝保存",
           apply_preview, "重新生成预览", tampered, store, "老板", confirm=True)

    stale_store = json.loads(json.dumps(store, ensure_ascii=False))
    stale_preview = build_preview(
        answer3, {"kind": "requirement", "customer_id": "c1", "project_id": "p1",
                  "requirement_id": "R1"},
        {k: stale_store[k] for k in ("customers", "projects", "requirements")},
        at=ts(36))
    stale_store["requirements"][0]["description"] = "预览后被人改动"
    expect("E_TARGET_CHANGED", "回写预览", "目标记录变化后拒绝保存",
           apply_preview, "重新预览", stale_preview, stale_store, "老板", confirm=True)

    retry_saved = apply_preview(retry_preview, store, "老板", confirm=True,
                                token=retry_preview["token"], at=ts(37))
    ensure("retry_writeback_saved", retry_saved["requirement"]["status"] == "待确认")
    expect("E_ALREADY_APPLIED", "回写预览", "同一预览不能重复保存",
           apply_preview, "使用新的预览", retry_preview, store, "老板",
           confirm=True, token=retry_preview["token"])

    # 8. External export.
    ws.answer(rid, "Q5", "以验收清单签字为准",
              [aev("chat://m1#msg=140", "验收清单签字")], answered_at=ts(38))
    ensure("completed_after_all", record["status"] == "completed")
    log("回答", "补答最后的验收问题，状态转为已完成", detail={
        "question": "Q5", "status": record["status"]})

    internal_text = ws.render_text(rid)
    external_text = ws.render_text(rid, external=True)
    ensure("internal_has_reason", "提问理由" in internal_text)
    ensure("internal_has_evidence", "证据" in internal_text and "chat://m1" in internal_text)
    ensure("external_hides_internal", "提问理由" not in external_text
           and "证据" not in external_text and "chat://m1" not in external_text)
    ensure("external_keeps_answer", "扫码巡检与异常上报" in external_text
           and "2026-12-01" in external_text)
    by_project = ws.render_text(rid, group_by="project", external=True)
    ensure("group_by_project", "项目：设备巡检小程序（一期）" in by_project)

    OUT.mkdir(parents=True, exist_ok=True)
    docx_in = ws.export_docx(rid, OUT / "澄清记录-内部.docx")
    docx_out = ws.export_docx(rid, OUT / "澄清记录-对外.docx", external=True)
    with zipfile.ZipFile(docx_in) as zf:
        xml_in = zf.read("word/document.xml").decode("utf-8")
    with zipfile.ZipFile(docx_out) as zf:
        xml_out = zf.read("word/document.xml").decode("utf-8")
    ensure("docx_internal", "提问理由" in xml_in and "证据" in xml_in)
    ensure("docx_external", "提问理由" not in xml_out and "证据" not in xml_out
           and "扫码巡检" in xml_out)
    pdf = ws.export_pdf(rid, OUT / "澄清记录-对外.pdf", external=True)
    ensure("pdf_valid", pdf.read_bytes()[:5] == b"%PDF-" and pdf.stat().st_size > 1500)
    log("对外导出", "内部/对外文本与 Word、PDF 均生成，对外版隐藏理由与证据", detail={
        "docx_internal": str(docx_in), "docx_external": str(docx_out),
        "pdf": str(pdf), "pdf_size": pdf.stat().st_size})

    # 9. Lifecycle smoke: archive/restore, copy, delete keeps sources.
    ws.archive(rid, at=ts(40))
    ensure("archive_hidden", rid not in {r["id"] for r in ws.list_records()})
    ws.restore(rid, at=ts(41))
    ensure("restore_completed", ws.record(rid)["status"] == "completed")
    copy = ws.copy_as_draft(rid, at=ts(42))
    ensure("copy_draft", copy["status"] == "draft"
           and len(ws.ledger(copy["id"]).questions) == 7
           and ws.ledger(copy["id"]).questions[0]["status"] == "pending")
    before_sources = len(ws.sources)
    ws.delete_record(copy["id"], confirm=True, at=ts(43))
    ensure("delete_keeps_sources", len(ws.sources) == before_sources
           and copy["id"] in {r["id"] for r in ws.list_records(include_deleted=True)})
    log("生命周期", "归档/恢复/复制草稿/删除保留资料冒烟通过", detail={
        "archived": True, "restored": True, "copy": copy["id"]})

    run = {
        "schema": "clientgraph.clarification_e2e.v1",
        "run_id": "CLARIFY-E2E-2026-11-08",
        "started_at": ts(0),
        "finished_at": ts(45),
        "environment": {"platform": "Windows", "python": sys.version.split()[0],
                        "pdf_engine": "Edge headless"},
        "data_note": "全部客户、项目、资料均为虚构演示数据",
        "steps": steps,
        "failures": failures,
        "records": [{
            "id": r["id"], "name": r["name"], "status": r["status"],
            "status_label": r["status_label"], "status_history": r["status_history"],
            "error_message": r["error_message"],
            "questions": ws.summary(r["id"])["questions"],
            "open": ws.summary(r["id"])["open"],
            "deleted_at": r["deleted_at"],
        } for r in ws.records],
        "writeback": {
            "requirements": store["requirements"],
            "versions": [{"id": v["id"], "requirement_id": v["requirement_id"],
                          "version": v["version"], "change_reason": v["change_reason"],
                          "adopted_at": v["adopted_at"]} for v in store["versions"]],
            "operations": [{"id": o["id"], "action": o["action"],
                            "requirement_id": o["requirement_id"],
                            "confirmed_by": o["confirmed_by"],
                            "confirmed_at": o["confirmed_at"]} for o in store["operations"]],
        },
        "exports": {
            "docx_internal": {"name": docx_in.name, "bytes": docx_in.stat().st_size},
            "docx_external": {"name": docx_out.name, "bytes": docx_out.stat().st_size},
            "pdf": {"name": pdf.name, "bytes": pdf.stat().st_size},
            "note": "导出产物在 .temp/e2e-exports，不纳入版本库",
        },
        "checks": checks,
        "all_passed": all(checks.values()),
    }
    failures_doc = {
        "schema": "clientgraph.clarification_failures.v1",
        "run_id": run["run_id"],
        "note": "失败案例全部保留，不删除；用于回归对照",
        "cases": failures,
    }
    RUN_EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    RUN_EVIDENCE.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    FAIL_EVIDENCE.write_text(json.dumps(failures_doc, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("steps:", len(steps), "failures kept:", len(failures),
          "checks:", len(checks), "passed:", sum(checks.values()))
    print("evidence:", RUN_EVIDENCE)
    return 0 if run["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
