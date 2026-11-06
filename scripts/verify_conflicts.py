# -*- coding: utf-8 -*-
"""Verify conflict detection across eight dimensions and links."""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from conflict_detection import detect  # noqa: E402

EVIDENCE = ROOT / "evidence" / "conflicts-2026-11-06.json"


def obs(dim, value, raw, file, occurred, source_type="chat",
        requirement_key=None, requirement_id=None, task_ids=None):
    return {
        "dimension": dim,
        "value": value,
        "raw": raw,
        "requirement_key": requirement_key,
        "requirement_id": requirement_id,
        "task_ids": task_ids or [],
        "source": {
            "file": file,
            "source_type": source_type,
            "locator": f"{source_type}://{file}#{dim}",
            "occurred_at": occurred,
        },
    }


def context():
    return {
        "customer": {"id": "c1", "name": "青岚智能装备（虚构）"},
        "project": {"id": "p1", "name": "设备巡检小程序（一期）", "customer_id": "c1"},
        "requirements": [
            {"id": "R1", "key": "上线时间", "title": "上线时间"},
            {"id": "R2", "key": "审批流", "title": "审批流"},
            {"id": "R3", "key": "设备台账", "title": "设备台账"},
            {"id": "R4", "key": "权限", "title": "权限"},
        ],
    }


def observations():
    return [
        obs("budget", "80000", "预算 8 万", "call_0918.mp3", "2026-09-18T14:05:00+08:00", "asr"),
        obs("budget", "100000", "报价 100,000 元", "quote_1012.docx", "2026-10-12T15:00:00+08:00", "document"),
        obs("budget", "90000", "预算 9 万", "mail_1015.eml", "2026-10-15T10:00:00+08:00", "email"),
        obs("budget", "80000", "预算 8 万", "chat_0920.txt", "2026-09-20T09:00:00+08:00", "chat"),
        obs("timeline", "2026-11-15", "2026-11-15 上线", "minutes_0925.docx", "2026-09-25T14:00:00+08:00", "document", "上线时间", "R1"),
        obs("timeline", "2026-12-01", "调整为 2026-12-01", "quote_1012.docx", "2026-10-12T15:00:00+08:00", "document", "上线时间", "R1"),
        obs("scope", "include:审批流", "一期包含审批流", "chat_0922.txt", "2026-09-22T09:16:00+08:00", "chat", "审批流", "R2"),
        obs("scope", "exclude:审批流", "审批流不进入一期", "minutes_0925.docx", "2026-09-25T14:00:00+08:00", "document", "审批流", "R2"),
        obs("owner", "陈经理", "负责人：陈经理", "mail_0925.eml", "2026-09-25T11:00:00+08:00", "email", "设备台账", "R3"),
        obs("owner", "王工", "负责人：王工", "req.docx", "2026-09-29T09:00:00+08:00", "document", "设备台账", "R3"),
        obs("platform", "微信小程序", "平台：微信小程序", "chat_0918.txt", "2026-09-18T14:10:00+08:00", "chat"),
        obs("platform", "App", "客户希望做 App", "mail_0929.eml", "2026-09-29T10:12:00+08:00", "email"),
        obs("interface", "ERP", "接口：对接 ERP", "mail_0929.eml", "2026-09-29T10:12:00+08:00", "email"),
        obs("interface", "OA", "接口：走 OA 单点登录", "req.docx", "2026-09-29T09:00:00+08:00", "document"),
        obs("permission", "按车间隔离", "权限：按车间隔离", "req.docx", "2026-09-29T09:00:00+08:00", "document", "权限", "R4"),
        obs("permission", "全部可见", "权限：全部可见", "chat_1010.txt", "2026-10-10T11:02:00+08:00", "chat", "权限", "R4"),
        obs("acceptance", "118台全部可扫码", "验收：118 台全部可扫码", "req.docx", "2026-09-29T09:00:00+08:00", "document"),
        obs("acceptance", "120台全部可扫码", "验收：120 台全部可扫码", "mail_1010.eml", "2026-10-10T09:00:00+08:00", "email"),
    ]


