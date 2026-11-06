# -*- coding: utf-8 -*-
"""ffmpeg / ffprobe wrappers for the audio pipeline.

All operations write to a run directory; the input file is never modified.
"""
from __future__ import annotations

import csv
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class AudioInfo:
    duration_ms: int
    sample_rate: int
    channels: int
    codec: str
    has_audio: bool


def _run(cmd: list[str], timeout_s: int = 600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_s,
        )
    except FileNotFoundError as exc:
        raise MediaError("E_FFMPEG_MISSING", "未找到 ffmpeg/ffprobe，请先安装并加入 PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError("E_FFMPEG_TIMEOUT", f"ffmpeg 超时（>{timeout_s}s）") from exc


def probe(path: Path) -> AudioInfo:
    if not path.exists():
        raise MediaError("E_INPUT_MISSING", f"输入文件不存在：{path.name}")
    if path.stat().st_size == 0:
        raise MediaError("E_EMPTY_AUDIO", "输入文件为 0 字节")

    cp = _run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ], timeout_s=60)
    if cp.returncode != 0:
        raise MediaError("E_PROBE_FAILED", (cp.stderr or "ffprobe 解析失败").strip()[:400])

    data = json.loads(cp.stdout or "{}")
    streams = data.get("streams") or []
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not audio:
        raise MediaError("E_NO_AUDIO_STREAM", "文件中没有音频流")

    stream = audio[0]
    fmt = data.get("format") or {}
    duration = 0.0
    for candidate in (fmt.get("duration"), stream.get("duration")):
        try:
            duration = float(candidate)
            if duration > 0:
                break
        except (TypeError, ValueError):
            continue

    sample_rate = int(stream.get("sample_rate") or 0)
    channels = int(stream.get("channels") or 0)
    codec = str(stream.get("codec_name") or "unknown")
    if duration <= 0:
        raise MediaError("E_EMPTY_AUDIO", "音频时长为 0")
    return AudioInfo(
        duration_ms=int(round(duration * 1000)),
        sample_rate=sample_rate,
        channels=channels,
        codec=codec,
        has_audio=True,
    )


def normalize(input_path: Path, out_dir: Path) -> dict:
    """Decode to 16 kHz mono PCM WAV. Returns the derived asset metadata."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "normalized.wav"
    cp = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_path), "-vn", "-map", "0:a:0",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_path),
    ], timeout_s=900)
    if cp.returncode != 0 or not out_path.exists():
        raise MediaError("E_NORMALIZE_FAILED", (cp.stderr or "音频归一化失败").strip()[:400])

    info = probe(out_path)
    if info.sample_rate != 16000 or info.channels != 1:
        raise MediaError("E_NORMALIZE_INVALID", "归一化结果不是 16kHz 单声道")
    return {
        "path": out_path.name,
        "sample_rate": info.sample_rate,
        "channels": info.channels,
        "codec": info.codec,
        "duration_ms": info.duration_ms,
        "size_bytes": out_path.stat().st_size,
    }


def slice_audio(
    normalized_path: Path,
    out_dir: Path,
    chunk_seconds: int,
    duration_ms: int,
    fail_at: int | None = None,
) -> list[dict]:
    """Split into fixed-length chunks, keeping each chunk's start/end offset."""
    chunk_dir = out_dir / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    list_path = out_dir / "chunks.csv"
    pattern = chunk_dir / "chunk_%03d.wav"

    cp = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(normalized_path),
        "-f", "segment", "-segment_time", str(chunk_seconds),
        "-reset_timestamps", "1",
        "-segment_list", str(list_path), "-segment_list_type", "csv",
        str(pattern),
    ], timeout_s=900)
    if cp.returncode != 0:
        raise MediaError("E_SEGMENT_FAILED", (cp.stderr or "切片失败").strip()[:400])

    chunks: list[dict] = []
    if list_path.exists():
        with list_path.open("r", encoding="utf-8", errors="replace") as fh:
            for row in csv.reader(fh):
                if len(row) < 3 or row[0].strip() == "filename":
                    continue
                try:
                    start_s = float(row[1])
                    end_s = float(row[2])
                except ValueError:
                    continue
                path = Path(row[0])
                if not path.is_absolute():
                    path = (out_dir / path).resolve()
                if not path.exists():
                    path = chunk_dir / path.name
                chunks.append({
                    "index": len(chunks),
                    "file": path.name,
                    "path": str(path),
                    "start_ms": int(round(start_s * 1000)),
                    "end_ms": int(round(end_s * 1000)),
                })

    if not chunks:
        files = sorted(chunk_dir.glob("chunk_*.wav"))
        step = chunk_seconds * 1000
        for i, path in enumerate(files):
            start = i * step
            end = min(duration_ms, start + step)
            chunks.append({
                "index": i, "file": path.name, "path": str(path),
                "start_ms": start, "end_ms": end,
            })

    for ch in chunks:
        ch["duration_ms"] = max(0, ch["end_ms"] - ch["start_ms"])

    if not chunks:
        raise MediaError("E_SEGMENT_EMPTY", "未生成任何音频片段")

    if fail_at is not None and 0 <= fail_at < len(chunks):
        for ch in chunks[fail_at:]:
            try:
                Path(ch["path"]).unlink(missing_ok=True)
            except OSError:
                pass
        raise MediaError(
            "E_SEGMENT_FAILED",
            f"模拟切片失败：第 {fail_at + 1} 个片段写入失败，已完成 {fail_at} 个片段",
        )

    return chunks
