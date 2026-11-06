# -*- coding: utf-8 -*-
"""CLI: python -m evidence_layer.cli --input bundle.json --out evidence.json"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import collect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClientGraph AI evidence layer")
    parser.add_argument("--input", required=True, help="bundle JSON")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
    merged = collect(
        bundle.get("results") or [],
        bundle.get("context") or {},
        hints=bundle.get("hints") or {},
        occurred_at=bundle.get("occurred_at") or {},
        window_seconds=int(bundle.get("window_seconds") or 300),
    )
    Path(args.out).write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"items": len(merged["items"]), **merged["stats"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
