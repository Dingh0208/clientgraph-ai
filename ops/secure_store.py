# -*- coding: utf-8 -*-
"""Server-side secure configuration for the single-owner web instance.

Secrets (owner password hash, session secret, model API keys) live only in this
file and in process memory. They are never returned by the settings API, never
written to the frontend bundle, browser storage, URLs or logs.
"""
from __future__ import annotations

import copy
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from .auth import AuthError, SessionManager, hash_password, verify_password

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "clientgraph.settings.v1"
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DEFAULT_SETTINGS = {
    "profile": {
        "display_name": "老板",
        "email": "",
        "timezone": "Asia/Shanghai",
        "language": "zh-CN",
    },
    "import": {
        "default_customer_id": "",
        "default_project_id": "",
        "duplicate_policy": "ask",
        "auto_archive": False,
        "date_format": "YYYY-MM-DD",
    },
    "models": {
        "text_model": "qwen3.8-flash",
        "speech_model": "qwen3-asr-flash",
        "text_base_url": "",
        "speech_base_url": "",
    },
    "notifications": {
        "desktop": True,
        "daily_digest": False,
        "digest_time": "09:00",
        "quiet_hours": "22:00-08:00",
        "overdue_only": False,
    },
    "privacy": {
        "backup_enabled": False,
        "backup_dir": "",
        "retention_days": 90,
        "external_hide_internal": True,
    },
}

ENUMS = {
    ("import", "duplicate_policy"): {"ask", "skip", "merge"},
}


