# -*- coding: utf-8 -*-
"""CLI: python -m customer360.cli --input bundle.json --customer c1 --out 360.json"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .aggregator import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClientGraph AI customer 360")
    parser.add_argument("--input", required=True)
    parser.add_argument("--customer", required=True)
    parser.add_argument("--now")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = build(bundle, args.customer, args.now)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result.get("stats", {}), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
