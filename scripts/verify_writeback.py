# -*- coding: utf-8 -*-
"""Verify answer write-back: target selection, preview, confirmation, snapshot."""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from writeback.converter import (  # noqa: E402
    WritebackError, apply_preview, build_preview, suggest_requirement_priority,
)

EVIDENCE = ROOT / "evidence" / "answer-writeback-2026-11-08.json"


def ev(locator: str, text: str) -> dict:
    return {"text": text, "file": "微信聊天-2026-11-07.txt", "source_type": "chat",
            "locator": locator, "occurred_at": "2026-11-07"}


def answer(aid: str, qid: str, label: str, text: str, q_priority: str,
           locator: str) -> dict:
    return {
        "id": aid, "question_id": qid, "question_text": f"请问{label}是什么？",
        "question_field_label": label, "question_priority": q_priority,
        "text": text, "answered_at": "2026-11-07T10:00:00+08:00",
        "operator": "张总", "evidence": [ev(locator, text)],
    }


def store() -> dict:
    requirement = {
        "id": "R1", "customer_id": "c1", "project_id": "p1",
        "title": "设备巡检小程序", "description": "设备台账与扫码巡检",
        "status": "已确认", "priority": "P1", "due_text": None, "owner": "张工",
        "current_version": 1, "review_state": "confirmed",
    }
    project = {
        "id": "p1", "customer_id": "c1", "name": "设备巡检小程序（一期）",
        "budget": {"amount": 80000, "raw": "8 万"}, "schedule": "2026-11-30",
        "platform": "微信小程序", "scope_in": ["扫码巡检"], "scope_out": [],
        "owner": "王工",
    }
    return {
        "customers": [
            {"id": "c1", "name": "青岚能装备（虚构）"},
            {"id": "c2", "name": "恒晟精工（虚构）"},
        ],
        "projects": [
            project,
            {"id": "p2", "customer_id": "c1", "name": "售后工单系统升级"},
            {"id": "p3", "customer_id": "c2", "name": "供应链协同平台（预研）"},
        ],
        "requirements": [requirement],
        "versions": [{"id": "V1", "requirement_id": "R1", "version": 1,
                      "content_json": copy.deepcopy(requirement)}],
        "operations": [],
        "applied_previews": [],
    }


