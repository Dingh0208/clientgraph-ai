# -*- coding: utf-8 -*-
"""Merge evidence fragments that describe the same fact at the same time."""
from __future__ import annotations

from collections import defaultdict

from .context import parse_time, sha


def _cust_key(frag: dict) -> str:
    if frag.get("customer"):
        return "c:" + frag["customer"]["id"]
    cands = frag.get("customer_candidates") or []
    if cands:
        return "amb:" + ",".join(sorted({c["id"] for c in cands}))
    return "none"


def _proj_key(frag: dict) -> str:
    if frag.get("project"):
        return "p:" + frag["project"]["id"]
    cands = frag.get("project_candidates") or []
    if cands:
        return "amb:" + ",".join(sorted({c["id"] for c in cands}))
    return "none"


def _union_candidates(items: list[dict]) -> list[dict]:
    best = {}
    for item in items:
        old = best.get(item["id"])
        if old is None or item.get("confidence", 0) > old.get("confidence", 0):
            best[item["id"]] = item
    return sorted(best.values(), key=lambda x: -x.get("confidence", 0))


def _clusters(frags: list[dict], window_seconds: int) -> list[list[dict]]:
    known, unknown = [], []
    for f in frags:
        _, dt, _ = parse_time(f.get("occurred_at"))
        if dt is None:
            unknown.append(f)
        else:
            f = {**f, "_dt": dt}
            known.append(f)
    known.sort(key=lambda x: x["_dt"])
    clusters: list[list[dict]] = []
    current: list[dict] = []
    for f in known:
        if not current or (f["_dt"] - current[0]["_dt"]).total_seconds() <= window_seconds:
            current.append(f)
        else:
            clusters.append(current)
            current = [f]
    if current:
        clusters.append(current)

    # No timestamp: only merge within the same file, never across files.
    by_file = defaultdict(list)
    for f in unknown:
        by_file[f["file"]].append(f)
    clusters.extend(by_file.values())
    return clusters


def _merge_cluster(cluster: list[dict]) -> dict:
    primary = max(
        cluster,
        key=lambda f: (f.get("confidence") or 0.0, len(f.get("text") or "")),
    )
    sources = []
    seen = set()
    for f in sorted(cluster, key=lambda x: (x["file"], x["locator"])):
        if f["source_hash"] in seen:
            continue
        seen.add(f["source_hash"])
        sources.append({
            "source_type": f["source_type"],
            "file": f["file"],
            "file_hash": f["file_hash"],
            "locator": f["locator"],
            "occurred_at": f["occurred_at"],
            "page": f["page"],
            "timestamp": f["timestamp"],
            "confidence": f["confidence"],
            "hash": f["source_hash"],
            "meta": f["source_meta"],
        })

    known = [f for f in cluster if f.get("occurred_at")]
    earliest = min(known, key=lambda f: parse_time(f["occurred_at"])[1]) if known else None
    time_value = (primary.get("occurred_at") or (earliest or {}).get("occurred_at"))
    time_key = (parse_time(time_value)[1].timestamp()
                if time_value else "unknown:" + "|".join(sorted({f["file"] for f in cluster})))
    cust_key = _cust_key(primary)
    proj_key = _proj_key(primary)
    h = sha(f"{primary['text_key']}|{cust_key}|{proj_key}|{time_key}")

    confidences = [f["confidence"] for f in cluster if isinstance(f.get("confidence"), (int, float))]
    page = primary.get("page")
    if page is None:
        page = next((f["page"] for f in cluster if f.get("page") is not None), None)
    timestamp = primary.get("timestamp") or next(
        (f["timestamp"] for f in cluster if f.get("timestamp")), None
    )
    bbox = primary.get("bbox") or next(
        (f["bbox"] for f in cluster if f.get("bbox")), None
    )

    return {
        "id": f"ev_{h[:12]}",
        "text": primary["text"],
        "normalized_text": primary["text_key"],
        "text_hash": sha(primary["text_key"]),
        "hash": h,
        "source_type": primary["source_type"],
        "source_file": primary["file"],
        "customer": primary.get("customer"),
        "customer_candidates": _union_candidates(
            [c for f in cluster for c in f.get("customer_candidates") or []]
        ),
        "project": primary.get("project"),
        "project_candidates": _union_candidates(
            [c for f in cluster for c in f.get("project_candidates") or []]
        ),
        "occurred_at": time_value,
        "time_precision": primary.get("time_precision"),
        "page": page,
        "timestamp": timestamp,
        "bbox": bbox,
        "confidence": max(confidences) if confidences else None,
        "confidence_avg": round(sum(confidences) / len(confidences), 4) if confidences else None,
        "sources": sources,
        "source_count": len(sources),
    }


def merge(fragments: list[dict], window_seconds: int = 300) -> dict:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for f in fragments:
        groups[(f["text_key"], _cust_key(f), _proj_key(f))].append(f)

    items = []
    for cluster in groups.values():
        for part in _clusters(cluster, window_seconds):
            items.append(_merge_cluster(part))

    items.sort(key=lambda x: (x["occurred_at"] is None, x["occurred_at"] or "", x["text"]))
    return {
        "schema": "clientgraph.evidence.v1",
        "items": items,
        "stats": {
            "fragments": len(fragments),
            "items": len(items),
            "merged_items": sum(1 for i in items if i["source_count"] > 1),
            "sources": sum(i["source_count"] for i in items),
            "merge_window_seconds": window_seconds,
        },
    }
