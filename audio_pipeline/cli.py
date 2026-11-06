# -*- coding: utf-8 -*-
"""Command line entry point for the audio pipeline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .asr import ASRError, build_provider
from .pipeline import PipelineConfig, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClientGraph AI long-audio pipeline")
    parser.add_argument("--input", required=True, help="input audio/video file")
    parser.add_argument("--out", required=True, help="run directory")
    parser.add_argument("--chunk-seconds", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--provider", choices=["mock", "qwen"], default="mock")
    args = parser.parse_args(argv)

    cfg = PipelineConfig(
        chunk_seconds=args.chunk_seconds,
        concurrency=args.concurrency,
        timeout_s=args.timeout,
        max_attempts=args.max_attempts,
        provider=args.provider,
    )
    try:
        provider = build_provider(args.provider, {})
    except ASRError as exc:
        print(json.dumps({"status": "failed", "error": {"code": exc.code, "message": exc.message}},
                         ensure_ascii=False))
        return 1

    result = run(args.input, args.out, cfg, provider=provider)
    print(json.dumps({
        "status": result["status"],
        "chunks": len(result.get("chunks") or []),
        "segments": len(result.get("segments") or []),
        "result": str(Path(args.out) / "result.json"),
        "error": result.get("error"),
    }, ensure_ascii=False, indent=2))
    if result["status"] == "completed":
        return 0
    if result["status"] == "partial":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
