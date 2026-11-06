# -*- coding: utf-8 -*-
"""CLI: python -m task_center.cli --input next-actions.json --out tasks.json"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .generator import generate_tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClientGraph AI task generation")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
    now = datetime.fromisoformat(bundle.get("now") or datetime.now().isoformat())
    tasks = generate_tasks(bundle.get("items") or [], bundle.get("context") or {}, now)
    Path(args.out).write_text(json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(json.dumps({"tasks": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
