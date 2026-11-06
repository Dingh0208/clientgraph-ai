# -*- coding: utf-8 -*-
"""Normalize multiple pipeline results and merge them into citable evidence."""
from __future__ import annotations

from .merge import merge
from .normalize import normalize


def collect(results: list[dict], context: dict, hints: dict | None = None,
            occurred_at: dict | None = None, window_seconds: int = 300) -> dict:
    hints = hints or {}
    occurred_at = occurred_at or {}
    fragments = []
    for result in results:
        name = (result.get("source") or {}).get("name") or ""
        fragments.extend(normalize(
            result, context,
            hints=hints.get(name),
            occurred_at=occurred_at.get(name),
        ))
    merged = merge(fragments, window_seconds=window_seconds)
    merged["stats"]["results"] = len(results)
    return merged
