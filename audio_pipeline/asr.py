# -*- coding: utf-8 -*-
"""ASR providers.

Only the mock provider is exercised in the local verification. The Qwen
adapter implements the DashScope OpenAI-compatible transcription endpoint and
is selected explicitly via configuration; it never falls back to mock silently.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path


class ASRError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = True):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class ASRTimeout(ASRError):
    def __init__(self, message: str):
        super().__init__("E_ASR_TIMEOUT", message, retryable=True)


@dataclass
class ASRResult:
    text: str
    segments: list[dict] = field(default_factory=list)
    raw: dict | None = None
    timestamp_source: str = "segment"


class ASRProvider:
    name = "base"
    model = "base"
    capabilities: dict = {"diarization": False}

    def transcribe(self, chunk: dict, timeout_s: float) -> ASRResult:
        raise NotImplementedError


class MockASR(ASRProvider):
    """Deterministic local provider for pipeline verification."""

    name = "mock"
    model = "mock-asr-v1"
    capabilities = {"diarization": False, "timestamps": "segment"}

    def __init__(
        self,
        delay_ms: int = 5,
        fail_once: dict[int, int] | None = None,
        timeout_once: dict[int, int] | None = None,
        empty_chunks: set[int] | None = None,
    ):
        self.delay_ms = delay_ms
        self.fail_once = dict(fail_once or {})
        self.timeout_once = dict(timeout_once or {})
        self.empty_chunks = set(empty_chunks or set())

    def transcribe(self, chunk: dict, timeout_s: float) -> ASRResult:
        idx = int(chunk["index"])

        if self.timeout_once.get(idx, 0) > 0:
            self.timeout_once[idx] -= 1
            # Deliberately exceed the caller's timeout so the wrapper trips.
            time.sleep(float(timeout_s) + 0.4)
            raise ASRError("E_ASR_TIMEOUT", f"模拟超时：片段 {idx}", retryable=True)

        if self.fail_once.get(idx, 0) > 0:
            self.fail_once[idx] -= 1
            raise ASRError("E_ASR_ENGINE", f"模拟识别失败：片段 {idx}", retryable=True)

        time.sleep(max(0, self.delay_ms) / 1000.0)

        if idx in self.empty_chunks:
            return ASRResult(text="", segments=[], raw={"empty": True})

        dur = int(chunk["duration_ms"])
        cuts = [0, int(dur * 0.32), int(dur * 0.72), dur]
        segments = []
        for n in range(3):
            start = cuts[n]
            end = cuts[n + 1]
            segments.append({
                "start_ms": start,
                "end_ms": end,
                "text": f"片段{idx + 1}第{n + 1}段：设备巡检、报价与上线时间的模拟转写内容。",
            })
        return ASRResult(
            text=" ".join(s["text"] for s in segments),
            segments=segments,
            raw={"provider": self.name},
        )


class QwenASR(ASRProvider):
    """DashScope / Qwen ASR adapter (OpenAI-compatible transcriptions).

    Configure:
      DASHSCOPE_API_KEY   required
      QWEN_ASR_MODEL      default qwen3-asr-flash
      QWEN_ASR_BASE_URL   default https://dashscope.aliyuncs.com/compatible-mode/v1

    This adapter is implemented but not exercised by the local verification
    because no API key is configured. It never falls back to mock.
    """

    name = "qwen"
    capabilities = {"diarization": False, "timestamps": "segment_or_chunk"}

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 base_url: str | None = None):
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        if not self.api_key:
            raise ASRError("E_ASR_NOT_CONFIGURED", "未配置 DASHSCOPE_API_KEY", retryable=False)
        self.model = model or os.environ.get("QWEN_ASR_MODEL", "qwen3-asr-flash")
        self.base_url = (base_url or os.environ.get(
            "QWEN_ASR_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )).rstrip("/")

    def transcribe(self, chunk: dict, timeout_s: float) -> ASRResult:
        path = Path(chunk["path"])
        boundary = "----cg" + uuid.uuid4().hex
        body = bytearray()

        def add_field(name: str, value: str):
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(value.encode("utf-8") + b"\r\n")

        add_field("model", self.model)
        add_field("response_format", "verbose_json")
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode()
        )
        body.extend(b"Content-Type: audio/wav\r\n\r\n")
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            f"{self.base_url}/audio/transcriptions",
            data=bytes(body),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            raise ASRError("E_ASR_HTTP", f"ASR 服务返回 {exc.code}", retryable=retryable) from exc
        except (urllib.error.URLError, socket.timeout) as exc:
            raise ASRError("E_ASR_NETWORK", f"ASR 网络异常：{exc}", retryable=True) from exc

        text = str(payload.get("text") or "").strip()
        raw_segments = payload.get("segments") or []
        segments: list[dict] = []
        for seg in raw_segments:
            try:
                if "start_ms" in seg:
                    start = int(seg["start_ms"])
                    end = int(seg["end_ms"])
                else:
                    start = int(round(float(seg.get("start", 0)) * 1000))
                    end = int(round(float(seg.get("end", 0)) * 1000))
            except (TypeError, ValueError):
                continue
            segments.append({
                "start_ms": start, "end_ms": end,
                "text": str(seg.get("text") or "").strip(),
            })

        if not segments and text:
            # Provider returned no timestamps: keep one segment for the chunk.
            segments = [{"start_ms": 0, "end_ms": int(chunk["duration_ms"]), "text": text}]
            return ASRResult(text=text, segments=segments, raw=payload, timestamp_source="chunk")

        return ASRResult(text=text, segments=segments, raw=payload)


def build_provider(name: str, config: dict | None = None) -> ASRProvider:
    cfg = config or {}
    if name == "mock":
        return MockASR(
            delay_ms=int(cfg.get("delay_ms", 5)),
            fail_once=cfg.get("fail_once"),
            timeout_once=cfg.get("timeout_once"),
            empty_chunks=set(cfg.get("empty_chunks") or []),
        )
    if name == "qwen":
        return QwenASR(
            api_key=cfg.get("api_key"),
            model=cfg.get("model"),
            base_url=cfg.get("base_url"),
        )
    raise ASRError("E_ASR_PROVIDER", f"未知的 ASR 提供方：{name}", retryable=False)
