# -*- coding: utf-8 -*-
"""Verify append-only requirement history over three incremental batches."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from requirement_history import build  # noqa: E402

EVIDENCE = ROOT / "evidence" / "requirement-history-2026-11-06.json"


def item(iid, text, stype, file, occurred, proposer=None):
    return {
        "id": iid,
        "text": text,
        "source_type": stype,
        "source_file": file,
        "occurred_at": occurred,
        "proposer": proposer,
        "sources": [{
            "source_type": stype,
            "file": file,
            "locator": f"{stype}://{file}#{iid}",
            "meta": {"sender": proposer} if proposer else {},
        }],
    }


def batches():
    return [
        {"id": "b1", "occurred_at": "2026-09-18T14:10:00+08:00", "items": [
            item("E1", "设备台账要能扫码查看档案", "chat", "chat_0918.txt",
                 "2026-09-18T14:10:00+08:00", "陈晓岚"),
            item("E2", "预算大概 8 万左右", "asr", "call_0918.mp3",
                 "2026-09-18T14:05:00+08:00"),
            item("E3", "希望 10 月底上线", "chat", "chat_0918.txt",
                 "2026-09-18T14:12:00+08:00", "陈晓岚"),
        ]},
        {"id": "b2", "occurred_at": "2026-09-25T14:00:00+08:00", "items": [
            item("E4", "一期范围：设备台账与二维码、巡检计划、异常上报", "document",
                 "minutes_0925.docx", "2026-09-25T14:00:00+08:00", "王工"),
            item("E5", "上线时间定为 2026-11-15", "document",
                 "minutes_0925.docx", "2026-09-25T14:00:00+08:00", "王工"),
            item("E6", "验收标准：118 台设备全部可扫码查看档案", "document",
                 "minutes_0925.docx", "2026-09-25T14:00:00+08:00", "王工"),
            item("E7", "审批流要加在异常工单上", "chat", "chat_0925.txt",
                 "2026-09-25T15:10:00+08:00", "陈晓岚"),
        ]},
        {"id": "b3", "occurred_at": "2026-10-12T15:00:00+08:00", "items": [
            item("E8", "预算调整为 10 万", "document", "quote_1012.docx",
                 "2026-10-12T15:00:00+08:00", "王工"),
            item("E9", "上线时间调整为 2026-12-01", "document",
                 "quote_1012.docx", "2026-10-12T15:00:00+08:00", "王工"),
            item("E10", "统计看板新增，完成率与明细一致", "document",
                 "quote_1012.docx", "2026-10-12T15:00:00+08:00", "王工"),
            item("E11", "审批流取消，不进入一期", "chat", "chat_1012.txt",
                 "2026-10-12T16:20:00+08:00", "陈晓岚"),
            item("E12", "设备台账负责人：陈经理，需求已确认", "document",
                 "contract_1012.docx", "2026-10-12T17:00:00+08:00", "王工"),
            item("E13", "验收标准：118 台设备全部可扫码查看档案，统计看板数据与明细一致",
                 "document", "contract_1012.docx", "2026-10-12T17:00:00+08:00", "王工"),
        ]},
    ]


def main() -> int:
    result = build(batches(), {"project_id": "p1", "project_name": "设备巡检小程序（一期）"})
    checks = {}

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    pv = result["project"]["versions"]
    ensure("three_project_versions", len(pv) == 3, len(pv))
    ensure("v1_budget_8w", any(v["amount"] == 80000 for v in pv[0]["budget"]["values"]))
    ensure("v1_deadline_pending", pv[0]["deadline"]["value"] is None and
           pv[0]["deadline"]["status"] == "pending_vague", pv[0]["deadline"])
    ensure("v1_scope", {s["key"] for s in pv[0]["scope"]} == {"设备台账", "上线时间"},
           [s["key"] for s in pv[0]["scope"]])
    ensure("v2_budget_carried", any(v["amount"] == 80000 for v in pv[1]["budget"]["values"]))
    ensure("v2_deadline", pv[1]["deadline"]["value"] == "2026-11-15", pv[1]["deadline"])
    ensure("v2_scope_added", {"巡检计划", "异常上报", "审批流"} <= {s["key"] for s in pv[1]["scope"]})
    ensure("v2_acceptance", len(pv[1]["acceptance"]) == 1 and "118 台" in pv[1]["acceptance"][0]["text"])
    ensure("v3_budget_10w", any(v["amount"] == 100000 for v in pv[2]["budget"]["values"]))
    ensure("v3_deadline", pv[2]["deadline"]["value"] == "2026-12-01", pv[2]["deadline"])
    ensure("v3_scope_stats", "统计看板" in {s["key"] for s in pv[2]["scope"]})
    ensure("v3_acceptance_changed", "统计看板" in pv[2]["acceptance"][0]["text"], pv[2]["acceptance"])
    ensure("v3_changes", {"scope", "budget", "deadline", "acceptance"} <=
           {c["field"] for c in pv[2]["changes"]}, pv[2]["changes"])
    ensure("v3_reason", "预算由" in pv[2]["change_reason"] and "工期由" in pv[2]["change_reason"],
           pv[2]["change_reason"])

    reqs = {r["key"]: r for r in result["requirements"]}
    dev = reqs["设备台账"]
    ensure("dev_versions", len(dev["versions"]) >= 3, len(dev["versions"]))
    ensure("dev_first_immutable",
           dev["versions"][0]["description"] == "设备台账要能扫码查看档案",
           dev["versions"][0]["description"])
    ensure("dev_current_confirmed", dev["current_status"] == "confirmed", dev["current_status"])
    ensure("dev_owner", dev["current_owner"] == "陈经理", dev["current_owner"])
    ensure("dev_confirmed_version",
           any(v["change_type"] == "confirmed" for v in dev["versions"]),
           [v["change_type"] for v in dev["versions"]])

    online = reqs["上线时间"]
    values = [v["deadline"]["value"] for v in online["versions"]]
    ensure("online_values", values == [None, "2026-11-15", "2026-12-01"], values)
    ensure("online_vague_raw", online["versions"][0]["deadline"]["raw"] == "10 月底",
           online["versions"][0]["deadline"])

    approval = reqs["审批流"]
    ensure("approval_cancelled", approval["current_status"] == "cancelled", approval["current_status"])
    ensure("approval_versions", [v["status"] for v in approval["versions"]] == ["pending", "cancelled"],
           [v["status"] for v in approval["versions"]])
    ensure("stats_new", reqs["统计看板"]["first_seen_at"].startswith("2026-10-12"))
    ensure("stats_one_version", len(reqs["统计看板"]["versions"]) == 1)

    for r in result["requirements"]:
        for v in r["versions"]:
            ensure("version_source", bool(v["sources"]) and bool(v["occurred_at"]) and bool(v["change_reason"]))
            ensure("version_status", v["status"] in ("pending", "confirmed", "cancelled"))
    ensure("stats_total", result["stats"]["project_versions"] == 3 and result["stats"]["batches"] == 3)

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
        "project": {
            "name": result["project"]["name"],
            "versions": [{
                "version": v["version"],
                "occurred_at": v["occurred_at"],
                "budget": [b["amount"] for b in v["budget"]["values"]],
                "deadline": v["deadline"],
                "scope": [s["key"] for s in v["scope"]],
                "acceptance": [a["text"] for a in v["acceptance"]],
                "changes": [c["field"] for c in v["changes"]],
                "change_reason": v["change_reason"],
            } for v in pv],
        },
        "requirements": [{
            "key": r["key"], "current_status": r["current_status"],
            "current_owner": r["current_owner"], "current_deadline": r["current_deadline"],
            "versions": [{
                "version": v["version"], "change_type": v["change_type"],
                "status": v["status"], "description": v["description"],
                "owner": v["owner"], "deadline": v["deadline"],
                "occurred_at": v["occurred_at"], "change_reason": v["change_reason"],
                "sources": sorted({s["file"] for s in v["sources"]}),
            } for v in r["versions"]],
        } for r in result["requirements"]],
        "stats": result["stats"],
        "checks": checks,
        "all_passed": all(checks.values()),
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
