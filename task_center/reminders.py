# -*- coding: utf-8 -*-
"""Reminder policy for local Windows notifications.

Rules:
  * only when the application is running;
  * quiet hours 22:00–08:00, no OS notification;
  * one notification per task/customer per day;
  * if the app was closed, catch-up is in-app only and never marks a
    notification as sent.
"""
from __future__ import annotations

from datetime import datetime, time as dtime

from .store import TaskStore


class FakeNotifier:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.sent = []

    def send(self, title: str, message: str) -> bool:
        if self.fail_times > 0:
            self.fail_times -= 1
            return False
        self.sent.append({"title": title, "message": message})
        return True


def _date(value):
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except ValueError:
            return None


class ReminderEngine:
    def __init__(self, store: TaskStore, customers: list[dict],
                 notifier, quiet=(22, 8), stale_days: int = 7):
        self.store = store
        self.customers = {c["id"]: c for c in customers}
        self.notifier = notifier
        self.quiet = quiet
        self.stale_days = stale_days
        self.sent_keys = set()
        self.sent_log = []
        self.failures = []

    def _quiet(self, now: datetime) -> bool:
        hour = now.hour
        start, end = self.quiet
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end

    def candidates(self, now: datetime) -> list[dict]:
        today = now.date()
        out = []
        for task in self.store.tasks:
            if task["status"] != "open" or not task.get("due_at"):
                continue
            due = _date(task["due_at"])
            if due is None or due > today:
                continue
            days = (today - due).days
            rtype = "task_overdue" if days > 0 else "task_due"
            out.append({
                "key": f"task:{task['id']}:{today.isoformat()}",
                "type": rtype,
                "task_id": task["id"],
                "title": task["title"],
                "customer_id": task["customer"]["id"],
                "project_id": task["project"]["id"],
                "due_at": task["due_at"],
                "days": days,
                "message": (f"已逾期 {days} 天：{task['title']}" if days > 0
                            else f"今天到期：{task['title']}"),
            })

        for cid, customer in self.customers.items():
            last = _date(customer.get("last_contact_at"))
            days = None if last is None else (today - last).days
            if days is not None and days <= self.stale_days:
                continue
            out.append({
                "key": f"customer:{cid}:{today.isoformat()}",
                "type": "customer_no_follow_up",
                "customer_id": cid,
                "project_id": None,
                "due_at": None,
                "days": days,
                "message": (f"客户 {customer.get('name', cid)} 已 {days} 天无跟进"
                            if days is not None else
                            f"客户 {customer.get('name', cid)} 从未记录跟进"),
            })
        out.sort(key=lambda r: (r["type"] != "task_overdue", r["type"] != "task_due", r["key"]))
        return out

    def tick(self, now: datetime, app_active: bool = True) -> dict:
        if not app_active:
            return {"sent": [], "skipped": "app_inactive", "candidates": []}
        if self._quiet(now):
            return {"sent": [], "skipped": "quiet_hours", "candidates": self.candidates(now)}

        sent, failures = [], []
        for item in self.candidates(now):
            if item["key"] in self.sent_keys:
                continue
            ok = self.notifier.send("ClientGraph AI 提醒", item["message"])
            if not ok:
                failures.append({"key": item["key"], "message": item["message"]})
                self.failures.append({"key": item["key"], "at": now.isoformat()})
                continue
            self.sent_keys.add(item["key"])
            record = {
                "key": item["key"], "type": item["type"], "message": item["message"],
                "task_id": item.get("task_id"), "customer_id": item.get("customer_id"),
                "sent_at": now.isoformat(), "delivery": "windows",
            }
            self.sent_log.append(record)
            sent.append(record)
            if item.get("task_id"):
                task = self.store.by_id.get(item["task_id"])
                if task is not None:
                    task["reminders_sent"].append(record)
        return {"sent": sent, "failures": failures, "skipped": None,
                "candidates": self.candidates(now)}

    def catch_up(self, now: datetime) -> list[dict]:
        """In-app only: never marks OS notifications as sent."""
        return [{**item, "delivery": "in_app", "sent_at": None}
                for item in self.candidates(now)]
