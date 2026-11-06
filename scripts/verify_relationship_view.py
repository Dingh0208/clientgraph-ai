# -*- coding: utf-8 -*-
"""Verify explainable relationships: same names, cross-customer similarity,
shared files and manual confirmations."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from relationship_view import build, explain  # noqa: E402

EVIDENCE = ROOT / "evidence" / "relationship-view-2026-11-06.json"


def entities():
    return {
        "customers": [
            {"id": "c1", "name": "同名客户（虚构）", "company": "A 公司"},
            {"id": "c2", "name": "同名客户（虚构）", "company": "B 公司"},
        ],
        "projects": [
            {"id": "p1", "name": "同名项目", "customer_id": "c1"},
            {"id": "p2", "name": "同名项目", "customer_id": "c2"},
            {"id": "p3", "name": "共享文件项目", "customer_id": "c1"},
        ],
        "communications": [
            {"id": "m1", "title": "合同沟通", "customer_id": "c1", "project_id": "p1", "file_id": "f1", "channel": "email"},
            {"id": "m2", "title": "补充沟通", "customer_id": "c1", "project_id": "p3", "file_id": "f1", "channel": "chat"},
        ],
        "files": [
            {"id": "f1", "name": "共享合同.pdf"},
            {"id": "f2", "name": "其他附件.pdf"},
        ],
        "requirements": [
            {"id": "r1", "title": "设备台账要支持扫码查看档案", "project_id": "p1", "description": "设备台账要支持扫码查看档案", "evidence_ids": ["ev1", "ev3"]},
            {"id": "r2", "title": "统计看板按车间筛选", "project_id": "p3", "description": "统计看板按车间筛选", "evidence_ids": ["ev2"]},
            {"id": "r3", "title": "设备台账需要扫码查看档案", "project_id": "p2", "description": "设备台账需要扫码查看档案", "evidence_ids": ["ev4"]},
        ],
        "risks": [
            {"id": "k1", "title": "预算未确认", "project_id": "p1", "evidence_ids": ["ev1"]},
        ],
        "tasks": [
            {"id": "t1", "title": "确认预算", "project_id": "p1", "requirement_id": "r1", "evidence_ids": ["ev1"]},
        ],
        "evidence": [
            {"id": "ev1", "source_type": "file", "source_id": "f1", "locator": "pdf://f1#page=1", "text": "设备台账..."},
            {"id": "ev2", "source_type": "file", "source_id": "f1", "locator": "pdf://f1#page=2", "text": "统计看板..."},
            {"id": "ev3", "source_type": "communication", "source_id": "m1", "locator": "chat://m1#msg=1", "text": "扫码查看..."},
            {"id": "ev4", "source_type": "file", "source_id": "f1", "locator": "pdf://f1#page=3", "text": "设备台账..."},
        ],
    }


def main() -> int:
    manual = [{
        "from": "customer:c1", "to": "file:f1", "relation": "uses_file",
        "operator": "王工（我）", "at": "2026-11-06T10:00:00+08:00",
        "note": "合同由青岚提供", "sources": [{"type": "file", "id": "f1"}],
    }]
    graph = build(entities(), manual)
    checks = {}

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    nodes = {n["id"]: n for n in graph["nodes"]}
    edges = graph["edges"]

    def find(frm, to, etype=None):
        for e in edges:
            if e["from"] == frm and e["to"] == to and (etype is None or e["type"] == etype):
                return e
        return None

    ensure("node_types", {"customer", "project", "communication", "file",
                          "requirement", "risk", "task", "evidence"} ==
           {n["type"] for n in graph["nodes"]})
    ensure("same_name_customers_kept", "customer:c1" in nodes and "customer:c2" in nodes and
           nodes["customer:c1"]["label"] == nodes["customer:c2"]["label"])
    ensure("no_direct_customer_merge", find("customer:c1", "customer:c2", "direct_evidence") is None)
    dup_cust = find("customer:c1", "customer:c2", "semantic_similar")
    ensure("customer_name_suggestion", dup_cust is not None and dup_cust["requires_confirmation"] and
           "名称完全相同" in dup_cust["why"], dup_cust)

    ensure("same_name_projects_kept", "project:p1" in nodes and "project:p2" in nodes)
    dup_proj = find("project:p1", "project:p2", "semantic_similar")
    ensure("project_name_suggestion", dup_proj is not None and dup_proj["requires_confirmation"])

    ensure("r1_own_project", find("project:p1", "requirement:r1") is not None)
    ensure("r3_own_project", find("project:p2", "requirement:r3") is not None)
    ensure("no_cross_project_attach", find("project:p1", "requirement:r3") is None)
    sim_req = find("requirement:r1", "requirement:r3", "semantic_similar")
    ensure("cross_customer_similarity", sim_req is not None and sim_req["requires_confirmation"] and
           "相似度" in sim_req["why"] and sim_req["confidence"] >= 0.55, sim_req)
    ensure("similarity_not_merged", find("requirement:r1", "requirement:r3", "direct_evidence") is None)

    file_node = nodes["file:f1"]
    ensure("file_multi_project", set(file_node["attrs"].get("project_ids", [])) == {"p1", "p3"},
           file_node["attrs"].get("project_ids"))
    ensure("file_from_m1", find("communication:m1", "file:f1") is not None)
    ensure("file_from_m2", find("communication:m2", "file:f1") is not None)
    ensure("file_multi_evidence", all(find(f"evidence:{e}", "file:f1") is not None
                                      for e in ("ev1", "ev2", "ev4")))

    req_ev = find("requirement:r1", "evidence:ev1")
    ensure("direct_evidence_edge", req_ev is not None and req_ev["type"] == "direct_evidence" and
           req_ev["why"] and req_ev["requires_confirmation"] is False)
    ensure("evidence_points_file", find("evidence:ev1", "file:f1") is not None)
    ensure("risk_evidence", find("risk:k1", "evidence:ev1") is not None)
    ensure("task_requirement", find("task:t1", "requirement:r1") is not None)

    manual_edge = find("customer:c1", "file:f1")
    ensure("manual_confirmed", manual_edge is not None and manual_edge["type"] == "manual_confirmed" and
           manual_edge["requires_confirmation"] is False and "王工" in manual_edge["why"], manual_edge)

    allowed = {"direct_evidence", "semantic_similar", "manual_confirmed"}
    ensure("all_types", all(e["type"] in allowed for e in edges))
    ensure("all_why", all(e["why"] for e in edges))
    ensure("semantic_pending", all(e["requires_confirmation"] for e in edges
                                   if e["type"] == "semantic_similar"))
    ensure("direct_not_pending", all(not e["requires_confirmation"] for e in edges
                                     if e["type"] == "direct_evidence"))
    ensure("stats", graph["stats"]["nodes"] == len(graph["nodes"]) and
           graph["stats"]["manual_confirmed"] == 1 and
           graph["stats"]["semantic_similar"] >= 3, graph["stats"])

    explained = explain(graph, manual_edge["id"])
    ensure("explain", explained["type"] == "manual_confirmed" and "人工确认" in explained["why"])

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": graph["stats"],
        "checks": checks,
        "all_passed": all(checks.values()),
        "nodes": [{"id": n["id"], "type": n["type"], "label": n["label"]} for n in graph["nodes"]],
        "edges": [{
            "id": e["id"], "from": e["from"], "to": e["to"], "type": e["type"],
            "why": e["why"], "requires_confirmation": e["requires_confirmation"],
            "confidence": e["confidence"],
        } for e in edges],
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("stats:", graph["stats"])
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
