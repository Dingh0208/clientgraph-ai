# -*- coding: utf-8 -*-
"""Document pipeline entry point."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .common import ParseError, finish, sha256
from .docx_ops import parse_docx
from .eml_ops import parse_eml
from .pptx_ops import parse_pptx
from .text_ops import parse_html, parse_json, parse_txt
from .xls_ops import parse_xls
from .xlsx_ops import parse_xlsx

KIND_BY_SUFFIX = {
    ".docx": "docx", ".doc": "doc",
    ".xlsx": "xlsx", ".xls": "xls",
    ".pptx": "pptx", ".ppt": "ppt",
    ".eml": "eml",
    ".txt": "txt",
    ".html": "html", ".htm": "html",
    ".json": "json",
}


def _convert_legacy(path: Path, out_dir: Path, target: str) -> Path:
    import shutil
    soffice = shutil.which("soffice")
    if not soffice:
        raise ParseError(
            "E_LEGACY_FORMAT",
            f"旧版 {path.suffix} 需要转换器才能解析",
            f"请用 Word/WPS 打开后另存为 {target}；或在安装 LibreOffice 后重试。",
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    cp = subprocess.run(
        [soffice, "--headless", "--convert-to", target.lstrip("."),
         "--outdir", str(out_dir), str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    converted = out_dir / f"{path.stem}{target}"
    if cp.returncode != 0 or not converted.exists():
        raise ParseError(
            "E_LEGACY_CONVERT_FAILED",
            f"旧版 {path.suffix} 转换失败：{(cp.stderr or '').strip()[:200]}",
            f"请手动另存为 {target} 后重试。",
        )
    return converted


def process(path: str | Path, out_dir: str | Path | None = None) -> dict:
    path = Path(path)
    out_dir = Path(out_dir) if out_dir else path.parent / ".document-runs"
    kind = KIND_BY_SUFFIX.get(path.suffix.lower(), "unsupported")
    started = time.perf_counter()

    result = {
        "schema": "clientgraph.document.run.v1",
        "source": {
            "name": path.name,
            "kind": kind,
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "sha256": sha256(path) if path.exists() else None,
            "unchanged": None,
        },
        "status": "failed",
        "text": "",
        "blocks": [],
        "messages": [],
        "meta": {},
        "errors": [],
        "warnings": [],
        "stats": {"processing_ms": 0},
    }

    if not path.exists():
        result["errors"].append({
            "code": "E_INPUT_MISSING", "message": f"文件不存在：{path.name}",
            "hint": "确认路径后重试。", "recoverable": False,
        })
        return result
    if path.stat().st_size == 0:
        result["errors"].append({
            "code": "E_FILE_EMPTY", "message": "文件为 0 字节",
            "hint": "重新导出或复制原始文件后重试。", "recoverable": False,
        })
        return result

    try:
        if kind == "docx":
            child = parse_docx(path)
        elif kind == "doc":
            converted = _convert_legacy(path, out_dir, ".docx")
            child = parse_docx(converted)
            child.setdefault("meta", {})["converted_from"] = path.name
        elif kind == "xlsx":
            child = parse_xlsx(path)
        elif kind == "xls":
            child = parse_xls(path)
        elif kind == "pptx":
            child = parse_pptx(path)
        elif kind == "ppt":
            converted = _convert_legacy(path, out_dir, ".pptx")
            child = parse_pptx(converted)
            child.setdefault("meta", {})["converted_from"] = path.name
        elif kind == "eml":
            child = parse_eml(path)
        elif kind == "txt":
            child = parse_txt(path)
        elif kind == "html":
            child = parse_html(path)
        elif kind == "json":
            child = parse_json(path)
        else:
            raise ParseError(
                "E_UNSUPPORTED_FORMAT",
                f"不支持的文件类型：{path.suffix or '无扩展名'}",
                "支持 docx/doc、xlsx/xls、pptx/ppt、eml、txt、html、json。",
            )
    except ParseError as exc:
        result["errors"].append({
            "code": exc.code,
            "message": exc.message,
            "hint": exc.hint,
            "recoverable": exc.recoverable,
        })
        result["source"]["unchanged"] = (sha256(path) == result["source"]["sha256"])
        finish(result)
        result["stats"]["processing_ms"] = int((time.perf_counter() - started) * 1000)
        return result
    except Exception as exc:
        result["errors"].append({
            "code": "E_PROCESS_FAILED",
            "message": f"解析失败：{str(exc)[:300]}",
            "hint": "原始文件已保留；可另存为较新的格式后重试。",
            "recoverable": True,
        })
        result["source"]["unchanged"] = (sha256(path) == result["source"]["sha256"])
        finish(result)
        result["stats"]["processing_ms"] = int((time.perf_counter() - started) * 1000)
        return result

    for key in ("blocks", "messages", "meta", "warnings", "errors"):
        result[key] = child.get(key, result[key])
    finish(result)
    result["source"]["unchanged"] = (sha256(path) == result["source"]["sha256"])
    if not result["source"]["unchanged"]:
        result["status"] = "failed"
        result["errors"].append({
            "code": "E_ORIGINAL_MODIFIED",
            "message": "原始文件在解析期间被修改",
            "hint": "停止写入该文件后重试。",
            "recoverable": False,
        })
    result["stats"]["processing_ms"] = int((time.perf_counter() - started) * 1000)
    return result


def search(result: dict, query: str) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return []
    hits = []
    seen = set()
    for item in (result.get("blocks") or []) + (result.get("messages") or []):
        if q not in (item.get("text") or "").lower():
            continue
        key = item.get("id")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        hits.append(item)
    return hits
