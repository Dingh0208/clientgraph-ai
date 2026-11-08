# -*- coding: utf-8 -*-
"""Question lifecycle: pending / asked / answered / not applicable.

Rules enforced here:
- asking does not complete a question; only an answer or "not applicable" does;
- every answer is appended with its own time snapshot, never overwritten;
- an answer must cite the original question and at least one evidence item;
- a follow-up question is created only when the owner explicitly asks for it.
"""
from __future__ import annotations

import copy
import re
from datetime import datetime, timezone

STATUS_PENDING = "pending"
STATUS_ASKED = "asked"
STATUS_ANSWERED = "answered"
STATUS_NOT_APPLICABLE = "not_applicable"

STATUS_LABELS = {
    STATUS_PENDING: "待问",
    STATUS_ASKED: "已问",
    STATUS_ANSWERED: "已回答",
    STATUS_NOT_APPLICABLE: "不适用",
}

RESOLVED_STATUSES = {STATUS_ANSWERED, STATUS_NOT_APPLICABLE}
OPEN_STATUSES = {STATUS_PENDING, STATUS_ASKED}


class LifecycleError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _clean(text) -> str:
    return str(text or "").strip()


def _norm_evidence(items) -> list[dict]:
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if not any(_clean(item.get(k)) for k in ("excerpt", "text", "locator", "file")):
            continue
        out.append(copy.deepcopy(item))
    return out


