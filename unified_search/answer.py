# -*- coding: utf-8 -*-
"""Natural-language questions over the unified index.

Answers always carry customers/projects, conclusion, evidence, times and an
explicit uncertainty block. No model is called.
"""
from __future__ import annotations

import re
from datetime import datetime

from .index import SearchIndex, terms


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


def _uniq(items, key="id"):
    out, seen = [], set()
    for item in items:
        if not item:
            continue
        k = item.get(key)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


def _evidence(items):
    out, seen = [], set()
    for item in items:
        loc = item.get("locator") or (item.get("source") or {}).get("locator")
        label = item.get("label") or item.get("title") or item.get("entity_id") or item.get("file")
        occurred = item.get("occurred_at") or (item.get("source") or {}).get("occurred_at")
        key = loc or (label, occurred)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "type": item.get("entity_type") or item.get("source_type") or item.get("type") or "evidence",
            "label": label or "来源",
            "locator": loc,
            "occurred_at": occurred,
            "snippet": (item.get("snippet") or item.get("text") or "")[:220],
        })
    return [e for e in out if e["locator"]]


def _base(query, intent, conclusion, customers, projects, evidence, times,
          uncertainty, items=None):
    times = sorted({t for t in times if t})
    return {
        "query": query,
        "intent": intent,
        "conclusion": conclusion,
        "customers": _uniq(customers or []),
        "projects": _uniq(projects or []),
        "time": times[-1] if times else None,
        "times": times,
        "evidence": evidence[:12],
        "items": items or [],
        "uncertainty": uncertainty,
    }


def _mentions(query, index):
    hits = index.search(query, limit=40,
                        types=["communication", "document", "requirement", "evidence"])
    customers = _uniq([h["customer"] for h in hits if h.get("customer")])
    projects = _uniq([h["project"] for h in hits if h.get("project")])
    evidence = _evidence(hits)
    times = [h.get("occurred_at") for h in hits]
    qterms = query
    m = re.search(r"(?:提过|提到)(.+)", query)
    if m:
        qterms = m.group(1).strip(" ？?。")
    if not qterms:
        qterms = "".join(terms(query)[:3]) or query
    if customers:
        names = "、".join(c["name"] for c in customers)
        conclusion = f"提过“{qterms}”的客户：{names}"
        direct = [h for h in hits if h["entity_type"] in ("communication", "document")]
        if direct:
            uncertainty = {"level": "low",
                           "reasons": [f"命中 {len(direct)} 条原始沟通/文档，可逐条定位"]}
        else:
            uncertainty = {"level": "medium",
                           "reasons": ["仅需求条目命中，缺少原始沟通原文"]}
    else:
        conclusion = f"未找到客户提过“{qterms}”的记录"
        uncertainty = {"level": "high", "reasons": ["关键词未命中任何客户资料"]}
    return _base(query, "customer_mentions", conclusion, customers, projects,
                 evidence, times, uncertainty, hits)


def _find_project(name, index):
    name = (name or "").strip(" 的？?")
    projects = list(index.projects.values())
    if name and name not in ("某项目", "这个项目"):
        exact = [p for p in projects if p.get("name") == name]
        if exact:
            return exact[0]
        partial = [p for p in projects if name and (name in p.get("name", "") or
                                                    p.get("name", "") in name)]
        if partial:
            return partial[0]
    if len(projects) == 1:
        return projects[0]
    return None


