# -*- coding: utf-8 -*-
"""EML parsing: sender/recipients/date/subject, body and attachments."""
from __future__ import annotations

import email as email_lib
import html as html_lib
import re
from email import policy
from email.header import decode_header
from email.utils import getaddresses, parsedate_to_datetime

from .common import ParseError, clean


def _decode_header(value) -> str:
    if value is None:
        return ""
    out = []
    for part, enc in decode_header(str(value)):
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(part)
    return clean("".join(out))


def _addresses(value) -> list[str]:
    result = []
    for name, addr in getaddresses([str(value or "")]):
        name = _decode_header(name)
        if name and addr:
            result.append(f"{name} <{addr}>")
        elif addr:
            result.append(addr)
        elif name:
            result.append(name)
    return result


def _html_to_text(raw: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|tr|h\d)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    lines = [clean(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def parse_eml(path) -> dict:
    try:
        msg = email_lib.message_from_bytes(path.read_bytes(), policy=policy.default)
    except Exception as exc:
        raise ParseError(
            "E_EMAIL_PARSE_FAILED",
            f"EML 无法解析：{str(exc)[:200]}",
            "确认文件是标准 .eml；可在邮件客户端重新导出。",
        ) from exc

    subject = _decode_header(msg.get("Subject"))
    from_list = _addresses(msg.get("From"))
    to_list = _addresses(msg.get("To"))
    cc_list = _addresses(msg.get("Cc"))

    date_raw = _decode_header(msg.get("Date"))
    try:
        date_iso = parsedate_to_datetime(str(msg.get("Date"))).isoformat()
    except Exception:
        date_iso = date_raw or None

    blocks: list[dict] = []
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict] = []

    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        filename = part.get_filename()
        if filename:
            filename = _decode_header(filename)
            payload = part.get_payload(decode=True) or b""
            attachments.append({
                "filename": filename,
                "content_type": ctype,
                "size_bytes": len(payload),
            })
            blocks.append({
                "id": f"att{len(attachments):02d}",
                "type": "attachment",
                "text": filename,
                "locator": f"mail://{path.name}#attach={filename}",
                "source": {"file": path.name, "kind": "eml", "part": "attachment"},
            })
            continue
        if ctype == "text/plain":
            try:
                plain_parts.append(part.get_content())
            except Exception:
                payload = part.get_payload(decode=True) or b""
                plain_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        elif ctype == "text/html":
            try:
                html_parts.append(part.get_content())
            except Exception:
                payload = part.get_payload(decode=True) or b""
                html_parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))

    body = "\n".join(clean(p) for p in plain_parts if clean(p)).strip()
    body_format = "plain" if body else ""
    if not body and html_parts:
        body = _html_to_text("\n".join(html_parts)).strip()
        body_format = "html"
    if body:
        for i, para in enumerate([p for p in body.split("\n") if p.strip()], 1):
            blocks.append({
                "id": f"body{i:03d}",
                "type": "paragraph",
                "text": clean(para),
                "locator": f"mail://{path.name}#part={body_format or 'text'}",
                "source": {"file": path.name, "kind": "eml", "part": "body"},
            })

    meta = {
        "email": {
            "from": from_list,
            "to": to_list,
            "cc": cc_list,
            "date": date_iso,
            "date_raw": date_raw or None,
            "subject": subject,
            "message_id": clean(msg.get("Message-ID")) or None,
            "body_format": body_format or None,
            "attachments": attachments,
        }
    }
    warnings = []
    if not body and not attachments:
        warnings.append({"code": "W_EMPTY_EMAIL", "message": "邮件没有可提取的正文或附件"})
    return {"blocks": blocks, "messages": [], "meta": meta,
            "warnings": warnings, "errors": []}
