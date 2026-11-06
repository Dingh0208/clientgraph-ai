# -*- coding: utf-8 -*-
"""Normalize ASR / OCR / Office / email / chat results into evidence fragments."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))


def normalize_text(text: str) -> str:
    """NFKC + lowercase + remove whitespace/punctuation.

    Strict equality is intentional: similar wording must not be merged.
    """
    s = unicodedata.normalize("NFKC", str(text or "")).lower()
    out = []
    for ch in s:
        if ch.isspace():
            continue
        if unicodedata.category(ch).startswith("P"):
            continue
        out.append(ch)
    return "".join(out)


def sha(text: str, length: int = 64) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def parse_time(value):
    """Return (iso_string, datetime, precision) or (None, None, None)."""
    if value is None or value == "":
        return None, None, None
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e11:
            v /= 1000.0
        dt = datetime.fromtimestamp(v, tz=TZ)
        return dt.isoformat(), dt, "second"

    raw = str(value).strip()
    if not raw:
        return None, None, None
    text = raw.replace("/", "-").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return None, None, None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    precision = "second"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        precision = "day"
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", text):
        precision = "minute"
    return dt.isoformat(), dt, precision


def _digits(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _candidate(cid, name, method, confidence):
    return {"id": cid, "name": name, "method": method, "confidence": round(confidence, 2)}


def resolve_candidates(text: str, file_name: str, context: dict, extra_text: str = "",
                       hints: dict | None = None):
    """Resolve customer/project candidates by exact identifiers or names."""
    hints = hints or {}
    haystack = f"{text}\n{file_name}\n{extra_text}"
    low = haystack.lower()
    digits = _digits(haystack)

    customers = []
    for c in (context or {}).get("customers", []):
        best = None

        def take(method, conf):
            nonlocal best
            if best is None or conf > best["confidence"]:
                best = _candidate(c["id"], c.get("name") or c["id"], method, conf)

        if hints.get("customer_id") == c["id"]:
            take("manual", 1.0)
        for phone in c.get("phones") or []:
            if _digits(phone) and _digits(phone) in digits:
                take("phone", 0.98)
        for email in c.get("emails") or []:
            if email and email.lower() in low:
                take("email", 1.0)
        for wx in c.get("wechat") or []:
            if wx and wx.lower() in low:
                take("wechat", 0.95)
        for alias in [c.get("name")] + list(c.get("aliases") or []):
            if alias and len(str(alias)) >= 2 and str(alias).lower() in low:
                method = "name" if alias == c.get("name") else "alias"
                take(method, 0.9 if method == "name" else 0.85)
        if best:
            customers.append(best)

    # Deduplicate by id, keeping the strongest method.
    by_id = {}
    for item in customers:
        old = by_id.get(item["id"])
        if old is None or item["confidence"] > old["confidence"]:
            by_id[item["id"]] = item
    customers = sorted(by_id.values(), key=lambda x: -x["confidence"])

    chosen_customer = None
    if len(customers) == 1 and customers[0]["confidence"] >= 0.8:
        chosen_customer = customers[0]

    projects = []
    for p in (context or {}).get("projects", []):
        if chosen_customer and p.get("customer_id") and p["customer_id"] != chosen_customer["id"]:
            continue
        best = None

        def take_p(method, conf):
            nonlocal best
            if best is None or conf > best["confidence"]:
                best = _candidate(p["id"], p.get("name") or p["id"], method, conf)

        if hints.get("project_id") == p["id"]:
            take_p("manual", 1.0)
        for alias in [p.get("name")] + list(p.get("aliases") or []):
            if alias and len(str(alias)) >= 2 and str(alias).lower() in low:
                take_p("name", 0.9)
        if best:
            projects.append(best)

    by_id = {}
    for item in projects:
        old = by_id.get(item["id"])
        if old is None or item["confidence"] > old["confidence"]:
            by_id[item["id"]] = item
    projects = sorted(by_id.values(), key=lambda x: -x["confidence"])

    chosen_project = None
    if len(projects) == 1 and projects[0]["confidence"] >= 0.8:
        chosen_project = projects[0]
    return chosen_customer, customers, chosen_project, projects