def main() -> int:
    checks = {}

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    def raises(code, fn, *args, **kwargs):
        try:
            fn(*args, **kwargs)
        except WritebackError as exc:
            return exc.code == code
        return False

    data = store()
    catalog = {k: data[k] for k in ("customers", "projects", "requirements")}
    a1 = answer("A1", "Q2", "上线日期", "上线日期定在 2026-12-15，由李工负责",
                "must_confirm", "msg 201")
    a2 = answer("A2", "Q1", "上线日期", "月底前必须上线，二期再优化",
                "must_confirm", "msg 202")
    a3 = answer("A3", "Q5", "外部接口", "必须在上线前完成设备台账对接",
                "later", "msg 203")
    a4 = answer("A4", "Q9", "预算",
                "预算改成 12 万，2026-12-20 上线，平台还是微信小程序，一期不包含报表",
                "important", "msg 204")
    a5 = answer("A5", "Q10", "运维责任", "客户说这个需求不做了", "later", "msg 205")

    # Target must be chosen explicitly and must match.
    ensure("target_required", raises(
        "E_TARGET_REQUIRED", build_preview, a1,
        {"kind": "requirement", "customer_id": "c1"}, catalog))
    ensure("target_mismatch", raises(
        "E_TARGET_MISMATCH", build_preview, a1,
        {"kind": "requirement", "customer_id": "c2", "project_id": "p1"}, catalog))
    ensure("requirement_missing", raises(
        "E_REQUIREMENT_NOT_FOUND", build_preview, a1,
        {"kind": "requirement", "customer_id": "c1", "project_id": "p1",
         "requirement_id": "R9"}, catalog))
    ensure("answer_needs_evidence", raises(
        "E_NO_EVIDENCE", build_preview, {**a1, "evidence": []},
        {"kind": "requirement", "customer_id": "c1", "project_id": "p1"}, catalog))

    # New requirement preview.
    create = build_preview(
        a1, {"kind": "requirement", "customer_id": "c1", "project_id": "p1"},
        catalog, at="2026-11-08T09:00:00+08:00")
    by_field = {f["field"]: f for f in create["fields"]}
    ensure("create_action", create["action"] == "create_requirement")
    ensure("create_target_names", create["target"]["customer_name"] == "青岚能装备（虚构）"
           and create["target"]["project_name"] == "设备巡检小程序（一期）")
    ensure("create_status_pending", create["new_requirement"]["status"] == "待确认"
           and create["new_requirement"]["review_state"] == "pending")
    ensure("create_fields_supported",
           set(by_field) == {"title", "description", "due_text", "owner"}, set(by_field))
    ensure("create_title", by_field["title"]["after"] == "上线日期：2026-12-15",
           by_field["title"]["after"])
    ensure("create_due", by_field["due_text"]["after"] == "2026-12-15")
    ensure("create_owner", by_field["owner"]["after"] == "李工")
    ensure("create_no_status_field", "status" not in by_field)
    ensure("create_skipped_status", any(s["field"] == "status" for s in create["skipped"]))
    ensure("create_evidence", all(f["evidence"][0]["locator"] == "msg 201"
                                  for f in create["fields"]))
    ensure("create_not_written", create["writes"] is False
           and create["requires_confirmation"] is True)
    ensure("create_priority_p1", create["suggested_priority"]["value"] == "P1")

    # Vague date: no deadline prefill, P2 despite a must_confirm question.
    vague = build_preview(
        a2, {"kind": "requirement", "customer_id": "c1", "project_id": "p1"}, catalog)
    vague_fields = {f["field"] for f in vague["fields"]}
    ensure("vague_no_due", "due_text" not in vague_fields)
    ensure("vague_skip_reason", any(s["field"] == "due_text" and "模糊" in s["reason"]
                                    for s in vague["skipped"]))
    partial = build_preview(
        answer("A6", "Q3", "上线日期", "12 月上线", "important", "msg 206"),
        {"kind": "project", "customer_id": "c1", "project_id": "p1"}, catalog)
    ensure("partial_date_not_written",
           all(f["field"] != "schedule" for f in partial["fields"])
           and any(s["field"] == "schedule" and "日期" in s["reason"]
                   for s in partial["skipped"]))

    # Requirement priority is independent from question priority.
    hard = build_preview(
        a3, {"kind": "requirement", "customer_id": "c1", "project_id": "p1"}, catalog)
    ensure("priority_p2_ignores_question",
           vague["suggested_priority"]["value"] == "P2"
           and vague["suggested_priority"]["question_priority_ignored"] == "must_confirm")
    ensure("priority_p0_ignores_question",
           hard["suggested_priority"]["value"] == "P0"
           and hard["suggested_priority"]["question_priority_ignored"] == "later")
    ensure("priority_rule_flag",
           vague["suggested_priority"]["independent_of_question_priority"] is True
           and vague["suggested_priority"]["source"] == "requirement_rule")
    ensure("priority_p1_default",
           suggest_requirement_priority("需要支持扫码巡检")["value"] == "P1")

    # Existing requirement: only supported fields move, status/priority stay.
    update = build_preview(
        a1, {"kind": "requirement", "customer_id": "c1", "project_id": "p1",
             "requirement_id": "R1"}, catalog)
    upd = {f["field"]: f for f in update["fields"]}
    ensure("update_action", update["action"] == "update_requirement")
    ensure("update_fields", set(upd) == {"description", "due_text", "owner"}, set(upd))
    ensure("update_no_status_priority", "status" not in upd and "priority" not in upd)
    ensure("update_before_after",
           upd["owner"]["before"] == "张工" and upd["owner"]["after"] == "李工"
           and upd["due_text"]["before"] is None
           and upd["due_text"]["after"] == "2026-12-15")
    ensure("update_evidence", upd["description"]["evidence"][0]["locator"] == "msg 201")
    ensure("update_no_new_requirement", update["new_requirement"] is None)
    ensure("update_priority_unchanged_in_fields", "priority" not in upd)

    # No-op answer produces no field changes.
    noop_catalog = copy.deepcopy(catalog)
    noop_catalog["requirements"] = [{**copy.deepcopy(catalog["requirements"][0]),
                                     "due_text": "2026-12-15"}]
    noop = build_preview(
        {**a1, "text": "2026-12-15", "evidence": [ev("msg 206", "2026-12-15")]},
        {"kind": "requirement", "customer_id": "c1", "project_id": "p1",
         "requirement_id": "R1"}, noop_catalog)
    ensure("noop_empty", noop["fields"] == [])

    # Project update.
    project_preview = build_preview(
        a4, {"kind": "project", "customer_id": "c1", "project_id": "p1"}, catalog)
    pfields = {f["field"]: f for f in project_preview["fields"]}
    ensure("project_fields", set(pfields) == {"budget", "schedule", "scope_out"},
           set(pfields))
    ensure("project_budget", pfields["budget"]["after"] == {"amount": 120000, "raw": "12 万"})
    ensure("project_schedule", pfields["schedule"]["after"] == "2026-12-20")
    ensure("project_scope_out", pfields["scope_out"]["after"] == ["报表"])
    ensure("project_platform_unchanged", "platform" not in pfields)
    ensure("project_scope_in_unchanged", "scope_in" not in pfields)
    ensure("project_no_requirement_fields",
           "description" not in pfields and "owner" not in pfields)

    # Confirmation is mandatory and the preview cannot be altered.
    ensure("confirm_required", raises(
        "E_CONFIRM_REQUIRED", apply_preview, create, data, "老板", confirm=False))
    ensure("nothing_written", data["operations"] == [] and len(data["requirements"]) == 1)
    ensure("confirmer_required", raises(
        "E_CONFIRMER_REQUIRED", apply_preview, create, data, "  ", confirm=True))
    tampered = copy.deepcopy(create)
    tampered["fields"][0]["after"] = "被改过的标题"
    ensure("preview_tampered", raises(
        "E_PREVIEW_TAMPERED", apply_preview, tampered, data, "老板", confirm=True))
    ensure("token_mismatch", raises(
        "E_PREVIEW_CHANGED", apply_preview, create, data, "老板", confirm=True,
        token="sha256:bad"))

    stale_store = copy.deepcopy(data)
    stale_catalog = {k: stale_store[k] for k in ("customers", "projects", "requirements")}
    stale = build_preview(
        a1, {"kind": "requirement", "customer_id": "c1", "project_id": "p1",
             "requirement_id": "R1"}, stale_catalog)
    stale_store["requirements"][0]["description"] = "被别人改过"
    ensure("stale_target", raises(
        "E_TARGET_CHANGED", apply_preview, stale, stale_store, "老板", confirm=True))
    ensure("stale_not_written", stale_store["operations"] == [])

    # Save new requirement + operation snapshot + version.
    saved = apply_preview(create, data, "老板", confirm=True,
                          token=create["token"], at="2026-11-08T09:05:00+08:00")
    new_req = saved["requirement"]
    op = saved["operation"]
    ensure("new_requirement_saved", new_req["id"] == "R2"
           and new_req["status"] == "待确认" and new_req["priority"] == "P1")
    ensure("new_requirement_meta", new_req["review_state"] == "pending"
           and new_req["origin"] == "clarification"
           and new_req["confirmed_at"] is None
           and new_req["source_question_id"] == "Q2"
           and new_req["source_answer_id"] == "A1")
    ensure("new_requirement_fields", new_req["title"] == "上线日期：2026-12-15"
           and new_req["due_text"] == "2026-12-15" and new_req["owner"] == "李工")
    ensure("new_requirement_version", saved["version"]["version"] == 1
           and saved["version"]["requirement_id"] == "R2")
    ensure("operation_snapshot", op["target_before"] is None
           and op["target_after"]["id"] == "R2"
           and op["confirmed_by"] == "老板"
           and op["evidence"][0]["locator"] == "msg 201"
           and op["applied"] is True)
    ensure("operation_counted", len(data["operations"]) == 1
           and create["preview_id"] in data["applied_previews"])
    ensure("duplicate_blocked", raises(
        "E_ALREADY_APPLIED", apply_preview, create, data, "老板", confirm=True))

    # Save requirement update: untouched fields stay, versions append.
    old_content = copy.deepcopy(data["versions"][0]["content_json"])
    upd_saved = apply_preview(update, data, "老板", confirm=True,
                              at="2026-11-08T09:10:00+08:00")
    r1 = upd_saved["requirement"]
    ensure("update_saved", r1["description"] == a1["text"]
           and r1["due_text"] == "2026-12-15" and r1["owner"] == "李工")
    ensure("update_untouched", r1["status"] == "已确认" and r1["priority"] == "P1"
           and r1["title"] == "设备巡检小程序" and r1["project_id"] == "p1")
    ensure("update_version", r1["current_version"] == 2
           and upd_saved["version"]["version"] == 2)
    ensure("old_version_intact", data["versions"][0]["content_json"] == old_content)
    ensure("update_operation_before", upd_saved["operation"]["target_before"]["owner"] == "张工"
           and upd_saved["operation"]["target_after"]["owner"] == "李工")
    ensure("update_status_snapshot", upd_saved["operation"]["status_after"] == "已确认")

    # Save project update.
    proj_saved = apply_preview(project_preview, data, "老板", confirm=True,
                               at="2026-11-08T09:15:00+08:00")
    p1 = proj_saved["project"]
    ensure("project_saved", p1["budget"]["amount"] == 120000
           and p1["schedule"] == "2026-12-20" and p1["scope_out"] == ["报表"])
    ensure("project_untouched", p1["platform"] == "微信小程序"
           and p1["scope_in"] == ["扫码巡检"] and p1["owner"] == "王工")
    ensure("project_snapshot", proj_saved["operation"]["target_before"]["budget"]["amount"] == 80000
           and proj_saved["operation"]["target_after"]["budget"]["amount"] == 120000)
    snapshot_after = copy.deepcopy(proj_saved["operation"]["target_after"])
    p1["budget"]["amount"] = 1
    ensure("snapshot_isolated", proj_saved["operation"]["target_after"] == snapshot_after)

    # Status is never auto-filled by an answer.
    cancel_preview = build_preview(
        a5, {"kind": "requirement", "customer_id": "c1", "project_id": "p1",
             "requirement_id": "R1"}, {k: data[k] for k in
                                       ("customers", "projects", "requirements")})
    ensure("no_status_prefill", all(f["field"] != "status" for f in cancel_preview["fields"]))
    ensure("status_kept", data["requirements"][0]["status"] == "已确认")

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema": "clientgraph.answer_writeback.evidence.v1",
        "previews": {
            "create_requirement": create,
            "update_requirement": update,
            "update_project": project_preview,
        },
        "operations": copy.deepcopy(data["operations"]),
        "requirements": copy.deepcopy(data["requirements"]),
        "versions": copy.deepcopy(data["versions"]),
        "project": copy.deepcopy(p1),
        "checks": checks,
        "all_passed": all(checks.values()),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("checks:", len(checks), "operations:", len(data["operations"]),
          "requirements:", len(data["requirements"]))
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
