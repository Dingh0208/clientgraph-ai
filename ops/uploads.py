# -*- coding: utf-8 -*-
"""Server-side upload jobs: validation, staged processing, persistence.

Stages: upload -> parse -> transcribe -> OCR -> match.
- Limits and allowed types are checked before a job is created.
- WeChat uploads must carry the user's prior selection/date scope; the server
  never scans a local WeChat database or widens the selected range.
- Jobs are persisted as JSON so leaving the page or restarting the service does
  not lose completed stage results.
- Retry resumes at the first failed/cancelled/unavailable stage; cancel keeps
  results already produced.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import queue
import re
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path

STAGES = ("upload", "parse", "transcribe", "ocr", "match")
STAGE_LABELS = {
    "upload": "上传", "parse": "解析", "transcribe": "转写",
    "ocr": "OCR", "match": "匹配",
}
JOB_STATUS_LABELS = {
    "queued": "排队中", "running": "处理中", "completed": "已完成",
    "partial": "部分完成", "failed": "失败", "cancelled": "已取消",
}
DEFAULT_MAX_BYTES = 50 * 1024 * 1024

DOC_EXTS = {".pdf", ".docx", ".doc", ".txt", ".md", ".rtf", ".xlsx", ".xls",
            ".pptx", ".ppt", ".csv"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".amr", ".aac", ".flac", ".ogg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
EMAIL_EXTS = {".eml", ".msg", ".txt", ".html", ".htm"}
CHAT_EXTS = {".txt", ".html", ".htm", ".json", ".csv"}
ALLOWED = {
    "file": DOC_EXTS | AUDIO_EXTS | IMAGE_EXTS,
    "email": EMAIL_EXTS,
    "chat": CHAT_EXTS,
    "wechat": CHAT_EXTS,
}

WECHAT_TIME = re.compile(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})[ T](\d{1,2}):(\d{2})")


class UploadError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class StageFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class StageUnavailable(StageFailure):
    """Stage cannot run because a capability is absent (not a data failure)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_name(name: str) -> str:
    base = Path(str(name or "")).name.replace("\\", "/").split("/")[-1]
    base = re.sub(r"[\x00-\x1f<>:\"|?*]+", "_", base).strip(" .")
    if not base:
        base = "upload.bin"
    if len(base) > 120:
        stem, dot, ext = base.rpartition(".")
        base = (stem[:100] + "." + ext) if dot else base[:120]
    return base


def source_kind(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in IMAGE_EXTS:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in (".docx", ".xlsx", ".pptx"):
        return "office"
    if ext in (".eml", ".msg"):
        return "email"
    if ext in (".txt", ".md", ".csv", ".json", ".html", ".htm"):
        return "text"
    return "other"


def parse_wechat_scope(raw: str | None) -> dict:
    if not raw:
        raise UploadError("E_WECHAT_SCOPE_REQUIRED",
                          "微信资料必须带上用户已选择的会话与日期范围")
    try:
        scope = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
    except Exception:
        raise UploadError("E_WECHAT_SCOPE_INVALID", "微信导入范围格式不正确")
    if not isinstance(scope, dict) or scope.get("selected_by_user") is not True:
        raise UploadError("E_WECHAT_SCOPE_INVALID", "微信导入范围未经用户确认")
    for key in ("contact_id", "conversation_id", "date_from", "date_to"):
        if not str(scope.get(key) or "").strip():
            raise UploadError("E_WECHAT_SCOPE_INVALID", f"微信导入范围缺少 {key}")
    for key in ("date_from", "date_to"):
        if not re.match(r"^20\d{2}-\d{2}-\d{2}$", str(scope[key])):
            raise UploadError("E_WECHAT_SCOPE_INVALID", f"{key} 必须是 YYYY-MM-DD")
    if scope["date_from"] > scope["date_to"]:
        raise UploadError("E_WECHAT_SCOPE_INVALID", "微信导入开始日期晚于结束日期")
    return scope


def _decode_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "ignore")


def _strip_xml(xml: str) -> str:
    xml = re.sub(r"<[^>]+>", " ", xml)
    return re.sub(r"\s+", " ", xml).strip()


