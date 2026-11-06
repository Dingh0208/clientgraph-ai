# -*- coding: utf-8 -*-
"""Convert pipeline results into normalized evidence fragments."""
from __future__ import annotations

from .context import normalize_text, parse_time, resolve_candidates, sha


def _meta(**kwargs) -> dict:
    return {k: v for k, v in kwargs.items() if v not in (None, "", [])}


def _fragment(text, source_type, file, file_hash, locator, context, hints,
              occurred_at=None, page=None, timestamp=None, confidence=None,
              bbox=None, source_meta=None, extra_text=""):
    text = (text or "").strip()
    text_key = normalize_text(text)
    if not text_key:
        return None
    customer, customers, project, projects = resolve_candidates(
        text, file, context, extra_text=extra_text, hints=hints,
    )
    iso, _dt, precision = parse_time(occurred_at)
    fhash = sha(f"{file_hash}|{locator}|{text_key}")
    return {
        "text": text,
        "text_key": text_key,
        "source_type": source_type,
        "file": file,
        "file_hash": file_hash,
        "locator": locator,
        "occurred_at": iso,
        "time_precision": precision,
        "page": page,
        "timestamp": timestamp,
        "bbox": bbox,
        "confidence": round(float(confidence), 4) if isinstance(confidence, (int, float)) else None,
        "customer": customer,
        "customer_candidates": customers,
        "project": project,
        "project_candidates": projects,
        "source_meta": source_meta or {},
        "source_hash": fhash,
    }


def _source_base(result: dict):
    src = result.get("source") or {}
    return src.get("name") or "unknown", src.get("sha256") or ""


def normalize_audio(result: dict, context: dict, hints: dict | None = None,
                    occurred_at: str | None = None) -> list[dict]:
    file, file_hash = _source_base(result)
    frags = []
    for seg in result.get("segments") or []:
        start = seg.get("start_ms")
        end = seg.get("end_ms")
        frag = _fragment(
            text=seg.get("text"),
            source_type="asr",
            file=file, file_hash=file_hash,
            locator=f"file://{file}#t={start}-{end}",
            context=context, hints=hints,
            occurred_at=occurred_at or (hints or {}).get("occurred_at"),
            timestamp={"start_ms": start, "end_ms": end},
            confidence=None,
            source_meta=_meta(
                provider=(seg.get("source") or {}).get("provider"),
                model=(seg.get("source") or {}).get("model"),
                chunk_index=seg.get("chunk_index"),
                timestamp_source=(seg.get("source") or {}).get("timestamp_source"),
            ),
        )
        if frag:
            frags.append(frag)
    return frags


def normalize_media(result: dict, context: dict, hints: dict | None = None,
                    occurred_at: str | None = None) -> list[dict]:
    file, file_hash = _source_base(result)
    frags = []
    for block in result.get("blocks") or []:
        btype = block.get("type")
        if btype == "asr":
            source_type = "asr"
        elif btype == "ocr":
            source_type = "ocr"
        else:
            source_type = "document"
        page = block.get("page")
        ts = None
        if block.get("start_ms") is not None:
            ts = {"start_ms": block.get("start_ms"), "end_ms": block.get("end_ms")}
        src = block.get("source") or {}
        frag = _fragment(
            text=block.get("text"),
            source_type=source_type,
            file=file, file_hash=file_hash,
            locator=block.get("locator") or f"file://{file}",
            context=context, hints=hints,
            occurred_at=occurred_at or (hints or {}).get("occurred_at"),
            page=page,
            timestamp=ts,
            confidence=block.get("confidence"),
            bbox=block.get("bbox"),
            source_meta=_meta(
                image_ref=src.get("image_ref"),
                image_sha256=src.get("image_sha256"),
                method=src.get("method"),
                provider=src.get("provider"),
                model=src.get("model"),
                chunk_index=src.get("chunk_index"),
                extracted_audio_ref=src.get("extracted_audio_ref"),
            ),
        )
        if frag:
            frags.append(frag)
    return frags


