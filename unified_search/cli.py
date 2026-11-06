# -*- coding: utf-8 -*-
"""CLI: python -m unified_search.cli --input bundle.json --out answer.json"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .answer import answer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClientGraph AI unified search")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = answer(bundle.get("query") or "", bundle.get("data") or {},
                    bundle.get("now"))
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"intent": result["intent"], "customers": len(result["customers"]),
                      "evidence": len(result["evidence"]),
                      "uncertainty": result["uncertainty"]["level"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
