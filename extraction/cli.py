# -*- coding: utf-8 -*-
"""CLI: python -m extraction.cli --input bundle.json --out extracted.json"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .extractor import extract


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClientGraph AI requirement extraction")
    parser.add_argument("--input", required=True, help="bundle JSON with items/context")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = extract(
        bundle.get("items") or [],
        bundle.get("context") or {},
        bundle.get("confirmed_dates") or {},
    )
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["stats"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
