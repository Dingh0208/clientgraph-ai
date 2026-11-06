# -*- coding: utf-8 -*-
"""End-to-end regression for v0.3.0: two customers, three projects, multi-source."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from customer360.aggregator import build as customer360  # noqa: E402
from requirement_history import build as history  # noqa: E402
from extraction import extract  # noqa: E402
from conflict_detection import detect  # noqa: E402
from task_center.generator import generate_tasks  # noqa: E402
from task_center.reminders import FakeNotifier, ReminderEngine  # noqa: E402
from task_center.store import TaskStore  # noqa: E402
from relationship_view import build as graph  # noqa: E402
from unified_search import answer, SearchIndex  # noqa: E402

EVIDENCE = ROOT / "evidence" / "integration-v0.3.0-2026-11-06.json"
TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 6, 9, 30, tzinfo=TZ)


def src(iid, stype, file, locator, occurred):
    return {"id": iid, "source_type": stype, "source_file": file,
            "locator": locator, "occurred_at": occurred,
            "sources": [{"source_type": stype, "file": file, "locator": locator}]}


def dataset():
    return {
        "customers": [
            {"id": "c1", "name": "青岚智能装备（虚构）", "aliases": ["青岚"],
             "phone": "13800001024", "email": "chen.xiaolan@example.com",
             "wechat": "demo_qinglan_chen",
             "contacts": [{"name": "陈晓岚", "role": "信息化负责人"}]},
            {"id": "c2", "name": "恒晟精工（虚构）", "aliases": ["恒晟"],
             "phone": "13900002048", "email": "zhou.mingyuan@example.com",
             "wechat": "demo_heng_zhou",
             "contacts": [{"name": "周明远", "role": "供应链总监"}]},
        ],
        "projects": [
            {"id": "p1", "name": "设备巡检小程序（一期）", "customer_id": "c1"},
            {"id": "p2", "name": "售后工单系统升级", "customer_id": "c1"},
            {"id": "p3", "name": "供应链协同平台（预研）", "customer_id": "c2"},
        ],
        "communications": [
            {"id": "m1", "title": "聊天-小程序需求", "text": "设备台账与扫码巡检，想开发一个小程序",
             "customer_id": "c1", "project_id": "p1", "occurred_at": "2026-09-18T14:10:00+08:00",
             "locator": "chat://m1#msg=1", "file_id": "f1"},
            {"id": "m2", "title": "聊天-售后工单", "text": "售后工单要加审批",
             "customer_id": "c1", "project_id": "p2", "occurred_at": "2026-10-14T10:20:00+08:00",
             "locator": "chat://m2#msg=1"},
            {"id": "m3", "title": "邮件-供应链预研", "text": "供应链协同平台需要支持 ERP 接口",
             "customer_id": "c2", "project_id": "p3", "occurred_at": "2026-10-09T16:40:00+08:00",
             "locator": "mail://m3#part=text"},
        ],
        "files": [
            {"id": "f1", "name": "巡检需求.pdf"},
        ],
        "documents": [
            {"id": "d1", "title": "设备巡检小程序需求文档", "text": "设备台账与巡检计划、异常上报",
             "customer_id": "c1", "project_id": "p1", "occurred_at": "2026-09-29T09:00:00+08:00",
             "locator": "doc://d1#page=1"},
            {"id": "d2", "title": "第二轮报价单", "text": "报价合计 100,000 元",
             "customer_id": "c1", "project_id": "p1", "occurred_at": "2026-10-12T15:00:00+08:00",
             "locator": "doc://d2#table=1&row=8"},
            {"id": "d3", "title": "供应链协同方案", "text": "供应商门户与采购订单协同",
             "customer_id": "c2", "project_id": "p3", "occurred_at": "2026-10-10T10:00:00+08:00",
             "locator": "doc://d3#page=1"},
            {"id": "d4", "title": "历史设备清单", "text": "旧版设备清单，来源时间未知",
             "customer_id": "c1", "project_id": "p1", "occurred_at": None,
             "locator": "doc://d4#page=1"},
        ],
        "requirements": [
            {"id": "r1", "title": "设备巡检小程序", "description": "设备台账与扫码巡检",
             "customer_id": "c1", "project_id": "p1", "locator": "doc://d1#page=1"},
            {"id": "r2", "title": "售后工单审批", "description": "工单审批流",
             "customer_id": "c1", "project_id": "p2", "locator": "chat://m2#msg=2"},
            {"id": "r3", "title": "供应链协同平台", "description": "供应商门户与 ERP 接口",
             "customer_id": "c2", "project_id": "p3", "locator": "mail://m3#part=text"},
            {"id": "r4", "title": "设备巡检报表", "description": "设备巡检报表导出",
             "customer_id": "c2", "project_id": "p3", "locator": "doc://d3#page=2"},
        ],
        "risks": [
            {"id": "k1", "title": "预算未确认", "project_id": "p1", "customer_id": "c1",
             "evidence_ids": ["e1"]},
            {"id": "k2", "title": "ERP 接口未确认", "project_id": "p3", "customer_id": "c2",
             "evidence_ids": ["e3"]},
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
            {"id": "t4", "title": "补充工单需求", "status": "done", "due_at": "2026-10-01",
             "customer": {"id": "c1", "name": "青岚智能装备（虚构）"},
             "project": {"id": "p2", "name": "售后工单系统升级"},
             "source": {"locator": "chat://m2#msg=1", "occurred_at": "2026-10-14T10:20:00+08:00"}},
        ],
        "evidence": [
            {"id": "e1", "text": "设备台账与扫码巡检", "locator": "doc://d1#page=1",
             "customer_id": "c1", "project_id": "p1", "occurred_at": "2026-09-29T09:00:00+08:00"},
            {"id": "e2", "text": "售后工单要加审批", "locator": "chat://m2#msg=1",
             "customer_id": "c1", "project_id": "p2", "occurred_at": "2026-10-14T10:20:00+08:00"},
            {"id": "e3", "text": "供应链协同平台需要支持 ERP 接口", "locator": "mail://m3#part=text",
             "customer_id": "c2", "project_id": "p3", "occurred_at": "2026-10-09T16:40:00+08:00"},
            {"id": "e4", "text": "设备巡检报表导出", "locator": "doc://d3#page=2",
             "customer_id": "c2", "project_id": "p3", "occurred_at": "2026-10-10T10:00:00+08:00"},
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
    }


def item(iid, text, file, locator, occurred, customer_id, project_id, stype="chat"):
    return {"id": iid, "text": text, "source_type": stype, "source_file": file,
            "occurred_at": occurred, "customer_id": customer_id, "project_id": project_id,
            "sources": [{"source_type": stype, "file": file, "locator": locator}]}


def main() -> int:
    data = dataset()
    d = {"now": NOW.isoformat()}
    checks = {}

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    # Extraction per project
    c1_items = [
        item("x1", "设备台账与扫码巡检", "d1", "doc://d1#page=1", "2026-09-29T09:00:00+08:00", "c1", "p1", "document"),
        item("x2", "预算大概 8 万", "m1", "chat://m1#msg=1", "2026-09-18T14:10:00+08:00", "c1", "p1"),
    ]
    c2_items = [
        item("x3", "供应链协同平台需要支持 ERP 接口", "m3", "mail://m3#part=text",
             "2026-10-09T16:40:00+08:00", "c2", "p3", "email"),
    ]
    c1_ex = extract(c1_items, {"project_id": "p1", "project_name": "设备巡检小程序（一期）"})
    c2_ex = extract(c2_items, {"project_id": "p3", "project_name": "供应链协同平台（预研）"})
    ensure("extract_c1", any(r["canonical_key"] == "设备台账" for r in c1_ex["requirements"]))
    ensure("extract_c2", any(r["canonical_key"] not in ("设备台账", "巡检计划") for r in c2_ex["requirements"]))
    ensure("extract_no_cross", not any(r["canonical_key"] == "设备台账" for r in c2_ex["requirements"]))

    # History p1
    batches = [
        {"id": "b1", "occurred_at": "2026-09-18T14:10:00+08:00", "items": [
            item("h1", "设备台账要能扫码查看档案", "chat", "chat://h1", "2026-09-18T14:10:00+08:00", "c1", "p1"),
            item("h2", "预算大概 8 万", "call", "call://h2", "2026-09-18T14:05:00+08:00", "c1", "p1", "asr"),
            item("h3", "希望 10 月底上线", "chat", "chat://h3", "2026-09-18T14:12:00+08:00", "c1", "p1"),
        ]},
        {"id": "b2", "occurred_at": "2026-09-25T14:00:00+08:00", "items": [
            item("h4", "设备台账与巡检计划、异常上报", "doc", "doc://h4", "2026-09-25T14:00:00+08:00", "c1", "p1", "document"),
            item("h5", "上线时间定为 2026-11-15", "doc", "doc://h5", "2026-09-25T14:00:00+08:00", "c1", "p1", "document"),
            item("h6", "验收标准：118 台设备全部可扫码", "doc", "doc://h6", "2026-09-25T14:00:00+08:00", "c1", "p1", "document"),
        ]},
        {"id": "b3", "occurred_at": "2026-10-12T15:00:00+08:00", "items": [
            item("h7", "预算调整为 10 万", "doc", "doc://h7", "2026-10-12T15:00:00+08:00", "c1", "p1", "document"),
            item("h8", "上线时间调整为 2026-12-01", "doc", "doc://h8", "2026-10-12T15:00:00+08:00", "c1", "p1", "document"),
            item("h9", "统计看板新增，完成率与明细一致", "doc", "doc://h9", "2026-10-12T15:00:00+08:00", "c1", "p1", "document"),
            item("h10", "设备台账负责人：陈经理，需求已确认", "doc", "doc://h10", "2026-10-12T17:00:00+08:00", "c1", "p1", "document"),
        ]},
    ]
    hist = history(batches, {"project_id": "p1", "project_name": "设备巡检小程序（一期）"})
    ensure("history_versions", hist["stats"]["project_versions"] == 3)
    ensure("history_budget", any(v["budget"]["values"] and v["budget"]["values"][0]["amount"] == 100000
                                 for v in hist["project"]["versions"]))

    # Conflicts: c1 and c2 separate projects
    observations = [
        {"dimension": "budget", "value": "80000", "raw": "预算 8 万", "source": {"file": "m1", "occurred_at": "2026-09-18T14:05:00+08:00"}},
        {"dimension": "budget", "value": "100000", "raw": "报价 100,000 元", "source": {"file": "d2", "occurred_at": "2026-10-12T15:00:00+08:00"}},
        {"dimension": "interface", "value": "ERP", "raw": "接口 ERP", "project_id": "p3",
         "source": {"file": "m3", "occurred_at": "2026-10-09T16:40:00+08:00"}},
        {"dimension": "interface", "value": "OA", "raw": "接口 OA", "project_id": "p3",
         "source": {"file": "d3", "occurred_at": "2026-10-10T10:00:00+08:00"}},
    ]
    ctx = {
        "customer": {"id": "c1", "name": "青岚智能装备（虚构）"},
        "project": {"id": "p1", "name": "设备巡检小程序（一期）", "customer_id": "c1"},
        "customers": data["customers"], "projects": data["projects"],
        "requirements": [{"id": "R1", "key": "设备台账", "title": "设备台账"},
                         {"id": "R2", "key": "供应链", "title": "供应链"}],
    }
    conflicts = detect(observations, ctx, data["tasks"])
    ensure("conflict_two", len(conflicts["conflicts"]) == 2)
    ensure("conflict_projects", {c["project"]["id"] for c in conflicts["conflicts"]} == {"p1", "p3"})
    ensure("conflict_must", all(c["status"] == "must_confirm" and c["model_choice"] is None for c in conflicts["conflicts"]))

    # Tasks and reminders
    actions = [
        item("a1", "请在 2026-10-15 前确认预算", "chat", "chat://m1#msg=3", "2026-09-22T09:19:00+08:00", "c1", "p1"),
        item("a2", "下周给一版原型", "chat", "chat://m1#msg=4", "2026-09-22T09:25:00+08:00", "c1", "p1"),
        item("a3", "尽快回复供应链预研问题", "mail", "mail://m3#part=text", "2026-10-09T16:40:00+08:00", "c2", "p3", "email"),
        item("a4", "2026-11-10 前提交验收材料", "doc", "doc://d1#page=9", "2026-09-29T09:00:00+08:00", "c1", "p1", "document"),
    ]
    tctx = {"customers": data["customers"], "projects": data["projects"],
            "customer": data["customers"][0], "project": data["projects"][0]}
    tasks = generate_tasks(actions, tctx, NOW)
    ensure("task_four", len(tasks) == 4, len(tasks))
    ensure("task_cross", {t["customer"]["id"] for t in tasks} == {"c1", "c2"})
    ensure("task_vague", tasks[1]["due_at"] is None and tasks[2]["due_at"] is None)
    store = TaskStore(tasks)
    store.complete("T1", "王工", NOW)
    ensure("complete_isolated", store.get("T1")["status"] == "done" and store.get("T3")["status"] == "open")
    reminder_store = TaskStore(generate_tasks(actions, tctx, NOW))
    notifier = FakeNotifier()
    engine = ReminderEngine(reminder_store, data["customers"], notifier)
    sent = engine.tick(NOW, app_active=True)
    ensure("reminder", any(r["task_id"] == "T1" for r in sent["sent"]) and
           any(r["customer_id"] == "c2" for r in sent["sent"]))
    inactive = engine.tick(NOW + timedelta(days=1), app_active=False)
    ensure("inactive_no_sent", inactive["skipped"] == "app_inactive")

    # Customer 360
    c1_360 = customer360(data, "c1", NOW.isoformat())
    c2_360 = customer360(data, "c2", NOW.isoformat())
    ensure("c360_projects", len(c1_360["projects"]) == 2 and len(c2_360["projects"]) == 1)
    ensure("c360_no_cross_c1", all(x["id"] not in ("m3", "d3") for x in c1_360["timeline"]))
    ensure("c360_no_cross_c2", all(x["id"] not in ("m1", "d1", "m2", "d2") for x in c2_360["timeline"]))
    ensure("c360_missing_time", c1_360["timeline"][-1]["id"] == "d4" and
           c1_360["timeline"][-1]["occurred_at"] is None)
    ensure("c360_requirements", c1_360["requirements"]["total"] == 2 and c2_360["requirements"]["total"] == 2)

    # Relationship graph
    manual = [{"from": "customer:c1", "to": "document:d2", "relation": "uses_document",
               "operator": "王工", "at": "2026-11-06T10:00:00+08:00", "note": "报价由青岚提供"}]
    rel = graph(data, manual)
    ensure("graph_no_cross", not any(e["from"] == "customer:c1" and e["to"] == "project:p3" for e in rel["edges"]) and
           not any(e["from"] == "customer:c2" and e["to"] == "project:p1" for e in rel["edges"]))
    ensure("graph_manual", any(e["type"] == "manual_confirmed" for e in rel["edges"]))
    ensure("graph_why", all(e["why"] for e in rel["edges"]))

    # Unified search
    mentions = answer("哪些客户提过小程序开发", data, NOW.isoformat())
    ensure("search_mentions", [c["id"] for c in mentions["customers"]] == ["c1"])
    ensure("search_mentions_locator", any(e["locator"] == "chat://m1#msg=1" for e in mentions["evidence"]))
    c2_only = answer("供应链协同平台", data, NOW.isoformat())
    ensure("search_c2", any(c["id"] == "c2" for c in c2_only["customers"]) and
           not any(c["id"] == "c1" for c in c2_only["customers"]), c2_only["customers"])
    overdue = answer("哪些待办已逾期", data, NOW.isoformat())
    ensure("search_overdue", {t["id"] for t in overdue["items"]} == {"t1", "t3"})
    change = answer("设备巡检小程序最近一次变更是什么", data, NOW.isoformat())
    ensure("search_change", "100,000" in change["conclusion"] and change["time"] == "2026-10-12T15:00:00+08:00")
    c2_change = answer("供应链协同最近一次变更是什么", data, NOW.isoformat())
    ensure("search_change_no_history", c2_change["uncertainty"]["level"] == "high" and
           "暂无变更记录" in c2_change["conclusion"], c2_change)
    unknown = answer("有没有提到海外部署", data, NOW.isoformat())
    ensure("search_unknown", unknown["uncertainty"]["level"] == "high")

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
        "customers": 2, "projects": 3,
        "checks": checks,
        "all_passed": all(checks.values()),
        "summary": {
            "extraction_c1": [r["canonical_key"] for r in c1_ex["requirements"]],
            "extraction_c2": [r["canonical_key"] for r in c2_ex["requirements"]],
            "history_versions": hist["stats"]["project_versions"],
            "conflicts": len(conflicts["conflicts"]),
            "tasks": len(tasks),
            "reminders": len(sent["sent"]),
            "c360_c1": c1_360["stats"], "c360_c2": c2_360["stats"],
            "graph": rel["stats"],
            "search_mentions": [c["name"] for c in mentions["customers"]],
            "search_overdue": [t["id"] for t in overdue["items"]],
        },
        "failures": [
            {"case": "unknown search", "level": unknown["uncertainty"]["level"]},
            {"case": "vague task", "due_at": tasks[1]["due_at"], "status": tasks[1]["due_status"]},
            {"case": "notifications while app inactive", "skipped": inactive["skipped"]},
            {"case": "conflict unresolved", "count": len(conflicts["conflicts"])},
            {"case": "project without history", "query": "供应链协同最近一次变更", "level": "high"},
        ],
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("summary:", evidence["summary"])
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
