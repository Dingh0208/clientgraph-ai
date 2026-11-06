# -*- coding: utf-8 -*-
"""CLI: python -m conflict_detection.cli --input conflicts.json --out result.json"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .detector import detect, observations_from_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClientGraph AI conflict detection")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    bundle = json.loads(Path(args.input).read_text(encoding="utf-8"))
    observations = bundle.get("observations")
    if observations is None:
        observations = observations_from_evidence(bundle.get("items") or [])
    result = detect(observations, bundle.get("context") or {}, bundle.get("tasks") or [])
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["stats"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
