# -*- coding: utf-8 -*-
"""Verify evidence normalization and merging rules."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evidence_layer import collect  # noqa: E402

EVIDENCE = ROOT / "evidence" / "evidence-layer-2026-11-06.json"


def build_bundle():
    context = {
        "customers": [
            {"id": "c1", "name": "青岚智能装备（虚构）", "aliases": ["青岚"],
             "phones": ["13800001024"], "emails": ["chen.xiaolan@example.com"],
             "wechat": ["demo_qinglan_chen"]},
            {"id": "c2", "name": "恒晟精工（虚构）", "aliases": ["恒晟"],
             "phones": ["13900002048"], "emails": ["zhou.mingyuan@example.com"]},
        ],
        "projects": [
            {"id": "p1", "customer_id": "c1", "name": "设备巡检小程序（一期）", "aliases": ["巡检小程序"]},
            {"id": "p2", "customer_id": "c1", "name": "售后工单系统升级"},
            {"id": "p3", "customer_id": "c2", "name": "供应链协同平台（预研）"},
        ],
    }

    audio = {
        "schema": "clientgraph.audio.run.v1",
        "source": {"name": "call_0922.mp3", "sha256": "a" * 64},
        "segments": [
            {"text": "预算大概8万左右", "start_ms": 120000, "end_ms": 125000,
             "chunk_index": 0, "source": {"provider": "mock", "model": "mock-asr-v1",
                                          "timestamp_source": "segment"}},
            {"text": "设备巡检每个车间不一样", "start_ms": 840000, "end_ms": 846000,
             "chunk_index": 1, "source": {"provider": "mock", "model": "mock-asr-v1"}},
        ],
    }

    def chat(file_name, sha, ts, text, msg_id="m001"):
        return {
            "schema": "clientgraph.document.run.v1",
            "source": {"name": file_name, "sha256": sha, "kind": "txt"},
            "messages": [{"id": msg_id, "ts": ts, "sender": "陈晓岚",
                          "text": text, "locator": f"chat://{file_name}#msg={msg_id}"}],
            "blocks": [{"type": "message", "text": text, "ts": ts,
                        "sender": "陈晓岚", "locator": f"chat://{file_name}#msg={msg_id}"}],
        }

    chat_same = chat("chat_0922.txt", "b" * 64, "2026-09-22 09:19:30", "预算大概8万左右")
    chat_other_time = chat("chat_1012.txt", "c" * 64, "2026-10-12 10:00:00", "预算大概8万左右")
    chat_other_customer = chat("chat_heng.txt", "d" * 64, "2026-09-22 09:19:30", "预算大概8万左右")
    chat_other_project = chat("chat_p2.txt", "e" * 64, "2026-09-22 09:19:30", "预算大概8万左右")
    chat_similar = chat("chat_similar.txt", "f" * 64, "2026-09-22 09:19:30", "预算8万")

    ocr = {
        "schema": "clientgraph.media.run.v1",
        "source": {"name": "scan.pdf", "sha256": "1" * 64, "kind": "pdf"},
        "blocks": [{
            "type": "ocr", "text": "青岚智能装备 设备巡检报告", "page": 2,
            "bbox": [10, 20, 100, 50], "confidence": 0.93,
            "locator": "pdf://scan.pdf#page=2&bbox=10,20,100,50&ocr=1",
            "source": {"image_ref": "images/page_002.png", "image_sha256": "2" * 64, "method": "ocr"},
        }],
    }

    office = {
        "schema": "clientgraph.document.run.v1",
        "source": {"name": "req.docx", "sha256": "3" * 64, "kind": "docx"},
        "meta": {"created": "2026-09-29 09:00:00"},
        "blocks": [{
            "type": "table_row", "text": "设备台账 | P0", "table_id": "docxt1",
            "table_index": 1, "row": 2, "cols": ["设备台账", "P0"],
            "locator": "docx://req.docx#table=1&row=2", "source": {"kind": "docx"},
        }],
    }

    email = {
        "schema": "clientgraph.document.run.v1",
        "source": {"name": "mail.eml", "sha256": "4" * 64, "kind": "eml"},
        "meta": {"email": {
            "from": ["陈晓岚 <chen.xiaolan@example.com>"],
            "to": ["王工 <wang.gong@example.com>"],
            "cc": ["李副总 <li.fu@example.com>"],
            "date": "2026-09-29T10:12:00+08:00",
            "subject": "需求确认",
        }},
        "blocks": [{
            "type": "paragraph", "text": "请确认预算区间按 8–10 万准备",
            "locator": "mail://mail.eml#part=plain", "source": {"kind": "eml"},
        }],
    }

    hints = {
        "call_0922.mp3": {"customer_id": "c1", "project_id": "p1"},
        "chat_0922.txt": {"customer_id": "c1", "project_id": "p1"},
        "chat_1012.txt": {"customer_id": "c1", "project_id": "p1"},
        "chat_heng.txt": {"customer_id": "c2", "project_id": "p3"},
        "chat_p2.txt": {"customer_id": "c1", "project_id": "p2"},
        "chat_similar.txt": {"customer_id": "c1", "project_id": "p1"},
        "req.docx": {"customer_id": "c1", "project_id": "p1"},
    }
    occurred = {"call_0922.mp3": "2026-09-22T09:20:00+08:00"}

    return {
        "context": context,
        "results": [audio, chat_same, chat_other_time, chat_other_customer,
                    chat_other_project, chat_similar, ocr, office, email],
        "hints": hints,
        "occurred_at": occurred,
        "window_seconds": 300,
    }


def main() -> int:
    bundle = build_bundle()
    out = collect(bundle["results"], bundle["context"], hints=bundle["hints"],
                  occurred_at=bundle["occurred_at"], window_seconds=bundle["window_seconds"])
    out2 = collect(bundle["results"], bundle["context"], hints=bundle["hints"],
                   occurred_at=bundle["occurred_at"], window_seconds=bundle["window_seconds"])
    items = out["items"]
    checks = {}

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    # Same fact across ASR + chat (30s apart) merges, keeping both sources.
    budget = [i for i in items if i["normalized_text"] == "预算大概8万左右"]
    merged = next((i for i in budget if i["source_count"] == 2), None)
    ensure("cross_source_merge", merged is not None)
    ensure("merged_sources_kept",
           {s["source_type"] for s in merged["sources"]} == {"asr", "chat"},
           [s["source_type"] for s in merged["sources"]])
    ensure("merged_customer", merged["customer"]["id"] == "c1", merged["customer"])
    ensure("merged_project", merged["project"]["id"] == "p1", merged["project"])
    ensure("merged_asr_timestamp",
           any(s["timestamp"] for s in merged["sources"]),
           merged["sources"])

    # Same text at a different time remains separate.
    time_item = next((i for i in budget if (i["occurred_at"] or "").startswith("2026-10-12")), None)
    ensure("time_not_merged", time_item is not None and time_item["source_count"] == 1)

    # Same text, different customer / project remains separate.
    ensure("customer_not_merged",
           any(i["customer"] and i["customer"]["id"] == "c2" and i["source_count"] == 1 for i in budget))
    ensure("project_not_merged",
           any(i["project"] and i["project"]["id"] == "p2" and i["source_count"] == 1 for i in budget))

    # Similar but not identical text is not merged.
    ensure("similar_text_not_merged",
           any(i["normalized_text"] == "预算8万" and i["source_count"] == 1 for i in items))

    # OCR evidence keeps page, bbox, confidence and image reference.
    ocr_item = next(i for i in items if i["source_type"] == "ocr")
    ensure("ocr_page", ocr_item["page"] == 2)
    ensure("ocr_confidence", ocr_item["confidence"] == 0.93, ocr_item["confidence"])
    ensure("ocr_bbox", ocr_item["bbox"] is not None)
    ensure("ocr_image_ref",
           ocr_item["sources"][0]["meta"].get("image_ref") == "images/page_002.png")

    # Office table evidence keeps row/column locator.
    table_item = next(i for i in items if i["source_type"] == "table")
    ensure("table_locator", "table=1" in table_item["sources"][0]["locator"])
    ensure("table_no_confidence", table_item["confidence"] is None)

    # Email evidence keeps sender/recipients/time.
    email_item = next(i for i in items if i["source_type"] == "email")
    ensure("email_customer", email_item["customer"] and email_item["customer"]["id"] == "c1")
    ensure("email_time", email_item["occurred_at"].startswith("2026-09-29T10:12"))
    ensure("email_subject", email_item["sources"][0]["meta"].get("subject") == "需求确认")

    # Every item is citable and has a stable hash.
    for item in items:
        ensure("required_fields", all(item.get(k) for k in
               ("id", "text", "hash", "source_type", "source_file", "sources")))
        ensure("has_locator_or_page", bool(item["sources"][0].get("locator")))
        ensure("hash_length", len(item["hash"]) == 64)
    ensure("stable_ids", [i["id"] for i in items] == [i["id"] for i in out2["items"]])

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": sys.version.split()[0], "platform": sys.platform},
        "stats": out["stats"],
        "checks": checks,
        "all_passed": all(checks.values()),
        "items": [{
            "id": i["id"],
            "text": i["text"],
            "source_type": i["source_type"],
            "source_file": i["source_file"],
            "customer": i["customer"],
            "project": i["project"],
            "occurred_at": i["occurred_at"],
            "page": i["page"],
            "timestamp": i["timestamp"],
            "confidence": i["confidence"],
            "hash": i["hash"],
            "sources": [{"type": s["source_type"], "file": s["file"],
                         "locator": s["locator"], "hash": s["hash"]}
                        for s in i["sources"]],
        } for i in items],
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("items:", len(items), "stats:", out["stats"])
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