def _change(query, index, data):
    m = re.search(r"^(.*?)(?:最近一次变更|最近变更|最新变更|变更历史|改了什么)", query)
    name = m.group(1).strip() if m else ""
    project = _find_project(name, index)
    if not project:
        return _base(query, "project_change", "未识别到对应项目，无法给出最近变更。",
                     [], [], [], [], {"level": "high", "reasons": ["查询中没有可匹配的项目名称"]})
    customer = index._customer(project.get("customer_id"))
    history = next((h for h in (data.get("history") or {}).get("projects") or []
                    if h.get("id") == project["id"]), None)
    versions = sorted((history or {}).get("versions") or [], key=lambda v: v.get("version", 0))
    if not versions:
        return _base(query, "project_change", f"项目“{project['name']}”暂无变更记录。",
                     [customer], [{"id": project["id"], "name": project["name"]}], [],
                     [], {"level": "high", "reasons": ["没有版本历史"]})
    latest = versions[-1]
    reason = latest.get("change_reason") or "未记录变更原因"
    conclusion = f"项目“{project['name']}”最近一次变更为 v{latest.get('version')}：{reason}"
    sources = latest.get("sources") or latest.get("evidence") or []
    evidence = _evidence([{**s, "entity_type": s.get("type") or "source",
                            "label": s.get("label") or s.get("file")} for s in sources])
    times = [latest.get("occurred_at")] + [s.get("occurred_at") for s in sources]
    uncertainty = ({"level": "low", "reasons": ["版本记录含变更原因与来源"]}
                   if sources else
                   {"level": "medium", "reasons": ["有版本记录，但缺少来源引用"]})
    return _base(query, "project_change", conclusion, [customer],
                 [{"id": project["id"], "name": project["name"]}],
                 evidence, times, uncertainty,
                 [{"version": latest.get("version"), "changes": latest.get("changes") or [],
                   "change_reason": reason}])


def _overdue(query, index, data, now):
    today = _date(now) or datetime.now().date()
    tasks = []
    for t in data.get("tasks") or []:
        if t.get("status") != "open" or not t.get("due_at"):
            continue
        due = _date(t["due_at"])
        if due is None or due >= today:
            continue
        days = (today - due).days
        tasks.append({**t, "_days": days})
    tasks.sort(key=lambda t: t["due_at"])
    evidence = _evidence([t.get("source") or {} for t in tasks])
    evidence = [e for e in evidence if e.get("locator")]
    customers = _uniq([(t.get("customer") or {}) for t in tasks if t.get("customer")])
    projects = _uniq([(t.get("project") or {}) for t in tasks if t.get("project")])
    times = [t["due_at"] for t in tasks]
    if tasks:
        names = "、".join(f"{t.get('title')}（逾期 {t['_days']} 天）" for t in tasks)
        conclusion = f"已逾期 {len(tasks)} 项：{names}"
        uncertainty = {"level": "low", "reasons": ["按待办状态与截止日期筛选"]}
    else:
        conclusion = "没有已逾期的待办。"
        uncertainty = {"level": "low", "reasons": ["按当前数据与日期计算"]}
    return _base(query, "overdue_tasks", conclusion, customers, projects,
                 evidence, times, uncertainty,
                 [{"id": t["id"], "title": t.get("title"), "due_at": t["due_at"],
                   "days": t["_days"]} for t in tasks])


def answer(query: str, data: dict, now: str | None = None) -> dict:
    q = (query or "").strip()
    index = SearchIndex(data)
    if re.search(r"哪些客户|谁.*提过|客户.*提过|哪些.*客户", q):
        return _mentions(q, index)
    if re.search(r"最近.*变更|变更.*什么|改了什么|变更历史", q):
        return _change(q, index, data)
    if re.search(r"逾期|超期|过期", q):
        return _overdue(q, index, data, now)
    hits = index.search(q, limit=20)
    evidence = _evidence(hits)
    customers = _uniq([h["customer"] for h in hits if h.get("customer")])
    projects = _uniq([h["project"] for h in hits if h.get("project")])
    times = [h.get("occurred_at") for h in hits]
    if hits:
        conclusion = f"检索到 {len(hits)} 条相关记录；仅做关键词检索，未生成推断。"
        uncertainty = {"level": "medium", "reasons": ["关键词检索结果，未做语义结论"]}
    else:
        conclusion = "未找到相关记录。"
        uncertainty = {"level": "high", "reasons": ["关键词未命中"]}
    return _base(q, "keyword", conclusion, customers, projects, evidence, times,
                 uncertainty, hits)
