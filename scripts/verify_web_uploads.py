# -*- coding: utf-8 -*-
"""Verify web uploads and server-side staged jobs.

Covers limits/types, stage status, resume after leaving the page, retry/cancel,
service restart, duplicate submit, interrupted upload, partial failure, and the
WeChat selection-scope rule.
"""
from __future__ import annotations

import base64
import http.client
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ops.server as server_module  # noqa: E402
from ops.auth import LoginLimiter  # noqa: E402
from ops.secure_store import SecureSettings  # noqa: E402
from ops.uploads import (  # noqa: E402
    LocalProcessor, StageFailure, UploadError, UploadManager, parse_wechat_scope,
)

CHECKS = {}


def ensure(key, cond, detail=None):
    CHECKS[key] = bool(cond)
    if not cond:
        raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))


class DemoProcessor:
    def __init__(self):
        self.calls = []

    def parse(self, job, path):
        self.calls.append("parse")
        text = path.read_bytes().decode("utf-8", "ignore")
        return {"chars": len(text), "preview": text[:120], "format": path.suffix.lstrip(".")}

    def transcribe(self, job, path):
        self.calls.append("transcribe")
        return {"text": "演示转写"}

    def ocr(self, job, path):
        self.calls.append("ocr")
        return {"text": "演示 OCR"}

    def match(self, job):
        self.calls.append("match")
        return {"customer_id": job.get("customer_id"), "project_id": job.get("project_id")}


class FlakyProcessor(DemoProcessor):
    def __init__(self):
        super().__init__()
        self.fail_ocr = True

    def ocr(self, job, path):
        self.calls.append("ocr")
        if self.fail_ocr:
            raise StageFailure("E_OCR_ENGINE", "模拟 OCR 失败")
        return {"text": "重试后的 OCR"}


class SlowProcessor(DemoProcessor):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def parse(self, job, path):
        self.started.set()
        self.release.wait(timeout=8)
        return super().parse(job, path)


def read_raw(sock, timeout=3.0) -> str:
    sock.settimeout(timeout)
    chunks = []
    while True:
        try:
            chunk = sock.recv(8192)
        except socket.timeout:
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks).decode("latin-1", "ignore")


class Client:
    def __init__(self, port):
        self.port = port
        self.cookie = None

    def _conn(self):
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)

    def request(self, method, path, body=None, headers=None, use_cookie=True,
                raw: bytes | None = None):
        conn = self._conn()
        hdrs = dict(headers or {})
        if use_cookie and self.cookie:
            hdrs["Cookie"] = self.cookie
        if raw is not None:
            conn.request(method, path, body=raw, headers=hdrs)
        else:
            payload = body
            if isinstance(body, (dict, list)):
                payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
                hdrs.setdefault("Content-Type", "application/json")
            conn.request(method, path, body=payload, headers=hdrs)
        response = conn.getresponse()
        data = response.read()
        out = {k.lower(): v for k, v in response.getheaders()}
        conn.close()
        return response.status, out, data

    def login(self, password):
        status, headers, _ = self.request(
            "POST", "/api/auth/login", {"password": password}, use_cookie=False)
        if status == 200:
            self.cookie = headers.get("set-cookie", "").split(";", 1)[0]
        return status

    def upload(self, name, data: bytes, source="file", customer="", project="",
               scope=None, idem=None):
        headers = {
            "X-File-Name": quote(name, safe=""),
            "X-Source-Type": source,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/octet-stream",
        }
        if customer:
            headers["X-Customer-Id"] = customer
        if project:
            headers["X-Project-Id"] = project
        if scope is not None:
            raw = json.dumps(scope, ensure_ascii=False).encode("utf-8")
            headers["X-Wechat-Scope"] = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        if idem:
            headers["X-Idempotency-Key"] = idem
        return self.request("POST", "/api/uploads", raw=data, headers=headers)


