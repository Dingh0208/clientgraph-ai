# -*- coding: utf-8 -*-
"""Render a clarification record to text, Word (.docx) and PDF.

The external version hides internal reasons and evidence. Word is written with
zero third-party dependencies; PDF is printed by a local Edge/Chrome headless
browser so Chinese fonts come from the system.
"""
from __future__ import annotations

import html
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

STATUS_LABELS = {
    "pending": "待问",
    "asked": "已问",
    "answered": "已回答",
    "not_applicable": "不适用",
}

PRIORITY_LABELS = {
    "must_confirm": "必须先确认",
    "important": "重要",
    "later": "后续确认",
}

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]


class ExportError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _clean(text) -> str:
    return " ".join(str(text or "").split())


def _names(record: dict):
    customers = {c.get("id"): c.get("name") for c in record.get("scope", {}).get("customers") or []}
    projects = {p.get("id"): p.get("name") for p in record.get("scope", {}).get("projects") or []}
    return customers, projects


def _group_key(question: dict, record: dict):
    customer_id = question.get("customer_id")
    project_id = question.get("project_id")
    customers = record.get("scope", {}).get("customers") or []
    projects = record.get("scope", {}).get("projects") or []
    if customer_id is None and len(customers) == 1:
        customer_id = customers[0].get("id")
    if project_id is None and len(projects) == 1:
        project_id = projects[0].get("id")
    return customer_id, project_id


def _answer_line(answer: dict) -> str:
    stamp = answer.get("answered_at") or answer.get("recorded_at") or ""
    operator = answer.get("operator") or "甲方"
    return f"回答（{stamp}，{operator}）：{_clean(answer.get('text'))}"


def build_blocks(record: dict, ledger, group_by: str = "customer",
                 external: bool = False) -> list[tuple[str, str]]:
    """Return (kind, text) blocks shared by text, Word and PDF output."""
    customers, projects = _names(record)
    blocks: list[tuple[str, str]] = [("title", _clean(record.get("name")) or "需求澄清单")]

    scope_names = []
    for cid, name in customers.items():
        scope_names.append(f"客户：{name}")
    for pid, name in projects.items():
        scope_names.append(f"项目：{name}")
    meta = [f"状态：{record.get('status_label') or record.get('status')}",
            f"生成日期：{datetime.now(timezone.utc).date().isoformat()}"]
    if scope_names:
        meta.append("范围：" + "、".join(scope_names))
    blocks.append(("meta", " ｜ ".join(meta)))

    groups: dict[tuple, list[dict]] = {}
    for question in ledger.questions:
        groups.setdefault(_group_key(question, record), []).append(question)

    def order(key):
        cid, pid = key
        return (customers.get(cid, ""), projects.get(pid, ""), cid or "", pid or "")

    index = 0
    for cid, pid in sorted(groups, key=order):
        if group_by == "project":
            if pid:
                blocks.append(("h1", f"项目：{projects.get(pid, pid)}"))
            if cid:
                blocks.append(("h2", f"客户：{customers.get(cid, cid)}"))
        else:
            if cid:
                blocks.append(("h1", f"客户：{customers.get(cid, cid)}"))
            if pid:
                blocks.append(("h2", f"项目：{projects.get(pid, pid)}"))
        if not cid and not pid:
            blocks.append(("h1", "未归属"))

        for question in groups[(cid, pid)]:
            index += 1
            priority = question.get("priority_label") or PRIORITY_LABELS.get(
                question.get("priority"), question.get("priority") or "")
            label = f"{index}. {_clean(question.get('text'))}"
            if priority:
                label += f"（{priority}）"
            blocks.append(("h3", label))

            answers = question.get("answers") or []
            if answers:
                blocks.append(("p", _answer_line(answers[-1])))
                if len(answers) > 1:
                    blocks.append(("p", f"另有 {len(answers) - 1} 条历史回答，按时间顺序保留"))
            elif question.get("status") == "not_applicable":
                if external:
                    blocks.append(("p", "处理：不适用"))
                else:
                    blocks.append(("p", f"处理：不适用（{_clean(question.get('not_applicable_reason'))}）"))
            else:
                blocks.append(("p", f"状态：{STATUS_LABELS.get(question.get('status'), question.get('status'))}"))

            if not external:
                if question.get("reason"):
                    blocks.append(("p", f"提问理由：{_clean(question.get('reason'))}"))
                for item in question.get("evidence") or []:
                    parts = [str(item.get("file") or "unknown")]
                    if item.get("locator"):
                        parts.append(str(item["locator"]))
                    excerpt = item.get("excerpt") or item.get("text")
                    if excerpt:
                        parts.append(_clean(excerpt))
                    blocks.append(("p", "证据：" + " · ".join(parts)))
    return blocks


def render_text(record: dict, ledger, group_by: str = "customer",
                external: bool = False) -> str:
    return "\n".join(text for _kind, text in
                     build_blocks(record, ledger, group_by=group_by, external=external))


def _xml(text: str) -> str:
    return html.escape(text, quote=True)


