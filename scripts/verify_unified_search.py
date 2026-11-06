# -*- coding: utf-8 -*-
"""Verify unified keyword search and three natural-language questions."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from unified_search import SearchIndex, answer  # noqa: E402

EVIDENCE = ROOT / "evidence" / "unified-search-2026-11-06.json"


def data():
    return {
        "customers": [
            {"id": "c1", "name": "青岚智能装备（虚构）", "aliases": ["青岚"]},
            {"id": "c2", "name": "恒晟精工（虚构）", "aliases": ["恒晟"]},
        ],
        "projects": [
            {"id": "p1", "name": "设备巡检小程序（一期）", "customer_id": "c1"},
            {"id": "p2", "name": "售后工单系统升级", "customer_id": "c1"},
            {"id": "p3", "name": "供应链协同平台（预研）", "customer_id": "c2"},
        ],
        "communications": [
            {"id": "m1", "title": "微信聊天-需求", "text": "我们想开发一个小程序做设备巡检",
             "customer_id": "c1", "project_id": "p1", "occurred_at": "2026-09-18T14:10:00+08:00",
             "locator": "chat://m1#msg=1"},
            {"id": "m2", "title": "电话-排期", "text": "希望十月底上线，年底要审计",
             "customer_id": "c1", "project_id": "p1", "occurred_at": "2026-09-25T14:05:00+08:00",
             "locator": "call://m2#t=120000"},
            {"id": "m3", "title": "邮件-恒晟预研", "text": "供应链协同平台预研，想了解 ERP 对接",
             "customer_id": "c2", "project_id": "p3", "occurred_at": "2026-10-09T16:40:00+08:00",
             "locator": "mail://m3#part=text"},
        ],
        "documents": [
            {"id": "d1", "title": "设备巡检小程序需求文档", "text": "设备巡检小程序需求文档 v1.0",
             "customer_id": "c1", "project_id": "p1", "occurred_at": "2026-09-29T09:00:00+08:00",
             "locator": "doc://d1#page=1"},
            {"id": "d2", "title": "第二轮报价单", "text": "报价合计 100,000 元",
             "customer_id": "c1", "project_id": "p1", "occurred_at": "2026-10-12T15:00:00+08:00",
             "locator": "doc://d2#table=1&row=8"},
        ],
        "requirements": [
            {"id": "r1", "title": "设备巡检小程序", "description": "扫码巡检与设备台账",
             "customer_id": "c1", "project_id": "p1", "locator": "doc://d1#page=2"},
            {"id": "r2", "title": "供应链协同平台", "description": "供应商门户",
             "customer_id": "c2", "project_id": "p3", "locator": "mail://m3#part=text"},
        ],
        "tasks": [
            {"id": "t1", "title": "确认一期预算", "status": "open", "due_at": "2026-10-15",
             "customer": {"id": "c1", "name": "青岚智能装备（虚构）"},
             "project": {"id": "p1", "name": "设备巡检小程序（一期）"},
             "source": {"locator": "chat://m1#msg=3", "occurred_at": "2026-09-22T09:19:00+08:00"}},
            {"id": "t2", "title": "提交验收材料", "status": "open", "due_at": "2026-11-10",
             "customer": {"id": "c1", "name": "青岚智能装备（虚构）"},
             "project": {"id": "p1", "name": "设备巡检小程序（一期）"},
             "source": {"locator": "doc://d1#page=9", "occurred_at": "2026-09-29T09:00:00+08:00"}},
            {"id": "t3", "title": "回复供应链预研问题", "status": "open", "due_at": "2026-11-05",
             "customer": {"id": "c2", "name": "恒晟精工（虚构）"},
             "project": {"id": "p3", "name": "供应链协同平台（预研）"},
             "source": {"locator": "mail://m3#part=text", "occurred_at": "2026-10-09T16:40:00+08:00"}},
            {"id": "t4", "title": "已完成任务", "status": "done", "due_at": "2026-10-01",
             "customer": {"id": "c1", "name": "青岚智能装备（虚构）"},
             "project": {"id": "p1", "name": "设备巡检小程序（一期）"},
             "source": {"locator": "doc://d1#page=10", "occurred_at": "2026-09-29T09:00:00+08:00"}},
        ],
        "history": {"projects": [
            {"id": "p1", "versions": [
                {"version": 1, "occurred_at": "2026-09-25T14:00:00+08:00",
                 "change_reason": "首次出现", "changes": [],
                 "sources": [{"file": "minutes.docx", "locator": "doc://minutes#page=1",
                              "occurred_at": "2026-09-25T14:00:00+08:00"}]},
                {"version": 2, "occurred_at": "2026-10-12T15:00:00+08:00",
                 "change_reason": "范围新增 统计看板；预算由 80,000 元 改为 100,000 元；工期由 2026-11-15 改为 2026-12-01",
                 "changes": [{"field": "scope"}, {"field": "budget"}, {"field": "deadline"}],
                 "sources": [{"file": "quote.docx", "locator": "doc://d2#table=1&row=8",
                              "occurred_at": "2026-10-12T15:00:00+08:00"}]},
            ]},
        ]},
        "evidence": [
            {"id": "e1", "text": "我们想开发一个小程序做设备巡检", "locator": "chat://m1#msg=1",
             "customer_id": "c1", "project_id": "p1", "occurred_at": "2026-09-18T14:10:00+08:00"},
            {"id": "e2", "text": "设备巡检小程序需求文档", "locator": "doc://d1#page=1",
             "customer_id": "c1", "project_id": "p1", "occurred_at": "2026-09-29T09:00:00+08:00"},
            {"id": "e3", "text": "供应链协同平台预研", "locator": "mail://m3#part=text",
             "customer_id": "c2", "project_id": "p3", "occurred_at": "2026-10-09T16:40:00+08:00"},
        ],
    }


def main() -> int:
    d = data()
    now = "2026-11-06T09:30:00+08:00"
    checks = {}

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    index = SearchIndex(d)
    hits = index.search("小程序")
    ensure("keyword_hits", len(hits) >= 3, len(hits))
    ensure("keyword_locators", all(h["locator"] for h in hits))
    ensure("keyword_sources", {"communication", "document", "requirement"} <=
           {h["entity_type"] for h in hits})

    mentions = answer("哪些客户提过小程序开发", d, now)
    ensure("mentions_intent", mentions["intent"] == "customer_mentions")
    ensure("mentions_customer", [c["id"] for c in mentions["customers"]] == ["c1"],
           mentions["customers"])
    ensure("mentions_project", any(p["id"] == "p1" for p in mentions["projects"]))
    ensure("mentions_evidence", any(e["locator"] == "chat://m1#msg=1" for e in mentions["evidence"]) and
           any(e["locator"] == "doc://d1#page=1" for e in mentions["evidence"]), mentions["evidence"])
    ensure("mentions_conclusion", "青岚" in mentions["conclusion"] or "提过" in mentions["conclusion"])
    ensure("mentions_uncertainty", mentions["uncertainty"]["level"] in ("low", "medium"))

    change = answer("设备巡检小程序最近一次变更是什么", d, now)
    ensure("change_intent", change["intent"] == "project_change")
    ensure("change_project", [p["id"] for p in change["projects"]] == ["p1"], change["projects"])
    ensure("change_conclusion", "100,000" in change["conclusion"] and "2026-12-01" in change["conclusion"],
           change["conclusion"])
    ensure("change_time", change["time"] == "2026-10-12T15:00:00+08:00", change["time"])
    ensure("change_evidence", any(e["locator"] == "doc://d2#table=1&row=8" for e in change["evidence"]))
    ensure("change_uncertainty", change["uncertainty"]["level"] == "low")

    overdue = answer("哪些待办已逾期", d, now)
    ensure("overdue_intent", overdue["intent"] == "overdue_tasks")
    ensure("overdue_items", {i["id"] for i in overdue["items"]} == {"t1", "t3"}, overdue["items"])
    ensure("overdue_conclusion", "2 项" in overdue["conclusion"], overdue["conclusion"])
    ensure("overdue_customers", {c["id"] for c in overdue["customers"]} == {"c1", "c2"})
    ensure("overdue_evidence", {e["locator"] for e in overdue["evidence"]} >=
           {"chat://m1#msg=3", "mail://m3#part=text"})
    ensure("overdue_uncertainty", overdue["uncertainty"]["level"] == "low")

    unknown = answer("有没有提到海外部署", d, now)
    ensure("unknown_high", unknown["uncertainty"]["level"] == "high" and not unknown["evidence"])
    ensure("unknown_conclusion", "未找到" in unknown["conclusion"])

    fallback = answer("报价", d, now)
    ensure("fallback_medium", fallback["intent"] == "keyword" and
           fallback["uncertainty"]["level"] == "medium" and fallback["evidence"])

    for ans in (mentions, change, overdue):
        ensure("answer_contract", all(k in ans for k in
               ("customers", "projects", "conclusion", "evidence", "time", "times", "uncertainty")))
        ensure("answer_locators", all(e.get("locator") for e in ans["evidence"]))
        ensure("answer_times", isinstance(ans["times"], list))

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
        "keyword": {"count": len(hits), "results": hits},
        "answers": {"mentions": mentions, "change": change, "overdue": overdue,
                    "unknown": unknown, "fallback": fallback},
        "checks": checks,
        "all_passed": all(checks.values()),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("hits:", len(hits), "overdue:", len(overdue["items"]))
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