class Server:
    def __init__(self, store, manager, require_auth):
        self.httpd = server_module.create_server(
            "127.0.0.1", 0, store, require_auth=require_auth,
            uploads=manager)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def wait_job(client, job_id, statuses, timeout=15):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status, _, body = client.request("GET", f"/api/jobs/{job_id}")
        if status == 200:
            last = json.loads(body)
            if last["status"] in statuses:
                return last
        time.sleep(0.08)
    raise AssertionError(f"job {job_id} did not reach {statuses}: {last}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cg-upload-") as tmp:
        tmp = Path(tmp)

        # Unit: scope and limits.
        try:
            parse_wechat_scope(None)
            ensure("wechat_scope_required", False)
        except UploadError as exc:
            ensure("wechat_scope_required", exc.code == "E_WECHAT_SCOPE_REQUIRED")
        bad_scope = base64.urlsafe_b64encode(json.dumps({
            "selected_by_user": False, "contact_id": "c", "conversation_id": "v",
            "date_from": "2026-09-01", "date_to": "2026-09-30"}).encode()).decode().rstrip("=")
        try:
            parse_wechat_scope(bad_scope)
            ensure("wechat_scope_unconfirmed", False)
        except UploadError as exc:
            ensure("wechat_scope_unconfirmed", exc.code == "E_WECHAT_SCOPE_INVALID")

        def temp_file(name, data: bytes) -> Path:
            path = tmp / name
            path.write_bytes(data)
            return path

        unit = UploadManager(tmp / "unit", max_bytes=10, auto_start=False)
        try:
            unit.submit("file", "bad.exe", temp_file("bad.exe", b"MZ"))
            ensure("type_rejected", False)
        except UploadError as exc:
            ensure("type_rejected", exc.code == "E_FILE_TYPE")
        try:
            unit.submit("file", "big.txt", temp_file("big.txt", b"x" * 20))
            ensure("size_rejected", False)
        except UploadError as exc:
            ensure("size_rejected", exc.code == "E_FILE_TOO_LARGE")
        try:
            unit.submit("file", "empty.txt", temp_file("empty.txt", b""))
            ensure("empty_rejected", False)
        except UploadError as exc:
            ensure("empty_rejected", exc.code == "E_EMPTY_FILE")

        # Unit: stage plan and retry from the first failed stage.
        flaky = FlakyProcessor()
        manager = UploadManager(tmp / "retry", processor=flaky, auto_start=False)
        job, dup = manager.submit(
            "file", "photo.png", temp_file("photo.png", b"fakepng"),
            customer_id="c1", project_id="p1")
        ensure("created_once", not dup)
        job = manager.run_job(job["id"])
        ensure("partial_status", job["status"] == "partial", job["status"])
        ensure("parse_kept", job["result"].get("parse") is not None)
        ensure("ocr_failed", next(s for s in job["stages"] if s["name"] == "ocr")["status"] == "failed")
        flaky.fail_ocr = False
        manager.retry(job["id"])
        job = manager.run_job(job["id"])
        ensure("retry_completed", job["status"] == "completed", job["status"])
        ensure("retry_only_failed_stage", flaky.calls.count("parse") == 1
               and flaky.calls.count("ocr") == 2, flaky.calls)

        # Unit: duplicate and idempotency.
        manager2 = UploadManager(tmp / "dup", processor=DemoProcessor(), auto_start=False)
        first, _ = manager2.submit("file", "same.txt", temp_file("same1.txt", b"same"))
        second, duplicate = manager2.submit("file", "same.txt", temp_file("same2.txt", b"same"))
        ensure("duplicate_detected", duplicate and second["id"] == first["id"])
        third, duplicate3 = manager2.submit(
            "file", "other.txt", temp_file("other.txt", b"other"), idempotency_key="k1")
        try:
            manager2.submit("file", "other2.txt", temp_file("other2.txt", b"different"),
                            idempotency_key="k1")
            ensure("idempotency_conflict", False)
        except UploadError as exc:
            ensure("idempotency_conflict", exc.code == "E_IDEMPOTENCY_CONFLICT")
        same, duplicate4 = manager2.submit(
            "file", "other3.txt", temp_file("other3.txt", b"other"), idempotency_key="k1")
        ensure("idempotency_key", duplicate4 and same["id"] == third["id"])

        # Unit: service restart marks interrupted stage failed, keeps results.
        restart_dir = tmp / "restart"
        old = UploadManager(restart_dir, processor=DemoProcessor(), auto_start=False)
        job, _ = old.submit("file", "restart.txt", temp_file("restart.txt", b"restart"))
        job["status"] = "running"
        parse_stage = next(s for s in job["stages"] if s["name"] == "parse")
        parse_stage["status"] = "running"
        old._save(job)
        new = UploadManager(restart_dir, processor=DemoProcessor(), auto_start=False)
        recovered = new.get(job["id"])
        ensure("restart_interrupted", recovered["status"] == "failed"
               and next(s for s in recovered["stages"] if s["name"] == "parse")["error"]["code"]
               == "E_SERVICE_RESTART")
        ensure("upload_kept", next(s for s in recovered["stages"] if s["name"] == "upload")["status"]
               == "done")
        new.retry(job["id"])
        recovered = new.run_job(job["id"])
        ensure("restart_retry", recovered["status"] == "completed")

        # HTTP instance with auth, local processor for real parse.
        store = SecureSettings(tmp / "auth", iterations=1000)
        store.set_password("test-password-123")
        http_manager = UploadManager(tmp / "http", processor=LocalProcessor(),
                                     max_bytes=1024 * 1024, auto_start=True)
        server = Server(store, http_manager, require_auth=True)
        api = Client(server.port)
        try:
            status, _, _ = api.request("GET", "/api/jobs", use_cookie=False)
            ensure("jobs_require_auth", status == 401)
            ensure("login_ok", api.login("test-password-123") == 200)
            status, _, page = api.request("GET", "/upload")
            html = page.decode("utf-8")
            ensure("upload_page", status == 200 and "上传任务" in html)
            ensure("stage_labels", all(t in html for t in ("上传", "解析", "转写", "OCR", "匹配")))
            ensure("no_auto_upload", "setInterval(upload" not in html)

            status, _, body = api.upload(
                "需求.txt", "一期先做扫码巡检".encode("utf-8"),
                customer="c1", project="p1")
            ensure("upload_created", status == 201, body[:200])
            job = json.loads(body)
            finished = wait_job(api, job["id"], {"completed", "partial", "failed"})
            stage_names = [s["name"] for s in finished["stages"]]
            ensure("stage_order", stage_names == ["upload", "parse", "transcribe", "ocr", "match"])
            ensure("text_completed", finished["status"] == "completed", finished)
            stage_map = {s["name"]: s["status"] for s in finished["stages"]}
            ensure("text_skips", stage_map["transcribe"] == "skipped"
                   and stage_map["ocr"] == "skipped" and stage_map["match"] == "done")
            ensure("parse_output", finished["result"]["parse"]["chars"] > 0)

            # Audio exercises the transcribe stage; OCR stays skipped.
            http_manager.processor = DemoProcessor()
            status, _, body = api.upload("call.mp3", b"fakeaudio", customer="c1")
            audio_job = wait_job(api, json.loads(body)["id"], {"completed"})
            audio_stages = {s["name"]: s["status"] for s in audio_job["stages"]}
            ensure("audio_transcribed", audio_stages["transcribe"] == "done"
                   and audio_stages["ocr"] == "skipped")
            http_manager.processor = LocalProcessor()

            # Re-enter from a new connection: job still queryable.
            again = Client(server.port)
            again.cookie = api.cookie
            status, _, body = again.request("GET", f"/api/jobs/{job['id']}")
            ensure("reenter_query", status == 200 and json.loads(body)["id"] == job["id"])
            status, _, body = again.request("GET", "/api/jobs")
            ensure("reenter_list", status == 200
                   and any(j["id"] == job["id"] for j in json.loads(body)["jobs"]))

            # Duplicate submit.
            status, _, body = api.upload(
                "需求.txt", "一期先做扫码巡检".encode("utf-8"),
                customer="c1", project="p1")
            duplicate = json.loads(body)
            ensure("duplicate_same_job", status == 200 and duplicate["duplicate"] is True
                   and duplicate["id"] == job["id"])

            # Type rejection.
            status, _, body = api.upload("virus.exe", b"MZ")
            ensure("http_type_rejected", status == 415
                   and json.loads(body)["error"]["code"] == "E_FILE_TYPE")

            # Large upload rejected from Content-Length before reading.
            sock = socket.create_connection(("127.0.0.1", server.port), timeout=10)
            request = (
                "POST /api/uploads HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                f"Cookie: {api.cookie}\r\n"
                "X-File-Name: big.txt\r\nX-Source-Type: file\r\n"
                "X-Requested-With: XMLHttpRequest\r\n"
                "Content-Length: 2097152\r\n\r\n"
            ).encode()
            sock.sendall(request)
            response = read_raw(sock)
            sock.close()
            ensure("http_size_rejected", " 413 " in response and "E_FILE_TOO_LARGE" in response,
                   response[:300])

            # Interrupted upload must not create a job.
            before = len(json.loads(api.request("GET", "/api/jobs")[2])["jobs"])
            sock = socket.create_connection(("127.0.0.1", server.port), timeout=10)
            request = (
                "POST /api/uploads HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                f"Cookie: {api.cookie}\r\n"
                "X-File-Name: cut.txt\r\nX-Source-Type: file\r\n"
                "X-Requested-With: XMLHttpRequest\r\n"
                "Content-Length: 100\r\n\r\n"
            ).encode()
            sock.sendall(request + b"only-ten!!")
            sock.shutdown(socket.SHUT_WR)
            response = read_raw(sock)
            sock.close()
            after = len(json.loads(api.request("GET", "/api/jobs")[2])["jobs"])
            ensure("interrupted_rejected", " 400 " in response and "E_UPLOAD_INCOMPLETE" in response)
            ensure("interrupted_no_job", before == after)

            # Email and chat parsing.
            eml = (b"From: sender@example.com\r\nTo: boss@example.com\r\n"
                   b"Subject: =?utf-8?b?5beh5qOA6ZyA5rGC?=\r\n"
                   b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
                   b"\xe5\xb7\xa1\xe6\xa3\x80\xe9\x9c\x80\xe6\xb1\x82")
            status, _, body = api.upload("mail.eml", eml, source="email", customer="c1")
            ensure("email_accepted", status == 201)
            mail_job = wait_job(api, json.loads(body)["id"], {"completed"})
            ensure("email_parsed", "subject" in mail_job["result"]["parse"])

            chat = "2026-09-05 10:00 张总：一期先做巡检\n2026-09-05 10:05 我：收到".encode("utf-8")
            status, _, body = api.upload("chat.txt", chat, source="chat", customer="c1")
            ensure("chat_accepted", status == 201)
            chat_job = wait_job(api, json.loads(body)["id"], {"completed"})
            ensure("chat_lines", chat_job["result"]["parse"]["lines"] >= 2)

            # WeChat: valid scope only; out-of-scope and missing scope rejected.
            scope = {"selected_by_user": True, "contact_id": "wx1",
                     "conversation_id": "conv1", "date_from": "2026-09-01",
                     "date_to": "2026-09-30"}
            status, _, body = api.upload("wechat.txt", chat, source="wechat", scope=scope)
            ensure("wechat_accepted", status == 201, body[:200])
            wait_job(api, json.loads(body)["id"], {"completed"})
            status, _, body = api.upload("wechat.txt", chat, source="wechat")
            ensure("wechat_scope_required", status == 400
                   and json.loads(body)["error"]["code"] == "E_WECHAT_SCOPE_REQUIRED")
            out_of_scope = chat + "\n2026-10-05 09:00 张总：范围外消息".encode("utf-8")
            status, _, body = api.upload("wechat-out.txt", out_of_scope,
                                         source="wechat", scope=scope)
            ensure("wechat_out_of_scope", status == 422
                   and json.loads(body)["error"]["code"] == "E_WECHAT_OUT_OF_SCOPE")

            # Partial failure, retry, completed results retained.
            flaky_http = FlakyProcessor()
            http_manager.processor = flaky_http
            status, _, body = api.upload("photo.png", b"fakepng", customer="c1")
            ensure("image_accepted", status == 201)
            failed_job = wait_job(api, json.loads(body)["id"], {"partial", "failed"})
            ensure("partial_failure", failed_job["status"] == "partial"
                   and failed_job["result"].get("parse") is not None)
            flaky_http.fail_ocr = False
            status, _, _ = api.request(
                "POST", f"/api/jobs/{failed_job['id']}/retry",
                headers={"X-Requested-With": "XMLHttpRequest"})
            ensure("retry_accepted", status == 200)
            retried = wait_job(api, failed_job["id"], {"completed", "failed"})
            ensure("retry_completed_http", retried["status"] == "completed")
            ensure("retry_kept_parse", flaky_http.calls.count("parse") == 1)

            # Cancel keeps the completed stage.
            slow = SlowProcessor()
            http_manager.processor = slow
            status, _, body = api.upload("slow.txt", b"slow", customer="c1")
            slow_job = json.loads(body)
            deadline = time.time() + 5
            while time.time() < deadline:
                current = json.loads(api.request("GET", f"/api/jobs/{slow_job['id']}")[2])
                if current["stages"][1]["status"] == "running":
                    break
                time.sleep(0.05)
            status, _, _ = api.request(
                "POST", f"/api/jobs/{slow_job['id']}/cancel",
                headers={"X-Requested-With": "XMLHttpRequest"})
            slow.release.set()
            cancelled = wait_job(api, slow_job["id"], {"cancelled"})
            ensure("cancel_status", cancelled["status"] == "cancelled")
            ensure("cancel_keeps_done", cancelled["result"].get("parse") is not None)

            http_manager.processor = DemoProcessor()
            status, _, _ = api.request(
                "POST", f"/api/jobs/{slow_job['id']}/retry",
                headers={"X-Requested-With": "XMLHttpRequest"})
            ensure("cancel_retry", status == 200)
            wait_job(api, slow_job["id"], {"completed"})

            status, _, body = api.request("GET", "/api/jobs/unknown")
            ensure("unknown_job", status == 404
                   and json.loads(body)["error"]["code"] == "E_JOB_NOT_FOUND")
        finally:
            server.stop()
            http_manager.stop()

        # Restart the HTTP service on the same data dir: completed jobs remain.
        manager2 = UploadManager(tmp / "http", processor=LocalProcessor(), auto_start=True)
        server2 = Server(store, manager2, require_auth=True)
        api2 = Client(server2.port)
        try:
            ensure("restart_login", api2.login("test-password-123") == 200)
            status, _, body = api2.request("GET", f"/api/jobs/{job['id']}")
            ensure("http_restart_query", status == 200
                   and json.loads(body)["status"] == "completed")
            status, _, page = api2.request("GET", "/upload")
            ensure("http_restart_page", status == 200
                   and "任务列表" in page.decode("utf-8"))
        finally:
            server2.stop()
            manager2.stop()

        evidence = {
            "schema": "clientgraph.web_uploads.evidence.v1",
            "checks": CHECKS,
            "all_passed": all(CHECKS.values()),
            "side_effects": dict(server_module.SIDE_EFFECTS),
        }
        out = ROOT / "evidence" / "web-uploads-2026-11-08.json"
        out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        for key, value in CHECKS.items():
            print(("PASS " if value else "FAIL ") + key)
        print("checks:", len(CHECKS), "passed:", sum(CHECKS.values()))
        print("evidence:", out)
        return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
