# -*- coding: utf-8 -*-
"""CLI: python -m relationship_view.cli --input graph.json --out result.json"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .graph import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClientGraph AI relationship view")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
    graph = build(bundle.get("entities") or {}, bundle.get("manual_links") or [],
                  float(bundle.get("similarity_threshold") or 0.55))
    Path(args.out).write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(graph["stats"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
