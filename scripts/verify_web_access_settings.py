# -*- coding: utf-8 -*-
"""Verify single-owner web access protection and the settings page.

Checks: local bypass, LAN/online auth, session cookie flags, CSRF, rate limits,
server-side-only model keys, six settings sections, explicit test action, and
that opening/saving settings never fetches email or calls a model.
"""
from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ops.server as server_module  # noqa: E402
from ops.auth import (  # noqa: E402
    LoginLimiter, SessionManager, hash_password, verify_password,
)
from ops.secure_store import SecureSettings  # noqa: E402

CHECKS = {}
SECRET = "test-key-not-real"


def ensure(key, cond, detail=None):
    CHECKS[key] = bool(cond)
    if not cond:
        raise AssertionError(f"{key} failed" + (f": {detail}" if detail else ""))


class Client:
    def __init__(self, port: int):
        self.port = port
        self.cookie = None

    def request(self, method: str, path: str, body=None, headers=None,
                use_cookie: bool = True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = dict(headers or {})
        if use_cookie and self.cookie:
            hdrs["Cookie"] = self.cookie
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=payload, headers=hdrs)
        response = conn.getresponse()
        data = response.read()
        out_headers = {k.lower(): v for k, v in response.getheaders()}
        conn.close()
        return response.status, out_headers, data

    def login(self, password: str):
        status, headers, data = self.request(
            "POST", "/api/auth/login", {"password": password}, use_cookie=False)
        if status == 200:
            raw = headers.get("set-cookie", "")
            self.cookie = raw.split(";", 1)[0]
        return status, headers, data


