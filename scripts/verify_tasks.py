# -*- coding: utf-8 -*-
"""Verify task generation, operations and reminder policy."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from task_center.generator import generate_tasks  # noqa: E402
from task_center.reminders import FakeNotifier, ReminderEngine  # noqa: E402
from task_center.store import TaskError, TaskStore  # noqa: E402

EVIDENCE = ROOT / "evidence" / "tasks-2026-11-06.json"
TZ = timezone(timedelta(hours=8))


def item(iid, text, file, customer_id="c1", project_id="p1", stype="chat", occurred="2026-10-20T09:00:00+08:00"):
    return {
        "id": iid,
        "text": text,
        "source_type": stype,
        "source_file": file,
        "occurred_at": occurred,
        "customer_id": customer_id,
        "project_id": project_id,
        "sources": [{"locator": f"{stype}://{file}#{iid}", "file": file}],
    }


def build_items():
    return [
        item("I1", "请在 2026-10-15 前确认预算", "chat_1010.txt"),
        item("I2", "王工，请在 2026-11-06 前把报价发给陈晓岚", "mail_1101.eml", stype="email"),
        item("I3", "下周给一版原型", "chat_1102.txt"),
        item("I4", "尽快回复恒晟的预研问题", "mail_0929.eml", "c2", "p3", "email", "2026-09-29T10:12:00+08:00"),
        item("I5", "2026-11-10 前提交验收材料", "req.docx", stype="document"),
    ]


def contexts():
    return {
        "customers": [
            {"id": "c1", "name": "青岚智能装备（虚构）", "last_contact_at": "2026-11-04"},
            {"id": "c2", "name": "恒晟精工（虚构）", "last_contact_at": "2026-10-09"},
        ],
        "projects": [
            {"id": "p1", "name": "设备巡检小程序（一期）", "customer_id": "c1"},
            {"id": "p3", "name": "供应链协同平台（预研）", "customer_id": "c2"},
        ],
        "customer": {"id": "c1", "name": "青岚智能装备（虚构）"},
        "project": {"id": "p1", "name": "设备巡检小程序（一期）"},
    }


def main() -> int:
    now = datetime(2026, 11, 6, 9, 30, tzinfo=TZ)
    tasks = generate_tasks(build_items(), contexts(), now)
    checks = {}

    def ensure(key, cond, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    by_id = {t["id"]: t for t in tasks}
    ensure("task_count", len(tasks) == 5, len(tasks))
    ensure("overdue_explicit", by_id["T1"]["due_at"] == "2026-10-15" and
           by_id["T1"]["due_status"] == "explicit" and by_id["T1"]["priority"] == "P0", by_id["T1"])
    ensure("overdue_risk", by_id["T1"]["risk"]["level"] == "high" and "逾期" in by_id["T1"]["risk"]["note"])
    ensure("owner_extracted", by_id["T2"]["owner"] == "王工", by_id["T2"]["owner"])
    ensure("due_today_risk", by_id["T2"]["risk"]["level"] == "high")
    ensure("vague_no_due", by_id["T3"]["due_at"] is None and by_id["T3"]["due_status"] == "pending_vague")
    ensure("vague_question", any("下周" in p["question"] for p in by_id["T3"]["pending"]))
    ensure("other_customer", by_id["T4"]["customer"]["id"] == "c2" and by_id["T4"]["project"]["id"] == "p3")
    ensure("future_explicit", by_id["T5"]["due_at"] == "2026-11-10" and by_id["T5"]["due_status"] == "explicit")

    # Operations
    store = TaskStore(tasks)
    store.complete("T2", "王工（我）", now)
    ensure("complete", store.get("T2")["status"] == "done" and store.get("T2")["completed_at"])
    store.postpone("T5", "2026-11-12", "客户改期", "王工（我）", now)
    ensure("postpone", store.get("T5")["due_at"] == "2026-11-12" and
           store.get("T5")["postpone_count"] == 1, store.get("T5")["history"][-1])
    store.reopen("T2", "客户要求补充材料", "王工（我）", now)
    ensure("reopen", store.get("T2")["status"] == "open" and store.get("T2")["completed_at"] is None)
    batch = store.batch(["T1", "T5", "T9"], "complete", "王工（我）", now)
    ensure("batch_success", batch["succeeded"] == 2 and batch["failed"] == 1, batch["results"])
    ensure("batch_status", store.get("T1")["status"] == "done" and store.get("T5")["status"] == "done")
    try:
        store.postpone("T3", "下周", "模糊日期", "王工（我）", now)
        ensure("postpone_vague_rejected", False)
    except TaskError as exc:
        ensure("postpone_vague_rejected", exc.code == "E_DUE_INVALID", exc.code)

    # Reminder policy starts from a fresh store.
    store2 = TaskStore(generate_tasks(build_items(), contexts(), now))
    notifier = FakeNotifier()
    engine = ReminderEngine(store2, contexts()["customers"], notifier)
    day1 = datetime(2026, 11, 6, 9, 30, tzinfo=TZ)
    first = engine.tick(day1, app_active=True)
    ensure("reminder_count", len(first["sent"]) == 3, first["sent"])
    ensure("overdue_reminder", any(r["type"] == "task_overdue" and "22 天" in r["message"]
                                   for r in first["sent"]))
    ensure("due_reminder", any(r["type"] == "task_due" for r in first["sent"]))
    ensure("no_follow_up", any(r["type"] == "customer_no_follow_up" and "28 天" in r["message"]
                               for r in first["sent"]))
    ensure("task_reminder_recorded", len(store2.get("T1")["reminders_sent"]) == 1)
    again = engine.tick(day1, app_active=True)
    ensure("dedupe", len(again["sent"]) == 0 and len(engine.sent_log) == 3)

    quiet = engine.tick(datetime(2026, 11, 6, 23, 0, tzinfo=TZ), app_active=True)
    ensure("quiet_hours", quiet["skipped"] == "quiet_hours" and len(engine.sent_log) == 3)

    before_log = len(engine.sent_log)
    inactive = engine.tick(datetime(2026, 11, 7, 9, 30, tzinfo=TZ), app_active=False)
    ensure("app_inactive_skip", inactive["skipped"] == "app_inactive" and
           len(engine.sent_log) == before_log)
    ensure("no_fake_sent", len(store2.get("T1")["reminders_sent"]) == 1)
    catch = engine.catch_up(datetime(2026, 11, 7, 9, 30, tzinfo=TZ))
    ensure("catch_up_in_app", len(catch) >= 3 and all(r["delivery"] == "in_app" and
                                                      r["sent_at"] is None for r in catch))
    ensure("catch_up_no_mutation", len(store2.get("T1")["reminders_sent"]) == 1)

    fail_notifier = FakeNotifier(fail_times=1)
    store3 = TaskStore(generate_tasks(build_items(), contexts(), now))
    engine3 = ReminderEngine(store3, contexts()["customers"], fail_notifier)
    fail = engine3.tick(day1, app_active=True)
    ensure("notifier_failure", len(fail["sent"]) == 2 and len(fail["failures"]) == 1, fail)
    ensure("failure_not_marked", len(store3.get("T1")["reminders_sent"]) == 0)

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "now": now.isoformat(),
        "tasks": [{
            "id": t["id"], "title": t["title"], "owner": t["owner"],
            "customer": t["customer"], "project": t["project"],
            "due_at": t["due_at"], "due_status": t["due_status"],
            "priority": t["priority"], "status": t["status"], "risk": t["risk"],
            "source": t["source"], "pending": t["pending"],
        } for t in tasks],
        "reminders": {
            "sent": first["sent"],
            "dedupe_second_tick": len(again["sent"]),
            "quiet_skipped": quiet["skipped"],
            "inactive_skipped": inactive["skipped"],
            "catch_up": catch,
            "failure": fail,
        },
        "stats": store.summary(),
        "checks": checks,
        "all_passed": all(checks.values()),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print("tasks:", len(tasks), "reminders:", len(first["sent"]))
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
