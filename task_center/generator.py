# -*- coding: utf-8 -*-
"""Generate tasks only from explicit next actions.

A deadline is written only for an explicit calendar date. Vague expressions
become pending questions and keep due_at empty.
"""
from __future__ import annotations

import re
from datetime import datetime

ACTION = re.compile(r"请|需要|安排|跟进|发送|提供|确认|联系|回复|提交|完成|报价|上线|给到|准备|补充|整理|推进|给一版|原型")
EXPLICIT_DATE = re.compile(r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})\s*日?")
VAGUE = re.compile(r"\d{1,2}\s*月\s*底|月底|尽快|下周[一二三四五六日天]?|本周|下个月|之后|晚点|越快越好")
OWNER_PREFIX = re.compile(r"^([\u4e00-\u9fa5]{2,4})[，,]\s*请")
OWNER_LABEL = re.compile(r"负责人\s*[:：]\s*([^\s，。；]{2,30})")
OWNER_BY = re.compile(r"由\s*([\u4e00-\u9fa5]{2,4})\s*负责")


def _today(now: datetime):
    return now.date()


def _due(clause: str):
    dates = []
    for m in EXPLICIT_DATE.finditer(clause):
        try:
            dates.append(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d"))
        except ValueError:
            continue
    vague = [m.group(0) for m in VAGUE.finditer(clause)]
    if dates:
        return dates[0], "explicit", vague
    if vague:
        return None, "pending_vague", vague
    return None, "missing", []


def _owner(clause: str):
    for pattern in (OWNER_PREFIX, OWNER_LABEL, OWNER_BY):
        m = pattern.search(clause)
        if m:
            return m.group(1)
    return None


def _priority(clause: str, due, now: datetime) -> str:
    if re.search(r"紧急|P0|立即|马上|今天", clause):
        return "P0"
    if due:
        try:
            days = (datetime.strptime(due, "%Y-%m-%d").date() - _today(now)).days
            if days < 0:
                return "P0"
        except ValueError:
            pass
    if re.search(r"重要|P1|本周", clause):
        return "P1"
    return "P2"


def _risk(priority: str, due, now: datetime) -> dict:
    days = None
    if due:
        try:
            days = (datetime.strptime(due, "%Y-%m-%d").date() - _today(now)).days
        except ValueError:
            days = None
    if days is not None and days < 0:
        return {"level": "high", "note": f"已逾期 {-days} 天"}
    if days == 0:
        return {"level": "high", "note": "今天到期"}
    if days is not None and days <= 3:
        return {"level": "medium", "note": f"{days} 天内到期"}
    if priority == "P0":
        return {"level": "high", "note": "高优先级"}
    if priority == "P1":
        return {"level": "medium", "note": "重要但不紧急"}
    return {"level": "low", "note": "常规跟进"}


def generate_tasks(items: list[dict], context: dict, now: datetime) -> list[dict]:
    context = context or {}
    customers = {c["id"]: c for c in context.get("customers") or []}
    projects = {p["id"]: p for p in context.get("projects") or []}
    default_customer = context.get("customer") or {"id": "c_unknown", "name": "未命名客户"}
    default_project = context.get("project") or {"id": "p_unknown", "name": "未命名项目"}

    tasks = []
    for item in items:
        text = (item.get("text") or "").strip()
        if not text or not ACTION.search(text):
            continue
        cid = item.get("customer_id") or (item.get("customer") or {}).get("id") or default_customer.get("id")
        pid = item.get("project_id") or (item.get("project") or {}).get("id") or default_project.get("id")
        customer = customers.get(cid, default_customer)
        project = projects.get(pid, default_project)
        due, due_status, vague = _due(text)
        owner = item.get("owner") or _owner(text)
        priority = _priority(text, due, now)
        pending = []
        if due_status == "pending_vague":
            pending.append({
                "type": "due_vague",
                "question": f"“{vague[0]}”不是明确日期，请确认具体截止时间（年-月-日）。",
            })
        elif due_status == "missing":
            pending.append({"type": "due_missing", "question": "该动作没有明确截止时间，请补充日期。"})
        if not owner:
            pending.append({"type": "owner_missing", "question": "该动作未指定负责人，请确认由谁负责。"})

        source = item.get("sources") or [{}]
        src = source[0] if source else {}
        tasks.append({
            "id": f"T{len(tasks) + 1}",
            "title": text[:80],
            "owner": owner,
            "customer": {"id": customer.get("id"), "name": customer.get("name")},
            "project": {"id": project.get("id"), "name": project.get("name")},
            "due_at": due,
            "due_status": due_status,
            "due_raw": vague[0] if vague else due,
            "priority": priority,
            "status": "open",
            "risk": _risk(priority, due, now),
            "source": {
                "file": item.get("source_file") or "unknown",
                "source_type": item.get("source_type") or "unknown",
                "locator": src.get("locator"),
                "occurred_at": item.get("occurred_at"),
                "text": text[:300],
            },
            "pending": pending,
            "postpone_count": 0,
            "reopened_count": 0,
            "reminders_sent": [],
            "created_at": now.isoformat(),
            "completed_at": None,
            "history": [{
                "action": "created",
                "at": now.isoformat(),
                "operator": "system",
                "detail": "从明确的下一步动作生成",
            }],
        })
    return tasks