class SecureStoreError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def default_config_dir() -> Path:
    override = os.environ.get("CG_CONFIG_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "ClientGraphAI"
    return Path.home() / ".config" / "clientgraph-ai"


def app_version() -> str:
    if os.environ.get("CG_VERSION"):
        return os.environ["CG_VERSION"]
    version_file = ROOT / "VERSION"
    try:
        return version_file.read_text(encoding="utf-8").strip() or "0.4.0"
    except OSError:
        return "0.4.0"


def _merge_defaults(data: dict) -> dict:
    out = copy.deepcopy(DEFAULT_SETTINGS)
    for section, values in (data or {}).items():
        if section in out and isinstance(values, dict):
            out[section].update({k: v for k, v in values.items() if k in out[section]})
    return out


class SecureSettings:
    def __init__(self, config_dir: Path | str | None = None,
                 iterations: int = 240_000):
        self.dir = Path(config_dir) if config_dir else default_config_dir()
        self.path = self.dir / "secure.json"
        self.iterations = iterations
        self.data = self._load()
        changed = False
        if "session_secret" not in self.data:
            self.data["session_secret"] = secrets.token_hex(32)
            changed = True
        if "session_epoch" not in self.data:
            self.data["session_epoch"] = 1
            changed = True
        if "models" not in self.data:
            self.data["models"] = {}
            changed = True
        if "settings" not in self.data:
            self.data["settings"] = {}
            changed = True
        if changed:
            self.save()

    # ---------------------------------------------------------------- storage
    def _load(self) -> dict:
        if not self.path.exists():
            return {"schema": 1, "settings": {}, "models": {}}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SecureStoreError("E_CONFIG_CORRUPT",
                                   f"安全配置无法读取：{self.path}（{exc}）")

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass
        tmp = self.path.with_suffix(".tmp")
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)

    # ---------------------------------------------------------------- password
    def has_password(self) -> bool:
        return bool(os.environ.get("CG_ADMIN_PASSWORD")) or bool(self.data.get("password"))

    def set_password(self, password: str):
        self.data["password"] = hash_password(password, self.iterations)
        self.data["session_epoch"] = int(self.data.get("session_epoch") or 1) + 1
        self.data["password_updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def verify_owner(self, password: str) -> bool:
        env_password = os.environ.get("CG_ADMIN_PASSWORD")
        if env_password:
            return secrets.compare_digest(str(password or ""), env_password)
        return verify_password(password, self.data.get("password"))

    # ---------------------------------------------------------------- session
    def session_manager(self) -> SessionManager:
        return SessionManager(self.data["session_secret"],
                             epoch=int(self.data.get("session_epoch") or 1))

    def issue_token(self) -> str:
        return self.session_manager().issue()

    def verify_token(self, token: str | None) -> bool:
        return self.session_manager().verify(token)

    # ---------------------------------------------------------------- models
    def model_key(self, target: str) -> tuple[str, str]:
        env_name = "CG_TEXT_API_KEY" if target == "text" else "CG_SPEECH_API_KEY"
        if os.environ.get(env_name):
            return os.environ[env_name], "env"
        value = (self.data.get("models") or {}).get(f"{target}_api_key") or ""
        return value, ("file" if value else "none")

    def set_model_key(self, target: str, value: str):
        if target not in ("text", "speech"):
            raise SecureStoreError("E_MODEL_TARGET", "模型类型只能是 text 或 speech")
        env_name = "CG_TEXT_API_KEY" if target == "text" else "CG_SPEECH_API_KEY"
        if os.environ.get(env_name):
            raise SecureStoreError("E_KEY_MANAGED_BY_ENV",
                                   f"{env_name} 已由服务端环境变量管理，不能在页面覆盖")
        key = str(value or "").strip()
        if not key:
            raise SecureStoreError("E_EMPTY_KEY", "密钥不能为空")
        self.data.setdefault("models", {})[f"{target}_api_key"] = key
        self.save()

    def clear_model_key(self, target: str):
        env_name = "CG_TEXT_API_KEY" if target == "text" else "CG_SPEECH_API_KEY"
        if os.environ.get(env_name):
            raise SecureStoreError("E_KEY_MANAGED_BY_ENV",
                                   f"{env_name} 已由服务端环境变量管理，不能在页面清除")
        (self.data.get("models") or {}).pop(f"{target}_api_key", None)
        self.save()

    # ---------------------------------------------------------------- settings
    def settings(self) -> dict:
        return _merge_defaults(self.data.get("settings") or {})

    def public(self) -> dict:
        settings = self.settings()
        models = dict(settings["models"])
        for target in ("text", "speech"):
            value, source = self.model_key(target)
            models[f"{target}_key"] = {"configured": bool(value), "source": source}
        settings["models"] = models
        return {
            "schema": SCHEMA,
            "profile": settings["profile"],
            "import": settings["import"],
            "models": models,
            "notifications": settings["notifications"],
            "privacy": settings["privacy"],
            "version": {
                "app": app_version(),
                "schema": 1,
                "config_path": str(self.path),
                "auth_mode": "single_owner",
            },
        }

    def update(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise SecureStoreError("E_INVALID_SETTINGS", "设置必须是对象")
        current = self.settings()

        for section in DEFAULT_SETTINGS:
            if section not in payload:
                continue
            values = payload[section]
            if not isinstance(values, dict):
                raise SecureStoreError("E_INVALID_SETTINGS", f"{section} 必须是对象")
            for key, value in values.items():
                if key not in DEFAULT_SETTINGS[section]:
                    raise SecureStoreError("E_INVALID_SETTING",
                                           f"未知设置项：{section}.{key}")
                self._validate(section, key, value)
                current[section][key] = value

        text_key = payload.get("text_api_key")
        speech_key = payload.get("speech_api_key")
        if text_key:
            self.set_model_key("text", text_key)
        if speech_key:
            self.set_model_key("speech", speech_key)
        if payload.get("clear_text_key"):
            self.clear_model_key("text")
        if payload.get("clear_speech_key"):
            self.clear_model_key("speech")

        self.data["settings"] = current
        self.data["settings_updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save()
        return self.public()

    def _validate(self, section: str, key: str, value):
        default = DEFAULT_SETTINGS[section][key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise SecureStoreError("E_INVALID_SETTING", f"{section}.{key} 必须是布尔值")
            return
        if isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, int):
                raise SecureStoreError("E_INVALID_SETTING", f"{section}.{key} 必须是整数")
            if key == "retention_days" and not 1 <= value <= 3650:
                raise SecureStoreError("E_INVALID_SETTING", "保留天数需在 1–3650 之间")
            return
        if not isinstance(value, str):
            raise SecureStoreError("E_INVALID_SETTING", f"{section}.{key} 必须是文本")
        text = value.strip()
        if key == "email" and text and not EMAIL_RE.match(text):
            raise SecureStoreError("E_INVALID_EMAIL", "邮箱格式不正确")
        if key in ("digest_time",) and not TIME_RE.match(text):
            raise SecureStoreError("E_INVALID_TIME", "时间格式应为 HH:MM")
        if key == "quiet_hours":
            parts = text.split("-")
            if len(parts) != 2 or not all(TIME_RE.match(p.strip()) for p in parts):
                raise SecureStoreError("E_INVALID_TIME", "免打扰时段应为 HH:MM-HH:MM")
        if (section, key) in ENUMS and text not in ENUMS[(section, key)]:
            raise SecureStoreError("E_INVALID_SETTING", f"{section}.{key} 取值不支持")
        if key.endswith("_base_url") and text and not re.match(r"^https?://", text):
            raise SecureStoreError("E_INVALID_URL", "接口地址必须以 http:// 或 https:// 开头")

    def backup(self) -> dict:
        return {
            "schema": "clientgraph.settings.backup.v1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "note": "不包含密码、会话密钥与模型密钥",
            "settings": self.public(),
        }

    def test_model(self, target: str, live: bool = False) -> dict:
        if target not in ("text", "speech"):
            raise SecureStoreError("E_MODEL_TARGET", "模型类型只能是 text 或 speech")
        settings = self.settings()["models"]
        key, source = self.model_key(target)
        model = settings.get(f"{target}_model")
        base_url = settings.get(f"{target}_base_url")
        result = {
            "target": target,
            "model": model,
            "base_url": base_url,
            "key_configured": bool(key),
            "key_source": source,
            "live": bool(live),
            "network_attempted": False,
            "model_called": False,
        }
        if not key:
            result.update({"ok": False, "code": "E_KEY_MISSING",
                           "message": "尚未配置模型密钥"})
            return result
        if not live:
            result.update({"ok": True, "code": "CONFIG_OK",
                           "message": "配置完整；未发起网络请求，也未调用模型"})
            return result
        if not base_url:
            result.update({"ok": False, "code": "E_NO_ENDPOINT",
                           "message": "未配置接口地址，无法做连通性探测"})
            return result
        result["network_attempted"] = True
        import urllib.error
        import urllib.request
        try:
            request = urllib.request.Request(base_url, method="HEAD",
                                             headers={"User-Agent": "ClientGraphAI/probe"})
            with urllib.request.urlopen(request, timeout=5) as response:
                result.update({"ok": True, "code": "ENDPOINT_OK",
                               "status": response.status,
                               "message": "接口地址可达；未发送模型请求"})
        except urllib.error.HTTPError as exc:
            result.update({"ok": True, "code": "ENDPOINT_REACHED",
                           "status": exc.code,
                           "message": f"接口可达（HTTP {exc.code}）；未发送模型请求"})
        except Exception as exc:  # noqa: BLE001
            result.update({"ok": False, "code": "E_ENDPOINT_UNREACHABLE",
                           "message": f"接口地址不可达：{type(exc).__name__}"})
        return result
