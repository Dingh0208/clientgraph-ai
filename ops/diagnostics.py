# -*- coding: utf-8 -*-
"""Local diagnostics for Sidecar, WeChat engine, ffmpeg, OCR and ASR.

The module only reports what it can actually observe. It never hides a failure
behind a generic "service unavailable" message: every component returns a
status, a concrete reason, remediation steps and, where applicable, a log tail.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "ops-logs"
MAX_ATTEMPTS = 2
COOLDOWN_S = 3
HEALTH_TIMEOUT_S = 5

_STATUS_WEIGHT = {"ok": 0, "degraded": 1, "not_configured": 2,
                  "not_installed": 2, "stopped": 3, "error": 4}
_PROCS: dict[str, subprocess.Popen] = {}
_ATTEMPTS: dict[str, int] = {}
_COOLDOWN_UNTIL: dict[str, float] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tail(path: Path, lines: int = 30) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(data[-lines:])
    except Exception:
        return ""


def _cmd_from_env(name: str) -> list[str] | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except Exception:
        return None
    if isinstance(value, list) and value and all(isinstance(x, str) for x in value):
        return value
    return None


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _health(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            body = resp.read(200).decode("utf-8", errors="replace")
            return 200 <= resp.status < 300, body
    except Exception as exc:
        return False, str(exc)[:200]


def _component(cid, name, status, summary, detail, help_steps,
               startable=False, actions=None, **extra) -> dict:
    return {
        "id": cid, "name": name, "status": status,
        "summary": summary, "detail": detail,
        "help": help_steps,
        "startable": startable,
        "actions": actions or (["start", "recheck", "log"] if startable else ["recheck"]),
        "attempts": _ATTEMPTS.get(cid, 0),
        "cooldown_s": max(0, int(_COOLDOWN_UNTIL.get(cid, 0) - time.time())),
        "log_path": str(LOG_DIR / f"{cid}.log"),
        "checked_at": _now(),
        **extra,
    }


def check_ffmpeg() -> dict:
    exe = shutil.which("ffmpeg")
    probe = shutil.which("ffprobe")
    if not exe or not probe:
        return _component(
            "ffmpeg", "ffmpeg", "not_installed",
            "未找到 ffmpeg / ffprobe，音视频转码与切片不可用",
            f"ffmpeg={exe or '未找到'}；ffprobe={probe or '未找到'}",
            ["安装 ffmpeg（Windows 可用 winget install Gyan.FFmpeg）",
             "把 ffmpeg/bin 加入 PATH，重启应用",
             "点击“重新检测”确认版本"],
        )
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=10).stdout
        version = (out.splitlines() or ["unknown"])[0]
        status = "ok"
        summary = "ffmpeg 可用"
        detail = version
    except Exception as exc:
        return _component("ffmpeg", "ffmpeg", "error",
                          "ffmpeg 存在但无法执行", str(exc)[:300],
                          ["在命令行运行 ffmpeg -version 查看报错",
                           "重新安装或修复杀毒软件拦截"])
    return _component("ffmpeg", "ffmpeg", status, summary, detail,
                      ["无需手动启动；由任务按需调用",
                       "若转码失败，查看任务错误码与原件格式"])


def check_ocr() -> dict:
    missing = []
    versions = []
    for name, label in (("pymupdf", "PyMuPDF"), ("PIL", "Pillow"),
                        ("rapidocr_onnxruntime", "RapidOCR")):
        try:
            mod = __import__(name)
            versions.append(f"{label}={getattr(mod, '__version__', 'unknown')}")
        except Exception:
            missing.append(label)
    if missing:
        return _component(
            "ocr", "OCR", "not_installed",
            f"缺少 OCR 依赖：{', '.join(missing)}",
            "；".join(versions) or "未加载任何 OCR 组件",
            ["在项目目录执行：pip install -r media_pipeline/requirements.txt",
             "确认 rapidocr-onnxruntime 模型文件完整",
             "点击“重新检测”，再用一张扫描页试跑"],
        )
    return _component(
        "ocr", "OCR", "ok", "OCR 组件已加载",
        "；".join(versions),
        ["OCR 无常驻进程，无需手动启动",
         "首次识别会加载模型，可能比后续慢 3–5 秒",
         "低置信度时请核对原图并人工修订"],
    )


def check_asr() -> dict:
    provider = os.environ.get("CG_ASR_PROVIDER", "mock").strip().lower() or "mock"
    model = os.environ.get("QWEN_ASR_MODEL", "qwen3-asr-flash")
    if provider == "mock":
        return _component(
            "asr", "ASR", "degraded",
            "当前为 Mock ASR：链路可验证，结果不是真实识别",
            "provider=mock；不会访问网络",
            ["在设置中配置 Qwen ASR：DASHSCOPE_API_KEY、CG_ASR_PROVIDER=qwen",
             "配置后重启 Sidecar 并点击“重新检测”",
             "未配置真实模型时，不要对外宣称已完成转写"],
        )
    if provider == "qwen":
        key = bool(os.environ.get("DASHSCOPE_API_KEY", "").strip())
        if not key:
            return _component(
                "asr", "ASR", "not_configured",
                "已选择 Qwen ASR，但未配置 DASHSCOPE_API_KEY",
                f"provider=qwen；model={model}；密钥=未设置",
                ["设置环境变量 DASHSCOPE_API_KEY（不要写入仓库）",
                 "确认账号已开通对应语音模型",
                 "重启 Sidecar 后重新检测"],
            )
        return _component(
            "asr", "ASR", "ok",
            "Qwen ASR 已配置（未验证网络连通性）",
            f"provider=qwen；model={model}；密钥=已设置（不展示）",
            ["真实识别前先用 10 秒短音频试跑",
             "检查限流、余额与地域端点",
             "失败时查看任务错误码 E_ASR_* 与日志"],
        )
    return _component(
        "asr", "ASR", "error", f"未知 ASR provider：{provider}",
        "支持 mock / qwen",
        ["把 CG_ASR_PROVIDER 设为 mock 或 qwen",
         "重启 Sidecar 后重新检测"],
    )


def _sidecar_url() -> str:
    return os.environ.get("CG_SIDECAR_URL", "http://127.0.0.1:8765/health").strip()


def check_sidecar() -> dict:
    url = _sidecar_url()
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765
    cmd = _cmd_from_env("CG_SIDECAR_CMD_JSON")
    if not _port_open(host, port):
        return _component(
            "sidecar", "Sidecar", "stopped",
            f"Sidecar 未运行（{host}:{port} 无监听）",
            f"health={url}；启动命令={'已配置' if cmd else '未配置'}",
            ["点击“启动”拉起 Sidecar；失败时查看日志",
             "若端口被占用，先结束旧进程或改端口",
             "仍失败时检查安装目录与杀毒软件拦截"],
            startable=True,
            configured=bool(cmd),
        )
    ok, body = _health(url)
    if ok:
        return _component(
            "sidecar", "Sidecar", "ok",
            f"Sidecar 正在运行（{host}:{port}）",
            f"health 返回：{body[:120]}",
            ["无需手动启动",
             "若任务仍失败，检查 Sidecar 日志与模型配置"],
            startable=True, configured=bool(cmd),
        )
    return _component(
        "sidecar", "Sidecar", "degraded",
        f"端口 {port} 有进程，但健康检查失败",
        f"health={url}；返回：{body}",
        ["确认监听进程是否为 Sidecar，而不是其他程序",
         "查看 Sidecar 日志中的启动错误",
         "结束冲突进程后重新启动"],
        startable=True, configured=bool(cmd),
        error_code="E_SIDECAR_UNHEALTHY",
    )


def _wechat_path() -> str:
    return os.environ.get("CG_WECHAT_ENGINE", "").strip()


def check_wechat() -> dict:
    path = _wechat_path()
    if not path:
        return _component(
            "wechat", "微信引擎", "not_installed",
            "未配置微信解析引擎",
            "CG_WECHAT_ENGINE 未设置；文件导入与粘贴仍可用",
            ["优先使用聊天记录文件/粘贴导入，不依赖引擎",
             "安装微信解析引擎后设置 CG_WECHAT_ENGINE 指向可执行文件",
             "配置后点击“启动”，成功后再重试微信导入"],
            startable=True, configured=False,
        )
    p = Path(path)
    if not p.exists():
        return _component(
            "wechat", "微信引擎", "not_installed",
            "配置的微信引擎不存在",
            f"路径：{path}",
            ["检查安装路径是否被移动或删除",
             "重新安装引擎并更新 CG_WECHAT_ENGINE",
             "可直接改用聊天记录文件导入"],
            startable=True, configured=False,
        )
    try:
        cp = subprocess.run([str(p), "--version"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=5)
        if cp.returncode == 0:
            return _component(
                "wechat", "微信引擎", "ok",
                "微信引擎可用",
                (cp.stdout or cp.stderr).strip()[:200] or "版本输出为空",
                ["无需手动启动；导入时按需调用",
                 "若解析失败，先导出聊天记录文件作为兜底"],
                startable=True, configured=True,
            )
        return _component(
            "wechat", "微信引擎", "error",
            "微信引擎无法执行",
            (cp.stderr or cp.stdout).strip()[:300] or f"退出码 {cp.returncode}",
            ["在命令行直接运行该程序查看报错",
             "重新安装或修复运行库",
             "临时改用聊天记录文件导入"],
            startable=True, configured=True,
        )
    except Exception as exc:
        return _component(
            "wechat", "微信引擎", "error",
            "微信引擎启动检查失败", str(exc)[:300],
            ["检查文件权限与杀毒软件拦截",
             "重新安装引擎",
             "临时改用文件导入"],
            startable=True, configured=True,
        )


def run_checks() -> dict:
    components = [check_sidecar(), check_wechat(), check_ffmpeg(), check_ocr(), check_asr()]
    overall = max(components, key=lambda c: _STATUS_WEIGHT.get(c["status"], 4))["status"]
    return {
        "schema": "clientgraph.diagnostics.v1",
        "generated_at": _now(),
        "platform": sys.platform,
        "overall": overall,
        "components": components,
        "policy": {
            "max_attempts": MAX_ATTEMPTS,
            "cooldown_s": COOLDOWN_S,
            "port_conflict": "端口被占用时不重复拉起，先提示结束冲突进程",
            "fallback": "Sidecar/微信引擎失败时，可改用文件导入、粘贴导入或 Mock ASR；不自动无限重试",
        },
    }


def start_component(cid: str) -> dict:
    if cid not in ("sidecar", "wechat"):
        return {"ok": False, "code": "E_NOT_STARTABLE",
                "message": f"{cid} 没有可启动的常驻进程", "retry_after_s": 0}
    now = time.time()
    if _COOLDOWN_UNTIL.get(cid, 0) > now:
        return {"ok": False, "code": "E_COOLDOWN",
                "message": f"启动过于频繁，请 {int(_COOLDOWN_UNTIL[cid] - now) + 1} 秒后重试",
                "retry_after_s": int(_COOLDOWN_UNTIL[cid] - now) + 1}
    if _ATTEMPTS.get(cid, 0) >= MAX_ATTEMPTS:
        return {"ok": False, "code": "E_MAX_ATTEMPTS",
                "message": "已达到最大尝试次数；请查看日志或按帮助手工启动",
                "retry_after_s": 0}

    if cid == "sidecar":
        url = _sidecar_url()
        parsed = urlparse(url)
        host, port = parsed.hostname or "127.0.0.1", parsed.port or 8765
        if _port_open(host, port):
            ok, _ = _health(url)
            if ok:
                return {"ok": True, "code": "E_ALREADY_RUNNING",
                        "message": "检测到 Sidecar 已在运行，已直接接管", "retry_after_s": 0}
            return {"ok": False, "code": "E_PORT_CONFLICT",
                    "message": f"端口 {port} 被其他进程占用，未重复启动；请先结束冲突进程",
                    "retry_after_s": 0}
        cmd = _cmd_from_env("CG_SIDECAR_CMD_JSON")
        log_name = "sidecar"
    else:
        path = _wechat_path()
        cmd = [path] if path else None
        log_name = "wechat"

    if not cmd:
        return {"ok": False, "code": "E_NOT_CONFIGURED",
                "message": "未配置启动命令，无法自动拉起", "retry_after_s": 0}

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{log_name}.log"
    log_fh = log_path.open("a", encoding="utf-8")
    log_fh.write(f"\n=== start {_now()} ===\n")
    log_fh.flush()
    try:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log_fh, stderr=subprocess.STDOUT)
    except Exception as exc:
        _ATTEMPTS[cid] = _ATTEMPTS.get(cid, 0) + 1
        _COOLDOWN_UNTIL[cid] = time.time() + COOLDOWN_S
        log_fh.close()
        return {"ok": False, "code": "E_SPAWN_FAILED",
                "message": f"无法启动：{str(exc)[:200]}",
                "log_tail": _tail(log_path), "retry_after_s": COOLDOWN_S}

    _PROCS[cid] = proc
    deadline = time.time() + HEALTH_TIMEOUT_S
    while time.time() < deadline:
        if cid == "sidecar":
            ok, _ = _health(_sidecar_url())
            if ok:
                _ATTEMPTS[cid] = 0
                log_fh.close()
                return {"ok": True, "code": "OK", "message": "Sidecar 已启动并通过健康检查",
                        "pid": proc.pid, "log_tail": _tail(log_path), "retry_after_s": 0}
        else:
            if proc.poll() is not None:
                break
            time.sleep(0.3)
            if time.time() >= deadline - HEALTH_TIMEOUT_S + 1.5 and proc.poll() is None:
                _ATTEMPTS[cid] = 0
                log_fh.close()
                return {"ok": True, "code": "OK", "message": "微信引擎进程已启动",
                        "pid": proc.pid, "log_tail": _tail(log_path), "retry_after_s": 0}
        if proc.poll() is not None:
            break
        time.sleep(0.4)

    _ATTEMPTS[cid] = _ATTEMPTS.get(cid, 0) + 1
    _COOLDOWN_UNTIL[cid] = time.time() + COOLDOWN_S
    alive = proc.poll() is None
    if alive:
        try:
            proc.terminate()
        except Exception:
            pass
    log_fh.close()
    return {
        "ok": False,
        "code": "E_START_TIMEOUT" if alive else "E_START_FAILED",
        "message": "启动超时，未通过健康检查" if alive else "进程已退出，启动失败",
        "log_tail": _tail(log_path),
        "retry_after_s": COOLDOWN_S,
        "attempts": _ATTEMPTS[cid],
    }


def stop_component(cid: str) -> dict:
    proc = _PROCS.get(cid)
    if not proc or proc.poll() is not None:
        return {"ok": True, "message": "进程未运行"}
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return {"ok": True, "message": "已停止本进程启动的组件"}


def get_log(cid: str, lines: int = 60) -> str:
    return _tail(LOG_DIR / f"{cid}.log", lines)

