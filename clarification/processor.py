# -*- coding: utf-8 -*-
"""Batch clarification with cancel, retry, append and conflict-safe dedupe."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .planner import PlanningError, plan


class ModelError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


class ClarificationRun:
    def __init__(self, materials: list[dict], provider, model: str = "qwen3.8-flash",
                 max_input_chars: int = 2000, now: datetime | None = None):
        self.materials = [dict(m) for m in materials]
        self.provider = provider
        self.model = model
        self.max_input_chars = max_input_chars
        self.now = now or datetime.now(timezone.utc)
        self.batches = plan(self.materials, max_input_chars)
        self.questions: list[dict] = []
        self.by_key: dict[str, dict] = {}
        self.by_text: dict[str, dict] = {}
        self.answers: dict[str, dict] = {}
        self.conflicts: list[dict] = []
        self.errors: list[dict] = []
        self.status = "pending" if self.batches else "completed"
        self.appended_materials = 0
        self.new_batches = 0
        self.retried_batches = 0

    @property
    def total_batches(self) -> int:
        return len(self.batches)

    @property
    def completed_batches(self) -> int:
        return sum(1 for b in self.batches if b["status"] == "completed")

    def progress(self) -> dict:
        return {
            "completed": self.completed_batches,
            "total": self.total_batches,
            "status": self.status,
            "text": f"{self.completed_batches}/{self.total_batches}",
        }

    def process_next(self) -> dict | None:
        batch = next((b for b in self.batches if b["status"] == "pending"), None)
        if batch is None:
            return None
        batch["status"] = "running"
        batch["attempts"] += 1
        self.status = "running"
        try:
            questions = self.provider.generate(self.model, batch) or []
        except ModelError as exc:
            batch["status"] = "failed"
            batch["error"] = {"code": exc.code, "message": exc.message}
            self.errors.append({"batch_id": batch["batch_id"], "code": exc.code,
                                "message": exc.message})
            self.status = "partial"
            return batch
        except Exception as exc:
            batch["status"] = "failed"
            batch["error"] = {"code": "E_MODEL_UNKNOWN", "message": str(exc)[:300]}
            self.errors.append({"batch_id": batch["batch_id"], "code": "E_MODEL_UNKNOWN",
                                "message": str(exc)[:300]})
            self.status = "partial"
            return batch

        ids = []
        for q in questions:
            question = self._merge_question(q, batch)
            ids.append(question["id"])
        batch["questions"] = ids
        batch["status"] = "completed"
        if all(b["status"] == "completed" for b in self.batches):
            self.status = "completed"
        else:
            self.status = "running"
        return batch

    def process_all(self) -> dict:
        while True:
            batch = self.process_next()
            if batch is None:
                break
            if batch["status"] == "failed":
                break
        return self.progress()

    def cancel(self) -> dict:
        for b in self.batches:
            if b["status"] == "pending":
                b["status"] = "cancelled"
        self.status = "cancelled"
        return self.progress()

    def retry_remaining(self) -> dict:
        for b in self.batches:
            if b["status"] == "failed":
                b["status"] = "pending"
                b["error"] = None
                self.retried_batches += 1
        self.status = "pending"
        return self.process_all()

    def append_materials(self, materials: list[dict]) -> list[dict]:
        new_batches = plan(materials, self.max_input_chars)
        offset = len(self.batches)
        for b in new_batches:
            b["index"] += offset
            b["batch_id"] = f"B{b['index'] + 1}"
        self.batches.extend(new_batches)
        self.materials.extend(dict(m) for m in materials)
        self.appended_materials += len(materials)
        self.new_batches += len(new_batches)
        if new_batches:
            self.status = "pending"
        return new_batches

    def _merge_evidence(self, existing: list[dict], incoming: list[dict]) -> list[dict]:
        seen = {(e.get("material_id"), e.get("locator"), e.get("excerpt")) for e in existing}
        out = list(existing)
        for e in incoming or []:
            key = (e.get("material_id"), e.get("locator"), e.get("excerpt"))
            if key not in seen:
                seen.add(key)
                out.append(e)
        return out

    def _merge_question(self, q: dict, batch: dict) -> dict:
        key = q.get("key") or _norm(q.get("text"))
        text_key = _norm(q.get("text"))
        existing = self.by_key.get(key) or self.by_text.get(text_key)
        evidence = q.get("evidence") or []
        if existing:
            existing["evidence"] = self._merge_evidence(existing.get("evidence") or [], evidence)
            existing["merged_count"] += 1
            existing.setdefault("batch_ids", []).append(batch["batch_id"])
            new_value = q.get("value")
            if new_value is not None and existing.get("value") is not None and \
                    new_value != existing.get("value"):
                existing.setdefault("values", [existing["value"]])
                if new_value not in existing["values"]:
                    existing["values"].append(new_value)
                conflict = {
                    "id": f"CF{len(self.conflicts) + 1}",
                    "question_id": existing["id"],
                    "old_value": existing.get("value"),
                    "new_value": new_value,
                    "old_evidence": existing.get("evidence") or [],
                    "new_evidence": evidence,
                    "status": "must_confirm",
                    "resolution": None,
                    "overwrite": False,
                    "created_at": self.now.isoformat(),
                }
                self.conflicts.append(conflict)
                existing.setdefault("conflict_ids", []).append(conflict["id"])
                existing["resolution_required"] = True
                existing["status"] = "conflict" if existing.get("answer") else "must_confirm"
            return existing

        question = {
            "id": f"Q{len(self.questions) + 1}",
            "key": key,
            "text": q.get("text") or "待确认问题",
            "value": q.get("value"),
            "values": [q.get("value")] if q.get("value") is not None else [],
            "priority": q.get("priority") or "must_confirm",
            "category": q.get("category") or "其他",
            "conclusion_type": q.get("conclusion_type") or "gap",
            "confidence": q.get("confidence"),
            "status": "must_confirm",
            "evidence": evidence,
            "batch_ids": [batch["batch_id"]],
            "merged_count": 1,
            "answer": None,
            "resolution_required": False,
            "conflict_ids": [],
        }
        self.questions.append(question)
        self.by_key[key] = question
        self.by_text[text_key] = question
        return question

    def set_answer(self, question_id: str, text: str, operator: str = "王工（我）") -> dict:
        question = next((q for q in self.questions if q["id"] == question_id), None)
        if question is None:
            raise KeyError(question_id)
        answer = {"question_id": question_id, "text": text,
                  "operator": operator, "at": self.now.isoformat()}
        self.answers[question_id] = answer
        question["answer"] = answer
        question["status"] = "answered"
        return answer

    def stats(self) -> dict:
        return {
            "materials": len(self.materials),
            "batches": len(self.batches),
            "completed_batches": self.completed_batches,
            "questions": len(self.questions),
            "answers": len(self.answers),
            "conflicts": len(self.conflicts),
            "appended_materials": self.appended_materials,
            "new_batches": self.new_batches,
            "retried_batches": self.retried_batches,
            "errors": len(self.errors),
        }


class FakeProvider:
    def __init__(self, fail_batches: set[int] | None = None,
                 questions_by_material: dict | None = None):
        self.fail_batches = set(fail_batches or set())
        self.questions_by_material = questions_by_material or {}

    def generate(self, model: str, batch: dict) -> list[dict]:
        if batch["index"] in self.fail_batches:
            raise ModelError("E_MODEL_TIMEOUT", f"批次 {batch['batch_id']} 超时")
        out = []
        for part in batch["parts"]:
            mid = part["material_id"]
            spec = self.questions_by_material.get(mid)
            if spec is None:
                spec = {"key": f"q_{mid}", "text": f"{mid} 还有哪些待确认？",
                        "value": "待确认", "priority": "important", "category": "其他"}
            out.append({
                "key": spec.get("key"),
                "text": spec.get("text"),
                "value": spec.get("value"),
                "priority": spec.get("priority", "must_confirm"),
                "category": spec.get("category", "其他"),
                "conclusion_type": spec.get("conclusion_type", "gap"),
                "confidence": spec.get("confidence", 0.8),
                "evidence": [{
                    "material_id": mid,
                    "locator": part.get("locator"),
                    "excerpt": (part.get("text") or "")[:80],
                }],
            })
        return out
