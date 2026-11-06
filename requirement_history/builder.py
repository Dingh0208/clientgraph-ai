# -*- coding: utf-8 -*-
"""Append-only requirement version history over incremental evidence batches.

Batches are processed in order. New evidence can add a version, but never
rewrites a previous version or silently replaces a conclusion.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from extraction import extract

STATUS_LABEL = {"pending": "待确认", "confirmed": "已确认", "cancelled": "已取消"}
CANCEL = re.compile(r"取消|不做|不进入|砍掉|暂不")
CONFIRM = re.compile(r"已确认|客户确认|确认(?:范围|需求|通过|无误)")


def _ev(item: dict) -> dict:
    sources = item.get("sources") or []
    locator = (sources[0] or {}).get("locator") if sources else None
    return {
        "file": item.get("source_file") or item.get("file") or "unknown",
        "source_type": item.get("source_type") or "unknown",
        "locator": locator,
        "occurred_at": item.get("occurred_at"),
        "text": (item.get("text") or "")[:300],
    }


def _dedupe(evs):
    seen, out = set(), []
    for e in evs:
        key = (e.get("file"), e.get("locator"), e.get("text"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _status_from(texts: str) -> str | None:
    if CANCEL.search(texts or ""):
        return "cancelled"
    if CONFIRM.search(texts or ""):
        return "confirmed"
    return None


def _fmt_deadline(d: dict | None) -> str:
    if not d or d.get("value") is None:
        return f"未确定（{d.get('raw') or '未提及'}）" if d and d.get("raw") else "未确定"
    return d["value"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _requirement_changes(prev: dict, cur: dict) -> list[dict]:
    changes = []
    if _norm(prev.get("description")) != _norm(cur.get("description")):
        changes.append({"field": "description", "before": prev.get("description"),
                        "after": cur.get("description"), "evidence": cur.get("sources") or []})
    if (prev.get("owner") or None) != (cur.get("owner") or None):
        changes.append({"field": "owner", "before": prev.get("owner"), "after": cur.get("owner"),
                        "evidence": cur.get("sources") or []})
    pd, cd = prev.get("deadline") or {}, cur.get("deadline") or {}
    if (pd.get("value"), pd.get("status"), pd.get("raw")) != (cd.get("value"), cd.get("status"), cd.get("raw")):
        changes.append({"field": "deadline", "before": pd, "after": cd,
                        "evidence": cur.get("sources") or []})
    if prev.get("status") != cur.get("status"):
        changes.append({"field": "status",
                        "before": STATUS_LABEL.get(prev.get("status")),
                        "after": STATUS_LABEL.get(cur.get("status")),
                        "evidence": cur.get("sources") or []})
    return changes


def _reason(changes: list[dict]) -> str:
    parts = []
    for c in changes:
        if c["field"] == "deadline":
            parts.append(f"截止时间由 {_fmt_deadline(c['before'])} 改为 {_fmt_deadline(c['after'])}")
        elif c["field"] == "owner":
            parts.append(f"负责人由 {c['before'] or '未指定'} 改为 {c['after'] or '未指定'}")
        elif c["field"] == "status":
            parts.append(f"状态由 {c['before']} 改为 {c['after']}")
        elif c["field"] == "description":
            parts.append("需求描述更新")
        else:
            parts.append(c["field"])
    return "；".join(parts) or "证据更新"


def _project_changes(prev: dict | None, cur: dict) -> list[dict]:
    if prev is None:
        return []
    changes = []
    before_scope = {s["key"] for s in prev.get("scope") or []}
    after_scope = {s["key"] for s in cur.get("scope") or []}
    added = sorted(after_scope - before_scope)
    removed = sorted(before_scope - after_scope)
    if added or removed:
        changes.append({"field": "scope", "before": sorted(before_scope), "after": sorted(after_scope),
                        "added": added, "removed": removed, "evidence": cur.get("sources") or []})
    pb, cb = prev.get("budget") or {}, cur.get("budget") or {}
    if (pb.get("status"), sorted({v["amount"] for v in pb.get("values") or []})) != \
       (cb.get("status"), sorted({v["amount"] for v in cb.get("values") or []})):
        changes.append({"field": "budget", "before": pb, "after": cb, "evidence": cur.get("sources") or []})
    pd, cd = prev.get("deadline") or {}, cur.get("deadline") or {}
    if (pd.get("value"), pd.get("status"), pd.get("raw")) != (cd.get("value"), cd.get("status"), cd.get("raw")):
        changes.append({"field": "deadline", "before": pd, "after": cd, "evidence": cur.get("sources") or []})
    pa = [a["text"] for a in prev.get("acceptance") or []]
    ca = [a["text"] for a in cur.get("acceptance") or []]
    if pa != ca:
        changes.append({"field": "acceptance", "before": pa, "after": ca, "evidence": cur.get("sources") or []})
    return changes


def _project_reason(changes: list[dict]) -> str:
    parts = []
    for c in changes:
        if c["field"] == "scope":
            if c.get("added"):
                parts.append("范围新增 " + "、".join(c["added"]))
            if c.get("removed"):
                parts.append("范围移除 " + "、".join(c["removed"]))
        elif c["field"] == "budget":
            before = "、".join(f"{v['amount']:,} 元" for v in c["before"].get("values") or []) or "未提及"
            after = "、".join(f"{v['amount']:,} 元" for v in c["after"].get("values") or []) or "未提及"
            parts.append(f"预算由 {before} 改为 {after}")
        elif c["field"] == "deadline":
            parts.append(f"工期由 {_fmt_deadline(c['before'])} 改为 {_fmt_deadline(c['after'])}")
        elif c["field"] == "acceptance":
            parts.append("验收标准更新")
    return "；".join(parts) or "证据更新"


def build(batches: list[dict], context: dict, confirmed_dates: dict | None = None) -> dict:
    context = context or {}
    confirmed_dates = confirmed_dates or {}
    now = datetime.now(timezone.utc).isoformat()
    project_versions: list[dict] = []
    req_states: dict[str, dict] = {}
    req_order: list[str] = []
    prev_project: dict | None = None

    for batch in batches:
        batch_id = batch.get("id") or batch.get("occurred_at") or "batch"
        occurred_at = batch.get("occurred_at")
        items = batch.get("items") or []
        ex = extract(items, context, confirmed_dates.get(batch_id) or {})
        batch_evidence = _dedupe([_ev(i) for i in items])

        current_reqs = ex.get("requirements") or []
        current_scope = [{"key": r["canonical_key"], "title": r["title"]} for r in current_reqs]
        scope = list(prev_project.get("scope") or []) if prev_project else []
        known = {s["key"] for s in scope}
        for s in current_scope:
            if s["key"] not in known:
                scope.append(s)
                known.add(s["key"])

        budget = ex.get("project", {}).get("budget") or {"status": "missing", "values": [], "evidence": []}
        if budget.get("status") == "missing" and prev_project:
            budget = prev_project["budget"]

        online = next((r for r in current_reqs if r["canonical_key"] == "上线时间"), None)
        deadline = online["deadline"] if online else {"value": None, "status": "missing", "raw": None}
        if prev_project:
            prev_deadline = prev_project.get("deadline") or {}
            if deadline.get("value") is None and prev_deadline.get("value") is not None:
                deadline = prev_deadline
            elif deadline.get("status") == "missing" and prev_deadline:
                deadline = prev_deadline

        acceptance = ex.get("project", {}).get("acceptance_criteria") or []
        if not acceptance and prev_project:
            acceptance = prev_project.get("acceptance") or []

        snapshot = {
            "scope": scope,
            "budget": budget,
            "deadline": deadline,
            "acceptance": acceptance,
            "stage": (ex.get("project", {}).get("stage") or {}).get("value") or
                     (prev_project.get("stage") if prev_project else None),
            "sources": batch_evidence,
        }
        changes = _project_changes(prev_project, snapshot)
        if prev_project is None or changes:
            version = len(project_versions) + 1
            project_versions.append({
                "version": version,
                "occurred_at": occurred_at,
                "recorded_at": now,
                "change_type": "created" if version == 1 else "modified",
                "change_reason": "首次出现" if version == 1 else _project_reason(changes),
                "changes": changes,
                **snapshot,
            })
            prev_project = snapshot
        else:
            prev_project.setdefault("observations", []).append({
                "occurred_at": occurred_at,
                "sources": batch_evidence,
                "note": "证据更新，范围/预算/工期/验收无变化",
            })

        for r in current_reqs:
            key = r["canonical_key"]
            texts = " ".join(e.get("text", "") for e in r.get("evidence") or [])
            event = _status_from(texts)
            state = req_states.get(key)
            current = {
                "title": r["title"],
                "description": r["description"],
                "owner": r["owner"],
                "deadline": r["deadline"],
                "sources": r.get("evidence") or [],
                "proposer": r.get("proposer") or [],
            }

            if state is None:
                status = event or "pending"
                version = {
                    "version": 1,
                    "occurred_at": occurred_at,
                    "recorded_at": now,
                    "change_type": "cancelled" if status == "cancelled" else
                                    ("confirmed" if status == "confirmed" else "created"),
                    "status": status,
                    "change_reason": "首次出现" if status == "pending" else
                                     ("首次出现即取消" if status == "cancelled" else "首次出现并确认"),
                    "changes": [],
                    **current,
                }
                state = {
                    "id": f"R{len(req_order) + 1}",
                    "key": key,
                    "title": r["title"],
                    "versions": [version],
                    "observations": [],
                    "current_status": status,
                    "current_description": current["description"],
                    "current_owner": current["owner"],
                    "current_deadline": current["deadline"],
                    "first_seen_at": occurred_at,
                    "last_seen_at": occurred_at,
                }
                req_states[key] = state
                req_order.append(key)
                continue

            prev_version = state["versions"][-1]
            merged = {
                "title": current["title"],
                "description": current["description"],
                "owner": current["owner"] or prev_version.get("owner"),
                "deadline": current["deadline"],
                "sources": current["sources"],
                "proposer": current["proposer"],
            }
            prev_deadline = prev_version.get("deadline") or {}
            if merged["deadline"].get("value") is None and prev_deadline.get("value") is not None:
                merged["deadline"] = prev_deadline

            status = state["current_status"]
            if event and status != "cancelled":
                status = event
            merged_status = status
            prev_for_diff = {
                "description": prev_version.get("description"),
                "owner": prev_version.get("owner"),
                "deadline": prev_version.get("deadline"),
                "status": prev_version.get("status"),
                "sources": current["sources"],
            }
            after_for_diff = {
                "description": merged["description"],
                "owner": merged["owner"],
                "deadline": merged["deadline"],
                "status": merged_status,
                "sources": current["sources"],
            }
            changes = _requirement_changes(prev_for_diff, after_for_diff)
            if changes:
                change_type = "modified"
                if any(c["field"] == "status" for c in changes):
                    change_type = "cancelled" if merged_status == "cancelled" else \
                                  ("confirmed" if merged_status == "confirmed" else "modified")
                state["versions"].append({
                    "version": len(state["versions"]) + 1,
                    "occurred_at": occurred_at,
                    "recorded_at": now,
                    "change_type": change_type,
                    "status": merged_status,
                    "change_reason": _reason(changes),
                    "changes": changes,
                    **{k: merged[k] for k in ("title", "description", "owner", "deadline", "sources", "proposer")},
                })
                state.update({
                    "current_status": merged_status,
                    "current_description": merged["description"],
                    "current_owner": merged["owner"],
                    "current_deadline": merged["deadline"],
                    "last_seen_at": occurred_at,
                })
            else:
                state["observations"].append({
                    "occurred_at": occurred_at,
                    "sources": current["sources"],
                    "note": f"无字段变化，保留 v{len(state['versions'])}",
                })
                state["last_seen_at"] = occurred_at

    requirements = []
    for key in req_order:
        s = req_states[key]
        requirements.append({
            "id": s["id"],
            "key": s["key"],
            "title": s["title"],
            "current_status": s["current_status"],
            "current_owner": s["current_owner"],
            "current_deadline": s["current_deadline"],
            "first_seen_at": s["first_seen_at"],
            "last_seen_at": s["last_seen_at"],
            "versions": s["versions"],
            "observations": s["observations"],
        })

    return {
        "schema": "clientgraph.requirement_history.v1",
        "project": {
            "id": context.get("project_id") or "p_unknown",
            "name": context.get("project_name") or "未命名项目",
            "current_version": len(project_versions),
            "versions": project_versions,
        },
        "requirements": requirements,
        "stats": {
            "batches": len(batches),
            "requirements": len(requirements),
            "total_versions": sum(len(r["versions"]) for r in requirements),
            "modified_versions": sum(1 for r in requirements for v in r["versions"] if v["change_type"] == "modified"),
            "confirmed_versions": sum(1 for r in requirements for v in r["versions"] if v["change_type"] == "confirmed"),
            "cancelled_versions": sum(1 for r in requirements for v in r["versions"] if v["change_type"] == "cancelled"),
            "project_versions": len(project_versions),
        },
    }
