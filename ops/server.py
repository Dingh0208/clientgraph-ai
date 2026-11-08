# -*- coding: utf-8 -*-
"""Single-owner web server: static prototype, settings, diagnostics and auth.

Deployment rule:
- loopback-only use may stay passwordless;
- any LAN/internet-reachable bind must verify the owner password first;
- there is exactly one owner; no teams, roles or tenants.

Run:
    python -m ops.server --port 8123
    python -m ops.server --host 0.0.0.0 --port 8123
    python -m ops.server --set-password
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .auth import LoginLimiter, is_loopback
from .diagnostics import get_log, run_checks, start_component, stop_component
from .secure_store import SecureSettings, SecureStoreError, app_version
from .uploads import UploadError, UploadManager, parse_wechat_scope

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"
SESSION_MAX_AGE = 12 * 3600

# Test-visible side-effect counters. Settings operations must never move
# email_fetch or model_call; only an explicit live connection test may probe.
SIDE_EFFECTS = {"email_fetch": 0, "model_call": 0, "model_probe": 0}


def build_info() -> dict:
    import os
    import json as _json
    info = {"version": app_version(), "build_id": os.environ.get("CG_BUILD_ID", "dev"),
            "commit": os.environ.get("CG_BUILD_COMMIT", "unknown"), "built_at": None}
    manifest = ROOT / "BUILD-MANIFEST.json"
    if manifest.exists():
        try:
            data = _json.loads(manifest.read_text(encoding="utf-8"))
            info["build_id"] = os.environ.get("CG_BUILD_ID") or data.get("build_id", info["build_id"])
            info["commit"] = data.get("commit", info["commit"])
            info["built_at"] = data.get("built_at")
            info["version"] = data.get("version", info["version"])
        except (OSError, ValueError):
            pass
    return info


class RequestError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def auth_required_for(host: str, require_auth: bool) -> bool:
    return bool(require_auth) or not is_loopback(host)


def make_handler(store: SecureSettings, auth_required: bool,
                 secure_cookie: bool = False,
                 limiter: LoginLimiter | None = None,
                 uploads: UploadManager | None = None):
    limiter = limiter or LoginLimiter()

    class Handler(SimpleHTTPRequestHandler):
        upload_manager = uploads
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(PROTOTYPE), **kwargs)

        # ------------------------------------------------------------ io
        def _json(self, payload: dict, status: int = 200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, code: str, message: str, status: int = 400):
            self._json({"error": {"code": code, "message": message}}, status)

        def _discard_body(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if 0 < length <= 64 * 1024:
                self.rfile.read(length)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                raise RequestError("E_EMPTY_BODY", "请求体为空")
            if length > 64 * 1024:
                raise RequestError("E_BODY_TOO_LARGE", "请求体过大", 413)
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise RequestError("E_INVALID_JSON", "请求体不是有效 JSON")
            if not isinstance(data, dict):
                raise RequestError("E_INVALID_JSON", "请求体必须是对象")
            return data

        def _read_login(self) -> dict:
            ctype = (self.headers.get("Content-Type") or "").lower()
            length = int(self.headers.get("Content-Length") or 0)
            if length > 64 * 1024:
                raise RequestError("E_BODY_TOO_LARGE", "请求体过大", 413)
            raw = self.rfile.read(length) if length > 0 else b""
            if "application/json" in ctype:
                try:
                    data = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    raise RequestError("E_INVALID_JSON", "登录请求格式不正确")
                return data if isinstance(data, dict) else {}
            form = parse_qs(raw.decode("utf-8", "ignore"))
            return {k: (v[0] if v else "") for k, v in form.items()}

        def _page(self, name: str, extra: dict | None = None):
            path = PROTOTYPE / name
            if not path.exists():
                self._error("E_PAGE_NOT_FOUND", "页面不存在", 404)
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if extra:
                for key, value in extra.items():
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def send_header(self, keyword, value):
            if keyword.lower() == "cache-control":
                self._cache_sent = True
            super().send_header(keyword, value)

        def end_headers(self):
            if not getattr(self, "_cache_sent", False):
                self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            super().end_headers()

        # ------------------------------------------------------------ auth
        def _client_ip(self) -> str:
            return self.client_address[0] if self.client_address else "unknown"

        def _token(self) -> str | None:
            raw = self.headers.get("Cookie") or ""
            for part in raw.split(";"):
                key, _, value = part.strip().partition("=")
                if key == "cg_session":
                    return value
            return None

        def _authorized(self) -> bool:
            return store.verify_token(self._token())

        def _public(self, path: str) -> bool:
            return path in ("/login", "/api/health", "/api/auth/login")

        def _guard(self, path: str) -> bool:
            if not auth_required or self._authorized() or self._public(path):
                return True
            self._discard_body()
            if path.startswith("/api/"):
                self._error("E_AUTH_REQUIRED", "请先登录", 401)
            else:
                target = quote(path, safe="/")
                self.send_response(302)
                self.send_header("Location", f"/login?next={target}")
                self.send_header("Content-Length", "0")
                self.end_headers()
            return False

        def _csrf_ok(self) -> bool:
            if (self.headers.get("X-Requested-With") or "") != "XMLHttpRequest":
                return False
            origin = self.headers.get("Origin")
            if origin:
                host = self.headers.get("Host") or ""
                if urlparse(origin).netloc != host:
                    return False
            return True

        def _set_session_cookie(self, token: str):
            parts = [f"cg_session={token}", "Path=/", "HttpOnly",
                     "SameSite=Lax", f"Max-Age={SESSION_MAX_AGE}"]
            if secure_cookie:
                parts.append("Secure")
            self.send_header("Set-Cookie", "; ".join(parts))

        def _clear_session_cookie(self):
            parts = ["cg_session=", "Path=/", "HttpOnly", "SameSite=Lax",
                     "Max-Age=0", "Expires=Thu, 01 Jan 1970 00:00:00 GMT"]
            if secure_cookie:
                parts.append("Secure")
            self.send_header("Set-Cookie", "; ".join(parts))

        # ------------------------------------------------------------ GET
        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/api/version":
                self._json(build_info())
                return
            if path == "/api/health":
                info = build_info()
                self._json({"ok": True, "service": "clientgraph-ops",
                            "auth_required": auth_required,
                            "version": info["version"], "build_id": info["build_id"],
                            "commit": info["commit"], "built_at": info["built_at"]})
                return
            if not self._guard(path):
                return

            if path == "/login":
                if self._authorized():
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self._page("login.html", {"Content-Security-Policy":
                                              "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                              "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                                              "img-src 'self' data:"})
                return
            if path in ("/settings", "/settings.html"):
                self._page("settings.html", {"Content-Security-Policy":
                                             "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                             "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                                             "img-src 'self' data:"})
                return
            if path == "/upload":
                self._page("upload.html", {"Content-Security-Policy":
                                           "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                           "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                                           "img-src 'self' data:"})
                return
            if path == "/api/jobs":
                if self.upload_manager is None:
                    self._error("E_UPLOAD_DISABLED", "上传任务未启用", 404)
                    return
                self._json({"jobs": self.upload_manager.list_jobs()})
                return
            if path.startswith("/api/jobs/"):
                if self.upload_manager is None:
                    self._error("E_UPLOAD_DISABLED", "上传任务未启用", 404)
                    return
                job_id = path.split("/")[3]
                try:
                    self._json(self.upload_manager.get(job_id))
                except UploadError as exc:
                    self._error(exc.code, exc.message, exc.status)
                return
            if path == "/api/settings":
                self._json(store.public())
                return
            if path == "/api/settings/backup":
                payload = store.backup()
                body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'attachment; filename="clientgraph-settings-backup.json"')
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/auth/session":
                self._json({"authenticated": self._authorized() or not auth_required,
                            "auth_required": auth_required, "mode": "single_owner"})
                return
            if path == "/api/diagnostics":
                self._json(run_checks())
                return
            if path.startswith("/api/components/") and path.endswith("/log"):
                cid = path.split("/")[3]
                qs = parse_qs(urlparse(self.path).query)
                lines = int((qs.get("lines") or ["60"])[0])
                self._json({"id": cid, "content": get_log(cid, lines)})
                return
            if path.startswith("/api/"):
                self._error("E_NOT_FOUND", "接口不存在", 404)
                return
            super().do_GET()

        # ------------------------------------------------------------ POST
        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/api/auth/login":
                self._login()
                return
            if not self._guard(path):
                return
            if not self._csrf_ok():
                self._discard_body()
                self._error("E_CSRF", "缺少同源校验头", 403)
                return
            if path == "/api/uploads":
                self._upload()
                return
            if path == "/api/auth/logout":
                self.send_response(200)
                self._clear_session_cookie()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                body = b'{"ok": true}'
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/settings/test":
                try:
                    data = self._read_json()
                    target = str(data.get("target") or "")
                    live = bool(data.get("live"))
                    result = store.test_model(target, live=live)
                    if live:
                        SIDE_EFFECTS["model_probe"] += 1
                    self._json(result, 200 if result.get("ok") else 400)
                except RequestError as exc:
                    self._error(exc.code, exc.message, exc.status)
                except SecureStoreError as exc:
                    self._error(exc.code, exc.message, 400)
                return

            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "jobs" \
                    and parts[3] in ("retry", "cancel"):
                if self.upload_manager is None:
                    self._error("E_UPLOAD_DISABLED", "上传任务未启用", 404)
                    return
                try:
                    if parts[3] == "retry":
                        self._json(self.upload_manager.retry(parts[2]))
                    else:
                        self._json(self.upload_manager.cancel(parts[2]))
                except UploadError as exc:
                    self._error(exc.code, exc.message, exc.status)
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "components" \
                    and parts[3] in ("start", "retry", "stop"):
                if parts[3] == "stop":
                    self._json(stop_component(parts[2]))
                else:
                    self._json(start_component(parts[2]))
                return
            self._error("E_NOT_FOUND", "接口不存在", 404)

        # ------------------------------------------------------------ PUT
        def do_PUT(self):
            path = urlparse(self.path).path
            if not self._guard(path):
                return
            if not self._csrf_ok():
                self._discard_body()
                self._error("E_CSRF", "缺少同源校验头", 403)
                return
            if path == "/api/settings":
                try:
                    data = self._read_json()
                    self._json(store.update(data))
                except RequestError as exc:
                    self._error(exc.code, exc.message, exc.status)
                except SecureStoreError as exc:
                    self._error(exc.code, exc.message, 400)
                return
            self._error("E_NOT_FOUND", "接口不存在", 404)

        # ------------------------------------------------------------ upload
        def _upload(self):
            if self.upload_manager is None:
                self._error("E_UPLOAD_DISABLED", "上传任务未启用", 404)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0:
                self._error("E_LENGTH_REQUIRED", "缺少 Content-Length", 411)
                return
            if length > self.upload_manager.max_bytes:
                self._error("E_FILE_TOO_LARGE", "文件超过大小上限", 413)
                return

            name = unquote(self.headers.get("X-File-Name") or "upload.bin")
            source_type = (self.headers.get("X-Source-Type") or "file").strip().lower()
            customer_id = self.headers.get("X-Customer-Id") or ""
            project_id = self.headers.get("X-Project-Id") or ""
            idempotency = self.headers.get("X-Idempotency-Key")
            scope = None
            if source_type == "wechat":
                try:
                    scope = parse_wechat_scope(self.headers.get("X-Wechat-Scope"))
                except UploadError as exc:
                    self._discard_body()
                    self._error(exc.code, exc.message, exc.status)
                    return

            tmp = self.upload_manager.tmp_dir / ("up-" + uuid.uuid4().hex)
            written = 0
            try:
                with tmp.open("wb") as fh:
                    while written < length:
                        chunk = self.rfile.read(min(65536, length - written))
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > self.upload_manager.max_bytes:
                            raise UploadError("E_FILE_TOO_LARGE", "文件超过大小上限", 413)
                        fh.write(chunk)
                if written != length:
                    raise UploadError("E_UPLOAD_INCOMPLETE",
                                      f"上传中断：收到 {written} / {length} 字节", 400)
                job, duplicate = self.upload_manager.submit(
                    source_type, name, tmp, customer_id=customer_id,
                    project_id=project_id, wechat_scope=scope,
                    idempotency_key=idempotency)
                job["duplicate"] = duplicate
                self._json(job, 200 if duplicate else 201)
            except UploadError as exc:
                self._error(exc.code, exc.message, exc.status)
            except OSError as exc:
                self._error("E_UPLOAD_IO", f"上传写入失败：{type(exc).__name__}", 500)
            finally:
                if tmp.exists():
                    tmp.unlink()

        # ------------------------------------------------------------ login
        def _login(self):
            ip = self._client_ip()
            blocked, retry = limiter.blocked(ip)
            if blocked:
                self._discard_body()
                self._error("E_RATE_LIMITED",
                            f"尝试次数过多，请 {retry} 秒后再试", 429)
                return
            try:
                data = self._read_login()
            except RequestError as exc:
                self._error(exc.code, exc.message, exc.status)
                return
            password = str(data.get("password") or "")
            if not store.verify_owner(password):
                limiter.fail(ip)
                self._error("E_BAD_CREDENTIALS", "密码不正确", 401)
                return
            limiter.success(ip)
            token = store.issue_token()
            self.send_response(200)
            self._set_session_cookie(token)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = json.dumps({"ok": True, "auth_required": auth_required,
                               "mode": "single_owner"}, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            # Never log request lines: they can contain query strings or paths.
            pass

        def log_error(self, fmt, *args):
            pass

    return Handler


def create_server(host: str, port: int, store: SecureSettings,
                  require_auth: bool | None = None, secure_cookie: bool = False,
                  limiter: LoginLimiter | None = None,
                  uploads: UploadManager | None = None) -> ThreadingHTTPServer:
    required = auth_required_for(host, bool(require_auth))
    if required and not store.has_password():
        raise SecureStoreError(
            "E_AUTH_NOT_CONFIGURED",
            "该地址可被局域网或公网访问，必须先设置老板密码："
            "python -m ops.server --set-password")
    handler = make_handler(store, required, secure_cookie=secure_cookie,
                           limiter=limiter, uploads=uploads)
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--config-dir", default=None)
    parser.add_argument("--require-auth", action="store_true",
                        help="即使本地访问也要求登录（用于反向代理/测试）")
    parser.add_argument("--secure-cookie", action="store_true",
                        help="通过 HTTPS 提供服务时启用 Secure Cookie")
    parser.add_argument("--set-password", action="store_true")
    parser.add_argument("--login-max-attempts", type=int, default=5)
    parser.add_argument("--login-window", type=int, default=600)
    parser.add_argument("--max-upload-mb", type=int, default=50)
    args = parser.parse_args()

    try:
        store = SecureSettings(args.config_dir)
    except SecureStoreError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        sys.exit(2)

    if args.set_password:
        first = getpass.getpass("设置老板密码（至少 8 位）：")
        second = getpass.getpass("再输入一次：")
        if first != second:
            print("两次输入不一致", file=sys.stderr)
            sys.exit(1)
        try:
            store.set_password(first)
        except Exception as exc:  # noqa: BLE001
            print(f"设置失败：{exc}", file=sys.stderr)
            sys.exit(1)
        print(f"密码已保存到 {store.path}（文件权限 600）")
        return

    required = auth_required_for(args.host, args.require_auth)
    if required and not store.has_password():
        print("拒绝启动：该地址可被局域网或公网访问，必须先设置密码。", file=sys.stderr)
        print("  python -m ops.server --set-password", file=sys.stderr)
        sys.exit(2)

    limiter = LoginLimiter(args.login_max_attempts, args.login_window)
    uploads = UploadManager(store.dir / "data",
                            max_bytes=max(1, args.max_upload_mb) * 1024 * 1024,
                            auto_start=True)
    try:
        server = create_server(args.host, args.port, store,
                               require_auth=required,
                               secure_cookie=args.secure_cookie, limiter=limiter,
                               uploads=uploads)
    except SecureStoreError as exc:
        uploads.stop()
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        sys.exit(2)

    mode = "single-owner + password" if required else "single-owner + local-only"
    print(f"ClientGraph AI ops server: http://{args.host}:{args.port}/")
    print(f"access: {mode}")
    print(f"config: {store.path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        uploads.stop()
        server.server_close()


if __name__ == "__main__":
    main()
