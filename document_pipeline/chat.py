# -*- coding: utf-8 -*-
"""Chat export detection for TXT / HTML / JSON exports."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

from .common import clean

DATE = r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"
TIME = r"\d{1,2}:\d{2}(?::\d{2})?"
PAT_A = re.compile(rf"^\[?({DATE}[ T]{TIME})\]?\s*[,，]?\s*([^:：]{{1,40}})[:：]\s*(.*)$")
PAT_B = re.compile(rf"^\[?({DATE}[ T]{TIME})\]?\s+(.{{1,40}})$")
PAT_C = re.compile(rf"^({TIME})\s+([^:：]{{1,40}})[:：]\s*(.*)$")


def detect_chat(lines: list[str]) -> list[dict]:
    """Return messages when the text looks like a chat export, else []."""
    msgs: list[dict] = []
    cur: dict | None = None

    def push():
        nonlocal cur
        if cur and clean(cur.get("text", "")):
            msgs.append(cur)
        cur = None

    for raw in lines:
        line = clean(raw)
        if not line:
            continue
        m = PAT_A.match(line) or PAT_C.match(line)
        if m:
            push()
            cur = {"ts": clean(m.group(1)), "sender": clean(m.group(2)),
                   "text": clean(m.group(3)), "weak": False}
            continue
        m = PAT_B.match(line)
        if m:
            push()
            cur = {"ts": clean(m.group(1)), "sender": clean(m.group(2)),
                   "text": "", "weak": True}
            continue
        if cur:
            cur["text"] = (cur["text"] + "\n" + line).strip()
    push()

    strong = [m for m in msgs if not m["weak"]]
    weak = [m for m in msgs if m["weak"]]
    if len(strong) >= 2:
        chosen = strong
    elif len(weak) >= 3:
        counts = Counter(m["sender"] for m in weak)
        if counts and max(counts.values()) < 2:
            return []
        chosen = weak
    else:
        return []

    out = []
    for i, m in enumerate(chosen, 1):
        out.append({
            "id": f"m{i:03d}",
            "ts": m["ts"],
            "sender": m["sender"],
            "text": clean(m["text"]),
            "type": "text",
        })
    return out


def _pick(obj: dict, keys: list[str]):
    lower = {str(k).lower(): k for k in obj.keys()}
    for key in keys:
        if key.lower() in lower:
            return obj[lower[key.lower()]]
    return None


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return clean(value.get("name") or value.get("nickname") or "")
    if isinstance(value, list):
        return ""
    return clean(str(value))


def _as_time(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e11:
            v /= 1000.0
        try:
            return datetime.fromtimestamp(v).isoformat(sep=" ")
        except (OSError, ValueError):
            return str(value)
    return clean(str(value))


def detect_json_chat(obj) -> list[dict]:
    candidates = []
    if isinstance(obj, list):
        candidates.append(obj)
    elif isinstance(obj, dict):
        for key in ("messages", "messageList", "chat", "data", "list"):
            value = _pick(obj, [key])
            if isinstance(value, list):
                candidates.append(value)
    for items in candidates:
        messages = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = _as_text(_pick(item, ["content", "text", "msg", "message", "body"]))
            if not text:
                continue
            sender = _as_text(_pick(item, ["sender", "from", "nickname", "senderName",
                                           "talker", "userName", "name"]))
            ts = _as_time(_pick(item, ["time", "timestamp", "createTime", "msgTime",
                                       "date", "sendTime"]))
            messages.append({
                "id": f"m{len(messages) + 1:03d}",
                "ts": ts,
                "sender": sender,
                "text": text,
                "type": _as_text(_pick(item, ["type", "msgType"])) or "text",
            })
        if len(messages) >= 2 and any(m.get("ts") or m.get("sender") for m in messages):
            return messages
    return []


def participants(messages: list[dict]) -> list[str]:
    seen = []
    for m in messages:
        if m.get("sender") and m["sender"] not in seen:
            seen.append(m["sender"])
    return seen
