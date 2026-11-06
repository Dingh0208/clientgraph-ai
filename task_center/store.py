# -*- coding: utf-8 -*-
"""Task operations: complete, postpone, reopen, batch, audit history."""
from __future__ import annotations

import re
from datetime import datetime

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TaskError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _iso(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class TaskStore:
    def __init__(self, tasks: list[dict]):
        self.tasks = [dict(t) for t in tasks]
        self.by_id = {t["id"]: t for t in self.tasks}

    def get(self, task_id: str) -> dict:
        task = self.by_id.get(task_id)
        if not task:
            raise TaskError("E_TASK_NOT_FOUND", f"待办不存在：{task_id}")
        return task

    def complete(self, task_id: str, operator: str, at) -> dict:
        task = self.get(task_id)
        if task["status"] != "open":
            raise TaskError("E_INVALID_STATE", f"只有待处理任务可完成：{task['status']}")
        task["status"] = "done"
        task["completed_at"] = _iso(at)
        task["history"].append({
            "action": "complete", "at": _iso(at), "operator": operator,
            "detail": "标记完成",
        })
        return task

    def postpone(self, task_id: str, new_due: str, reason: str,
                 operator: str, at) -> dict:
        task = self.get(task_id)
        if task["status"] != "open":
            raise TaskError("E_INVALID_STATE", f"只有待处理任务可延期：{task['status']}")
        if not DATE.match(new_due or ""):
            raise TaskError("E_DUE_INVALID", "延期必须提供明确的年-月-日日期")
        before = task.get("due_at")
        task["due_at"] = new_due
        task["due_status"] = "explicit"
        task["postpone_count"] += 1
        task["history"].append({
            "action": "postpone", "at": _iso(at), "operator": operator,
            "before": before, "after": new_due, "reason": reason or "未填写原因",
            "detail": f"截止时间由 {before or '未设置'} 改为 {new_due}",
        })
        return task

    def reopen(self, task_id: str, reason: str, operator: str, at) -> dict:
        task = self.get(task_id)
        if task["status"] != "done":
            raise TaskError("E_INVALID_STATE", "只有已完成任务可重新打开")
        task["status"] = "open"
        task["completed_at"] = None
        task["reopened_count"] += 1
        task["history"].append({
            "action": "reopen", "at": _iso(at), "operator": operator,
            "reason": reason or "未填写原因", "detail": "重新打开",
        })
        return task

    def batch(self, ids: list[str], action: str, operator: str, at,
              **params) -> dict:
        results = []
        for task_id in ids:
            try:
                if action == "complete":
                    self.complete(task_id, operator, at)
                elif action == "postpone":
                    self.postpone(task_id, params.get("new_due"), params.get("reason", ""),
                                  operator, at)
                elif action == "reopen":
                    self.reopen(task_id, params.get("reason", ""), operator, at)
                else:
                    raise TaskError("E_INVALID_ACTION", f"未知批量动作：{action}")
                results.append({"id": task_id, "ok": True})
            except TaskError as exc:
                results.append({"id": task_id, "ok": False, "code": exc.code, "message": exc.message})
        return {
            "action": action,
            "operator": operator,
            "at": _iso(at),
            "results": results,
            "succeeded": sum(1 for r in results if r["ok"]),
            "failed": sum(1 for r in results if not r["ok"]),
        }

    def summary(self) -> dict:
        counts = {}
        for t in self.tasks:
            counts[t["status"]] = counts.get(t["status"], 0) + 1
        return {"total": len(self.tasks), "status": counts}