class LocalProcessor:
    """Lightweight local handlers. Missing ASR/OCR is reported, not faked."""

    def parse(self, job: dict, path: Path) -> dict:
        name = job["file_name"]
        ext = Path(name).suffix.lower()
        kind = source_kind(name)
        text = ""
        extra = {}
        if ext == ".eml":
            message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
            body = message.get_body(preferencelist=("plain",))
            text = body.get_content() if body else ""
            extra = {"subject": str(message.get("Subject") or ""),
                     "from": str(message.get("From") or ""),
                     "to": str(message.get("To") or ""),
                     "date": str(message.get("Date") or "")}
        elif ext in (".docx", ".xlsx", ".pptx"):
            with zipfile.ZipFile(path) as zf:
                if ext == ".docx":
                    text = _strip_xml(zf.read("word/document.xml").decode("utf-8", "ignore"))
                elif ext == ".xlsx":
                    names = [n for n in zf.namelist() if n.endswith("sharedStrings.xml")]
                    text = " ".join(_strip_xml(zf.read(n).decode("utf-8", "ignore"))
                                    for n in names)
                else:
                    text = " ".join(_strip_xml(zf.read(n).decode("utf-8", "ignore"))
                                    for n in zf.namelist() if n.startswith("ppt/slides/slide"))
        elif kind == "pdf":
            head = path.read_bytes()[:5]
            extra = {"pdf": head == b"%PDF-", "needs_ocr": True}
            if head != b"%PDF-":
                raise StageFailure("E_PDF_INVALID", "文件不是有效 PDF")
        elif kind in ("text", "audio", "image"):
            if kind == "text":
                text = _decode_text(path)
        else:
            raise StageFailure("E_PARSE_UNSUPPORTED", f"暂不支持解析 .{ext.lstrip('.')}")

        text = text or ""
        if job["source_type"] == "wechat":
            scope = job.get("wechat_scope") or {}
            stamps = []
            for match in WECHAT_TIME.finditer(text):
                y, m, d, hh, mm = map(int, match.groups())
                stamps.append(f"{y:04d}-{m:02d}-{d:02d}")
            if stamps:
                outside = [s for s in stamps if s < scope["date_from"] or s > scope["date_to"]]
                if outside:
                    raise StageFailure("E_WECHAT_OUT_OF_SCOPE",
                                       f"文件包含范围外消息：{outside[0]}")
        return {
            "format": ext.lstrip("."),
            "chars": len(text),
            "preview": text[:400],
            "lines": text.count("\n") + 1 if text else 0,
            **extra,
        }

    def transcribe(self, job: dict, path: Path) -> dict:
        if os.environ.get("CG_ASR_PROVIDER") == "mock":
            return {"text": "本地 Mock 转写：未接入真实语音识别。", "mode": "mock"}
        raise StageUnavailable("E_ASR_NOT_CONFIGURED",
                               "未配置语音识别，转写阶段跳过；已完成结果保留")

    def ocr(self, job: dict, path: Path) -> dict:
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            raise StageUnavailable("E_OCR_NOT_INSTALLED",
                                   "未安装本地 OCR，OCR 阶段跳过；已完成结果保留")
        raise StageUnavailable("E_OCR_NOT_RUN",
                               "OCR 引擎已安装但本服务未启用页面识别")

    def match(self, job: dict) -> dict:
        customer_id = job.get("customer_id")
        project_id = job.get("project_id")
        if not customer_id and not project_id:
            raise StageUnavailable("E_NO_TARGET", "未选择客户/项目，匹配阶段跳过")
        return {"customer_id": customer_id, "project_id": project_id,
                "matched_by": "user_selection"}