def normalize_document(result: dict, context: dict, hints: dict | None = None,
                       occurred_at: str | None = None) -> list[dict]:
    file, file_hash = _source_base(result)
    meta = result.get("meta") or {}
    email_meta = (meta.get("email") or {}) if isinstance(meta.get("email"), dict) else {}
    email_time = email_meta.get("date")
    doc_time = meta.get("created") or meta.get("occurred_at")
    extra_email = " ".join(
        list(email_meta.get("from") or []) + list(email_meta.get("to") or [])
        + list(email_meta.get("cc") or []) + [email_meta.get("subject") or ""]
    )
    frags = []

    for msg in result.get("messages") or []:
        frag = _fragment(
            text=msg.get("text"),
            source_type="chat",
            file=file, file_hash=file_hash,
            locator=msg.get("locator") or f"chat://{file}#msg={msg.get('id')}",
            context=context, hints=hints,
            occurred_at=msg.get("ts") or occurred_at,
            source_meta=_meta(sender=msg.get("sender"), message_id=msg.get("id"),
                              message_type=msg.get("type")),
            extra_text=msg.get("sender") or "",
        )
        if frag:
            frags.append(frag)

    for block in result.get("blocks") or []:
        btype = block.get("type")
        if btype == "message":
            continue
        src = block.get("source") or {}
        kind = src.get("kind") or result.get("source", {}).get("kind")
        page = block.get("page")
        source_type = "document"
        extra = ""
        when = occurred_at or (hints or {}).get("occurred_at")
        smeta = {}

        if btype == "table_row":
            source_type = "table"
            page = block.get("slide") or page
            when = doc_time or when
            smeta = _meta(sheet=block.get("sheet"), slide=block.get("slide"),
                          table=block.get("table_index"), row=block.get("row"),
                          col_count=len(block.get("cols") or []))
        elif btype in ("slide_text", "slide_note"):
            source_type = "slide"
            page = block.get("slide")
            when = doc_time or when
            smeta = _meta(slide=block.get("slide"), shape=block.get("shape"),
                          part=btype)
        elif btype == "attachment":
            source_type = "email"
            when = email_time or when
            smeta = _meta(part="attachment")
        elif kind == "eml":
            source_type = "email"
            when = email_time or when
            extra = extra_email
            smeta = _meta(part="body", sender=email_meta.get("from"),
                          recipients=email_meta.get("to"), cc=email_meta.get("cc"),
                          subject=email_meta.get("subject"))
        elif btype == "json_value":
            source_type = "document"
            when = doc_time or when
            smeta = _meta(json_path=block.get("path"))
        elif btype in ("paragraph", "heading"):
            source_type = "email" if kind == "eml" else "document"
            when = (email_time if kind == "eml" else (doc_time or when))
        else:
            when = doc_time or when

        frag = _fragment(
            text=block.get("text"),
            source_type=source_type,
            file=file, file_hash=file_hash,
            locator=block.get("locator") or f"file://{file}",
            context=context, hints=hints,
            occurred_at=when,
            page=page,
            confidence=block.get("confidence"),
            bbox=block.get("bbox"),
            source_meta=smeta,
            extra_text=extra,
        )
        if frag:
            frags.append(frag)
    return frags


def normalize(result: dict, context: dict, hints: dict | None = None,
              occurred_at: str | None = None) -> list[dict]:
    schema = result.get("schema") or ""
    if schema == "clientgraph.audio.run.v1":
        return normalize_audio(result, context, hints, occurred_at)
    if schema == "clientgraph.media.run.v1":
        return normalize_media(result, context, hints, occurred_at)
    if schema == "clientgraph.document.run.v1":
        return normalize_document(result, context, hints, occurred_at)
    return normalize_document(result, context, hints, occurred_at)
