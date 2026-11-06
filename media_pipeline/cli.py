# -*- coding: utf-8 -*-
"""CLI: python -m media_pipeline.cli --input file --out runs/demo"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from audio_pipeline import PipelineConfig, build_provider

from .pipeline import process


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClientGraph AI media pipeline")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--asr-provider", choices=["mock", "qwen"], default="mock")
    parser.add_argument("--chunk-seconds", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args(argv)

    provider = build_provider(args.asr_provider, {})
    cfg = PipelineConfig(chunk_seconds=args.chunk_seconds, concurrency=args.concurrency)
    result = process(args.input, args.out, asr_provider=provider, audio_cfg=cfg)
    out = Path(args.out) / "media-result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "kind": result["source"]["kind"],
        "blocks": len(result["blocks"]),
        "errors": len(result["errors"]),
        "warnings": len(result["warnings"]),
        "result": str(out),
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
