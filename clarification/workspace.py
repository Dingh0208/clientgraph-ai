# -*- coding: utf-8 -*-
"""Clarification work-order lifecycle, filtering, copy, archive and export.

Statuses: draft / analyzing / partial / incomplete / completed / archived.
A record is completed only when every question has a conclusion (answered or
not applicable); asking without an answer keeps it open.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime, timezone

from .exporters import ExportError, export_docx, export_pdf, render_text
from .planner import PlanningError, plan
from .question_lifecycle import QuestionLedger

STATUS_LABELS = {
    "draft": "草稿",
    "analyzing": "分析中",
    "partial": "部分完成",
    "incomplete": "未完成",
    "completed": "已完成",
    "archived": "已归档",
}

RESOLVED = {"answered", "not_applicable"}


class WorkspaceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _clean(text) -> str:
    return " ".join(str(text or "").split())


class ClarificationWorkspace:
    def __init__(self, now: datetime | None = None):
        self._clock = now
        self.records: list[dict] = []
        self.ledgers: dict[str, QuestionLedger] = {}
        self.sources: list[dict] = []

    # ---------------------------------------------------------------- helpers
    def _ts(self, at=None) -> str:
        if isinstance(at, str):
            return at
        if at is None:
            at = self._clock or datetime.now(timezone.utc)
        return at.isoformat()

    def _next_id(self, rows, prefix) -> str:
        nums = []
        for row in rows:
            m = re.fullmatch(re.escape(prefix) + r"(\d+)", str(row.get("id") or ""))
            if m:
                nums.append(int(m.group(1)))
        return f"{prefix}{max(nums) + 1 if nums else 1}"

    def record(self, record_id: str) -> dict:
        record = next((r for r in self.records if r["id"] == record_id), None)
        if record is None:
            raise WorkspaceError("E_RECORD_NOT_FOUND", f"澄清单不存在：{record_id}")
        return record

    def ledger(self, record_id: str) -> QuestionLedger:
        self.record(record_id)
        return self.ledgers.setdefault(record_id, QuestionLedger())

    def _default_target(self, record: dict):
        customers = record["scope"].get("customers") or []
        projects = record["scope"].get("projects") or []
        cid = customers[0]["id"] if len(customers) == 1 else None
        pid = projects[0]["id"] if len(projects) == 1 else None
        return cid, pid

    def _source_key(self, material: dict) -> tuple:
        return (material.get("source_type") or material.get("type"),
                material.get("source_id") or material.get("id") or material.get("name"),
                material.get("sha256") or material.get("name"))

    def _material(self, source: dict) -> dict:
        return {
            "material_id": source["id"],
            "name": source.get("name"),
            "type": source.get("type"),
            "locator": source.get("locator"),
            "text": source.get("text") or "",
            "readable": source.get("readable", True),
        }

    # ---------------------------------------------------------------- create
    def create_record(self, scope: dict, materials: list[dict] | None = None,
                      name: str | None = None, model: dict | None = None,
                      created_at=None) -> dict:
        stamp = self._ts(created_at)
        scope = {
            "customers": [dict(c) for c in (scope or {}).get("customers") or []],
            "projects": [dict(p) for p in (scope or {}).get("projects") or []],
        }
        if not scope["customers"] and not scope["projects"]:
            raise WorkspaceError("E_SCOPE_REQUIRED", "澄清单至少要选择一个客户或项目")
        record = {
            "id": self._next_id(self.records, "CR"),
            "name": _clean(name) or self._default_name(scope, stamp),
            "status": "draft",
            "status_label": STATUS_LABELS["draft"],
            "scope": scope,
            "model": copy.deepcopy(model or {"max_input_chars": 2000}),
            "language": "zh-CN",
            "batches": [],
            "round": 0,
            "incremental_pending": False,
            "confirmed_scope_at": None,
            "error_message": None,
            "batch_errors": [],
            "created_at": stamp,
            "updated_at": stamp,
            "archived_at": None,
            "archived_from": None,
            "deleted_at": None,
            "copy_of": None,
            "status_history": [{"status": "draft", "at": stamp, "reason": "created"}],
        }
        self.records.append(record)
        self.ledgers[record["id"]] = QuestionLedger()
        if materials:
            self._add_sources(record, materials, stamp)
        return record

    def _default_name(self, scope: dict, stamp: str) -> str:
        names = [c.get("name") for c in scope.get("customers") or []]
        names += [p.get("name") for p in scope.get("projects") or []]
        prefix = "、".join(n for n in names if n) or "未命名"
        return f"{prefix} {stamp[:10]}"

    def _add_sources(self, record: dict, materials: list[dict], stamp: str) -> list[dict]:
        existing = {self._source_key(s) for s in self.sources if s["record_id"] == record["id"]}
        added = []
        for material in materials:
            key = self._source_key(material)
            if key in existing:
                continue
            existing.add(key)
            source = {
                "id": self._next_id(self.sources, "S"),
                "record_id": record["id"],
                "source_id": material.get("source_id") or material.get("id"),
                "name": material.get("name") or "未命名资料",
                "type": material.get("type") or material.get("source_type"),
                "locator": material.get("locator"),
                "text": material.get("text") or "",
                "sha256": material.get("sha256"),
                "readable": material.get("readable", True),
                "customer_id": material.get("customer_id"),
                "project_id": material.get("project_id"),
                "analyzed": False,
                "round": 0,
                "created_at": stamp,
            }
            self.sources.append(source)
            added.append(source)
        return added

    # ---------------------------------------------------------------- analysis
    def append_materials(self, record_id: str, materials: list[dict], at=None) -> dict:
        record = self.record(record_id)
        if record["deleted_at"]:
            raise WorkspaceError("E_DELETED", "澄清单已删除")
        if record["status"] == "archived":
            raise WorkspaceError("E_ARCHIVED", "归档的澄清单需先恢复")
        stamp = self._ts(at)
        added = self._add_sources(record, materials or [], stamp)
        if added:
            record["incremental_pending"] = True
            record["updated_at"] = stamp
        return {"added": added, "duplicates": len(materials or []) - len(added)}

    def confirm_scope(self, record_id: str, at=None) -> dict:
        record = self.record(record_id)
        record["confirmed_scope_at"] = self._ts(at)
        record["updated_at"] = record["confirmed_scope_at"]
        return record

    def start_analysis(self, record_id: str, at=None) -> dict:
        record = self.record(record_id)
        if record["deleted_at"]:
            raise WorkspaceError("E_DELETED", "澄清单已删除")
        if record["status"] == "archived":
            raise WorkspaceError("E_ARCHIVED", "归档的澄清单需先恢复")
        if not record["confirmed_scope_at"]:
            raise WorkspaceError("E_SCOPE_NOT_CONFIRMED", "发送分析前必须先确认范围")

        pending = [s for s in self.sources
                   if s["record_id"] == record_id and not s["analyzed"]]
        if not pending:
            raise WorkspaceError("E_NOTHING_TO_ANALYZE", "没有待分析的新资料")
        for source in pending:
            if source.get("readable") is False:
                record["error_message"] = f"E_UNREADABLE: 资料不可读：{source.get('name')}"
                record["updated_at"] = self._ts(at)
                raise WorkspaceError("E_UNREADABLE", f"资料不可读：{source.get('name')}")

        max_chars = int((record.get("model") or {}).get("max_input_chars") or 2000)
        try:
            batches = plan([self._material(s) for s in pending], max_chars)
        except PlanningError as exc:
            raise WorkspaceError(exc.code, exc.message)

        record["round"] += 1
        round_no = record["round"]
        for batch in batches:
            batch["batch_id"] = f"R{round_no}-{batch['batch_id']}"
            batch["round"] = round_no
            batch["created_at"] = self._ts(at)
        record["batches"].extend(batches)
        for source in pending:
            source["analyzed"] = True
            source["round"] = round_no
        record["incremental_pending"] = False
        record["error_message"] = None
        record["updated_at"] = self._ts(at)
        self._refresh_status(record)
        return {"round": round_no, "batches": copy.deepcopy(batches)}

    def complete_batch(self, record_id: str, batch_id: str,
                       questions: list[dict] | None = None, at=None) -> dict:
        record = self.record(record_id)
        batch = next((b for b in record["batches"] if b["batch_id"] == batch_id), None)
        if batch is None:
            raise WorkspaceError("E_BATCH_NOT_FOUND", f"批次不存在：{batch_id}")
        if batch["status"] not in ("pending", "running"):
            raise WorkspaceError("E_BATCH_STATE", f"批次当前状态为 {batch['status']}，不能完成")
        batch["status"] = "completed"
        batch["completed_at"] = self._ts(at)
        if questions:
            self.add_questions(record_id, questions, at=at)
        record["updated_at"] = self._ts(at)
        self._refresh_status(record)
        return batch

    def fail_batch(self, record_id: str, batch_id: str, code: str,
                   message: str, at=None) -> dict:
        record = self.record(record_id)
        batch = next((b for b in record["batches"] if b["batch_id"] == batch_id), None)
        if batch is None:
            raise WorkspaceError("E_BATCH_NOT_FOUND", f"批次不存在：{batch_id}")
        batch["status"] = "failed"
        batch["error"] = {"code": code, "message": message}
        batch["completed_at"] = self._ts(at)
        record["error_message"] = f"{code}: {message}"
        record["batch_errors"].append({"batch_id": batch_id, "code": code,
                                       "message": message, "at": self._ts(at)})
        record["updated_at"] = self._ts(at)
        self._refresh_status(record)
        return batch

    def retry_failed(self, record_id: str, at=None) -> list[str]:
        record = self.record(record_id)
        failed = [b for b in record["batches"] if b["status"] == "failed"]
        if not failed:
            raise WorkspaceError("E_NO_FAILED_BATCH", "没有失败的批次")
        stamp = self._ts(at)
        for batch in failed:
            batch["status"] = "pending"
            batch["retried_at"] = stamp
            batch["error"] = None
        record["error_message"] = None
        record["updated_at"] = stamp
        self._refresh_status(record, at=at)
        return [b["batch_id"] for b in failed]

    def finish_analysis(self, record_id: str, at=None) -> dict:
        record = self.record(record_id)
        for batch in record["batches"]:
            if batch["status"] in ("pending", "running"):
                batch["status"] = "completed"
                batch["completed_at"] = self._ts(at)
        record["updated_at"] = self._ts(at)
        self._refresh_status(record)
        return record

    def add_questions(self, record_id: str, questions: list[dict],
                      customer_id: str | None = None,
                      project_id: str | None = None, at=None) -> list[dict]:
        ledger = self.ledger(record_id)
        record = self.record(record_id)
        default_cid, default_pid = self._default_target(record)
        added = []
        for question in questions or []:
            data = copy.deepcopy(question)
            data.pop("id", None)
            data.setdefault("customer_id", customer_id or default_cid)
            data.setdefault("project_id", project_id or default_pid)
            data.setdefault("text", "待确认问题")
            added.append(ledger.add_question(data))
        record["updated_at"] = self._ts(at)
        self._refresh_status(record)
        return added

    # ---------------------------------------------------------------- answers
    def ask(self, record_id: str, question_id: str, at=None) -> dict:
        question = self.ledger(record_id).mark_asked(question_id, at=at)
        self._refresh_status(self.record(record_id))
        return question

    def answer(self, record_id: str, question_id: str, text: str,
               evidence: list[dict], answered_at=None, operator: str = "甲方") -> dict:
        answer = self.ledger(record_id).add_answer(
            question_id, text, evidence=evidence, answered_at=answered_at,
            operator=operator)
        self._refresh_status(self.record(record_id))
        return answer

    def mark_not_applicable(self, record_id: str, question_id: str,
                            reason: str, at=None) -> dict:
        question = self.ledger(record_id).mark_not_applicable(
            question_id, reason, at=at)
        self._refresh_status(self.record(record_id))
        return question

    def generate_followup(self, record_id: str, question_id: str,
                          text: str | None = None, operator: str = "老板",
                          at=None) -> dict:
        child = self.ledger(record_id).generate_followup(
            question_id, text=text, operator=operator, at=at)
        self._refresh_status(self.record(record_id))
        return child

    # ---------------------------------------------------------------- status
    def _log_status(self, record: dict, status: str, at: str, reason: str):
        record["status_history"].append({"status": status, "at": at, "reason": reason})

    def _refresh_status(self, record: dict, at=None) -> str:
        if record["deleted_at"]:
            return record["status"]
        if record["status"] == "archived":
            record["status_label"] = STATUS_LABELS["archived"]
            return record["status"]
        previous = record["status"]
        stamp = self._ts(at)
        batches = record["batches"]
        if record["status"] == "draft" and not batches:
            record["status"] = "draft"
        elif any(b["status"] in ("pending", "running") for b in batches):
            record["status"] = "analyzing"
        else:
            questions = self.ledgers[record["id"]].questions
            total = len(questions)
            resolved = sum(1 for q in questions if q["status"] in RESOLVED)
            if total and resolved == total:
                status = "completed"
            elif total == 0:
                status = "completed" if any(b["status"] == "completed" for b in batches) else "incomplete"
            elif resolved > 0:
                status = "partial"
            else:
                status = "incomplete"
            record["status"] = status
        record["status_label"] = STATUS_LABELS[record["status"]]
        record["updated_at"] = stamp
        if record["status"] != previous:
            self._log_status(record, record["status"], stamp, "derived")
        return record["status"]

    def refresh(self, record_id: str, at=None) -> dict:
        record = self.record(record_id)
        self._refresh_status(record, at=at)
        return record

    # ---------------------------------------------------------------- archive
    def archive(self, record_id: str, at=None) -> dict:
        record = self.record(record_id)
        if record["deleted_at"]:
            raise WorkspaceError("E_DELETED", "已删除的澄清单不能归档")
        if record["status"] == "archived":
            raise WorkspaceError("E_ALREADY_ARCHIVED", "澄清单已归档")
        record["archived_from"] = record["status"]
        record["status"] = "archived"
        record["status_label"] = STATUS_LABELS["archived"]
        record["archived_at"] = self._ts(at)
        record["updated_at"] = record["archived_at"]
        self._log_status(record, "archived", record["archived_at"], "archived")
        return record

    def restore(self, record_id: str, at=None) -> dict:
        record = self.record(record_id)
        if record["status"] != "archived":
            raise WorkspaceError("E_NOT_ARCHIVED", "澄清单未归档")
        record["archived_at"] = None
        record["status"] = record.get("archived_from") or "incomplete"
        record["archived_from"] = None
        record["updated_at"] = self._ts(at)
        self._log_status(record, record["status"], record["updated_at"], "restored")
        self._refresh_status(record, at=at)
        return record

    def delete_record(self, record_id: str, confirm: bool = False, at=None) -> dict:
        if not confirm:
            raise WorkspaceError("E_CONFIRM_REQUIRED", "删除工作单需要人工确认")
        record = self.record(record_id)
        if record["deleted_at"]:
            raise WorkspaceError("E_ALREADY_DELETED", "澄清单已删除")
        stamp = self._ts(at)
        record["deleted_at"] = stamp
        record["updated_at"] = stamp
        self._log_status(record, record["status"], stamp, "deleted")
        return record

    # ---------------------------------------------------------------- copy
    def copy_as_draft(self, record_id: str, name: str | None = None,
                      at=None) -> dict:
        source = self.record(record_id)
        if source["deleted_at"]:
            raise WorkspaceError("E_DELETED", "已删除的澄清单不能复制")
        stamp = self._ts(at)
        record = self.create_record(
            scope=copy.deepcopy(source["scope"]),
            name=name or f"{source['name']}（副本）",
            model=copy.deepcopy(source["model"]),
            created_at=stamp,
        )
        record["copy_of"] = source["id"]

        old_sources = [s for s in self.sources if s["record_id"] == source["id"]]
        for old in old_sources:
            self.sources.append({
                **copy.deepcopy(old),
                "id": self._next_id(self.sources, "S"),
                "record_id": record["id"],
                "analyzed": False,
                "round": 0,
                "created_at": stamp,
            })

        ledger = self.ledgers[record["id"]]
        for question in self.ledgers[source["id"]].questions:
            data = {
                key: copy.deepcopy(question.get(key))
                for key in ("text", "priority", "priority_label", "dimension",
                            "dimension_label", "field", "field_label", "reason",
                            "conclusion_type", "confidence", "evidence",
                            "customer_id", "project_id")
            }
            data["text"] = data.get("text") or "待确认问题"
            ledger.add_question(data)
        return record

    # ---------------------------------------------------------------- filters
    def list_records(self, customer_id: str | None = None,
                     project_id: str | None = None,
                     date_from: str | None = None,
                     date_to: str | None = None,
                     view: str = "all",
                     include_archived: bool = False,
                     include_deleted: bool = False) -> list[dict]:
        out = []
        for record in self.records:
            if record["deleted_at"] and not include_deleted:
                continue
            if record["status"] == "archived" and not include_archived:
                continue
            if customer_id and customer_id not in {
                    c.get("id") for c in record["scope"].get("customers") or []}:
                continue
            if project_id and project_id not in {
                    p.get("id") for p in record["scope"].get("projects") or []}:
                continue
            day = record["created_at"][:10]
            if date_from and day < date_from[:10]:
                continue
            if date_to and day > date_to[:10]:
                continue
            summary = self.summary(record["id"])
            if view == "unanswered" and summary["open"] == 0:
                continue
            if view == "completed" and summary["status"] != "completed":
                continue
            out.append(summary)
        out.sort(key=lambda s: (s["updated_at"] or "", s["id"]), reverse=True)
        return out

    def summary(self, record_id: str) -> dict:
        record = self.record(record_id)
        questions = self.ledgers[record["id"]].questions
        resolved = sum(1 for q in questions if q["status"] in RESOLVED)
        return {
            "id": record["id"],
            "name": record["name"],
            "status": record["status"],
            "status_label": record["status_label"],
            "customers": copy.deepcopy(record["scope"].get("customers") or []),
            "projects": copy.deepcopy(record["scope"].get("projects") or []),
            "questions": len(questions),
            "open": len(questions) - resolved,
            "resolved": resolved,
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "archived_at": record["archived_at"],
            "deleted_at": record["deleted_at"],
        }

    def all_sources(self) -> list[dict]:
        deleted = {r["id"] for r in self.records if r["deleted_at"]}
        return [{**copy.deepcopy(s), "record_deleted": s["record_id"] in deleted}
                for s in self.sources]

    def sources_for(self, record_id: str) -> list[dict]:
        return [copy.deepcopy(s) for s in self.sources if s["record_id"] == record_id]

    # ---------------------------------------------------------------- export
    def render_text(self, record_id: str, group_by: str = "customer",
                    external: bool = False) -> str:
        return render_text(self.record(record_id), self.ledger(record_id),
                           group_by=group_by, external=external)

    def export_docx(self, record_id: str, path, group_by: str = "customer",
                    external: bool = False):
        return export_docx(self.record(record_id), self.ledger(record_id),
                           path, group_by=group_by, external=external)

    def export_pdf(self, record_id: str, path, group_by: str = "customer",
                   external: bool = False):
        return export_pdf(self.record(record_id), self.ledger(record_id),
                          path, group_by=group_by, external=external)
