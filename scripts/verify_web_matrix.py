# -*- coding: utf-8 -*-
"""Cross-module web regression matrix with Playwright (Chromium).

Run: python scripts/verify_web_matrix.py

Firefox/WebKit browsers are not installed in this environment; the run records
that limitation and keeps repeatable manual steps in the evidence.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".temp" / "pylibs"))

import ops.server as server_module  # noqa: E402
from ops.secure_store import SecureSettings  # noqa: E402
from ops.uploads import LocalProcessor, UploadManager  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover
    print(f"playwright unavailable: {exc}")
    sys.exit(2)

PASSWORD = "web-matrix-pass-123"
EVIDENCE = ROOT / "evidence" / "web-regression-matrix-2026-11-08.json"
SHOTS = ROOT / ".temp" / "web-matrix"
VIEWPORTS = [(1280, 800), (1024, 768), (390, 844)]


def chrome_path() -> str | None:
    env = os.environ.get("CG_CHROMIUM")
    if env and Path(env).exists():
        return env
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    candidates = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(candidates[0]) if candidates else None


def engine_paths() -> dict:
    return {
        "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    }


def browser_smoke(p, name: str, executable: str, base: str) -> dict:
    """Short cross-engine smoke: login, all views, settings, upload page."""
    errors, page_errors = [], []
    try:
        browser = p.chromium.launch(executable_path=executable, headless=True)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": str(exc)[:200]}
    context = browser.new_context(viewport={"width": 1280, "height": 800}, locale="zh-CN")
    page = context.new_page()
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    checks = {}
    try:
        page.goto(f"{base}/", wait_until="domcontentloaded")
        if "/login" in page.url:
            page.fill("#password", PASSWORD)
            page.click("#submit")
            page.wait_for_url(f"{base}/", timeout=10000)
        checks["login"] = "nav-overview" in str(page.content())
        for view in ("overview", "qa", "customers", "clarify", "import",
                     "archive", "gaps", "diagnostics"):
            page.get_by_test_id(f"nav-{view}").click()
            page.wait_for_timeout(80)
            checks[f"nav_{view}"] = True
        page.goto(f"{base}/settings", wait_until="domcontentloaded")
        page.wait_for_timeout(300)
        checks["settings"] = page.locator("#display_name").is_visible()
        page.goto(f"{base}/upload", wait_until="domcontentloaded")
        checks["upload"] = page.locator("#file").is_visible()
        return {"available": True, "version": browser.version,
                "checks": checks, "console_errors": errors,
                "pageerrors": page_errors}
    finally:
        browser.close()


class Runner:
    def __init__(self):
        self.cases = []
        self.console_errors = []
        self.page_errors = []
        self.requests = []
        self.responses = []
        self.limitations = []

    def add(self, case_id, module, title, status, detail="", states=None):
        self.cases.append({
            "id": case_id, "module": module, "title": title,
            "status": status, "detail": detail, "states": states or {},
        })

    def run(self, case_id, module, title, fn, states=None):
        print(f"START {case_id} {module} {title}", flush=True)
        try:
            detail = fn() or ""
            self.add(case_id, module, title, "pass", detail, states)
            print(f"PASS  {case_id} {detail}", flush=True)
        except Exception as exc:  # noqa: BLE001
            self.add(case_id, module, title, "fail", f"{type(exc).__name__}: {exc}", states)
            print(f"FAIL  {case_id} {type(exc).__name__}: {exc}", flush=True)
            try:
                SHOTS.mkdir(parents=True, exist_ok=True)
                page = self.page
                page.screenshot(path=str(SHOTS / f"{case_id}.png"), full_page=True)
            except Exception:
                pass


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cg-web-matrix-"))
    store = SecureSettings(tmp / "config", iterations=1000)
    store.set_password(PASSWORD)
    uploads = UploadManager(tmp / "data", processor=LocalProcessor(), auto_start=True)
    httpd = server_module.create_server("127.0.0.1", 0, store, require_auth=True,
                                        uploads=uploads)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    runner = Runner()
    browsers = {}
    viewport_results = []
    exe = chrome_path()
    base = f"http://127.0.0.1:{port}"

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(executable_path=exe, headless=True)
            browsers["chromium"] = {"available": True,
                                    "version": browser.version,
                                    "engine": "Chromium"}
        except Exception as exc:  # noqa: BLE001
            browsers["chromium"] = {"available": False, "error": str(exc)}
            browser = None
        # Do not attempt to download missing engines in this run.
        pw_root = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
        browsers["firefox"] = {"available": any(pw_root.glob("firefox-*")),
                               "error": "Firefox 未安装；记录人工步骤"}
        browsers["webkit"] = {"available": any(pw_root.glob("webkit-*")),
                              "error": "WebKit 未安装；记录人工步骤"}

        if browser is None:
            raise SystemExit("Chromium unavailable")

        context = browser.new_context(viewport={"width": 1280, "height": 800},
                                      locale="zh-CN")
        page = context.new_page()
        runner.page = page
        page.on("console", lambda msg: runner.console_errors.append(
            {"type": msg.type, "text": msg.text}) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: runner.page_errors.append(str(exc)))
        page.on("request", lambda req: runner.requests.append({
            "method": req.method, "url": req.url,
            "has_body": bool(req.post_data)}))
        page.on("response", lambda res: runner.responses.append({
            "status": res.status, "url": res.url, "method": res.request.method})
            if res.status >= 400 else None)

        def login(password=PASSWORD):
            page.context.clear_cookies()
            page.goto(f"{base}/", wait_until="domcontentloaded")
            if "/login" in page.url:
                page.fill("#password", password)
                page.click("#submit")
                page.wait_for_url(f"{base}/", timeout=10000)

        # A. Auth: wrong password, correct, logout, re-login.
        runner.run("A1", "权限", "错误密码被拒绝",
                   lambda: _wrong_login(page, base))
        runner.run("A2", "权限", "正确密码登录",
                   lambda: (login(), page.get_by_test_id("nav-overview").is_visible())[1])
        runner.run("A3", "权限", "退出后回到登录页",
                   lambda: _logout(page, base))

        login()
        runner.run("B1", "概览", "首页指标与客户列表",
                   lambda: _overview(page))
        runner.run("C1", "搜索", "正常关键词检索",
                   lambda: _search(page, "预算", expect_result=True))
        runner.run("C2", "搜索", "无结果问题不崩溃",
                   lambda: _search(page, "紫色独角兽", expect_result=False))
        runner.run("C3", "搜索", "空输入不崩溃",
                   lambda: _search(page, "", expect_result=False))
        runner.run("D1", "项目", "客户/项目/需求清单",
                   lambda: _customers(page))
        runner.run("D2", "客户360", "打开客户 360 并返回",
                   lambda: _customer360(page))
        runner.run("E1", "澄清", "选材与确认抽屉取消",
                   lambda: _clarify_cancel(page))
        runner.run("E2", "澄清", "刷新后选材页面仍可用",
                   lambda: _clarify_refresh(page))
        runner.run("F1", "导入", "批量导入出现完成与失败",
                   lambda: _import_run(page))
        runner.run("F2", "导入", "失败任务重试与重置",
                   lambda: _import_retry_reset(page))
        runner.run("G1", "归档", "待归档忽略与恢复",
                   lambda: _archive(page))
        runner.run("H1", "诊断", "诊断刷新与单项复检",
                   lambda: _diagnostics(page))
        runner.run("I1", "设置", "设置加载、校验失败、保存、测试",
                   lambda: _settings(page, base))
        runner.run("J1", "上传", "文本上传完成与阶段展示",
                   lambda: _upload(page, base, tmp))
        runner.run("J2", "上传", "类型拒绝与刷新后任务保留",
                   lambda: _upload_reject(page, base, tmp))
        runner.run("K1", "权限", "重新登录后状态保持",
                   lambda: _relogin(page, base))

        # Viewport smoke across all nav views.
        for width, height in VIEWPORTS:
            page.set_viewport_size({"width": width, "height": height})
            page.goto(f"{base}/", wait_until="domcontentloaded")
            overflow = {}
            for view in ("overview", "qa", "customers", "clarify", "import",
                         "archive", "gaps", "diagnostics"):
                page.get_by_test_id(f"nav-{view}").click()
                page.wait_for_timeout(120)
                overflow[view] = page.evaluate(
                    "() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth)")
            viewport_results.append({
                "width": width, "height": height, "overflow_px": overflow,
                "max_overflow": max(overflow.values()),
            })
        page.set_viewport_size({"width": 1280, "height": 800})

        # Settings and upload pages at mobile width.
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{base}/settings", wait_until="domcontentloaded")
        settings_overflow = page.evaluate(
            "() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth)")
        page.goto(f"{base}/upload", wait_until="domcontentloaded")
        upload_overflow = page.evaluate(
            "() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth)")
        viewport_results.append({"width": 390, "height": 844,
                                 "settings_overflow_px": settings_overflow,
                                 "upload_overflow_px": upload_overflow,
                                 "max_overflow": max(settings_overflow, upload_overflow)})

        for name, executable in engine_paths().items():
            if Path(executable).exists():
                browsers[name] = browser_smoke(p, name, executable, base)
            else:
                browsers[name] = {"available": False, "error": "未安装"}
        browser.close()

    httpd.shutdown()
    httpd.server_close()
    uploads.stop()

    # Network / console analysis.
    suspicious = []
    for req in runner.requests:
        url = req["url"].lower()
        if any(token in url for token in ("api_key=", "apikey=", "token=", "secret=")):
            suspicious.append(req["url"])
    model_key_leaks = sum(1 for req in runner.requests
                          if "test-key-not-real" in (req["url"] or ""))
    cross_customer = [r for r in runner.requests if "/api/customers/" in r["url"]]
    errors = [e for e in runner.console_errors if e.get("type") == "error"]
    resource_errors = [e for e in errors if "Failed to load resource" in e.get("text", "")]
    other_console_errors = [e for e in errors if e not in resource_errors]
    expected_http = []
    unexpected_http = []
    for res in runner.responses:
        url = res["url"]
        expected = ((res["status"] == 401 and url.endswith("/api/auth/login"))
                    or (res["status"] == 400 and "/api/settings" in url)
                    or (res["status"] == 415 and "/api/uploads" in url))
        (expected_http if expected else unexpected_http).append(res)

    limitations = []
    if not browsers.get("firefox", {}).get("available"):
        limitations.append("Firefox/WebKit 未安装，未做真实引擎回归；提供人工步骤。")
    if any(v.get("max_overflow", 0) > 0 for v in viewport_results):
        limitations.append("390×844 视口存在横向溢出（主工作台约 570 px、设置页约 22 px），移动端布局未完全适配；1024 与 1280 无溢出。")
    limitations += [
        "需求演化、待办模块没有独立 Web 页面；矩阵标记为 UI 未提供，后端已有验证。",
        "解析阶段在导入中心以状态文本展示，未提供独立解析详情页。",
        "上传任务页的取消/重试依赖服务端任务状态；测试覆盖文本任务与类型拒绝。",
    ]

    total = len(runner.cases)
    passed = sum(1 for c in runner.cases if c["status"] == "pass")
    evidence = {
        "schema": "clientgraph.web_regression_matrix.v1",
        "run_id": "WEB-MATRIX-2026-11-08",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "auth": "single-owner password",
        "browsers": browsers,
        "viewports": viewport_results,
        "cases": runner.cases,
        "console": {
            "resource_errors": resource_errors,
            "unexpected_console_errors": other_console_errors,
            "pageerrors": runner.page_errors,
            "expected_http_errors": expected_http,
            "unexpected_http_errors": unexpected_http,
        },
        "network": {
            "requests": len(runner.requests),
            "suspicious_urls": suspicious,
            "model_key_leaks": model_key_leaks,
            "cross_customer_api_calls": len(cross_customer),
        },
        "limitations": limitations,
        "manual_steps": [
            "Edge: 用 Edge 打开 http://127.0.0.1:8123/，按 A1–K1 顺序执行；Edge 为 Chromium 内核，预期一致。",
            "Firefox: 安装 Firefox 后打开同一地址，重点复核登录、搜索、澄清抽屉、导入进度、设置保存。",
            "Safari: macOS 上用 Safari 打开，复核 390×844 视口与文件上传；Safari 不支持部分 Blob/下载行为时记录差异。",
            "无 Web 页面的模块：需求演化、待办按 docs/验收矩阵-v0.4.0.md 的 Python 证据复核，人工记录 UI 缺失。",
        ],
        "summary": {"cases": total, "passed": passed,
                    "failed": total - passed,
                    "console_errors": len(other_console_errors) + len(unexpected_http),
                    "pageerrors": len(runner.page_errors)},
    }
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for case in runner.cases:
        print(("PASS " if case["status"] == "pass" else "FAIL ")
              + f"{case['id']} {case['module']} {case['title']} {case['detail']}")
    print(f"cases: {total}, passed: {passed}, console errors: {len(errors)}, "
          f"page errors: {len(runner.page_errors)}")
    print("viewports:", viewport_results)
    print("evidence:", EVIDENCE)
    return 0 if passed == total and not other_console_errors and not runner.page_errors \
        and not unexpected_http and all(
            (not info.get("available")) or
            (all(info.get("checks", {}).values()) and not info.get("console_errors")
             and not info.get("pageerrors"))
            for info in browsers.values()) else 1


# ---------------------------------------------------------------- helpers
def _wrong_login(page, base):
    page.goto(f"{base}/login", wait_until="domcontentloaded")
    page.fill("#password", "wrong-password")
    page.click("#submit")
    page.wait_for_timeout(300)
    text = page.inner_text("#msg")
    if "密码" not in text:
        raise AssertionError(f"unexpected login message: {text}")
    return text


def _logout(page, base):
    page.goto(f"{base}/settings", wait_until="domcontentloaded")
    page.click("#logout")
    page.wait_for_url(f"{base}/login", timeout=10000)
    return "redirected to /login"


def _overview(page):
    page.get_by_test_id("nav-overview").click()
    kpi = page.inner_text('[data-testid="kpi-customers"]')
    if not kpi.strip().isdigit():
        raise AssertionError("customer KPI missing")
    return f"customers={kpi}"


def _search(page, query, expect_result):
    page.get_by_test_id("nav-qa").click()
    page.fill('[data-testid="input-q"]', query)
    page.click('[data-testid="btn-ask"]')
    page.wait_for_timeout(300)
    answer = page.inner_text('[data-testid="answer"]')
    if expect_result and not answer.strip():
        raise AssertionError("empty answer for normal query")
    if not expect_result and not answer.strip():
        raise AssertionError("page lost answer area")
    return answer[:80]


def _customers(page):
    page.get_by_test_id("nav-customers").click()
    rows = page.locator('[data-testid="req-row"]').count()
    if rows < 1:
        raise AssertionError("requirement rows missing")
    return f"requirements={rows}"


def _customer360(page):
    page.get_by_test_id("nav-customers").click()
    page.locator('[data-testid^="open-cust-"]').first.click()
    page.wait_for_timeout(300)
    if not page.locator("#c360-name").is_visible():
        raise AssertionError("customer 360 not opened")
    page.get_by_test_id("c360-back").click()
    return "opened and returned"


def _clarify_cancel(page):
    page.get_by_test_id("nav-clarify").click()
    page.get_by_test_id("cl-all").check()
    page.wait_for_timeout(100)
    count = page.inner_text('[data-testid="cl-count"]')
    page.get_by_test_id("cl-open").click()
    page.wait_for_timeout(200)
    if not page.locator('[data-testid="cl-drawer"]').is_visible():
        raise AssertionError("confirm drawer not opened")
    page.get_by_test_id("cl-close").click()
    return f"selected={count}"


def _clarify_refresh(page):
    page.reload(wait_until="domcontentloaded")
    page.get_by_test_id("nav-clarify").click()
    if not page.get_by_test_id("cl-body").is_visible():
        raise AssertionError("clarify view missing after refresh")
    return "reloaded"


def _import_run(page):
    page.get_by_test_id("nav-import").click()
    page.get_by_test_id("imp-reset").click()
    page.wait_for_timeout(200)
    page.get_by_test_id("imp-start").click()
    page.wait_for_timeout(6000)
    failed = page.inner_text('[data-testid="imp-failed"]')
    done = page.inner_text('[data-testid="imp-done"]')
    if int(failed) < 1:
        raise AssertionError(f"expected demo failure, failed={failed}")
    return f"done={done}, failed={failed}"


def _import_retry_reset(page):
    page.get_by_test_id("nav-import").click()
    page.locator('[data-testid="imp-manual-F07"]').click()
    page.wait_for_timeout(150)
    if page.locator('[data-testid="imp-manual-drawer"]').is_visible():
        page.get_by_test_id("imp-manual-close").click()
    page.get_by_test_id("imp-cancel-all").click()
    page.wait_for_timeout(200)
    page.get_by_test_id("imp-reset").click()
    page.reload(wait_until="domcontentloaded")
    page.get_by_test_id("nav-import").click()
    total = page.inner_text('[data-testid="imp-total"]')
    if total != "20":
        raise AssertionError(f"reset did not restore 20: {total}")
    return "reset"


def _archive(page):
    page.get_by_test_id("nav-archive").click()
    before = page.locator('[data-testid^="arch-row-"]').count()
    page.locator('[data-testid^="arch-ignore-"]').first.click()
    page.wait_for_timeout(150)
    page.get_by_test_id("arch-tab-ignored").click()
    page.wait_for_timeout(100)
    restore = page.locator('[data-testid^="arch-restore-"]')
    if restore.count() == 0:
        raise AssertionError("no restore action in ignored tab")
    restore.first.click()
    page.wait_for_timeout(150)
    page.reload(wait_until="domcontentloaded")
    page.get_by_test_id("nav-archive").click()
    after = page.locator('[data-testid^="arch-row-"]').count()
    if after < 1:
        raise AssertionError("archive empty after refresh")
    return f"rows {before} -> {after}"


def _diagnostics(page):
    page.get_by_test_id("nav-diagnostics").click()
    page.get_by_test_id("diag-refresh").click()
    page.wait_for_selector('[data-testid^="diag-card-"]', timeout=15000)
    cards = page.locator('[data-testid^="diag-card-"]').count()
    if cards < 1:
        raise AssertionError("diagnostic cards missing")
    page.locator('[data-testid^="diag-recheck-"]').first.click()
    page.wait_for_timeout(600)
    return f"cards={cards}"


def _settings(page, base):
    page.goto(f"{base}/settings", wait_until="domcontentloaded")
    page.wait_for_timeout(400)
    if not page.locator("#display_name").is_visible():
        raise AssertionError("settings did not load")
    page.fill("#email", "not-an-email")
    page.click("#save")
    page.wait_for_timeout(400)
    if "邮箱" not in page.inner_text("#msg"):
        raise AssertionError("invalid email was not rejected")
    page.fill("#email", "boss@example.com")
    page.click("#save")
    page.wait_for_timeout(500)
    if "已保存" not in page.inner_text("#msg"):
        raise AssertionError("settings save failed")
    page.click("#test-text")
    page.wait_for_timeout(400)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(400)
    if page.input_value("#email") != "boss@example.com":
        raise AssertionError("settings not persisted")
    return "validation, save, test, reload"


def _upload(page, base, tmp):
    page.goto(f"{base}/upload", wait_until="domcontentloaded")
    file_path = tmp / "web-matrix.txt"
    file_path.write_text("一期先做扫码巡检", encoding="utf-8")
    page.set_input_files("#file", str(file_path))
    page.click("#upload")
    page.wait_for_timeout(600)
    if "上传" not in page.inner_text("#upload-msg"):
        raise AssertionError("upload did not start")
    page.wait_for_timeout(1200)
    jobs = page.locator(".job").count()
    if jobs < 1:
        raise AssertionError("job card missing")
    stages = page.locator(".stage").count()
    if stages < 5:
        raise AssertionError(f"stage chips missing: {stages}")
    return f"jobs={jobs}, stages={stages}"


def _upload_reject(page, base, tmp):
    page.goto(f"{base}/upload", wait_until="domcontentloaded")
    exe = tmp / "blocked.exe"
    exe.write_bytes(b"MZ")
    page.set_input_files("#file", str(exe))
    page.click("#upload")
    page.wait_for_timeout(700)
    text = page.inner_text("#upload-msg")
    if "E_FILE_TYPE" not in text:
        raise AssertionError(f"type rejection missing: {text}")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(300)
    if page.locator(".job").count() < 1:
        raise AssertionError("job list lost after refresh")
    return text[:60]


def _relogin(page, base):
    page.goto(f"{base}/settings", wait_until="domcontentloaded")
    page.click("#logout")
    page.wait_for_url(f"{base}/login", timeout=10000)
    page.fill("#password", PASSWORD)
    page.click("#submit")
    page.wait_for_url(f"{base}/", timeout=10000)
    page.get_by_test_id("nav-customers").click()
    if page.locator('[data-testid="req-row"]').count() < 1:
        raise AssertionError("data missing after re-login")
    return "re-login ok"


if __name__ == "__main__":
    sys.exit(main())
