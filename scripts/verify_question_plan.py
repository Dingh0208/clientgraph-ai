# -*- coding: utf-8 -*-
"""Verify three-tier question priority plus evidence and confidence fields.

Tiers: must_confirm (blocks scope/quote/schedule), important (affects solution
or cost), later (delivery/ops). Every question must expose its source excerpt,
source time, reason, fact/inference/unknown marker and a low-confidence hint.
A conflict must keep both sides and must never be auto-resolved.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clarification.questions import (  # noqa: E402
    DIMENSIONS, PRIORITY_LABELS, plan_questions,
)

EVIDENCE = ROOT / "evidence" / "question-priority-2026-11-06.json"
TIERS = {"must_confirm", "important", "later"}
CONCLUSIONS = {"fact", "inference", "unknown"}


def base_context():
    return {
        "project": {"id": "p1", "name": "设备巡检小程序（一期）", "type": "internal_tool"},
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
            "migration_source": None,
            "migration_scope": None,
            "interfaces": [],
            "third_party": [],
            "roles": ["巡检员", "车间主管"],
            "personal_data": False,
            "regulated": False,
            "performance": None,
            "reliability": None,
            "schedule": "2026-11-15",
            "budget": "10 万",
            "contract_required": False,
            "acceptance": None,
            "launch": None,
            "ops": None,
            "after_sales": None,
            "support": None,
        },
        "gaps": [],
        "evidence": {
            "business_goal": [{
                "text": "老板说主要是别再漏检了，补记录太费时间",
                "file": "会议纪要-2026-10-28.md",
                "source_type": "document",
                "locator": "line 12",
                "occurred_at": "2026-10-28",
            }],
            "scope_out": [{
                "text": "报表的事还没定，可能后面再加，一期先按不做算",
                "file": "微信聊天-2026-11-02.txt",
                "source_type": "chat",
                "locator": "msg 118",
                "occurred_at": "2026-11-02",
            }],
            "security": [{
                "text": "要能看到谁改过巡检记录",
                "file": "会议录音-2026-10-30.m4a",
                "source_type": "asr",
                "locator": "file://会议录音-2026-10-30.m4a#t=12000-18000",
                "occurred_at": "2026-10-30",
                "confidence": 0.42,
            }],
        },
        "conflicts": [],
    }


def conflict_context():
    ctx = base_context()
    ctx["conflicts"] = [
        {
            "id": "K1", "dimension": "timeline", "status": "must_confirm",
            "value_a": {"raw": "2026-11-15", "normalized": "2026-11-15",
                        "source": {"file": "需求确认单-2026-10-20.docx",
                                   "locator": "第 3 页",
                                   "occurred_at": "2026-10-20"}},
            "value_b": {"raw": "2026-12-01", "normalized": "2026-12-01",
                        "source": {"file": "微信聊天-2026-11-02.txt",
                                   "locator": "msg 120",
                                   "occurred_at": "2026-11-02"}},
            "resolution": None, "write_blocked": True,
        },
        {
            "id": "K2", "dimension": "interface", "status": "must_confirm",
            "excerpt_a": "要对接钉钉审批",
            "excerpt_b": "不用对接审批，先在系统里点通过就行",
            "value_a": {"raw": "钉钉", "normalized": "钉钉",
                        "source": {"file": "会议纪要-2026-10-28.md",
                                   "locator": "line 40",
                                   "occurred_at": "2026-10-28"}},
            "value_b": {"raw": "无", "normalized": "无",
                        "source": {"file": "微信聊天-2026-11-02.txt",
                                   "locator": "msg 121",
                                   "occurred_at": "2026-11-02"}},
            "resolution": None, "write_blocked": True,
        },
    ]
    return ctx


def main() -> int:
    checks = {}

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    def field_of(plan, field):
        return next(q for q in plan["questions"] if q["field"] == field)

    plan = plan_questions(base_context())
    shown = [d["id"] for d in plan["dimensions"]]
    hidden = [d["id"] for d in plan["hidden_dimensions"]]
    ensure("dimension_order", shown == ["goals", "users", "scope", "platform",
                                        "governance", "commercial", "delivery"], shown)
    ensure("hidden_irrelevant", set(hidden) == {"migration", "interfaces", "quality"}, hidden)
    ensure("users_clear", next(d for d in plan["dimensions"] if d["id"] == "users")["status"] == "clear")
    ensure("no_contract_question", not any(q["field"] == "contract" for q in plan["questions"]))
    ensure("question_count", len(plan["questions"]) == 10, len(plan["questions"]))
    ensure("question_ids", [q["id"] for q in plan["questions"]] ==
           [f"Q{i}" for i in range(1, 11)])

    for q in plan["questions"]:
        ensure("polite", q["text"].startswith("请问"), q["text"])
        ensure("one_question_mark", q["text"].count("？") == 1, q["text"])
        ensure("single_topic", not any(w in q["text"] for w in ("以及", "还是", "分别")), q["text"])
        ensure("concise", len(q["text"]) <= 45, q["text"])
        ensure("has_reason", bool(q["reason"]))
        ensure("priority_tier_valid", q["priority"] in TIERS, q["priority"])
        ensure("priority_label", q["priority_label"] == PRIORITY_LABELS[q["priority"]], q["field"])
        ensure("priority_basis", bool(q["priority_basis"]), q["field"])
        ensure("conclusion_type_valid", q["conclusion_type"] in CONCLUSIONS, q["field"])
        ensure("confidence_range", isinstance(q["confidence"], (int, float))
               and 0 <= q["confidence"] <= 1, q["field"])
        ensure("low_confidence_consistent",
               q["low_confidence"] == (q["confidence"] < 0.6), q["field"])
        ensure("evidence_is_list", isinstance(q["evidence"], list), q["field"])
        ensure("source_time_key", "source_time" in q, q["field"])
        ensure("conflict_key", "conflict_evidence" in q, q["field"])
        if q["low_confidence"]:
            ensure("low_confidence_hint", bool(q["confidence_note"]), q["field"])

    # Tier distribution for the base project.
    prio = plan["stats"]["priorities"]
    ensure("must_confirm_blocks_scope", prio["must_confirm"] == 1
           and field_of(plan, "scope_out")["priority"] == "must_confirm", prio)
    ensure("important_counts", prio["important"] == 5, prio)
    ensure("later_delivery_only",
           {q["field"] for q in plan["questions"] if q["priority"] == "later"} ==
           {"launch", "ops", "after_sales", "support"}, prio)
    ensure("later_label", field_of(plan, "ops")["priority_label"] == "后续确认")
    ensure("priority_stats_total",
           sum(prio.values()) == len(plan["questions"]), prio)

    # Evidence / conclusion / confidence behaviour.
    metrics = field_of(plan, "metrics")
    ensure("unknown_when_no_evidence",
           metrics["conclusion_type"] == "unknown" and metrics["low_confidence"]
           and metrics["evidence"] == [], metrics)

    scope_out = field_of(plan, "scope_out")
    ensure("fact_with_excerpt", scope_out["conclusion_type"] == "fact"
           and scope_out["excerpt"].startswith("报表的事还没定"), scope_out)
    ensure("excerpt_source", scope_out["evidence"][0]["file"] == "微信聊天-2026-11-02.txt"
           and scope_out["evidence"][0]["locator"] == "msg 118", scope_out["evidence"])
    ensure("source_time", scope_out["source_time"] == "2026-11-02", scope_out["source_time"])

    security = field_of(plan, "security")
    ensure("weak_asr_marks_low", security["conclusion_type"] == "fact"
           and security["low_confidence"] and security["confidence"] <= 0.55, security)
    ensure("weak_asr_note", "转写" in (security["confidence_note"] or ""),
           security["confidence_note"])

    # Conflicts keep both sides, block writing, never auto-resolve.
    cplan = plan_questions(conflict_context())
    sched = field_of(cplan, "schedule")
    ensure("conflict_question_shown", "commercial" in [d["id"] for d in cplan["dimensions"]])
    ensure("conflict_priority", sched["priority"] == "must_confirm", sched["priority"])
    ensure("conflict_conclusion_unknown", sched["conclusion_type"] == "unknown")
    ensure("conflict_low", sched["low_confidence"])
    ensure("conflict_keeps_both_sides", len(sched["conflict_evidence"]) == 1
           and sched["conflict_evidence"][0]["value_a"]["raw"] == "2026-11-15"
           and sched["conflict_evidence"][0]["value_b"]["raw"] == "2026-12-01",
           sched["conflict_evidence"])
    ensure("conflict_sources_kept",
           sched["conflict_evidence"][0]["value_a"]["file"] == "需求确认单-2026-10-20.docx"
           and sched["conflict_evidence"][0]["value_b"]["occurred_at"] == "2026-11-02")
    ensure("conflict_not_resolved",
           sched["conflict_evidence"][0]["resolution"] is None
           and sched["conflict_evidence"][0]["write_blocked"] is True)
    ensure("conflict_reason", sched["reason"] == "资料存在冲突，需人工确认", sched["reason"])
    ensure("conflict_excerpt", sched["excerpt"] == "2026-11-15 / 2026-12-01", sched["excerpt"])
    ensure("conflict_note", "冲突" in (sched["confidence_note"] or ""))

    # A conflict can force a normally hidden dimension to appear.
    iface = field_of(cplan, "interfaces")
    ensure("conflict_shows_hidden_dimension",
           "interfaces" in [d["id"] for d in cplan["dimensions"]])
    ensure("conflict_excerpt_fallback", iface["conflict_evidence"][0]["value_a"]["text"] == "要对接钉钉审批"
           and iface["conflict_evidence"][0]["value_b"]["text"] == "不用对接审批，先在系统里点通过就行")

    # Explicit gap still works and now carries evidence metadata.
    ctx = base_context()
    ctx["gaps"] = [{"dimension": "migration", "field": "migration_source",
                    "reason": "客户提到旧系统，但未说明来源"}]
    with_gap = plan_questions(ctx)
    ensure("gap_shows_migration", "migration" in [d["id"] for d in with_gap["dimensions"]])
    ensure("gap_question", any(q["field"] == "migration_source" for q in with_gap["questions"]))
    ensure("gap_reason", any(q["reason"] == "客户提到旧系统，但未说明来源"
                            for q in with_gap["questions"]))
    gap_q = next(q for q in with_gap["questions"] if q["field"] == "migration_source")
    ensure("gap_is_inference", gap_q["conclusion_type"] == "inference"
           and gap_q["low_confidence"], gap_q["conclusion_type"])
    ensure("gap_hidden_count", len(with_gap["hidden_dimensions"]) == 2)

    # Filling a fact removes its question while keeping the dimension visible.
    ctx2 = base_context()
    ctx2["facts"]["metrics"] = "漏检率、巡检完成率"
    filled = plan_questions(ctx2)
    ensure("filled_removes_question", not any(q["field"] == "metrics" for q in filled["questions"]))
    ensure("goals_still_shown", "goals" in [d["id"] for d in filled["dimensions"]])
    ensure("goals_clear", next(d for d in filled["dimensions"] if d["id"] == "goals")["status"] == "clear")

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema": "clientgraph.question_priority.evidence.v1",
        "dimensions": [{"id": d["id"], "order": d["order"], "label": d["label"]} for d in DIMENSIONS],
        "shown": shown,
        "hidden": hidden,
        "questions": plan["questions"],
        "stats": plan["stats"],
        "conflict_case": {
            "shown": [d["id"] for d in cplan["dimensions"]],
            "schedule_question": sched,
            "interfaces_question": iface,
        },
        "with_gap": {"shown": [d["id"] for d in with_gap["dimensions"]],
                     "question": [q for q in with_gap["questions"] if q["field"] == "migration_source"],
                     "hidden": [d["id"] for d in with_gap["hidden_dimensions"]]},
        "filled_metrics": [q["text"] for q in filled["questions"]],
        "checks": checks,
        "all_passed": all(checks.values()),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("questions:", len(plan["questions"]), "hidden:", hidden, "priorities:", prio)
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
