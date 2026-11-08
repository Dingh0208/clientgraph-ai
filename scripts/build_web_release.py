# -*- coding: utf-8 -*-
"""Build a public, desensitized web release artifact for ClientGraph AI."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ["ops", "clarification", "writeback", "prototype", "docs", "evidence", "scripts"]
ROOT_FILES = ["VERSION", "PRD摘要-v0.4.0.md"]
FORBIDDEN_NAMES = {".env", "secure.json", "credentials.json", "id_rsa", "id_ed25519"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_tree(src: Path, dst: Path, files: dict):
    for path in sorted(src.rglob("*")):
        if path.is_dir():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise SystemExit(f"forbidden file in artifact: {path}")
        rel = path.relative_to(ROOT)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        files[str(rel).replace("\\", "/")] = _sha256(target)


def build(out: Path, make_zip: bool = False) -> dict:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in INCLUDE:
        src = ROOT / name
        if src.exists():
            _copy_tree(src, out, files)
    for name in ROOT_FILES:
        src = ROOT / name
        if src.exists():
            target = out / name
            shutil.copy2(src, target)
            files[name] = _sha256(target)
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        commit = os.environ.get("CG_BUILD_COMMIT", "unknown")
    build_id = hashlib.sha256(
        (version + "|" + "|".join(f"{k}:{v}" for k, v in sorted(files.items())))
        .encode("utf-8")).hexdigest()[:16]
    manifest = {
        "schema": "clientgraph.build.v1",
        "version": version,
        "build_id": build_id,
        "commit": commit,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "file_count": len(files),
        "excluded": [".env", "secure.json", "data/", "demo-data/", "*.db",
                     "deployment credentials", "desktop installers"],
    }
    (out / "BUILD-MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if make_zip:
        archive = out.with_suffix(".zip")
        if archive.exists():
            archive.unlink()
        shutil.make_archive(str(out), "zip", out)
        manifest["archive"] = str(archive)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None)
    parser.add_argument("--zip", action="store_true")
    args = parser.parse_args()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    out = Path(args.out) if args.out else ROOT / ".temp" / "release-build" / f"clientgraph-ai-{version}"
    manifest = build(out, make_zip=args.zip)
    print(json.dumps({k: manifest[k] for k in ("version", "build_id", "commit",
                                               "file_count", "built_at", "archive")
                      if k in manifest}, ensure_ascii=False, indent=2))
    print("artifact:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