class Server:
    def __init__(self, store: SecureSettings, require_auth: bool,
                 secure_cookie: bool = False, limiter=None):
        self.httpd = server_module.create_server(
            "127.0.0.1", 0, store, require_auth=require_auth,
            secure_cookie=secure_cookie, limiter=limiter)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cg-web-") as tmp:
        store = SecureSettings(tmp, iterations=1000)
        store.set_password("correct-horse-9")
        store.data["settings"] = {
            "profile": {"display_name": "王老板", "email": "boss@example.com",
                        "timezone": "Asia/Shanghai", "language": "zh-CN"},
        }
        store.save()

        # Unit: password / session / limiter / binding.
        record = hash_password("another-pass-8", iterations=1000)
        ensure("password_hash_ok", verify_password("another-pass-8", record))
        ensure("password_hash_rejects", not verify_password("wrong-pass", record))
        sessions = SessionManager(store.data["session_secret"], epoch=1, ttl=60)
        token = sessions.issue(now=1000)
        ensure("session_valid", sessions.verify(token, now=1010))
        ensure("session_expired", not sessions.verify(token, now=1200))
        ensure("session_tampered", not sessions.verify(token[:-2] + "zz", now=1010))
        epoch_store = SecureSettings(Path(tmp) / "epoch", iterations=1000)
        epoch_store.set_password("first-password")
        old_token = epoch_store.issue_token()
        epoch_store.set_password("second-password")
        ensure("password_change_revokes", not epoch_store.verify_token(old_token))
        limiter = LoginLimiter(max_attempts=2, window_s=60)
        limiter.fail("1.2.3.4", now=10)
        limiter.fail("1.2.3.4", now=11)
        ensure("limiter_blocks", limiter.blocked("1.2.3.4", now=12)[0])
        limiter.success("1.2.3.4")
        ensure("limiter_resets", not limiter.blocked("1.2.3.4", now=12)[0])
        ensure("lan_requires_auth", server_module.auth_required_for("0.0.0.0", False))
        ensure("loopback_can_skip", not server_module.auth_required_for("127.0.0.1", False))

        no_pass = SecureSettings(Path(tmp) / "nopass", iterations=1000)
        try:
            server_module.create_server("0.0.0.0", 0, no_pass, require_auth=False)
            refused = False
        except Exception as exc:  # noqa: BLE001
            refused = getattr(exc, "code", "") == "E_AUTH_NOT_CONFIGURED"
        ensure("lan_without_password_refused", refused)

        # LAN/online-like instance: auth is forced even on loopback.
        auth_server = Server(store, require_auth=True, secure_cookie=True)
        api = Client(auth_server.port)
        try:
            status, _, body = api.request("GET", "/api/health", use_cookie=False)
            health = json.loads(body)
            ensure("health_public", status == 200 and health["auth_required"] is True)

            status, headers, _ = api.request("GET", "/", use_cookie=False)
            ensure("root_redirects_login", status == 302
                   and headers.get("location", "").startswith("/login?next="))
            status, headers, _ = api.request("GET", "/settings", use_cookie=False)
            ensure("settings_redirects_login", status == 302)

            status, _, body = api.request("GET", "/api/settings", use_cookie=False)
            ensure("settings_api_401", status == 401
                   and json.loads(body)["error"]["code"] == "E_AUTH_REQUIRED")
            status, _, _ = api.request("GET", "/api/settings/backup", use_cookie=False)
            ensure("backup_api_401", status == 401)
            status, _, _ = api.request("GET", "/api/diagnostics", use_cookie=False)
            ensure("diagnostics_api_401", status == 401)
            status, _, _ = api.request("GET", "/api/components/asr/log", use_cookie=False)
            ensure("component_log_401", status == 401)

            status, _, _ = api.request("POST", "/api/auth/login",
                                       {"password": "wrong-password"}, use_cookie=False)
            ensure("wrong_password_401", status == 401)

            status, headers, _ = api.login("correct-horse-9")
            cookie = headers.get("set-cookie", "")
            ensure("login_ok", status == 200)
            ensure("cookie_flags", "HttpOnly" in cookie and "SameSite=Lax" in cookie
                   and "Secure" in cookie and "Path=/" in cookie)

            status, _, body = api.request("GET", "/api/settings")
            settings = json.loads(body)
            ensure("settings_authorized", status == 200)
            ensure("settings_sections", all(k in settings for k in
                   ("profile", "import", "models", "notifications", "privacy", "version")))
            ensure("version_info", settings["version"]["app"] == "0.4.0"
                   and settings["version"]["auth_mode"] == "single_owner")
            ensure("no_key_initially",
                   settings["models"]["text_key"]["configured"] is False)

            status, headers, page = api.request("GET", "/settings")
            html = page.decode("utf-8")
            ensure("settings_page_ok", status == 200)
            ensure("page_sections", all(t in html for t in
                   ("个人信息", "导入偏好", "默认文本 / 语音模型",
                    "通知", "隐私与备份", "版本信息")))
            ensure("page_explicit_probe", "探测接口" in html and "检查配置" in html)
            ensure("page_no_browser_storage",
                   "localStorage" not in html and "sessionStorage" not in html)
            ensure("page_no_key_in_url", "api_key=" not in html)
            ensure("page_no_store", headers.get("cache-control") == "no-store")
            ensure("page_csp", "content-security-policy" in headers)

            status, _, body = api.request("GET", "/api/health")
            ensure("health_still_public", status == 200)

            # CSRF.
            status, _, _ = api.request("PUT", "/api/settings",
                                       {"profile": {"display_name": "X"}})
            ensure("csrf_required", status == 403)
            status, _, _ = api.request(
                "PUT", "/api/settings", {"profile": {"display_name": "X"}},
                headers={"X-Requested-With": "XMLHttpRequest",
                         "Origin": "http://evil.example"})
            ensure("csrf_origin_rejected", status == 403)

            # Save non-secret settings.
            status, _, body = api.request(
                "PUT", "/api/settings",
                {"profile": {"display_name": "王老板", "email": "boss@example.com"},
                 "import": {"duplicate_policy": "skip", "auto_archive": True},
                 "notifications": {"daily_digest": True, "digest_time": "08:30"}},
                headers={"X-Requested-With": "XMLHttpRequest"})
            saved = json.loads(body)
            ensure("save_ok", status == 200 and saved["import"]["duplicate_policy"] == "skip")
            ensure("save_persisted",
                   SecureSettings(tmp, iterations=1000).settings()["import"]["auto_archive"] is True)

            # Validation.
            status, _, body = api.request(
                "PUT", "/api/settings", {"profile": {"email": "not-an-email"}},
                headers={"X-Requested-With": "XMLHttpRequest"})
            ensure("invalid_email", status == 400
                   and json.loads(body)["error"]["code"] == "E_INVALID_EMAIL")
            status, _, body = api.request(
                "PUT", "/api/settings", {"notifications": {"digest_time": "9:00"}},
                headers={"X-Requested-With": "XMLHttpRequest"})
            ensure("invalid_time", status == 400
                   and json.loads(body)["error"]["code"] == "E_INVALID_TIME")
            status, _, body = api.request(
                "PUT", "/api/settings", {"profile": {"unknown": 1}},
                headers={"X-Requested-With": "XMLHttpRequest"})
            ensure("unknown_setting", status == 400
                   and json.loads(body)["error"]["code"] == "E_INVALID_SETTING")

            # Server-side only model key.
            status, _, body = api.request(
                "PUT", "/api/settings", {"text_api_key": SECRET},
                headers={"X-Requested-With": "XMLHttpRequest"})
            ensure("key_saved", status == 200)
            ensure("key_not_in_response", SECRET not in body.decode("utf-8"))
            status, _, body = api.request("GET", "/api/settings")
            ensure("key_not_in_get", SECRET not in body.decode("utf-8")
                   and json.loads(body)["models"]["text_key"]["configured"] is True)
            status, _, page = api.request("GET", "/settings")
            ensure("key_not_in_page", SECRET not in page.decode("utf-8"))
            status, _, backup = api.request("GET", "/api/settings/backup")
            ensure("key_not_in_backup", status == 200
                   and SECRET not in backup.decode("utf-8"))
            stored = (Path(tmp) / "secure.json").read_text(encoding="utf-8")
            ensure("key_in_server_config", SECRET in stored)

            # Opening/saving settings must not trigger email or model calls.
            ensure("no_side_effects_after_open_save",
                   server_module.SIDE_EFFECTS == {"email_fetch": 0, "model_call": 0,
                                                  "model_probe": 0},
                   server_module.SIDE_EFFECTS)

            status, _, body = api.request(
                "POST", "/api/settings/test", {"target": "text", "live": False},
                headers={"X-Requested-With": "XMLHttpRequest"})
            result = json.loads(body)
            ensure("test_config_ok", status == 200 and result["ok"] is True
                   and result["network_attempted"] is False)
            ensure("test_no_model_call", server_module.SIDE_EFFECTS["model_call"] == 0
                   and server_module.SIDE_EFFECTS["email_fetch"] == 0
                   and server_module.SIDE_EFFECTS["model_probe"] == 0)

            status, _, body = api.request(
                "POST", "/api/settings/test", {"target": "text", "live": True},
                headers={"X-Requested-With": "XMLHttpRequest"})
            result = json.loads(body)
            ensure("live_test_needs_endpoint", status == 400
                   and result["code"] == "E_NO_ENDPOINT")
            ensure("probe_explicit", server_module.SIDE_EFFECTS["model_probe"] == 1
                   and server_module.SIDE_EFFECTS["model_call"] == 0
                   and server_module.SIDE_EFFECTS["email_fetch"] == 0)

            status, _, body = api.request(
                "POST", "/api/settings/test", {"target": "email"},
                headers={"X-Requested-With": "XMLHttpRequest"})
            ensure("unknown_target", status == 400
                   and json.loads(body)["error"]["code"] == "E_MODEL_TARGET")

            # Session tampering and logout.
            good = api.cookie
            api.cookie = good[:-2] + "zz"
            status, _, _ = api.request("GET", "/api/settings")
            ensure("tampered_cookie_401", status == 401)
            api.cookie = good
            status, headers, _ = api.request(
                "POST", "/api/auth/logout", headers={"X-Requested-With": "XMLHttpRequest"})
            ensure("logout_clears_cookie", status == 200
                   and "Max-Age=0" in headers.get("set-cookie", ""))
            api.cookie = None
            status, _, _ = api.request("GET", "/api/settings")
            ensure("after_logout_401", status == 401)

            # Path traversal must not expose server code.
            api.login("correct-horse-9")
            status, _, body = api.request("GET", "/../ops/server.py")
            ensure("no_traversal", status in (400, 404)
                   and b"class Handler" not in body)
        finally:
            auth_server.stop()

        # Local-only instance: no login required.
        local_store = SecureSettings(Path(tmp) / "local", iterations=1000)
        local_server = Server(local_store, require_auth=False)
        local = Client(local_server.port)
        try:
            status, _, body = local.request("GET", "/api/settings", use_cookie=False)
            ensure("local_settings_open", status == 200)
            status, _, page = local.request("GET", "/settings", use_cookie=False)
            ensure("local_page_open", status == 200 and "个人信息" in page.decode("utf-8"))
            status, _, _ = local.request("GET", "/login", use_cookie=False)
            ensure("login_page_available", status == 200)
            ensure("local_no_side_effects",
                   server_module.SIDE_EFFECTS["email_fetch"] == 0
                   and server_module.SIDE_EFFECTS["model_call"] == 0)
        finally:
            local_server.stop()

        # Password is never present in frontend bundles or config URLs.
        settings_html = (ROOT / "prototype" / "settings.html").read_text(encoding="utf-8")
        login_html = (ROOT / "prototype" / "login.html").read_text(encoding="utf-8")
        index_html = (ROOT / "prototype" / "index.html").read_text(encoding="utf-8")
        ensure("settings_entry", 'data-testid="nav-settings"' in index_html
               and "/settings" in index_html)
        ensure("bundle_no_secret", SECRET not in settings_html and SECRET not in login_html)
        ensure("bundle_no_storage", "localStorage" not in login_html
               and "sessionStorage" not in login_html)
        ensure("bundle_no_password_prefill", "value=\"correct-horse-9\"" not in login_html)

        evidence = {
            "schema": "clientgraph.web_access_settings.evidence.v1",
            "checks": CHECKS,
            "side_effects": dict(server_module.SIDE_EFFECTS),
            "all_passed": all(CHECKS.values()),
        }
        out = ROOT / "evidence" / "web-access-settings-2026-11-08.json"
        out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        for key, value in CHECKS.items():
            print(("PASS " if value else "FAIL ") + key)
        print("checks:", len(CHECKS), "passed:", sum(CHECKS.values()))
        print("side_effects:", server_module.SIDE_EFFECTS)
        print("evidence:", out)
        return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
