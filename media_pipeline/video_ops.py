# -*- coding: utf-8 -*-
"""Video: extract the audio track only, then reuse the long-audio ASR pipeline."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from audio_pipeline import PipelineConfig, run as run_audio
from audio_pipeline.ffmpeg_ops import probe as probe_audio

from .ocr import OCREngineError  # noqa: F401  (kept for symmetry / callers)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe_video(path: Path) -> dict:
    cp = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or "ffprobe 失败").strip()[:300])
    data = json.loads(cp.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = 0.0
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    try:
        audio_start = float((audio or {}).get("start_time") or 0)
    except (TypeError, ValueError):
        audio_start = 0.0
    return {
        "duration_ms": int(round(duration * 1000)),
        "has_video": video is not None,
        "has_audio": audio is not None,
        "audio_codec": (audio or {}).get("codec_name"),
        "audio_channels": int((audio or {}).get("channels") or 0),
        "audio_sample_rate": int((audio or {}).get("sample_rate") or 0),
        "audio_start_ms": int(round(audio_start * 1000)),
    }


def process_video(path: str | Path, out_dir: str | Path, provider,
                  cfg: PipelineConfig | None = None) -> dict:
    path = Path(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg or PipelineConfig()

    result = {
        "status": "failed",
        "pages": [],
        "blocks": [],
        "errors": [],
        "warnings": [],
        "text": "",
        "diarization": {
            "supported": False,
            "status": "not_available",
            "reason": "未配置支持说话人分离的 ASR 模型；所有片段标记 speaker_role=unknown，不推断说话人。",
        },
        "stats": {
            "duration_ms": None,
            "has_audio": False,
            "audio_codec": None,
            "audio_channels": None,
            "audio_sample_rate": None,
            "extracted_audio_ref": None,
            "asr_chunks": 0,
            "asr_segments": 0,
            "frame_ocr": False,
        },
    }

    try:
        meta = _probe_video(path)
    except Exception as exc:
        result["errors"].append({
            "code": "E_VIDEO_OPEN_FAILED",
            "message": f"视频无法读取：{str(exc)[:200]}",
            "hint": "确认文件未损坏；原文件已保留。",
            "recoverable": False,
        })
        return result

    result["stats"].update({
        "duration_ms": meta["duration_ms"],
        "has_audio": meta["has_audio"],
        "audio_codec": meta["audio_codec"],
        "audio_channels": meta["audio_channels"],
        "audio_sample_rate": meta["audio_sample_rate"],
    })

    if not meta["has_audio"]:
        result["errors"].append({
            "code": "E_VIDEO_NO_AUDIO",
            "message": "视频中没有音频流，无法转写",
            "hint": "本版只处理音轨，不做画面 OCR；请提供带音轨的视频。",
            "recoverable": False,
        })
        return result

    audio_path = out_dir / "audio.wav"
    cp = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(path), "-vn", "-map", "0:a:0",
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
    )
    if cp.returncode != 0 or not audio_path.exists():
        result["errors"].append({
            "code": "E_VIDEO_EXTRACT_FAILED",
            "message": f"音轨提取失败：{(cp.stderr or '').strip()[:300]}",
            "hint": "尝试重新编码视频或提供标准 MP4；原视频已保留。",
            "recoverable": True,
        })
        return result

    try:
        info = probe_audio(audio_path)
    except Exception as exc:
        result["errors"].append({
            "code": "E_VIDEO_EXTRACT_FAILED",
            "message": f"提取后的音轨无效：{str(exc)[:200]}",
            "hint": "原视频已保留。",
            "recoverable": True,
        })
        return result

    result["stats"]["extracted_audio_ref"] = audio_path.name
    audio_result = run_audio(audio_path, out_dir / "asr", cfg, provider=provider)
    result["stats"]["asr_chunks"] = len(audio_result.get("chunks") or [])
    result["stats"]["asr_segments"] = len(audio_result.get("segments") or [])

    offset = max(0, meta["audio_start_ms"])
    video_duration = int(meta.get("duration_ms") or 0)
    for n, seg in enumerate(audio_result.get("segments") or []):
        start = offset + int(seg["start_ms"])
        end = offset + int(seg["end_ms"])
        if video_duration > 0:
            start = min(start, video_duration)
            end = min(end, video_duration)
        if end <= start:
            continue
        result["blocks"].append({
            "id": f"v{n:04d}",
            "type": "asr",
            "text": seg["text"],
            "page": None,
            "start_ms": start,
            "end_ms": end,
            "confidence": None,
            "locator": f"video://{path.name}#t={start}-{end}",
            "source": {
                "file": path.name,
                "kind": "video",
                "chunk_index": seg.get("chunk_index"),
                "extracted_audio_ref": audio_path.name,
                "provider": (audio_result.get("asr") or {}).get("provider"),
                "model": (audio_result.get("asr") or {}).get("model"),
                "timestamp_source": (seg.get("source") or {}).get("timestamp_source"),
            },
        })

    result["text"] = "\n".join(b["text"] for b in result["blocks"])
    result["diarization"] = audio_result.get("diarization") or result["diarization"]
    result["status"] = audio_result.get("status", "failed")
    if audio_result.get("error"):
        result["errors"].append({
            "code": audio_result["error"].get("code", "E_ASR_FAILED"),
            "message": audio_result["error"].get("message", "转写失败"),
            "hint": "可重试失败片段；原视频与提取音轨均已保留。",
            "recoverable": True,
        })
    if result["status"] == "partial":
        result["warnings"].append({
            "code": "W_PARTIAL",
            "message": "部分片段转写失败，已保留其余结果",
        })

    result["stats"]["audio_channels"] = info.channels
    result["stats"]["audio_sample_rate"] = info.sample_rate
    result["source_sha256"] = _sha256(path)
    return result
