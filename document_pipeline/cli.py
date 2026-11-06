# -*- coding: utf-8 -*-
"""CLI: python -m document_pipeline.cli --input file --out runs/doc"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import process


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClientGraph AI document pipeline")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    result = process(args.input, args.out)
    out = Path(args.out) / "document-result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "kind": result["source"]["kind"],
        "blocks": len(result["blocks"]),
        "messages": len(result["messages"]),
        "errors": len(result["errors"]),
        "result": str(out),
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
