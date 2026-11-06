# -*- coding: utf-8 -*-
"""Verify requirement extraction: explicit/vague dates, duplicates, evidence."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extraction import extract  # noqa: E402

EVIDENCE = ROOT / "evidence" / "extraction-2026-11-06.json"


def item(iid, text, stype, file, occurred, proposer=None):
    return {
        "id": iid,
        "text": text,
        "source_type": stype,
        "source_file": file,
        "occurred_at": occurred,
        "project": {"id": "p1", "name": "设备巡检小程序（一期）"},
        "proposer": proposer,
        "sources": [{
            "source_type": stype,
            "file": file,
            "locator": f"{stype}://{file}#{iid}",
            "meta": {"sender": proposer} if proposer else {},
        }],
    }


def build_items():
    return [
        item("E01", "设备台账要能扫码查看档案", "chat", "chat_0922.txt",
             "2026-09-22T09:16:00+08:00", "陈晓岚"),
        item("E02", "台账这块要支持二维码，扫码就能看", "chat", "chat_0922b.txt",
             "2026-09-22T09:20:00+08:00", "陈晓岚"),
        item("E03", "一期范围 5 项：设备台账与二维码、巡检计划、扫码巡检、异常上报、统计看板",
             "document", "req.docx", "2026-09-29T09:00:00+08:00", "王工"),
        item("E04", "验收标准：118 台设备全部可扫码查看档案", "document",
             "req.docx", "2026-09-29T09:00:00+08:00", "王工"),
        item("E05", "审批流要加在异常工单上", "chat", "chat_0922.txt",
             "2026-09-22T09:17:00+08:00", "陈晓岚"),
        item("E06", "审批流不进入一期，客户内部流程尚未定稿", "document",
             "minutes.docx", "2026-09-25T14:00:00+08:00", "王工"),
        item("E07", "希望 10 月底上线，年底要审计", "email", "mail_0929.eml",
             "2026-09-29T10:12:00+08:00", "李副总"),
        item("E08", "预算大概 8 万左右", "asr", "call_0918.mp3",
             "2026-09-18T14:05:00+08:00"),
        item("E09", "第二轮报价合计 100,000 元，含税 6%", "document",
             "quote.docx", "2026-10-12T15:00:00+08:00", "王工"),
        item("E10", "设备台账由客户提供，2026-10-08 前给到；负责人：陈经理",
             "email", "mail_0925.eml", "2026-09-25T11:00:00+08:00", "陈晓岚"),
        item("E11", "统计看板下周给一版原型", "chat", "chat_1010.txt",
             "2026-10-10T11:02:00+08:00", "陈晓岚"),
        item("E12", "一期上线时间定为 2026-11-15", "document",
             "minutes.docx", "2026-09-25T14:00:00+08:00", "王工"),
        item("E13", "合同签订，进入实施阶段", "document",
             "contract.docx", "2026-10-16T14:08:00+08:00", "王工"),
    ]


def main() -> int:
    items = build_items()
    context = {"project_id": "p1", "project_name": "设备巡检小程序（一期）"}
    result = extract(items, context, {"统计看板": "2026-11-12"})
    base = extract(items, context, {})
    checks = {}

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    reqs = {r["canonical_key"]: r for r in result["requirements"]}
    ensure("project_stage", result["project"]["stage"]["value"] == "已签约",
           result["project"]["stage"])
    ensure("stage_evidence", (result["project"]["stage"]["evidence"] or {}).get("file") == "contract.docx")
    ensure("budget_conflict", result["project"]["budget"]["status"] == "conflict",
           result["project"]["budget"])
    ensure("budget_values", {b["amount"] for b in result["project"]["budget"]["values"]} == {80000, 100000})
    ensure("acceptance", any("118 台" in a["text"] for a in result["project"]["acceptance_criteria"]))
    ensure("seven_requirements", len(reqs) == 7, list(reqs))

    dev = reqs["设备台账"]
    ensure("dev_merged", dev["merged_count"] >= 4, dev["merged_count"])
    ensure("dev_evidence_files",
           {"chat_0922.txt", "chat_0922b.txt", "req.docx", "mail_0925.eml"} <=
           {e["file"] for e in dev["evidence"]})
    ensure("dev_owner", dev["owner"] == "陈经理", dev["owner"])
    ensure("dev_deadline", dev["deadline"]["value"] == "2026-10-08" and dev["deadline"]["status"] == "explicit",
           dev["deadline"])
    ensure("dev_proposers", {"陈晓岚", "王工"} <= set(dev["proposer"]), dev["proposer"])

    online = reqs["上线时间"]
    ensure("explicit_deadline", online["deadline"]["value"] == "2026-11-15" and
           online["deadline"]["status"] == "explicit", online["deadline"])
    ensure("vague_mismatch",
           any(p["type"] == "deadline_mismatch" and "10 月底" in p["question"]
               for p in result["pending"]), result["pending"])
    ensure("online_merged", online["merged_count"] >= 2, online["merged_count"])

    stat = reqs["统计看板"]
    ensure("confirmed_deadline",
           stat["deadline"]["value"] == "2026-11-12" and stat["deadline"]["status"] == "user_confirmed",
           stat["deadline"])
    ensure("confirmed_no_vague_pending",
           not any(p["requirement_id"] == stat["id"] and p["type"] == "deadline_vague"
                   for p in result["pending"]))
    ensure("confirmed_evidence", stat["merged_count"] >= 2, stat["merged_count"])

    plan = reqs["巡检计划"]
    ensure("owner_missing", plan["owner"] is None and
           any(p["type"] == "owner_missing" and p["requirement_id"] == plan["id"] for p in result["pending"]))
    ensure("approval_merged", reqs["审批流"]["merged_count"] >= 2, reqs["审批流"]["merged_count"])

    # Without confirmation, the same vague deadline must stay pending and empty.
    base_reqs = {r["canonical_key"]: r for r in base["requirements"]}
    base_stat = base_reqs["统计看板"]
    ensure("vague_no_value",
           base_stat["deadline"]["value"] is None and base_stat["deadline"]["status"] == "pending_vague",
           base_stat["deadline"])
    ensure("vague_question",
           any(p["type"] == "deadline_vague" and "下周" in p["question"] for p in base["pending"]))

    # No vague-only requirement may carry a concrete date.
    for r in base["requirements"]:
        if r["deadline"]["status"] == "pending_vague":
            ensure("no_guessed_date", r["deadline"]["value"] is None, r["title"])
    ensure("proposer_unknown_call",
           not any(r for r in result["requirements"] if "预算" in r["title"]),
           [r["title"] for r in result["requirements"]])

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
        "project": result["project"],
        "requirements": [{
            "id": r["id"], "title": r["title"], "key": r["canonical_key"],
            "proposer": r["proposer"], "owner": r["owner"],
            "deadline": r["deadline"], "merged_count": r["merged_count"],
            "evidence_files": sorted({e["file"] for e in r["evidence"]}),
        } for r in result["requirements"]],
        "pending": result["pending"],
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