def _paragraph(text: str, size: int = 21, bold: bool = False,
               space_after: int = 100) -> str:
    rpr = ["<w:rFonts w:ascii=\"Microsoft YaHei\" w:eastAsia=\"微软雅黑\" "
           "w:hAnsi=\"Microsoft YaHei\"/>"]
    if bold:
        rpr.append("<w:b/>")
    rpr.append(f"<w:sz w:val=\"{size}\"/><w:szCs w:val=\"{size}\"/>")
    return (
        "<w:p><w:pPr><w:spacing w:after=\"" + str(space_after) + "\"/></w:pPr>"
        "<w:r><w:rPr>" + "".join(rpr) + "</w:rPr>"
        "<w:t xml:space=\"preserve\">" + _xml(text) + "</w:t></w:r></w:p>"
    )


def export_docx(record: dict, ledger, path, group_by: str = "customer",
                external: bool = False) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sizes = {"title": (32, True), "meta": (19, False), "h1": (28, True),
             "h2": (24, True), "h3": (22, True), "p": (21, False)}
    body = []
    for kind, text in build_blocks(record, ledger, group_by=group_by, external=external):
        size, bold = sizes.get(kind, (21, False))
        body.append(_paragraph(text, size=size, bold=bold))
    sect = ("<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
            "<w:pgMar w:top=\"1134\" w:right=\"1134\" w:bottom=\"1134\" "
            "w:left=\"1134\"/></w:sectPr>")
    document = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:body>" + "".join(body) + sect + "</w:body></w:document>"
    )
    styles = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:styles xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii=\"Microsoft YaHei\" "
        "w:eastAsia=\"微软雅黑\" w:hAnsi=\"Microsoft YaHei\"/>"
        "<w:sz w:val=\"21\"/><w:szCs w:val=\"21\"/></w:rPr></w:rPrDefault>"
        "</w:docDefaults></w:styles>"
    )
    content_types = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-"
        "officedocument.wordprocessingml.document.main+xml\"/>"
        "<Override PartName=\"/word/styles.xml\" ContentType=\"application/vnd.openxmlformats-"
        "officedocument.wordprocessingml.styles+xml\"/>"
        "</Types>"
    )
    root_rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/"
        "relationships/officeDocument\" Target=\"word/document.xml\"/>"
        "</Relationships>"
    )
    doc_rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/"
        "relationships/styles\" Target=\"styles.xml\"/>"
        "</Relationships>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("word/document.xml", document)
        zf.writestr("word/styles.xml", styles)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
    return path


def _html_document(blocks: list[tuple[str, str]]) -> str:
    style = """
    @page { size: A4; margin: 18mm 16mm; }
    body { font-family: "Microsoft YaHei", "SimHei", sans-serif; color: #1f2937;
           font-size: 11pt; line-height: 1.7; }
    h1.d { font-size: 20pt; margin: 0 0 6pt; }
    p.meta { color: #6b7280; font-size: 9.5pt; margin: 0 0 16pt; }
    h2 { font-size: 14pt; margin: 16pt 0 6pt; border-left: 4px solid #2f6fed;
         padding-left: 8pt; }
    h3 { font-size: 12pt; margin: 12pt 0 4pt; }
    h4 { font-size: 11pt; margin: 12pt 0 3pt; font-weight: 600; }
    .q { font-weight: 600; margin: 10pt 0 3pt; }
    p { margin: 3pt 0; }
    """
    parts = []
    for kind, text in blocks:
        if kind == "title":
            parts.append(f"<h1 class=\"d\">{_xml(text)}</h1>")
        elif kind == "meta":
            parts.append(f"<p class=\"meta\">{_xml(text)}</p>")
        elif kind == "h1":
            parts.append(f"<h2>{_xml(text)}</h2>")
        elif kind == "h2":
            parts.append(f"<h3>{_xml(text)}</h3>")
        elif kind == "h3":
            parts.append(f"<p class=\"q\">{_xml(text)}</p>")
        else:
            parts.append(f"<p>{_xml(text)}</p>")
    return ("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<title>需求澄清单</title><style>" + style + "</style></head><body>"
            + "".join(parts) + "</body></html>")


def _browser() -> str | None:
    for candidate in BROWSERS:
        if Path(candidate).exists():
            return candidate
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("google-chrome")


def export_pdf(record: dict, ledger, path, group_by: str = "customer",
               external: bool = False, timeout: int = 90) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    browser = _browser()
    if not browser:
        raise ExportError("E_PDF_ENGINE",
                          "未找到 Edge/Chrome，无法生成 PDF；Word 导出不受影响")
    html_text = _html_document(build_blocks(record, ledger, group_by=group_by,
                                            external=external))
    with tempfile.TemporaryDirectory(prefix="cg-pdf-") as tmp:
        tmp_dir = Path(tmp)
        html_path = tmp_dir / "record.html"
        html_path.write_text(html_text, encoding="utf-8")
        profile = tmp_dir / "profile"
        command = [
            browser, "--headless=new", "--disable-gpu", "--no-sandbox",
            "--no-first-run", "--disable-extensions",
            f"--user-data-dir={profile}",
            "--print-to-pdf=" + str(path),
            "--print-to-pdf-no-header", "--no-pdf-header-footer",
            html_path.resolve().as_uri(),
        ]
        try:
            proc = subprocess.run(command, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ExportError("E_PDF_TIMEOUT", "PDF 渲染超时，请重试或改用 Word")
    if not path.exists() or path.stat().st_size < 800:
        detail = (proc.stderr or b"")[-300:].decode("utf-8", "ignore")
        raise ExportError("E_PDF_FAILED", f"PDF 生成失败：{detail or '输出为空'}")
    with path.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            raise ExportError("E_PDF_INVALID", "生成的文件不是有效 PDF")
    return path
