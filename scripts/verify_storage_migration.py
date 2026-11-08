# -*- coding: utf-8 -*-
"""Verify the v1 -> v2 local storage migration is safe and idempotent."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ops.storage_migration import migrate  # noqa: E402

CHECKS = {}


def ensure(key, cond, detail=None):
    CHECKS[key] = bool(cond)
    if not cond:
        raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cg-migrate-") as tmp:
        root = Path(tmp)
        (root / "data" / "jobs").mkdir(parents=True)
        secret = "test-model-key-not-real"
        secure = {
            "schema": 1,
            "session_secret": "a" * 64,
            "session_epoch": 3,
            "password": {"algo": "pbkdf2_sha256", "iterations": 1000,
                         "salt": "00", "hash": "11"},
            "models": {"text_api_key": secret},
            "settings": {"profile": {"display_name": "老板"}},
        }
        (root / "secure.json").write_text(json.dumps(secure), encoding="utf-8")
        job = {"id": "J1", "status": "completed",
               "stages": [{"name": "upload", "status": "done"},
                          {"name": "parse", "status": "done"}]}
        (root / "data" / "jobs" / "J1.json").write_text(json.dumps(job), encoding="utf-8")

        first = migrate(root)
        ensure("secure_migrated", first["secure"] == "migrated")
        ensure("job_migrated", first["jobs"]["migrated"] == 1)
        data = json.loads((root / "secure.json").read_text(encoding="utf-8"))
        ensure("secret_unchanged", data["models"]["text_api_key"] == secret)
        ensure("version_2", data["storage_version"] == 2)
        ensure("settings_kept", data["settings"]["profile"]["display_name"] == "老板")
        migrated_job = json.loads((root / "data" / "jobs" / "J1.json").read_text(encoding="utf-8"))
        ensure("job_schema", migrated_job["schema_version"] == 2
               and migrated_job["stage_count"] == 2)
        ensure("backups", (root / "secure.v1.bak.json").exists()
               and (root / "data" / "jobs" / "J1.json.v1.bak").exists())
        ensure("report_no_secret", secret not in (root / "migration-v2.json").read_text(encoding="utf-8"))

        second = migrate(root)
        ensure("idempotent_secure", second["secure"] == "already_current")
        ensure("idempotent_jobs", second["jobs"]["migrated"] == 0
               and second["jobs"]["skipped"] == 1)

        evidence = {"schema": "clientgraph.storage_migration.evidence.v1",
                    "checks": CHECKS, "first": first, "second": second,
                    "all_passed": all(CHECKS.values())}
        out = ROOT / "evidence" / "storage-migration-v0.5.0.json"
        out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        for key, value in CHECKS.items():
            print(("PASS " if value else "FAIL ") + key)
        print("checks:", len(CHECKS), "passed:", sum(CHECKS.values()))
        print("evidence:", out)
        return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
