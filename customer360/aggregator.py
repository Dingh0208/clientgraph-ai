# -*- coding: utf-8 -*-
"""Customer 360 aggregation from the shared data model."""
from __future__ import annotations

from datetime import datetime


def _date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except ValueError:
            return None


def build(data: dict, customer_id: str, now: str | None = None) -> dict:
    customers = {c["id"]: c for c in data.get("customers") or []}
    projects_all = data.get("projects") or []
    customer = customers.get(customer_id)
    if not customer:
        return {"error": "E_CUSTOMER_NOT_FOUND", "customer_id": customer_id}

    projects = [p for p in projects_all if p.get("customer_id") == customer_id]
    pids = {p["id"] for p in projects}
    project_name = {p["id"]: p.get("name", p["id"]) for p in projects_all}

    timeline = []
    for m in data.get("communications") or []:
        if m.get("customer_id") != customer_id:
            continue
        timeline.append({
            "type": "communication",
            "id": m["id"],
            "label": m.get("title") or m["id"],
            "text": m.get("text", ""),
            "locator": m.get("locator"),
            "occurred_at": m.get("occurred_at"),
            "project": {"id": m.get("project_id"), "name": project_name.get(m.get("project_id"))},
        })
    for d in data.get("documents") or []:
        if d.get("customer_id") != customer_id:
            continue
        timeline.append({
            "type": "document",
            "id": d["id"],
            "label": d.get("title") or d["id"],
            "text": d.get("text", ""),
            "locator": d.get("locator"),
            "occurred_at": d.get("occurred_at"),
            "project": {"id": d.get("project_id"), "name": project_name.get(d.get("project_id"))},
        })
    timeline.sort(key=lambda x: (x["occurred_at"] is None, x["occurred_at"] or ""), reverse=False)
    timeline.sort(key=lambda x: (x["occurred_at"] is not None, x["occurred_at"] or ""), reverse=True)

    reqs = [r for r in data.get("requirements") or [] if r.get("project_id") in pids or
            r.get("customer_id") == customer_id]
    risks = [r for r in data.get("risks") or [] if r.get("customer_id") == customer_id or
             r.get("project_id") in pids]
    tasks = [t for t in data.get("tasks") or []
             if (t.get("customer") or {}).get("id") == customer_id]
    evidence = [e for e in data.get("evidence") or [] if e.get("customer_id") == customer_id or
                e.get("project_id") in pids]

    today = _date(now) or datetime.now().date()
    overdue = []
    upcoming = []
    for t in tasks:
        due = _date(t.get("due_at"))
        if t.get("status") != "open" or due is None:
            continue
        days = (today - due).days
        item = {**t, "days": days}
        (overdue if days > 0 else upcoming).append(item)
    overdue.sort(key=lambda t: t["due_at"])
    upcoming.sort(key=lambda t: t["due_at"])
    reminder = None
    if overdue:
        t = overdue[0]
        reminder = f"最近跟进提醒：{t['title']} · 逾期 {t['days']} 天 · 负责人 {t.get('owner') or '未指定'}"
    elif upcoming:
        t = upcoming[0]
        reminder = f"最近跟进提醒：{t['title']} · {t['due_at']} 到期"

    counts = {}
    for r in reqs:
        counts[r.get("status", "unknown")] = counts.get(r.get("status", "unknown"), 0) + 1

    return {
        "customer": {
            "id": customer["id"], "name": customer.get("name"),
            "contacts": customer.get("contacts") or [],
            "phone": customer.get("phone"), "email": customer.get("email"),
            "wechat": customer.get("wechat"),
        },
        "projects": projects,
        "requirements": {
            "total": len(reqs),
            "status": counts,
            "items": reqs,
        },
        "risks": risks,
        "tasks": tasks,
        "recent": [x for x in timeline if x["occurred_at"]][:3],
        "timeline": timeline,
        "evidence_count": len(evidence),
        "evidence": [{"id": e["id"], "locator": e.get("locator"), "text": e.get("text", "")[:120]}
                     for e in evidence],
        "reminder": reminder,
        "stats": {
            "projects": len(projects),
            "requirements": len(reqs),
            "risks": len(risks),
            "tasks": len(tasks),
            "timeline": len(timeline),
            "missing_time": sum(1 for x in timeline if not x["occurred_at"]),
            "evidence": len(evidence),
        },
    }
