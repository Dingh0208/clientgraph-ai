# -*- coding: utf-8 -*-
"""Long-audio pipeline: normalize -> fixed slicing -> concurrent ASR -> merge.

Guarantees:
  * the input file is only read, never written;
  * every merged segment keeps its original chunk offset and source;
  * one failed/timed-out chunk does not abort the other chunks;
  * speaker diarization is never inferred or claimed.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .asr import ASRProvider, ASRError, ASRTimeout, build_provider
from .ffmpeg_ops import MediaError, normalize, probe, slice_audio

DIARIZATION = {
    "supported": False,
    "status": "not_available",
    "reason": "未配置支持说话人分离的 ASR 模型；所有片段标记 speaker_role=unknown，不推断说话人。",
}


@dataclass
class PipelineConfig:
    chunk_seconds: int = 300
    concurrency: int = 2
    timeout_s: float = 60.0
    max_attempts: int = 2
    retry_backoff_s: float = 0.05
    provider: str = "mock"
    provider_config: dict = field(default_factory=dict)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _call_with_timeout(provider: ASRProvider, chunk: dict, timeout_s: float, stats: dict):
    with stats["lock"]:
        stats["active"] += 1
        stats["max_active"] = max(stats["max_active"], stats["active"])
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(provider.transcribe, chunk, timeout_s)
    try:
        return future.result(timeout=timeout_s)
    except FuturesTimeout as exc:
        raise ASRTimeout(f"片段 {chunk['index']} 超过 {timeout_s}s 未返回") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        with stats["lock"]:
            stats["active"] -= 1


def _process_chunk(chunk: dict, provider: ASRProvider, cfg: PipelineConfig,
                   stats: dict, start_attempt: int = 0) -> dict:
    attempts = start_attempt
    last_error = None
    while attempts < cfg.max_attempts:
        attempts += 1
        try:
            res = _call_with_timeout(provider, chunk, cfg.timeout_s, stats)
            return {
                "status": "completed",
                "attempts": attempts,
                "text": res.text,
                "segments": res.segments,
                "timestamp_source": getattr(res, "timestamp_source", "segment"),
                "error": None,
            }
        except ASRError as exc:
            last_error = {"code": exc.code, "message": exc.message, "retryable": exc.retryable}
            if not exc.retryable:
                break
        except Exception as exc:  # unexpected provider bug: isolate to this chunk
            last_error = {"code": "E_ASR_UNKNOWN", "message": str(exc)[:300], "retryable": False}
            break
        if attempts < cfg.max_attempts and cfg.retry_backoff_s > 0:
            time.sleep(cfg.retry_backoff_s)

    return {
        "status": "failed",
        "attempts": attempts,
        "text": "",
        "segments": [],
        "timestamp_source": "none",
        "error": last_error or {"code": "E_ASR_UNKNOWN", "message": "未执行识别", "retryable": False},
    }


def _merge(chunks: list[dict], duration_ms: int, source_name: str,
           provider: str, model: str) -> list[dict]:
    merged: list[dict] = []
    for ch in chunks:
        if ch.get("status") != "completed":
            continue
        for n, seg in enumerate(ch.get("segments") or []):
            local_start = max(0, min(int(seg.get("start_ms", 0)), ch["duration_ms"]))
            local_end = max(local_start, min(int(seg.get("end_ms", local_start)), ch["duration_ms"]))
            if local_end <= local_start:
                continue
            start = ch["start_ms"] + local_start
            end = min(ch["start_ms"] + local_end, duration_ms)
            merged.append({
                "id": f"c{ch['index']:03d}s{n:03d}",
                "text": str(seg.get("text") or "").strip(),
                "start_ms": start,
                "end_ms": end,
                "local_start_ms": local_start,
                "local_end_ms": local_end,
                "chunk_index": ch["index"],
                "speaker_role": "unknown",
                "speaker_source": "none",
                "source": {
                    "file": source_name,
                    "chunk_file": ch["file"],
                    "chunk_start_ms": ch["start_ms"],
                    "provider": provider,
                    "model": model,
                    "timestamp_source": ch.get("timestamp_source", "segment"),
                },
            })
    merged.sort(key=lambda s: (s["start_ms"], s["end_ms"], s["id"]))
    return merged


def _write(result: dict, out_dir: Path, name: str = "result.json") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _base_result(input_path: Path, sha_before: str, size: int) -> dict:
    return {
        "schema": "clientgraph.audio.run.v1",
        "run_id": uuid.uuid4().hex[:12],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed",
        "error": None,
        "source": {
            "name": input_path.name,
            "sha256": sha_before,
            "size_bytes": size,
            "unchanged": None,
            "duration_ms": None,
            "sample_rate": None,
            "channels": None,
            "codec": None,
        },
        "normalized": None,
        "segmentation": {"chunk_seconds": None, "count": 0, "overlap_ms": 0},
        "asr": {
            "provider": None, "model": None, "concurrency": None,
            "timeout_s": None, "max_attempts": None,
            "max_concurrency_observed": 0, "completed": 0, "failed": 0,
        },
        "diarization": {**DIARIZATION},
        "chunks": [],
        "segments": [],
        "text": "",
        "warnings": [],
        "metrics": {},
    }


def run(input_path: str | Path, out_dir: str | Path, cfg: PipelineConfig | None = None,
        provider: ASRProvider | None = None,
        faults: dict | None = None) -> dict:
    cfg = cfg or PipelineConfig()
    faults = faults or {}
    input_path = Path(input_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    sha_before = _sha256(input_path) if input_path.exists() else ""
    size = input_path.stat().st_size if input_path.exists() else 0
    result = _base_result(input_path, sha_before, size)
    result["segmentation"]["chunk_seconds"] = cfg.chunk_seconds

    try:
        info = probe(input_path)
        result["source"].update({
            "duration_ms": info.duration_ms,
            "sample_rate": info.sample_rate,
            "channels": info.channels,
            "codec": info.codec,
        })
        result["normalized"] = normalize(input_path, out_dir)
        chunks = slice_audio(
            out_dir / "normalized.wav", out_dir, cfg.chunk_seconds,
            info.duration_ms, fail_at=faults.get("slice_fail_at"),
        )
    except MediaError as exc:
        result["error"] = {"code": exc.code, "message": exc.message}
        result["source"]["unchanged"] = (_sha256(input_path) == sha_before) if input_path.exists() else True
        result["metrics"] = {"processing_ms": int((time.perf_counter() - started) * 1000)}
        _write(result, out_dir)
        return result

    if provider is None:
        try:
            provider = build_provider(cfg.provider, cfg.provider_config)
        except ASRError as exc:
            result["error"] = {"code": exc.code, "message": exc.message}
            result["source"]["unchanged"] = (_sha256(input_path) == sha_before)
            result["metrics"] = {"processing_ms": int((time.perf_counter() - started) * 1000)}
            _write(result, out_dir)
            return result

    result["asr"].update({
        "provider": provider.name,
        "model": provider.model,
        "concurrency": cfg.concurrency,
        "timeout_s": cfg.timeout_s,
        "max_attempts": cfg.max_attempts,
    })
    result["segmentation"]["count"] = len(chunks)
    result["chunks"] = chunks

    stats = {"lock": threading.Lock(), "active": 0, "max_active": 0}
    with ThreadPoolExecutor(max_workers=max(1, cfg.concurrency)) as pool:
        futures = {pool.submit(_process_chunk, ch, provider, cfg, stats): ch for ch in chunks}
        for fut in as_completed(futures):
            ch = futures[fut]
            ch.update(fut.result())

    result["asr"]["max_concurrency_observed"] = stats["max_active"]
    result["asr"]["completed"] = sum(1 for ch in chunks if ch["status"] == "completed")
    result["asr"]["failed"] = sum(1 for ch in chunks if ch["status"] == "failed")

    result["segments"] = _merge(
        chunks, info.duration_ms, input_path.name, provider.name, provider.model
    )
    result["text"] = " ".join(
        ch["text"] for ch in sorted(chunks, key=lambda x: x["index"]) if ch.get("text")
    ).strip()

    failed = result["asr"]["failed"]
    if failed == 0:
        result["status"] = "completed"
        if not result["segments"]:
            result["warnings"].append("未识别到语音内容（空转写），原始音频已保留")
    elif result["asr"]["completed"] > 0:
        result["status"] = "partial"
        result["error"] = {
            "code": "E_PARTIAL",
            "message": f"{failed} 个片段失败，已保留其余片段结果，可重试失败片段",
        }
        result["warnings"].append(f"{failed} 个片段失败，结果为部分完成")
    else:
        result["status"] = "failed"
        first = next((ch for ch in chunks if ch["status"] == "failed"), None)
        result["error"] = (first or {}).get("error") or {"code": "E_ASR_FAILED", "message": "全部片段失败"}

    result["source"]["unchanged"] = (_sha256(input_path) == sha_before)
    if not result["source"]["unchanged"]:
        result["status"] = "failed"
        result["error"] = {"code": "E_ORIGINAL_MODIFIED", "message": "原始文件在运行期间被修改"}

    result["metrics"] = {
        "processing_ms": int((time.perf_counter() - started) * 1000),
        "chunk_count": len(chunks),
        "segment_count": len(result["segments"]),
        "failed_chunks": [ch["index"] for ch in chunks if ch["status"] == "failed"],
    }
    _write(result, out_dir)
    return result


def retry_failed(result: dict, provider: ASRProvider, cfg: PipelineConfig,
                 out_dir: str | Path | None = None) -> dict:
    """Retry only failed chunks, then re-merge. Reuses existing chunk files."""
    out_dir = Path(out_dir) if out_dir else Path(result.get("_out_dir", "."))
    chunks = result.get("chunks") or []
    targets = [ch for ch in chunks if ch.get("status") == "failed"]
    if not targets:
        return result

    stats = {"lock": threading.Lock(), "active": 0, "max_active": 0}
    retried = []
    for ch in targets:
        start_attempt = int(ch.get("attempts", 0))
        fresh = _process_chunk(ch, provider, cfg, stats, start_attempt=start_attempt)
        ch.update(fresh)
        ch["retried"] = True
        retried.append(ch["index"])

    result["asr"]["provider"] = provider.name
    result["asr"]["model"] = provider.model
    result["asr"]["max_concurrency_observed"] = max(
        int(result["asr"].get("max_concurrency_observed", 0)), stats["max_active"]
    )
    result["asr"]["completed"] = sum(1 for ch in chunks if ch["status"] == "completed")
    result["asr"]["failed"] = sum(1 for ch in chunks if ch["status"] == "failed")
    result["segments"] = _merge(
        chunks, int(result["source"]["duration_ms"]), result["source"]["name"],
        provider.name, provider.model,
    )
    result["text"] = " ".join(
        ch["text"] for ch in sorted(chunks, key=lambda x: x["index"]) if ch.get("text")
    ).strip()

    if result["asr"]["failed"] == 0:
        result["status"] = "completed"
        result["error"] = None
        result["warnings"] = [w for w in result["warnings"] if "部分完成" not in w]
    elif result["asr"]["completed"] > 0:
        result["status"] = "partial"
        result["error"] = {"code": "E_PARTIAL", "message": "仍有片段失败"}
    else:
        result["status"] = "failed"

    result.setdefault("retry_history", []).append({
        "at": datetime.now(timezone.utc).isoformat(),
        "chunks": retried,
        "provider": provider.name,
    })
    result["metrics"]["failed_chunks"] = [ch["index"] for ch in chunks if ch["status"] == "failed"]
    result["metrics"]["segment_count"] = len(result["segments"])
    _write(result, out_dir, "result.retry.json")
    return result
