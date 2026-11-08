# -*- coding: utf-8 -*-
"""Verify question lifecycle: pending / asked / answered / not applicable.

Also checks multiple answer snapshots, evidence citations, and the rule that a
follow-up is created only by an explicit owner action.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clarification.question_lifecycle import (  # noqa: E402
    STATUS_ANSWERED, STATUS_ASKED, STATUS_LABELS, STATUS_NOT_APPLICABLE,
    STATUS_PENDING, LifecycleError, QuestionLedger,
)
from clarification.questions import plan_questions  # noqa: E402

EVIDENCE = ROOT / "evidence" / "question-status-2026-11-08.json"


def context():
    return {
        "project": {"id": "p1", "name": "设备巡检小程序（一期）"},
        "facts": {
            "business_goal": "减少漏检和补记录",
            "metrics": None,
            "users_roles": ["巡检员", "车间主管"],
            "core_flow": "计划生成→扫码巡检→提交→异常处理",
            "scope_in": ["扫码巡检", "异常上报"],
            "scope_out": None,
            "platform": "微信小程序",
            "interaction": None,
            "legacy_data": False,
            "roles": ["巡检员", "车间主管"],
            "personal_data": False,
            "regulated": False,
            "schedule": "2026-11-15",
            "budget": "10 万",
            "contract_required": False,
            "acceptance": None,
            "launch": None,
            "ops": None,
            "after_sales": None,
            "support": None,
        },
        "evidence": {
            "scope_out": [{
                "text": "报表的事还没定，可能后面再加，一期先按不做算",
                "file": "微信聊天-2026-11-02.txt",
                "source_type": "chat",
                "locator": "msg 118",
                "occurred_at": "2026-11-02",
            }],
        },
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
        except LifecycleError as exc:
            return exc.code == code
        return False

    plan = plan_questions(context())
    ledger = QuestionLedger(plan["questions"], now=datetime(2026, 11, 6, 9, 0,
                                                           tzinfo=timezone.utc))
    by_field = {q["field"]: q for q in ledger.questions}

    # Initial state: everything waits to be asked.
    ensure("initial_count", len(ledger.questions) == len(plan["questions"]))
    ensure("initial_pending", all(q["status"] == STATUS_PENDING for q in ledger.questions))
    ensure("status_label_pending", all(q["status_label"] == "待问" for q in ledger.questions))
    ensure("initial_open", ledger.stats()["open"] == len(ledger.questions))
    ensure("initial_resolved_zero", ledger.stats()["resolved"] == 0)

    scope = by_field["scope_out"]
    metrics = by_field["metrics"]
    launch = by_field["launch"]
    interaction = by_field["interaction"]

    # Asked is not done.
    ledger.mark_asked(scope["id"], at="2026-11-06T09:10:00+00:00")
    ensure("asked_status", scope["status"] == STATUS_ASKED)
    ensure("asked_label", scope["status_label"] == "已问")
    ensure("asked_not_resolved", not ledger.is_resolved(scope["id"]))
    ensure("asked_stays_open", scope["id"] in [q["id"] for q in ledger.open_questions()])
    ensure("asked_once", scope["ask_count"] == 1)
    ledger.mark_asked(scope["id"], at="2026-11-06T10:10:00+00:00",
                      operator="小李")
    ensure("reask_keeps_first_time", scope["asked_at"] == "2026-11-06T09:10:00+00:00"
           and scope["ask_count"] == 2)

    # Answer must cite the original question and evidence.
    ensure("answer_requires_asked",
           raises("E_NOT_ASKED", ledger.add_answer, metrics["id"], "第一期不做统计"))
    ledger.mark_asked(metrics["id"], at="2026-11-06T10:20:00+00:00")
    ensure("answer_requires_evidence",
           raises("E_NO_EVIDENCE", ledger.add_answer, metrics["id"], "先看漏检率"))
    answer1 = ledger.add_answer(
        scope["id"], "一期报表不做，放到二期再说", operator="张总",
        answered_at="2026-11-06T11:00:00+00:00",
        recorded_at="2026-11-06T11:05:00+00:00", answer_source="wechat")
    ensure("answer_status", scope["status"] == STATUS_ANSWERED)
    ensure("answer_label", scope["status_label"] == "已回答")
    ensure("answer_resolved", ledger.is_resolved(scope["id"]))
    ensure("answer_cites_question", answer1["question_text"] == scope["text"])
    ensure("answer_cites_evidence", len(answer1["evidence"]) == 1
           and answer1["evidence"][0]["locator"] == "msg 118", answer1["evidence"])
    ensure("answer_keeps_question_evidence", answer1["question_evidence"][0]["file"]
           == "微信聊天-2026-11-02.txt")
    ensure("answer_time_snapshot",
           answer1["answered_at"] == "2026-11-06T11:00:00+00:00"
           and answer1["recorded_at"] == "2026-11-06T11:05:00+00:00"
           and answer1["snapshot_at"] == answer1["recorded_at"])
    ensure("answer_sequence", answer1["sequence"] == 1)

    # Multiple answers are appended, earlier ones untouched.
    extra = {"text": "另外异常上报的统计也先不做", "file": "微信聊天-2026-11-03.txt",
             "locator": "msg 130", "occurred_at": "2026-11-03"}
    answer2 = ledger.add_answer(
        scope["id"], "补充：异常上报的统计也先不做", operator="张总",
        answered_at="2026-11-06T15:00:00+00:00",
        recorded_at="2026-11-06T15:02:00+00:00", evidence=[extra],
        answer_source="wechat")
    extra["locator"] = "MUTATED"
    ensure("answers_appended", len(scope["answers"]) == 2)
    ensure("answer_sequences", [a["sequence"] for a in scope["answers"]] == [1, 2])
    ensure("first_answer_unchanged", scope["answers"][0]["text"] == answer1["text"])
    ensure("latest_answer_pointer", scope["answer"]["id"] == answer2["id"]
           and scope["answer"]["sequence"] == 2)
    ensure("answer_snapshot_isolated", scope["answers"][1]["evidence"][0]["locator"] == "msg 130")
    ensure("resolved_time_kept", scope["resolved_at"] == "2026-11-06T11:00:00+00:00")
    ensure("stats_answers", ledger.stats()["answers"] == 2)

    # No follow-up is generated implicitly.
    ensure("no_auto_followup", scope["child_question_ids"] == []
           and ledger.stats()["followups"] == 0)
    ensure("question_count_unchanged", len(ledger.questions) == len(plan["questions"]))

    # Follow-up requires an answered question.
    ensure("followup_requires_answer",
           raises("E_NOT_ANSWERED", ledger.generate_followup, interaction["id"]))
    ensure("followup_not_for_pending",
           raises("E_NOT_ANSWERED", ledger.generate_followup, launch["id"]))

    # Explicit owner action creates one child question with inherited evidence.
    child = ledger.generate_followup(
        scope["id"], operator="老板", at="2026-11-06T16:00:00+00:00")
    ensure("child_pending", child["status"] == STATUS_PENDING)
    ensure("child_link", child["parent_question_id"] == scope["id"]
           and child["based_on_answer_id"] == answer2["id"])
    ensure("child_generated_from", child["generated_from"] == "followup")
    ensure("child_text_polite", child["text"].startswith("请问")
           and child["text"].count("？") == 1 and len(child["text"]) <= 45, child["text"])
    ensure("child_evidence", len(child["evidence"]) >= 2, child["evidence"])
    ensure("parent_tracks_child", scope["child_question_ids"] == [child["id"]])
    ensure("followup_action_log", len(ledger.followup_actions) == 1
           and ledger.followup_actions[0]["operator"] == "老板")
    ensure("followup_counted", ledger.stats()["followups"] == 1)

    # The owner may write the follow-up text himself.
    child2 = ledger.generate_followup(
        scope["id"], text="请问二期是否确定包含报表功能？", operator="老板",
        at="2026-11-06T16:05:00+00:00")
    ensure("child_custom_text", child2["text"] == "请问二期是否确定包含报表功能？")

    # Not applicable is a resolution and needs a reason.
    ensure("na_requires_reason",
           raises("E_REASON_REQUIRED", ledger.mark_not_applicable, launch["id"], "  "))
    ledger.mark_asked(launch["id"], at="2026-11-06T09:30:00+00:00")
    ledger.mark_not_applicable(launch["id"], "客户内部已定，由甲方自行处理",
                               at="2026-11-06T09:40:00+00:00")
    ensure("na_status", launch["status"] == STATUS_NOT_APPLICABLE)
    ensure("na_label", launch["status_label"] == "不适用")
    ensure("na_resolved", ledger.is_resolved(launch["id"]))
    ensure("na_reason_kept", launch["not_applicable_reason"] == "客户内部已定，由甲方自行处理")
    ensure("na_no_answers", launch["answers"] == [])
    ensure("na_blocks_answer",
           raises("E_NOT_APPLICABLE", ledger.add_answer, launch["id"], "还是做一下吧",
                  evidence=[{"text": "x", "locator": "m1"}]))
    ensure("na_blocks_reask",
           raises("E_ALREADY_RESOLVED", ledger.mark_asked, launch["id"]))
    ensure("followup_not_for_na",
           raises("E_NOT_ANSWERED", ledger.generate_followup, launch["id"]))

    # Answer on a resolved question appends rather than failing.
    answer3 = ledger.add_answer(scope["id"], "再补充一句：报表二期上",
                                operator="张总", answered_at="2026-11-07T09:00:00+00:00",
                                recorded_at="2026-11-07T09:01:00+00:00")
    ensure("third_answer", len(scope["answers"]) == 3 and answer3["sequence"] == 3)

    # Stats stay consistent.
    stats = ledger.stats()
    ensure("stats_partition", stats["questions"] ==
           stats["pending"] + stats["asked"] + stats["answered"] + stats["not_applicable"])
    ensure("stats_open_resolved", stats["open"] + stats["resolved"] == stats["questions"])
    ensure("asked_unanswered_open", metrics["status"] == STATUS_ASKED
           and metrics["id"] in [q["id"] for q in ledger.open_questions()])
    ensure("statuses_complete", set(STATUS_LABELS) ==
           {STATUS_PENDING, STATUS_ASKED, STATUS_ANSWERED, STATUS_NOT_APPLICABLE})

    # Report is a copy and keeps the full history.
    report = ledger.report()
    report_scope = next(q for q in report["questions"] if q["id"] == scope["id"])
    report_scope["answers"].clear()
    ensure("report_isolated", len(scope["answers"]) == 3)
    ensure("report_schema", report["schema"] == "clientgraph.question_status.v1")

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema": "clientgraph.question_status.evidence.v1",
        "ledger": ledger.report(),
        "status_labels": STATUS_LABELS,
        "stats": stats,
        "checks": checks,
        "all_passed": all(checks.values()),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("questions:", stats["questions"], "open:", stats["open"],
          "resolved:", stats["resolved"], "answers:", stats["answers"])
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