def tasks():
    return [
        {"id": "T1", "project_id": "p1", "requirement_id": "R1", "requirement_key": "上线时间", "title": "确认上线时间"},
        {"id": "T2", "project_id": "p1", "requirement_id": "R3", "requirement_key": "设备台账", "title": "补齐设备台账"},
        {"id": "T3", "project_id": "p1", "title": "内部排期"},
    ]


def main() -> int:
    data = observations()
    before = copy.deepcopy(data)
    result = detect(data, context(), tasks())
    checks = {}

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    conflicts = result["conflicts"]
    ensure("eight_conflicts", len(conflicts) == 8, len(conflicts))
    ensure("all_must_confirm", all(c["status"] == "must_confirm" for c in conflicts))
    ensure("no_model_choice", all(c["model_choice"] is None and c["resolution"] is None and
                                  c["selected_value"] is None and c["auto_resolved"] is False
                                  for c in conflicts))
    ensure("write_blocked", all(c["write_blocked"] is True and
                                c["apply_policy"] == "requires_user_confirmation" for c in conflicts))
    ensure("input_unchanged", data == before)

    by_dim = {c["dimension"]: c for c in conflicts}
    budget = by_dim["budget"]
    ensure("budget_three_values", budget["extra_value_count"] == 1 and
           {v["normalized"] for v in budget["all_values"]} == {"80000", "100000", "90000"})
    ensure("budget_link", budget["customer"]["id"] == "c1" and budget["project"]["id"] == "p1")
    ensure("budget_task_link", {"T1", "T2", "T3"} <= set(budget["task_ids"]), budget["task_ids"])

    timeline = by_dim["timeline"]
    ensure("timeline_values", {timeline["value_a"]["normalized"], timeline["value_b"]["normalized"]} ==
           {"2026-11-15", "2026-12-01"})
    ensure("timeline_requirement", timeline["requirement"]["id"] == "R1")
    ensure("timeline_task", "T1" in timeline["task_ids"])
    ensure("timeline_sources", timeline["value_a"]["source"]["occurred_at"] and
           timeline["value_b"]["source"]["occurred_at"])

    scope = by_dim["scope"]
    ensure("scope_entity", "审批流" in scope["question"])
    ensure("scope_values", any(v["normalized"].endswith(":include") for v in scope["all_values"]) and
           any(v["normalized"].endswith(":exclude") for v in scope["all_values"]))
    ensure("scope_requirement", scope["requirement"]["id"] == "R2")

    owner = by_dim["owner"]
    ensure("owner_values", {"陈经理", "王工"} ==
           {owner["value_a"]["normalized"], owner["value_b"]["normalized"]})
    ensure("owner_task", "T2" in owner["task_ids"])

    ensure("platform", {v["normalized"] for v in by_dim["platform"]["all_values"]} == {"微信小程序", "App"})
    ensure("interface", {v["normalized"] for v in by_dim["interface"]["all_values"]} == {"ERP", "OA"})
    ensure("permission", len(by_dim["permission"]["all_values"]) == 2)
    ensure("acceptance", len(by_dim["acceptance"]["all_values"]) == 2)

    same = detect([
        obs("owner", "王工", "负责人：王工", "a.docx", "2026-09-29T09:00:00+08:00", "document"),
        obs("owner", "王工", "负责人：王工", "b.docx", "2026-09-30T09:00:00+08:00", "document"),
    ], context(), tasks())
    ensure("same_value_no_conflict", len(same["conflicts"]) == 0, same["conflicts"])

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
        "stats": result["stats"],
        "checks": checks,
        "all_passed": all(checks.values()),
        "conflicts": [{
            "id": c["id"], "dimension": c["dimension"], "status": c["status"],
            "value_a": c["value_a"], "value_b": c["value_b"],
            "question": c["question"], "customer": c["customer"],
            "project": c["project"], "requirement": c["requirement"],
            "task_ids": c["task_ids"], "resolution": c["resolution"],
            "model_choice": c["model_choice"],
        } for c in conflicts],
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("stats:", result["stats"])
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
