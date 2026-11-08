# -*- coding: utf-8 -*-
"""Local storage migration for the web release.

The target environment is a single-user local install with no relational
database. The migration covers the two persisted state stores:
- secure.json (owner password hash, session secret, model keys, settings)
- data/jobs/*.json (upload task state)

It is idempotent, keeps a v1 backup, and never prints secret values.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 2


class MigrationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_atomic(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def migrate(config_dir: Path | str) -> dict:
    root = Path(config_dir)
    report = {
        "schema": "clientgraph.storage_migration.v2",
        "started_at": _now(),
        "config_dir": str(root),
        "secure": "skipped",
        "jobs": {"scanned": 0, "migrated": 0, "skipped": 0, "backed_up": 0},
        "from_version": None,
        "to_version": SCHEMA_VERSION,
        "status": "ok",
    }

    secure = root / "secure.json"
    if secure.exists():
        try:
            data = json.loads(secure.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MigrationError("E_STORAGE_CORRUPT", f"secure.json 无法读取：{exc}")
        report["from_version"] = data.get("storage_version", 1)
        if data.get("storage_version", 1) >= SCHEMA_VERSION:
            report["secure"] = "already_current"
        else:
            backup = secure.with_name("secure.v1.bak.json")
            if not backup.exists():
                shutil.copy2(secure, backup)
                report["secure_backup"] = backup.name
            data["storage_version"] = SCHEMA_VERSION
            data["schema_version"] = SCHEMA_VERSION
            data["migrated_at"] = _now()
            migrations = data.setdefault("migrations", [])
            if not any(m.get("to") == SCHEMA_VERSION for m in migrations):
                migrations.append({"from": 1, "to": SCHEMA_VERSION, "at": _now(),
                                   "scope": ["secure.settings", "secure.models"]})
            _write_atomic(secure, data)
            report["secure"] = "migrated"

    jobs_dir = root / "data" / "jobs"
    if jobs_dir.exists():
        for path in sorted(jobs_dir.glob("*.json")):
            report["jobs"]["scanned"] += 1
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                report["jobs"]["skipped"] += 1
                continue
            if job.get("schema_version", 1) >= SCHEMA_VERSION:
                report["jobs"]["skipped"] += 1
                continue
            backup = path.with_name(path.name + ".v1.bak")
            if not backup.exists():
                shutil.copy2(path, backup)
                report["jobs"]["backed_up"] += 1
            job["schema_version"] = SCHEMA_VERSION
            job["stage_count"] = len(job.get("stages") or [])
            job["migrated_at"] = _now()
            _write_atomic(path, job)
            report["jobs"]["migrated"] += 1

    root.mkdir(parents=True, exist_ok=True)
    report["finished_at"] = _now()
    report_path = root / "migration-v2.json"
    _write_atomic(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    args = parser.parse_args()
    try:
        report = migrate(args.config_dir)
    except MigrationError as exc:
        print(json.dumps({"status": "error", "code": exc.code,
                          "message": exc.message}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
