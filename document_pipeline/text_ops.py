# -*- coding: utf-8 -*-
"""TXT / HTML / JSON parsing, including common chat exports."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import quote

from .chat import detect_chat, detect_json_chat, participants
from .common import ParseError, clean, table_blocks

BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6",
              "blockquote", "section", "article", "tr"}


def read_text(path) -> tuple[str, str]:
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        candidates = ("utf-16", "utf-8-sig", "gb18030")
    elif data.startswith(b"\xef\xbb\xbf"):
        candidates = ("utf-8-sig", "gb18030", "utf-16")
    else:
        candidates = ("utf-8", "gb18030", "utf-16")
    for enc in candidates:
        try:
            text = data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if "\x00" in text and enc != "utf-16":
            continue
        return text.replace("\r\n", "\n").replace("\r", "\n"), enc
    raise ParseError(
        "E_ENCODING",
        "无法识别文本编码",
        "请另存为 UTF-8 或 GB18030 编码后重试。",
    )


def _message_blocks(messages: list[dict], file_name: str) -> list[dict]:
    blocks = []
    for m in messages:
        locator = f"chat://{file_name}#msg={m['id']}"
        m["locator"] = locator
        blocks.append({
            "id": m["id"],
            "type": "message",
            "text": m["text"],
            "ts": m["ts"],
            "sender": m["sender"],
            "locator": locator,
            "source": {"file": file_name, "kind": "chat", "part": "message"},
        })
    return blocks


def parse_txt(path) -> dict:
    text, encoding = read_text(path)
    lines = text.splitlines()
    messages = detect_chat(lines)
    if messages:
        return {
            "blocks": _message_blocks(messages, path.name),
            "messages": messages,
            "meta": {
                "encoding": encoding,
                "line_count": len(lines),
                "chat": {"message_count": len(messages),
                         "participants": participants(messages)},
            },
            "warnings": [],
            "errors": [],
        }

    blocks = []
    for i, line in enumerate(lines, 1):
        value = clean(line)
        if not value:
            continue
        blocks.append({
            "id": f"line{i:05d}",
            "type": "paragraph",
            "text": value,
            "locator": f"txt://{path.name}#line={i}",
            "source": {"file": path.name, "kind": "txt", "part": "text"},
        })
    return {
        "blocks": blocks,
        "messages": [],
        "meta": {"encoding": encoding, "line_count": len(lines), "chat": None},
        "warnings": [],
        "errors": [],
    }


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.tables: list[list[list[str]]] = []
        self.title = ""
        self._buf: list[str] = []
        self._skip = 0
        self._in_title = False
        self._in_table = 0
        self._row = None
        self._cell = None

    def _flush(self):
        value = clean("".join(self._buf))
        if value:
            self.blocks.append(value)
        self._buf = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style"):
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "table":
            self._flush()
            self._in_table += 1
            self.tables.append([])
            return
        if self._in_table:
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th"):
                self._cell = []
            return
        if tag in BLOCK_TAGS or tag == "br":
            self._flush()

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        if self._in_table:
            if self._cell is not None:
                self._cell.append(data)
            return
        self._buf.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if tag == "title":
            self._in_title = False
            return
        if self._in_table:
            if tag in ("td", "th") and self._cell is not None and self._row is not None:
                self._row.append(clean("".join(self._cell)))
                self._cell = None
            elif tag == "tr" and self._row is not None:
                if any(self._row):
                    self.tables[-1].append(self._row)
                self._row = None
            elif tag == "table":
                self._in_table = max(0, self._in_table - 1)
            return
        if tag in BLOCK_TAGS:
            self._flush()

    def close(self):
        super().close()
        self._flush()


def parse_html(path) -> dict:
    text, encoding = read_text(path)
    parser = _Extractor()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        raise ParseError(
            "E_PARSE_FAILED", f"HTML 解析失败：{str(exc)[:200]}",
            "确认文件是完整 HTML；可在浏览器打开后另存。",
        ) from exc

    table_blocks_list: list[dict] = []
    for ti, rows in enumerate(parser.tables, 1):
        if rows:
            table_blocks_list.extend(table_blocks(
                f"ht{ti}", ti, rows, f"html://{path.name}", part="table",
            ))

    messages = detect_chat(parser.blocks)
    if messages:
        blocks = _message_blocks(messages, path.name) + table_blocks_list
        meta = {
            "encoding": encoding,
            "title": clean(parser.title) or None,
            "table_count": len(parser.tables),
            "chat": {"message_count": len(messages),
                     "participants": participants(messages)},
        }
    else:
        blocks = [{
            "id": f"hb{i:05d}",
            "type": "paragraph",
            "text": value,
            "locator": f"html://{path.name}#block={i}",
            "source": {"file": path.name, "kind": "html", "part": "text"},
        } for i, value in enumerate(parser.blocks, 1)] + table_blocks_list
        meta = {
            "encoding": encoding,
            "title": clean(parser.title) or None,
            "table_count": len(parser.tables),
            "chat": None,
        }

    return {"blocks": blocks, "messages": messages, "meta": meta,
            "warnings": [], "errors": []}


def _flatten(obj, path: str, out: list[tuple[str, str]], limit: int = 800):
    if len(out) >= limit:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            _flatten(value, f"{path}.{key}" if path else str(key), out, limit)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _flatten(value, f"{path}[{i}]", out, limit)
    elif obj is not None:
        value = clean(str(obj))
        if value:
            out.append((path or "$", value[:2000]))


def parse_json(path) -> dict:
    text, encoding = read_text(path)
    try:
        obj = json.loads(text)
    except Exception as exc:
        raise ParseError(
            "E_JSON_INVALID",
            f"JSON 解析失败：{str(exc)[:200]}",
            "检查是否为合法 JSON；也可按纯文本导入。",
        ) from exc

    messages = detect_json_chat(obj)
    if messages:
        return {
            "blocks": _message_blocks(messages, path.name),
            "messages": messages,
            "meta": {
                "encoding": encoding,
                "root_type": type(obj).__name__,
                "chat": {"message_count": len(messages),
                         "participants": participants(messages)},
            },
            "warnings": [],
            "errors": [],
        }

    leaves: list[tuple[str, str]] = []
    _flatten(obj, "$", leaves)
    blocks = []
    for i, (json_path, value) in enumerate(leaves[:800], 1):
        blocks.append({
            "id": f"j{i:05d}",
            "type": "json_value",
            "text": value,
            "path": json_path,
            "locator": f"json://{path.name}#path={quote(json_path, safe='.$[]')}",
            "source": {"file": path.name, "kind": "json", "part": "value"},
        })
    warnings = []
    if len(leaves) > 800:
        warnings.append({
            "code": "W_JSON_TRUNCATED",
            "message": f"JSON 叶子节点超过 800 个，已截断（共 {len(leaves)} 个）",
        })
    return {
        "blocks": blocks,
        "messages": [],
        "meta": {"encoding": encoding, "root_type": type(obj).__name__,
                 "leaf_count": len(leaves), "chat": None},
        "warnings": warnings,
        "errors": [],
    }