class UploadManager:
    def __init__(self, data_dir: Path | str, processor=None,
                 max_bytes: int = DEFAULT_MAX_BYTES, auto_start: bool = False):
        self.data_dir = Path(data_dir)
        self.jobs_dir = self.data_dir / "jobs"
        self.uploads_dir = self.data_dir / "uploads"
        self.tmp_dir = self.data_dir / "tmp"
        for path in (self.jobs_dir, self.uploads_dir, self.tmp_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.processor = processor or LocalProcessor()
        self.max_bytes = int(max_bytes)
        self.jobs: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.queue: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._worker = None
        self._load()
        if auto_start:
            self.start()

    # ---------------------------------------------------------------- persist
    def _job_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def _save(self, job: dict):
        job["updated_at"] = _now()
        tmp = self._job_path(job["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._job_path(job["id"]))

    def _load(self):
        for path in sorted(self.jobs_dir.glob("*.json")):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            changed = False
            for stage in job.get("stages", []):
                if stage.get("status") == "running":
                    stage["status"] = "failed"
                    stage["error"] = {"code": "E_SERVICE_RESTART",
                                      "message": "服务重启时任务中断"}
                    stage["finished_at"] = _now()
                    changed = True
            if job.get("status") in ("running", "queued"):
                if not any(s.get("status") == "failed" for s in job.get("stages", [])):
                    target = next((s for s in job.get("stages", [])
                                   if s.get("name") == "parse"), None)
                    if target is not None:
                        target["status"] = "failed"
                        target["error"] = {"code": "E_SERVICE_RESTART",
                                           "message": "服务重启时任务中断"}
                        target["finished_at"] = _now()
                job["status"] = "partial" if self._has_result(job) else "failed"
                job["error"] = {"code": "E_SERVICE_RESTART",
                                "message": "服务重启时任务中断，可重试"}
                job["interrupted"] = True
                changed = True
            job["status_label"] = JOB_STATUS_LABELS.get(job["status"], job["status"])
            self.jobs[job["id"]] = job
            if changed:
                self._save(job)

    def _has_result(self, job: dict) -> bool:
        return any(stage.get("status") == "done" and stage.get("name") != "upload"
                   for stage in job.get("stages", []))

    # ---------------------------------------------------------------- worker
    def start(self):
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def stop(self):
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=3)

    def _loop(self):
        while not self._stop.is_set():
            try:
                job_id = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.run_job(job_id)
            finally:
                self.queue.task_done()

    # ---------------------------------------------------------------- create
    def _validate_wechat_content(self, path: Path, scope: dict):
        if not scope:
            raise UploadError("E_WECHAT_SCOPE_REQUIRED", "微信资料缺少用户选择范围")
        for key in ("date_from", "date_to"):
            if not scope.get(key):
                raise UploadError("E_WECHAT_SCOPE_INVALID", "微信导入范围缺少日期")
        try:
            text = _decode_text(path)
        except OSError:
            return
        stamps = []
        for match in WECHAT_TIME.finditer(text):
            y, m, d, _hh, _mm = map(int, match.groups())
            stamps.append(f"{y:04d}-{m:02d}-{d:02d}")
        outside = [s for s in stamps if s < scope["date_from"] or s > scope["date_to"]]
        if outside:
            raise UploadError("E_WECHAT_OUT_OF_SCOPE",
                              f"文件包含导入范围外的消息：{outside[0]}", 422)

    def submit(self, source_type: str, file_name: str, tmp_path: Path,
               customer_id: str = "", project_id: str = "",
               wechat_scope: dict | None = None,
               idempotency_key: str | None = None) -> tuple[dict, bool]:
        if source_type not in ALLOWED:
            raise UploadError("E_SOURCE_TYPE", "来源类型只能是 file / email / chat / wechat")
        name = sanitize_name(file_name)
        ext = Path(name).suffix.lower()
        if ext not in ALLOWED[source_type]:
            raise UploadError("E_FILE_TYPE",
                              f"{source_type} 不接受 {ext or '无扩展名'} 文件", 415)
        size = tmp_path.stat().st_size
        if size <= 0:
            raise UploadError("E_EMPTY_FILE", "文件为空")
        if size > self.max_bytes:
            raise UploadError("E_FILE_TOO_LARGE",
                              f"文件超过 {self.max_bytes // (1024 * 1024) or 1} MB 上限", 413)
        with tmp_path.open("rb") as fh:
            head = fh.read(8)
            digest_obj = hashlib.sha256()
            fh.seek(0)
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                digest_obj.update(chunk)
        digest = digest_obj.hexdigest()
        if ext == ".pdf" and not head.startswith(b"%PDF-"):
            raise UploadError("E_FILE_TYPE", "扩展名为 PDF 但内容不是 PDF", 415)

        scope_key = json.dumps(wechat_scope or {}, ensure_ascii=False, sort_keys=True)
        if source_type == "wechat":
            self._validate_wechat_content(tmp_path, wechat_scope or {})
        with self.lock:
            if idempotency_key:
                for job in self.jobs.values():
                    if job.get("idempotency_key") == idempotency_key:
                        if job.get("sha256") != digest:
                            raise UploadError(
                                "E_IDEMPOTENCY_CONFLICT",
                                "同一幂等键对应了不同文件，拒绝复用", 409)
                        return copy.deepcopy(job), True
            for job in self.jobs.values():
                if (job["sha256"] == digest and job["source_type"] == source_type
                        and job.get("customer_id", "") == customer_id
                        and job.get("project_id", "") == project_id
                        and job.get("scope_key", "") == scope_key
                        and job["status"] != "cancelled"):
                    return copy.deepcopy(job), True

            job_id = "J" + uuid.uuid4().hex[:10]
            target_dir = self.uploads_dir / job_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / name
            tmp_path.replace(target)

            job = {
                "id": job_id,
                "created_at": _now(),
                "updated_at": _now(),
                "status": "queued",
                "status_label": JOB_STATUS_LABELS["queued"],
                "source_type": source_type,
                "file_name": name,
                "size": size,
                "sha256": digest,
                "customer_id": customer_id,
                "project_id": project_id,
                "wechat_scope": wechat_scope,
                "scope_key": scope_key,
                "idempotency_key": idempotency_key,
                "stages": self._initial_stages(source_type),
                "result": {},
                "error": None,
                "cancel_requested": False,
                "duplicate": False,
                "interrupted": False,
            }
            job["stages"][0]["detail"] = {"bytes": size}
            self.adjust_stages(job)
            self.jobs[job_id] = job
            self._save(job)
        self.queue.put(job_id)
        return copy.deepcopy(job), False

    def _initial_stages(self, source_type: str) -> list[dict]:
        stages = []
        for name in STAGES:
            if name == "upload":
                stages.append(self._stage(name, "done", detail={"bytes": None}))
            elif name == "parse":
                stages.append(self._stage(name, "pending"))
            elif name == "transcribe":
                stages.append(self._stage(
                    name, "pending" if source_type in ("file",) else "skipped",
                    skip_kind="not_applicable",
                    reason="该资料不需要转写"))
            elif name == "ocr":
                stages.append(self._stage(
                    name, "pending" if source_type in ("file",) else "skipped",
                    skip_kind="not_applicable",
                    reason="该资料不需要 OCR"))
            else:
                stages.append(self._stage(name, "pending"))
        return stages

    @staticmethod
    def _stage(name: str, status: str, **kwargs) -> dict:
        stage = {"name": name, "label": STAGE_LABELS[name], "status": status,
                 "started_at": None, "finished_at": None,
                 "error": None, "skip_kind": None, "reason": None}
        stage.update(kwargs)
        return stage

    def adjust_stages(self, job: dict):
        """Set applicability from the actual file kind."""
        kind = source_kind(job["file_name"])
        for stage in job["stages"]:
            if stage["name"] == "transcribe":
                applicable = kind == "audio"
                if not applicable and stage["status"] == "pending":
                    stage.update({"status": "skipped", "skip_kind": "not_applicable",
                                  "reason": "非音频资料，无需转写"})
            elif stage["name"] == "ocr":
                applicable = kind in ("image", "pdf")
                if not applicable and stage["status"] == "pending":
                    stage.update({"status": "skipped", "skip_kind": "not_applicable",
                                  "reason": "非图片/PDF，无需 OCR"})
            elif stage["name"] == "match":
                if not job.get("customer_id") and not job.get("project_id"):
                    stage.update({"status": "skipped", "skip_kind": "not_applicable",
                                  "reason": "未选择客户/项目"})

    # ---------------------------------------------------------------- run
    def run_job(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise UploadError("E_JOB_NOT_FOUND", "任务不存在", 404)
            if job["status"] == "cancelled":
                return copy.deepcopy(job)
            if job["status"] not in ("queued", "failed", "partial", "cancelled"):
                return copy.deepcopy(job)
            if job.get("cancel_requested"):
                self._cancel_remaining(job)
                self._save(job)
                return copy.deepcopy(job)
            job["status"] = "running"
            job["status_label"] = JOB_STATUS_LABELS["running"]
            job["error"] = None
            self._save(job)

        for stage in job["stages"]:
            if stage["status"] != "pending":
                continue
            with self.lock:
                job = self.jobs[job_id]
                if job.get("cancel_requested"):
                    self._cancel_remaining(job)
                    self._save(job)
                    return copy.deepcopy(job)
                stage = next(s for s in job["stages"] if s["name"] == stage["name"])
                stage["status"] = "running"
                stage["started_at"] = _now()
                stage["error"] = None
                self._save(job)
            try:
                output = self._execute(job, stage["name"])
            except StageUnavailable as exc:
                with self.lock:
                    job = self.jobs[job_id]
                    stage = next(s for s in job["stages"] if s["name"] == stage["name"])
                    stage.update({"status": "skipped", "skip_kind": "unavailable",
                                  "reason": exc.message, "error": None,
                                  "finished_at": _now()})
                    self._save(job)
                continue
            except StageFailure as exc:
                with self.lock:
                    job = self.jobs[job_id]
                    stage = next(s for s in job["stages"] if s["name"] == stage["name"])
                    stage.update({"status": "failed", "finished_at": _now(),
                                  "error": {"code": exc.code, "message": exc.message}})
                    job["status"] = "partial" if self._has_result(job) else "failed"
                    job["status_label"] = JOB_STATUS_LABELS[job["status"]]
                    job["error"] = {"code": exc.code, "message": exc.message}
                    self._save(job)
                return copy.deepcopy(job)
            except Exception as exc:  # noqa: BLE001
                with self.lock:
                    job = self.jobs[job_id]
                    stage = next(s for s in job["stages"] if s["name"] == stage["name"])
                    stage.update({"status": "failed", "finished_at": _now(),
                                  "error": {"code": "E_STAGE_UNKNOWN",
                                            "message": type(exc).__name__}})
                    job["status"] = "partial" if self._has_result(job) else "failed"
                    job["status_label"] = JOB_STATUS_LABELS[job["status"]]
                    job["error"] = {"code": "E_STAGE_UNKNOWN",
                                    "message": type(exc).__name__}
                    self._save(job)
                return copy.deepcopy(job)

            with self.lock:
                job = self.jobs[job_id]
                stage = next(s for s in job["stages"] if s["name"] == stage["name"])
                stage.update({"status": "done", "finished_at": _now(),
                              "output": output, "error": None})
                job["result"][stage["name"]] = output
                self._save(job)

        with self.lock:
            job = self.jobs[job_id]
            if job.get("cancel_requested"):
                self._cancel_remaining(job)
            else:
                unavailable = any(s.get("skip_kind") == "unavailable"
                                  for s in job["stages"])
                job["status"] = "partial" if unavailable else "completed"
            job["status_label"] = JOB_STATUS_LABELS[job["status"]]
            job["updated_at"] = _now()
            self._save(job)
            return copy.deepcopy(job)

    def _execute(self, job: dict, stage: str):
        if stage == "match":
            return self.processor.match(job)
        path = self.uploads_dir / job["id"] / job["file_name"]
        return getattr(self.processor, stage)(job, path)

    def _cancel_remaining(self, job: dict):
        for stage in job["stages"]:
            if stage["status"] in ("pending", "running"):
                stage["status"] = "cancelled"
                stage["finished_at"] = _now()
                stage["reason"] = "用户取消，已完成结果保留"
        job["status"] = "cancelled"
        job["status_label"] = JOB_STATUS_LABELS["cancelled"]

    # ---------------------------------------------------------------- actions
    def cancel(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise UploadError("E_JOB_NOT_FOUND", "任务不存在", 404)
            if job["status"] not in ("queued", "running"):
                raise UploadError("E_JOB_STATE", "当前状态不能取消")
            job["cancel_requested"] = True
            if job["status"] == "queued":
                self._cancel_remaining(job)
                self._save(job)
            return copy.deepcopy(job)

    def retry(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise UploadError("E_JOB_NOT_FOUND", "任务不存在", 404)
            if job["status"] not in ("failed", "partial", "cancelled"):
                raise UploadError("E_JOB_STATE", "当前状态不能重试")
            resume = False
            for stage in job["stages"]:
                if resume or stage["status"] in ("failed", "cancelled") or \
                        (stage["status"] == "skipped" and stage.get("skip_kind") == "unavailable"):
                    stage["status"] = "pending"
                    stage["skip_kind"] = None
                    stage["reason"] = None
                    stage["error"] = None
                    stage["started_at"] = None
                    stage["finished_at"] = None
                    resume = True
            if not resume:
                raise UploadError("E_NOTHING_TO_RETRY", "没有可重试的阶段")
            job["status"] = "queued"
            job["status_label"] = JOB_STATUS_LABELS["queued"]
            job["error"] = None
            job["cancel_requested"] = False
            job["interrupted"] = False
            self._save(job)
        self.queue.put(job_id)
        return copy.deepcopy(job)

    # ---------------------------------------------------------------- query
    def get(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise UploadError("E_JOB_NOT_FOUND", "任务不存在", 404)
            return copy.deepcopy(job)

    def list_jobs(self) -> list[dict]:
        with self.lock:
            jobs = list(self.jobs.values())
        jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
        return [copy.deepcopy(j) for j in jobs]
