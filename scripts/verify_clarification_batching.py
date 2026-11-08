# -*- coding: utf-8 -*-
"""Verify batching, cancel, retry, append and conflict-safe dedupe."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clarification.planner import PlanningError, plan  # noqa: E402
from clarification.processor import ClarificationRun, FakeProvider  # noqa: E402

EVIDENCE = ROOT / "evidence" / "clarification-batching-2026-11-06.json"
NOW = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)


def material(mid, chars, locator=None, readable=True):
    return {"material_id": mid, "name": f"{mid}.txt", "type": "chat",
            "locator": locator or f"chat://{mid}", "readable": readable,
            "text": "甲" * chars}


QUESTIONS = {
    "M01": {"key": "budget", "text": "一期预算上限是多少？", "value": "8 万",
            "priority": "must_confirm", "category": "预算"},
    "M02": {"key": "scope", "text": "一期范围包含哪些？", "value": "5 项",
            "priority": "must_confirm", "category": "范围"},
    "M03": {"key": "budget", "text": "一期预算上限是多少？", "value": "10 万",
            "priority": "must_confirm", "category": "预算"},
    "M04": {"key": "scope", "text": "一期范围包含哪些？", "value": "5 项",
            "priority": "must_confirm", "category": "范围"},
}


def main() -> int:
    checks = {}

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    # Planner
    batches = plan([material("M01", 1200), material("M02", 1000), material("M03", 900)], 2000)
    ensure("batch_count", len(batches) == 2, len(batches))
    ensure("batch_limits", all(b["input_chars"] <= 2000 for b in batches))
    ensure("batch_materials", batches[0]["material_ids"] == ["M01"] and
           set(batches[1]["material_ids"]) == {"M02", "M03"})
    huge = plan([material("M05", 4500)], 2000)
    ensure("oversized_split", len(huge) == 3 and all(b["input_chars"] <= 2000 for b in huge))
    try:
        plan([material("M06", 100, readable=False)], 2000)
        ensure("unreadable_rejected", False)
    except PlanningError as exc:
        ensure("unreadable_rejected", exc.code == "E_UNREADABLE", exc.code)

    # Full processing and conflict in the same run
    run = ClarificationRun([material("M01", 1200), material("M02", 1000), material("M03", 900)],
                           FakeProvider(questions_by_material=QUESTIONS), max_input_chars=2000, now=NOW)
    progress = run.process_all()
    ensure("run_completed", progress["completed"] == 2 and progress["total"] == 2, progress)
    ensure("run_questions", len(run.questions) == 2, len(run.questions))
    ensure("run_conflict", len(run.conflicts) == 1 and run.conflicts[0]["overwrite"] is False)
    ensure("conflict_old_value", run.questions[0]["value"] == "8 万", run.questions[0])

    # Cancel: keep completed questions/answers
    run2 = ClarificationRun([material("M01", 1200), material("M02", 1000), material("M03", 900)],
                            FakeProvider(questions_by_material=QUESTIONS), max_input_chars=2000, now=NOW)
    run2.process_next()
    run2.set_answer("Q1", "预算 8 万已确认")
    cancelled = run2.cancel()
    ensure("cancel_progress", cancelled["completed"] == 1 and cancelled["total"] == 2, cancelled)
    ensure("cancel_kept_questions", len(run2.questions) == 1, len(run2.questions))
    ensure("cancel_kept_answer", run2.answers["Q1"]["text"] == "预算 8 万已确认")
    ensure("cancel_remaining", run2.batches[1]["status"] == "cancelled")

    # Failure and retry remaining
    provider = FakeProvider(fail_batches={1}, questions_by_material=QUESTIONS)
    run3 = ClarificationRun([material("M01", 1200), material("M02", 1000), material("M03", 900)],
                            provider, max_input_chars=2000, now=NOW)
    failed = run3.process_all()
    ensure("failure_progress", failed["completed"] == 1 and failed["status"] == "partial", failed)
    ensure("failure_recorded", run3.errors and run3.errors[0]["code"] == "E_MODEL_TIMEOUT")
    first_ids = [q["id"] for q in run3.questions]
    provider.fail_batches.clear()
    retried = run3.retry_remaining()
    ensure("retry_completed", retried["completed"] == 2 and retried["total"] == 2, retried)
    ensure("retry_kept_questions", [q["id"] for q in run3.questions][:len(first_ids)] == first_ids)
    ensure("retry_same_model", run3.model == "qwen3.8-flash")

    # Append: only new materials, dedupe and conflict without overwrite
    run4 = ClarificationRun([material("M01", 1200), material("M02", 1000)],
                            FakeProvider(questions_by_material=QUESTIONS), max_input_chars=2000, now=NOW)
    run4.process_all()
    run4.set_answer("Q1", "预算 8 万已确认")
    old_batches = [b["batch_id"] for b in run4.batches]
    new_batches = run4.append_materials([material("M03", 900)])
    ensure("append_only_new", len(new_batches) == 1 and new_batches[0]["material_ids"] == ["M03"])
    ensure("append_index", new_batches[0]["index"] == len(old_batches))
    run4.process_all()
    ensure("append_conflict", len(run4.conflicts) == 1 and run4.conflicts[0]["overwrite"] is False)
    ensure("append_old_answer", run4.questions[0]["answer"]["text"] == "预算 8 万已确认")
    ensure("append_no_new_question", len(run4.questions) == 2, len(run4.questions))
    ensure("append_new_batch_only", run4.appended_materials == 1 and run4.new_batches == 1)

    # Same-value append merges evidence, no duplicate question
    run4.append_materials([material("M04", 800)])
    run4.process_all()
    ensure("dedupe_questions", len(run4.questions) == 2, len(run4.questions))
    scope = next(q for q in run4.questions if q["key"] == "scope")
    ensure("dedupe_evidence", len(scope["evidence"]) >= 2 and scope["merged_count"] >= 2)

    # Oversized end-to-end
    run5 = ClarificationRun([material("M05", 4500)], FakeProvider(), max_input_chars=2000, now=NOW)
    progress5 = run5.process_all()
    ensure("oversized_batches", progress5["total"] == 3 and progress5["completed"] == 3, progress5)

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "planner": {"batches": [{"id": b["batch_id"], "chars": b["input_chars"],
                                 "materials": b["material_ids"]} for b in batches]},
        "full_run": {"progress": progress, "questions": run.questions,
                     "conflicts": run.conflicts},
        "cancel": {"progress": cancelled, "answers": run2.answers,
                   "statuses": [b["status"] for b in run2.batches]},
        "retry": {"progress": retried, "errors": run3.errors,
                  "retried_batches": run3.retried_batches, "model": run3.model},
        "append": {"stats": run4.stats(), "conflicts": run4.conflicts,
                   "questions": run4.questions},
        "oversized": progress5,
        "checks": checks,
        "all_passed": all(checks.values()),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("batches:", len(batches), "questions:", len(run.questions), "conflicts:", len(run.conflicts))
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
