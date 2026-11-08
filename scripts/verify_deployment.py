# -*- coding: utf-8 -*-
"""Verify a deployed web build: health, version, browser access, performance."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".temp" / "pylibs"))


def http_json(url: str, timeout: int = 20):
    started = time.perf_counter()
    with urllib.request.urlopen(url, timeout=timeout) as response:
        body = response.read()
        return response.status, json.loads(body), (time.perf_counter() - started) * 1000


def chrome_path() -> str | None:
    base = Path.home() / "AppData" / "Local" / "ms-playwright"
    candidates = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(candidates[0]) if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8140")
    parser.add_argument("--version", required=True)
    parser.add_argument("--build-id", default=None)
    parser.add_argument("--out", default=str(ROOT / "evidence" / "deployment-v0.5.0.json"))
    args = parser.parse_args()

    health_status, health, health_ms = http_json(args.base + "/api/health")
    version_status, version, version_ms = http_json(args.base + "/api/version")
    checks = {}
    checks["health_ok"] = health_status == 200 and health.get("ok") is True
    checks["version_match"] = version.get("version") == args.version
    if args.build_id:
        checks["build_match"] = health.get("build_id") == args.build_id
    checks["health_public"] = "auth_required" in health

    # Performance: 30 health requests + one page navigation.
    timings = []
    for _ in range(30):
        started = time.perf_counter()
        with urllib.request.urlopen(args.base + "/api/health", timeout=10) as response:
            response.read()
        timings.append((time.perf_counter() - started) * 1000)
    timings.sort()
    perf = {
        "health_ms": {"p50": round(statistics.median(timings), 2),
                      "p95": round(timings[int(len(timings) * 0.95) - 1], 2),
                      "max": round(max(timings), 2), "samples": len(timings)},
        "single_health_ms": round(health_ms, 2),
        "version_ms": round(version_ms, 2),
    }

    browser_evidence = {}
    try:
        from playwright.sync_api import sync_playwright
        executable = chrome_path()
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=executable, headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 800},
                                          locale="zh-CN")
            page = context.new_page()
            errors, page_errors = [], []
            page.on("console", lambda msg: errors.append(msg.text)
                    if msg.type == "error" else None)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            started = time.perf_counter()
            page.goto(args.base + "/", wait_until="domcontentloaded")
            load_ms = (time.perf_counter() - started) * 1000
            text = page.inner_text("body")
            title = page.title()
            browser_evidence = {
                "title": title,
                "version_visible": args.version in text,
                "version_text": "v" + args.version,
                "load_ms": round(load_ms, 2),
                "console_errors": errors,
                "pageerrors": page_errors,
                "screenshot": None,
            }
            checks["browser_version_visible"] = args.version in text
            checks["browser_console_clean"] = not errors and not page_errors
            browser.close()
    except Exception as exc:  # noqa: BLE001
        browser_evidence = {"error": f"{type(exc).__name__}: {exc}"}
        checks["browser_version_visible"] = False
        checks["browser_console_clean"] = False

    diagnostics = {}
    try:
        status, data, diag_ms = http_json(args.base + "/api/diagnostics", timeout=60)
        components = data.get("components") or []
        diagnostics = {
            "status": status,
            "elapsed_ms": round(diag_ms, 2),
            "components": [{"id": c.get("id"), "status": c.get("status"),
                            "reason": (c.get("reason") or "")[:160]}
                           for c in components],
        }
    except Exception as exc:  # noqa: BLE001
        diagnostics = {"error": f"{type(exc).__name__}: {exc}"}

    evidence = {
        "schema": "clientgraph.deployment.evidence.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base": args.base,
        "health": health,
        "version": version,
        "performance": perf,
        "browser": browser_evidence,
        "diagnostics": diagnostics,
        "checks": checks,
        "all_passed": all(checks.values()),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    for key, value in checks.items():
        print(("PASS " if value else "FAIL ") + key)
    print("health:", health)
    print("performance:", perf)
    print("browser:", {k: browser_evidence.get(k) for k in
                       ("title", "version_visible", "load_ms", "console_errors", "pageerrors")})
    print("evidence:", out)
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
