# -*- coding: utf-8 -*-
"""Verify the long-audio pipeline with six scenarios.

Run:  python scripts/verify_audio_pipeline.py
Writes evidence/audio-pipeline-2026-11-06.json and exits non-zero on failure.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from audio_pipeline import (  # noqa: E402
    MockASR, PipelineConfig, probe, retry_failed, run,
)

TMP = ROOT / ".temp" / "audio-verify"
EVIDENCE = ROOT / "evidence" / "audio-pipeline-2026-11-06.json"


def sh(cmd: list[str], timeout: int = 600) -> None:
    cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or "").strip()[:500])


def make_fixtures() -> dict:
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir(parents=True)
    src = TMP / "source"
    src.mkdir()

    sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3600",
        "-ar", "44100", "-ac", "2", "-b:a", "32k", str(src / "long_1h.mp3")])
    sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=660:duration=360",
        "-ar", "44100", "-ac", "2", "-b:a", "48k", str(src / "mid_6m.mp3")])
    sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=880:duration=8",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(src / "short_8s.wav")])
    sh(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "5",
        "-c:a", "pcm_s16le", str(src / "silent_5s.wav")])
    (src / "empty_0b.wav").write_bytes(b"")

    meta = {}
    for name, path in {
        "long_1h": src / "long_1h.mp3",
        "mid_6m": src / "mid_6m.mp3",
        "short_8s": src / "short_8s.wav",
        "silent_5s": src / "silent_5s.wav",
        "empty_0b": src / "empty_0b.wav",
    }.items():
        entry = {"file": path.name, "size_bytes": path.stat().st_size}
        if path.stat().st_size:
            info = probe(path)
            entry.update({
                "duration_ms": info.duration_ms,
                "sample_rate": info.sample_rate,
                "channels": info.channels,
                "codec": info.codec,
            })
        meta[name] = entry
    return {"dir": src, "meta": meta}


def summarize(result: dict) -> dict:
    return {
        "status": result.get("status"),
        "error": result.get("error"),
        "chunks": len(result.get("chunks") or []),
        "segments": len(result.get("segments") or []),
        "duration_ms": (result.get("source") or {}).get("duration_ms"),
        "normalized": result.get("normalized"),
        "max_concurrency_observed": (result.get("asr") or {}).get("max_concurrency_observed"),
        "diarization": result.get("diarization"),
        "source_unchanged": (result.get("source") or {}).get("unchanged"),
        "failed_chunks": (result.get("metrics") or {}).get("failed_chunks"),
    }


def main() -> int:
    fixtures = make_fixtures()
    src = fixtures["dir"]
    scenarios = []

    def record(name: str, result: dict, checks: dict, details: dict | None = None):
        scenarios.append({
            "name": name,
            "summary": summarize(result),
            "checks": checks,
            "details": details or {},
            "passed": all(checks.values()),
        })

    def ensure(checks: dict, key: str, cond: bool, detail=None):
        checks[key] = bool(cond)
        if not cond:
            raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))

    # S1: one-hour audio
    checks, details = {}, {}
    cfg = PipelineConfig(chunk_seconds=300, concurrency=2, timeout_s=10.0,
                         max_attempts=2, provider="mock", provider_config={"delay_ms": 5})
    r = run(src / "long_1h.mp3", TMP / "run-long", cfg, faults={})
    chunks = r.get("chunks") or []
    segs = r.get("segments") or []
    ensure(checks, "status_completed", r["status"] == "completed", r["status"])
    ensure(checks, "normalized_16k_mono",
           r["normalized"]["sample_rate"] == 16000 and r["normalized"]["channels"] == 1)
    ensure(checks, "chunk_count_12", len(chunks) == 12, len(chunks))
    ensure(checks, "segment_count_36", len(segs) == 36, len(segs))
    ensure(checks, "max_concurrency_2", r["asr"]["max_concurrency_observed"] == 2,
           r["asr"]["max_concurrency_observed"])
    ensure(checks, "first_segment_at_zero", segs and segs[0]["start_ms"] == 0, segs[0]["start_ms"] if segs else None)
    ensure(checks, "last_chunk_offset_3300s",
           chunks and abs(chunks[-1]["start_ms"] - 3300000) <= 300,
           chunks[-1]["start_ms"] if chunks else None)
    in_bounds = True
    for seg in segs:
        ch = chunks[seg["chunk_index"]]
        if not (ch["start_ms"] <= seg["start_ms"] < seg["end_ms"] <= ch["end_ms"]):
            in_bounds = False
            break
    ensure(checks, "segments_within_chunk_bounds", in_bounds)
    ensure(checks, "timestamps_sorted",
           all(segs[i]["start_ms"] <= segs[i + 1]["start_ms"] for i in range(len(segs) - 1)))
    ensure(checks, "source_unchanged", r["source"]["unchanged"] is True)
    ensure(checks, "duration_about_1h", abs(r["source"]["duration_ms"] - 3600000) <= 1500,
           r["source"]["duration_ms"])
    ensure(checks, "diarization_not_claimed",
           r["diarization"]["supported"] is False and r["diarization"]["status"] == "not_available")
    ensure(checks, "speaker_unknown",
           all(s["speaker_role"] == "unknown" and s["speaker_source"] == "none" for s in segs))
    ensure(checks, "segment_source_kept",
           all(s["source"]["chunk_start_ms"] == chunks[s["chunk_index"]]["start_ms"] for s in segs))
    details["chunk_offsets"] = [c["start_ms"] for c in chunks]
    record("一小时音频（12 段）", r, checks, details)

    # S2: short audio
    checks, details = {}, {}
    r = run(src / "short_8s.wav", TMP / "run-short", cfg, faults={})
    segs = r.get("segments") or []
    ensure(checks, "status_completed", r["status"] == "completed", r["status"])
    ensure(checks, "single_chunk", len(r["chunks"]) == 1, len(r["chunks"]))
    ensure(checks, "three_segments", len(segs) == 3, len(segs))
    ensure(checks, "within_8s", all(0 <= s["start_ms"] < s["end_ms"] <= 8000 for s in segs))
    ensure(checks, "normalized_16k_mono",
           r["normalized"]["sample_rate"] == 16000 and r["normalized"]["channels"] == 1)
    ensure(checks, "source_unchanged", r["source"]["unchanged"] is True)
    record("短音频（8 秒）", r, checks, details)

    # S3: empty audio
    checks, details = {}, {}
    r = run(src / "empty_0b.wav", TMP / "run-empty", cfg, faults={})
    ensure(checks, "status_failed", r["status"] == "failed", r["status"])
    ensure(checks, "error_empty_audio", (r.get("error") or {}).get("code") == "E_EMPTY_AUDIO",
           r.get("error"))
    ensure(checks, "no_chunks", len(r.get("chunks") or []) == 0)
    ensure(checks, "source_unchanged", r["source"]["unchanged"] is True)
    record("空音频（0 字节）", r, checks, details)

    # S3b: silent audio, no speech recognized
    checks, details = {}, {}
    r = run(src / "silent_5s.wav", TMP / "run-silent", cfg,
            provider=MockASR(delay_ms=2, empty_chunks={0}), faults={})
    ensure(checks, "status_completed", r["status"] == "completed", r["status"])
    ensure(checks, "single_chunk", len(r["chunks"]) == 1, len(r["chunks"]))
    ensure(checks, "zero_segments", len(r["segments"]) == 0, len(r["segments"]))
    ensure(checks, "empty_transcript_warning",
           any("空转写" in w for w in r.get("warnings", [])), r.get("warnings"))
    ensure(checks, "source_unchanged", r["source"]["unchanged"] is True)
    record("静音音频（无语音）", r, checks, details)

    # S4: slicing failure
    checks, details = {}, {}
    r = run(src / "mid_6m.mp3", TMP / "run-slice-fail",
            PipelineConfig(chunk_seconds=120, concurrency=2, timeout_s=10, max_attempts=2),
            faults={"slice_fail_at": 1})
    ensure(checks, "status_failed", r["status"] == "failed", r["status"])
    ensure(checks, "error_segment_failed", (r.get("error") or {}).get("code") == "E_SEGMENT_FAILED",
           r.get("error"))
    ensure(checks, "message_mentions_injection",
           "模拟切片失败" in str((r.get("error") or {}).get("message", "")))
    ensure(checks, "no_asr_result", len(r.get("segments") or []) == 0)
    ensure(checks, "source_unchanged", r["source"]["unchanged"] is True)
    chunk_dir = TMP / "run-slice-fail" / "chunks"
    ensure(checks, "partial_chunk_kept", (chunk_dir / "chunk_000.wav").exists())
    ensure(checks, "failed_chunk_removed", not (chunk_dir / "chunk_001.wav").exists())
    record("切片失败（第 2 段注入）", r, checks, details)

    # S5 + S6: single-chunk timeout, then partial retry
    checks, details = {}, {}
    provider = MockASR(delay_ms=5, timeout_once={1: 1})
    cfg_partial = PipelineConfig(chunk_seconds=120, concurrency=2, timeout_s=0.15,
                                 max_attempts=1, provider="mock")
    r = run(src / "mid_6m.mp3", TMP / "run-timeout", cfg_partial, provider=provider, faults={})
    ensure(checks, "status_partial", r["status"] == "partial", r["status"])
    ensure(checks, "one_failed_chunk", r["asr"]["failed"] == 1, r["asr"]["failed"])
    ensure(checks, "two_completed_chunks", r["asr"]["completed"] == 2, r["asr"]["completed"])
    failed = [c for c in r["chunks"] if c["status"] == "failed"]
    ensure(checks, "timeout_error", failed and failed[0]["error"]["code"] == "E_ASR_TIMEOUT",
           failed[0]["error"] if failed else None)
    ensure(checks, "six_segments_kept", len(r["segments"]) == 6, len(r["segments"]))
    ensure(checks, "other_chunks_untouched",
           all(c["status"] == "completed" for c in r["chunks"] if c["index"] != 1))
    details["timeout_stage"] = {"failed_chunk": 1, "segments_kept": len(r["segments"])}
    record("单片段超时（部分完成）", r, checks, details)

    checks, details = {}, {}
    cfg_retry = PipelineConfig(chunk_seconds=120, concurrency=2, timeout_s=2.0,
                               max_attempts=2, provider="mock")
    r2 = retry_failed(r, provider, cfg_retry, out_dir=TMP / "run-timeout")
    ensure(checks, "retry_completed", r2["status"] == "completed", r2["status"])
    ensure(checks, "no_failed_left", r2["asr"]["failed"] == 0, r2["asr"]["failed"])
    ensure(checks, "nine_segments", len(r2["segments"]) == 9, len(r2["segments"]))
    ensure(checks, "retried_chunk_attempts_2", r2["chunks"][1]["attempts"] == 2,
           r2["chunks"][1]["attempts"])
    ensure(checks, "others_attempts_1",
           all(c["attempts"] == 1 for c in r2["chunks"] if c["index"] != 1))
    ensure(checks, "timestamps_preserved",
           all(c["start_ms"] <= s["start_ms"] < s["end_ms"] <= c["end_ms"]
               for s in r2["segments"] for c in [r2["chunks"][s["chunk_index"]]]))
    ensure(checks, "diarization_not_claimed",
           r2["diarization"]["supported"] is False and r2["diarization"]["status"] == "not_available")
    details["retry_history"] = r2.get("retry_history")
    record("失败片段部分重试", r2, checks, details)

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "ffmpeg": subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True,
                                      encoding="utf-8", errors="replace").stdout.splitlines()[0],
            "platform": sys.platform,
        },
        "fixtures": fixtures["meta"],
        "scenarios": scenarios,
        "all_passed": all(s["passed"] for s in scenarios),
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")

    for s in scenarios:
        print(("PASS " if s["passed"] else "FAIL ") + s["name"] +
              f" | status={s['summary']['status']} chunks={s['summary']['chunks']} "
              f"segments={s['summary']['segments']}")
        for k, v in s["checks"].items():
            if not v:
                print("   failed check:", k)
    print("evidence:", EVIDENCE)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
