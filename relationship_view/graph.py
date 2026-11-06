# -*- coding: utf-8 -*-
"""Explainable relationship graph for customer/project/communication/file/
requirement/risk/task/evidence.

Every edge says why it exists and whether it is direct evidence, semantic
similarity, or a human confirmation. Similarity never merges entities.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

PREFIX = {
    "customers": "customer", "projects": "project", "communications": "communication",
    "files": "file", "documents": "document", "requirements": "requirement",
    "risks": "risk", "tasks": "task", "evidence": "evidence",
}


def _norm(text) -> str:
    s = unicodedata.normalize("NFKC", str(text or "")).lower()
    return "".join(ch for ch in s if not ch.isspace() and not unicodedata.category(ch).startswith("P"))


def _bigrams(text: str) -> set[str]:
    s = _norm(text)
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def similarity(a: str, b: str) -> tuple[float, list[str]]:
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return 0.0, []
    common = ba & bb
    score = len(common) / len(ba | bb)
    return round(score, 3), sorted(common)[:8]


def _label(entity: dict, kind: str) -> str:
    if kind in ("customers", "projects", "files"):
        return entity.get("name") or entity.get("id")
    if kind in ("requirements", "risks", "tasks"):
        return entity.get("title") or entity.get("description") or entity.get("id")
    if kind == "communications":
        return entity.get("title") or entity.get("id")
    if kind == "evidence":
        return (entity.get("text") or entity.get("locator") or entity.get("id"))[:40]
    return entity.get("id")


def build(entities: dict, manual_links: list[dict] | None = None,
          similarity_threshold: float = 0.55) -> dict:
    manual_links = manual_links or []
    nodes: dict[str, dict] = {}
    raw_to_node: dict[str, str] = {}
    by_kind: dict[str, list[dict]] = {}

    for kind, prefix in PREFIX.items():
        items = entities.get(kind) or []
        by_kind[kind] = items
        for entity in items:
            nid = f"{prefix}:{entity['id']}"
            attrs = {k: v for k, v in entity.items() if k != "id"}
            nodes[nid] = {
                "id": nid,
                "type": prefix,
                "label": _label(entity, kind),
                "attrs": attrs,
            }
            raw_to_node[str(entity["id"])] = nid

    edges: list[dict] = []
    seen = set()

    def add_edge(frm, to, relation, etype, why, evidence=None,
                 confidence=1.0, requires=False, sources=None):
        if frm not in nodes or to not in nodes or frm == to:
            return
        key = (frm, to, etype, relation)
        if key in seen:
            return
        seen.add(key)
        edges.append({
            "id": f"E{len(edges) + 1}",
            "from": frm,
            "to": to,
            "relation": relation,
            "type": etype,
            "why": why,
            "evidence": evidence or [],
            "sources": sources or [],
            "confidence": confidence,
            "requires_confirmation": requires,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    projects = {p["id"]: p for p in by_kind["projects"]}
    customers = {c["id"]: c for c in by_kind["customers"]}
    communications = {m["id"]: m for m in by_kind["communications"]}
    files = {f["id"]: f for f in by_kind["files"]}
    requirements = {r["id"]: r for r in by_kind["requirements"]}

    # Ownership
    for p in by_kind["projects"]:
        cid = p.get("customer_id")
        if cid:
            add_edge(f"customer:{cid}", f"project:{p['id']}", "owns_project", "direct_evidence",
                     f"项目「{p.get('name', p['id'])}」的 customer_id={cid}，属于直接归属。",
                     sources=[{"type": "project", "id": p["id"]}])

    # Communications
    for m in by_kind["communications"]:
        cid, pid = m.get("customer_id"), m.get("project_id")
        if cid:
            add_edge(f"customer:{cid}", f"communication:{m['id']}", "has_communication",
                     "direct_evidence",
                     f"沟通 {m['id']} 的 customer_id={cid}，来源：导入归属。",
                     sources=[{"type": "communication", "id": m["id"]}])
        if pid:
            add_edge(f"project:{pid}", f"communication:{m['id']}", "has_communication",
                     "direct_evidence",
                     f"沟通 {m['id']} 的 project_id={pid}，来源：导入归属。",
                     sources=[{"type": "communication", "id": m["id"]}])
        fid = m.get("file_id")
        if fid:
            add_edge(f"communication:{m['id']}", f"file:{fid}", "has_source_file",
                     "direct_evidence",
                     f"沟通 {m['id']} 引用文件 {fid}，属于直接来源。",
                     sources=[{"type": "file", "id": fid}])
            file_node = nodes.get(f"file:{fid}")
            if file_node is not None and m.get("project_id"):
                plist = file_node["attrs"].setdefault("project_ids", [])
                if m["project_id"] not in plist:
                    plist.append(m["project_id"])

    # Requirements
    for r in by_kind["requirements"]:
        pid = r.get("project_id")
        cid = r.get("customer_id") or (projects.get(pid) or {}).get("customer_id")
        if pid:
            add_edge(f"project:{pid}", f"requirement:{r['id']}", "has_requirement",
                     "direct_evidence",
                     f"需求「{r.get('title', r['id'])}」的 project_id={pid}，来源：需求抽取。",
                     sources=[{"type": "requirement", "id": r["id"]}])
        if cid:
            add_edge(f"customer:{cid}", f"requirement:{r['id']}", "has_requirement",
                     "direct_evidence",
                     f"需求「{r.get('title', r['id'])}」归属客户 {cid}（由项目归属推导）。",
                     sources=[{"type": "requirement", "id": r["id"]}])
        for ev in r.get("evidence_ids") or []:
            add_edge(f"requirement:{r['id']}", f"evidence:{ev}", "supported_by",
                     "direct_evidence",
                     f"需求 {r['id']} 显式引用证据 {ev}。",
                     evidence=[ev], sources=[{"type": "evidence", "id": ev}])

    # Evidence source
    for ev in by_kind["evidence"]:
        st, sid = ev.get("source_type"), ev.get("source_id")
        if st == "file" and sid:
            add_edge(f"evidence:{ev['id']}", f"file:{sid}", "points_to_source",
                     "direct_evidence",
                     f"证据 {ev['id']} 的 locator={ev.get('locator')}，指向文件 {sid}。",
                     evidence=[ev["id"]], sources=[{"type": "file", "id": sid,
                                                    "locator": ev.get("locator")}])
        elif st == "communication" and sid:
            add_edge(f"evidence:{ev['id']}", f"communication:{sid}", "points_to_source",
                     "direct_evidence",
                     f"证据 {ev['id']} 的 locator={ev.get('locator')}，指向沟通 {sid}。",
                     evidence=[ev["id"]], sources=[{"type": "communication", "id": sid,
                                                    "locator": ev.get("locator")}])

    # Risks and tasks
    for k in by_kind["risks"]:
        pid = k.get("project_id")
        if pid:
            add_edge(f"project:{pid}", f"risk:{k['id']}", "has_risk", "direct_evidence",
                     f"风险「{k.get('title', k['id'])}」的 project_id={pid}。",
                     sources=[{"type": "risk", "id": k["id"]}])
        for ev in k.get("evidence_ids") or []:
            add_edge(f"risk:{k['id']}", f"evidence:{ev}", "supported_by", "direct_evidence",
                     f"风险 {k['id']} 显式引用证据 {ev}。", evidence=[ev],
                     sources=[{"type": "evidence", "id": ev}])

    for t in by_kind["tasks"]:
        pid = t.get("project_id")
        if pid:
            add_edge(f"project:{pid}", f"task:{t['id']}", "has_task", "direct_evidence",
                     f"待办「{t.get('title', t['id'])}」的 project_id={pid}。",
                     sources=[{"type": "task", "id": t["id"]}])
        rid = t.get("requirement_id")
        if rid:
            add_edge(f"task:{t['id']}", f"requirement:{rid}", "implements", "direct_evidence",
                     f"待办 {t['id']} 的 requirement_id={rid}。",
                     sources=[{"type": "task", "id": t["id"]}])
        for ev in t.get("evidence_ids") or []:
            add_edge(f"task:{t['id']}", f"evidence:{ev}", "supported_by", "direct_evidence",
                     f"待办 {t['id']} 显式引用来源证据 {ev}。", evidence=[ev],
                     sources=[{"type": "evidence", "id": ev}])

    # Same-name customers/projects: suggestion only.
    for kind, prefix in (("customers", "customer"), ("projects", "project")):
        items = by_kind[kind]
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                na, nb = _norm(a.get("name")), _norm(b.get("name"))
                if na and na == nb:
                    add_edge(f"{prefix}:{a['id']}", f"{prefix}:{b['id']}",
                             "name_duplicate_suggestion", "semantic_similar",
                             f"名称完全相同（“{a.get('name')}”），疑似重复；仅作建议，不合并，需人工确认。",
                             confidence=1.0, requires=True,
                             sources=[{"type": kind, "id": a["id"]},
                                      {"type": kind, "id": b["id"]}])

    # Similar requirements across any scope: suggestion only.
    reqs = by_kind["requirements"]
    for i in range(len(reqs)):
        for j in range(i + 1, len(reqs)):
            a, b = reqs[i], reqs[j]
            text_a = f"{a.get('title', '')} {a.get('description', '')}"
            text_b = f"{b.get('title', '')} {b.get('description', '')}"
            score, common = similarity(text_a, text_b)
            if score < similarity_threshold:
                continue
            add_edge(f"requirement:{a['id']}", f"requirement:{b['id']}",
                     "similar_text_suggestion", "semantic_similar",
                     f"文本相似度 {score:.2f}（共同片段：{'、'.join(common[:5]) or '无'}）；"
                     f"仅作建议，不合并，需人工确认。",
                     confidence=score, requires=True,
                     sources=[{"type": "requirement", "id": a["id"]},
                              {"type": "requirement", "id": b["id"]}])

    # Manual confirmations
    warnings = []
    for link in manual_links:
        frm = link.get("from")
        to = link.get("to")
        frm = frm if frm in nodes else raw_to_node.get(str(frm))
        to = to if to in nodes else raw_to_node.get(str(to))
        if not frm or not to:
            warnings.append({"code": "W_MANUAL_LINK_INVALID", "link": link})
            continue
        add_edge(frm, to, link.get("relation") or "manual_link", "manual_confirmed",
                 f"人工确认：{link.get('operator') or '未知操作人'} 于 "
                 f"{link.get('at') or '未记录时间'} 关联；备注：{link.get('note') or '无'}。",
                 evidence=link.get("evidence") or [], confidence=1.0, requires=False,
                 sources=link.get("sources") or [])

    edges.sort(key=lambda e: ({"direct_evidence": 0, "semantic_similar": 1,
                               "manual_confirmed": 2}[e["type"]], e["id"]))
    for i, e in enumerate(edges, 1):
        e["id"] = f"E{i}"

    return {
        "schema": "clientgraph.relationships.v1",
        "nodes": list(nodes.values()),
        "edges": edges,
        "warnings": warnings,
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "direct_evidence": sum(1 for e in edges if e["type"] == "direct_evidence"),
            "semantic_similar": sum(1 for e in edges if e["type"] == "semantic_similar"),
            "manual_confirmed": sum(1 for e in edges if e["type"] == "manual_confirmed"),
            "pending_confirmation": sum(1 for e in edges if e["requires_confirmation"]),
        },
    }


def explain(graph: dict, edge_id: str) -> dict:
    for edge in graph.get("edges") or []:
        if edge["id"] == edge_id:
            return {
                "edge_id": edge_id,
                "type": edge["type"],
                "why": edge["why"],
                "evidence": edge["evidence"],
                "sources": edge["sources"],
                "confidence": edge["confidence"],
                "requires_confirmation": edge["requires_confirmation"],
            }
    return {"edge_id": edge_id, "error": "E_EDGE_NOT_FOUND"}