class QuestionLedger:
    """Holds questions and their full interaction history."""

    def __init__(self, questions: list[dict] | None = None,
                 now: datetime | None = None):
        self._clock = now
        self.questions: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.answers: list[dict] = []
        self.followup_actions: list[dict] = []
        for question in questions or []:
            self.add_question(question)

    # ---------------------------------------------------------------- helpers
    def _ts(self, at) -> str:
        if isinstance(at, str):
            return at
        if at is None:
            at = self._clock or datetime.now(timezone.utc)
        return at.isoformat()

    def _next_question_id(self) -> str:
        used = {qid for qid in self.by_id}
        n = len(self.questions) + 1
        while f"Q{n}" in used:
            n += 1
        return f"Q{n}"

    def _next_answer_id(self) -> str:
        return f"A{len(self.answers) + 1}"

    def get(self, question_id: str) -> dict:
        question = self.by_id.get(question_id)
        if question is None:
            raise KeyError(question_id)
        return question

    def is_resolved(self, question_id: str) -> bool:
        return self.get(question_id)["status"] in RESOLVED_STATUSES

    def open_questions(self) -> list[dict]:
        return [q for q in self.questions if q["status"] in OPEN_STATUSES]

    # ---------------------------------------------------------------- create
    def add_question(self, question: dict, parent_question_id: str | None = None,
                     based_on_answer_id: str | None = None,
                     generated_from: str = "initial") -> dict:
        qid = _clean(question.get("id")) or self._next_question_id()
        if qid in self.by_id:
            raise LifecycleError("E_DUPLICATE_ID", f"问题编号重复：{qid}")
        text = _clean(question.get("text"))
        if not text:
            raise LifecycleError("E_EMPTY_TEXT", "问题文本不能为空")
        record = {
            "id": qid,
            "text": text,
            "priority": question.get("priority") or "important",
            "priority_label": question.get("priority_label"),
            "dimension": question.get("dimension"),
            "dimension_label": question.get("dimension_label"),
            "field": question.get("field"),
            "field_label": question.get("field_label"),
            "customer_id": question.get("customer_id"),
            "project_id": question.get("project_id"),
            "reason": question.get("reason"),
            "conclusion_type": question.get("conclusion_type"),
            "conclusion_label": question.get("conclusion_label"),
            "confidence": question.get("confidence"),
            "low_confidence": question.get("low_confidence"),
            "confidence_note": question.get("confidence_note"),
            "excerpt": question.get("excerpt"),
            "source_time": question.get("source_time"),
            "priority_basis": question.get("priority_basis"),
            "conflict_evidence": copy.deepcopy(question.get("conflict_evidence")),
            "evidence": _norm_evidence(question.get("evidence")),
            "status": STATUS_PENDING,
            "status_label": STATUS_LABELS[STATUS_PENDING],
            "asked_at": None,
            "last_asked_at": None,
            "ask_count": 0,
            "answers": [],
            "answer": None,
            "not_applicable_reason": None,
            "resolved_at": None,
            "child_question_ids": [],
            "parent_question_id": parent_question_id,
            "based_on_answer_id": based_on_answer_id,
            "generated_from": generated_from,
            "created_at": self._ts(None),
            "updated_at": self._ts(None),
        }
        self.questions.append(record)
        self.by_id[qid] = record
        return record

    # ---------------------------------------------------------------- status
    def mark_asked(self, question_id: str, at=None, operator: str = "王工（我）",
                   channel: str | None = None) -> dict:
        question = self.get(question_id)
        if question["status"] in RESOLVED_STATUSES:
            raise LifecycleError("E_ALREADY_RESOLVED",
                                 f"{question_id} 已有处理结论，不能再标记为已问")
        stamp = self._ts(at)
        if question["status"] == STATUS_PENDING:
            question["asked_at"] = stamp
            question["status"] = STATUS_ASKED
            question["status_label"] = STATUS_LABELS[STATUS_ASKED]
        question["last_asked_at"] = stamp
        question["ask_count"] += 1
        question["updated_at"] = stamp
        question.setdefault("ask_log", []).append(
            {"at": stamp, "operator": operator, "channel": channel})
        return question

    def add_answer(self, question_id: str, text: str, answered_at=None,
                   operator: str = "甲方", recorded_at=None,
                   evidence: list[dict] | None = None,
                   answer_source: str | None = None) -> dict:
        question = self.get(question_id)
        body = _clean(text)
        if not body:
            raise LifecycleError("E_EMPTY_ANSWER", "回答内容不能为空")
        if question["status"] == STATUS_NOT_APPLICABLE:
            raise LifecycleError("E_NOT_APPLICABLE", f"{question_id} 已标记不适用")
        if question["status"] == STATUS_PENDING:
            raise LifecycleError("E_NOT_ASKED", f"{question_id} 尚未标记已问")

        cites = _norm_evidence(evidence) if evidence is not None else []
        if not cites:
            cites = copy.deepcopy(question["evidence"])
        if not cites:
            raise LifecycleError(
                "E_NO_EVIDENCE",
                "回答必须引用原问题和相关证据：未提供回答证据，原问题也没有证据")

        recorded = self._ts(recorded_at)
        said = self._ts(answered_at if answered_at is not None else recorded_at)
        answer = {
            "id": self._next_answer_id(),
            "question_id": question_id,
            "sequence": len(question["answers"]) + 1,
            "text": body,
            "answered_at": said,
            "recorded_at": recorded,
            "snapshot_at": recorded,
            "operator": operator,
            "answer_source": answer_source,
            "question_text": question["text"],
            "question_priority": question["priority"],
            "question_dimension": question.get("dimension"),
            "question_field": question.get("field"),
            "question_field_label": question.get("field_label"),
            "question_evidence": copy.deepcopy(question["evidence"]),
            "evidence": cites,
            "status_before": question["status"],
        }
        question["answers"].append(answer)
        self.answers.append(answer)
        question["answer"] = copy.deepcopy(answer)
        question["status"] = STATUS_ANSWERED
        question["status_label"] = STATUS_LABELS[STATUS_ANSWERED]
        if question["resolved_at"] is None:
            question["resolved_at"] = said
        question["updated_at"] = recorded
        return copy.deepcopy(answer)

    def mark_not_applicable(self, question_id: str, reason: str, at=None,
                            operator: str = "王工（我）") -> dict:
        question = self.get(question_id)
        why = _clean(reason)
        if not why:
            raise LifecycleError("E_REASON_REQUIRED", "标记不适用必须写明原因")
        if question["status"] in RESOLVED_STATUSES:
            raise LifecycleError("E_ALREADY_RESOLVED",
                                 f"{question_id} 已有处理结论，不能重复标记")
        stamp = self._ts(at)
        question["status"] = STATUS_NOT_APPLICABLE
        question["status_label"] = STATUS_LABELS[STATUS_NOT_APPLICABLE]
        question["not_applicable_reason"] = why
        question["resolved_at"] = stamp
        question["updated_at"] = stamp
        question.setdefault("resolution_log", []).append(
            {"at": stamp, "operator": operator, "action": "not_applicable",
             "reason": why})
        return question

    # ---------------------------------------------------------------- followup
    def can_generate_followup(self, question_id: str) -> bool:
        return self.get(question_id)["status"] == STATUS_ANSWERED

    def generate_followup(self, question_id: str, text: str | None = None,
                          operator: str = "老板", at=None,
                          evidence: list[dict] | None = None) -> dict:
        """Create a follow-up only when explicitly invoked by the owner."""
        question = self.get(question_id)
        if question["status"] != STATUS_ANSWERED:
            raise LifecycleError(
                "E_NOT_ANSWERED",
                f"{question_id} 还没有回答，不能基于回答生成追问")
        latest = question["answers"][-1]
        stamp = self._ts(at)

        body = _clean(text)
        if not body:
            core = re.sub(r"^请问|？+$", "", question["text"]).strip()
            if len(core) > 20:
                core = core[:20]
            body = f"请问关于「{core}」，还有哪些情况需要补充？"

        cites = _norm_evidence(evidence) if evidence is not None else []
        merged = copy.deepcopy(question["evidence"])
        for item in latest.get("evidence") or []:
            merged.append(copy.deepcopy(item))
        for item in cites:
            merged.append(item)
        deduped, seen = [], set()
        for item in merged:
            key = (_clean(item.get("locator")), _clean(item.get("excerpt") or item.get("text")))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)

        child = self.add_question(
            {
                "id": self._next_question_id(),
                "text": body,
                "priority": question["priority"],
                "priority_label": question["priority_label"],
                "dimension": question["dimension"],
                "dimension_label": question["dimension_label"],
                "field": question["field"],
                "field_label": question["field_label"],
                "reason": "基于已回答内容生成追问",
                "conclusion_type": "inference",
                "confidence": question.get("confidence"),
                "evidence": deduped,
            },
            parent_question_id=question_id,
            based_on_answer_id=latest["id"],
            generated_from="followup",
        )
        question["child_question_ids"].append(child["id"])
        question["updated_at"] = stamp
        self.followup_actions.append({
            "action": "generate_followup",
            "question_id": question_id,
            "answer_id": latest["id"],
            "child_question_id": child["id"],
            "operator": operator,
            "at": stamp,
        })
        return child

    # ---------------------------------------------------------------- report
    def stats(self) -> dict:
        counts = {status: 0 for status in STATUS_LABELS}
        for question in self.questions:
            counts[question["status"]] += 1
        return {
            "questions": len(self.questions),
            "pending": counts[STATUS_PENDING],
            "asked": counts[STATUS_ASKED],
            "answered": counts[STATUS_ANSWERED],
            "not_applicable": counts[STATUS_NOT_APPLICABLE],
            "resolved": counts[STATUS_ANSWERED] + counts[STATUS_NOT_APPLICABLE],
            "open": counts[STATUS_PENDING] + counts[STATUS_ASKED],
            "answers": len(self.answers),
            "followups": sum(1 for q in self.questions
                             if q["generated_from"] == "followup"),
            "followup_actions": len(self.followup_actions),
        }

    def report(self) -> dict:
        return {
            "schema": "clientgraph.question_status.v1",
            "questions": copy.deepcopy(self.questions),
            "stats": self.stats(),
        }
