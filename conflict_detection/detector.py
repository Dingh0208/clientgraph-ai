# -*- coding: utf-8 -*-
"""Conflict detection across budget, timeline, scope, owner, platform,
interface, permission and acceptance criteria.

The detector never chooses a value. A conflict is a separate, blocking record;
the caller must ask a human to confirm. Existing records are not mutated.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

DIMENSIONS = ["budget", "timeline", "scope", "owner", "platform",
              "interface", "permission", "acceptance"]

LABELS = {
    "budget": "预算", "timeline": "工期", "scope": "范围", "owner": "负责人",
    "platform": "平台", "interface": "接口", "permission": "权限",
    "acceptance": "验收标准",
}

PLATFORM_MAP = [
    ("微信小程序", re.compile(r"微信小程序|小程序")),
    ("App", re.compile(r"\bapp\b|安卓|ios", re.I)),
    ("H5", re.compile(r"\bh5\b|网页|web", re.I)),
    ("钉钉", re.compile(r"钉钉")),
    ("企业微信", re.compile(r"企业微信")),
]
INTERFACE_MAP = [
    ("ERP", re.compile(r"\berp\b", re.I)),
    ("OA", re.compile(r"\boa\b", re.I)),
    ("财务系统", re.compile(r"财务系统|用友|金蝶")),
    ("短信", re.compile(r"短信")),
    ("企业微信", re.compile(r"企业微信")),
]


def _nfkc(text) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def normalize_value(dimension: str, value, raw: str = "") -> str | None:
    text = _nfkc(raw or value)
    if dimension == "budget":
        m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(万|万元|元|块)?", text)
        if not m:
            return None
        num = float(m.group(1).replace(",", ""))
        if m.group(2) in ("万", "万元"):
            num *= 10000
        return str(int(round(num)))
    if dimension == "timeline":
        m = re.search(r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})\s*日?", text)
        if not m:
            return None
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return None
    if dimension == "scope":
        s = text.lower()
        m = re.search(r"(include|exclude)\s*[:：]\s*(.+)", s)
        if m:
            mode, entity = m.group(1), m.group(2)
        else:
            mode = "exclude" if re.search(r"不|取消|不做|不进入|排除", s) else "include"
            entity = s
        entity = re.sub(r"(不|取消|不做|不进入|排除|包含|include|exclude|范围|[:：])", "", entity).strip()
        return f"{entity}:{mode}" if entity else None
    if dimension == "owner":
        s = re.sub(r"^负责人\s*[:：]\s*", "", text)
        return re.sub(r"\s+", "", s).lower() or None
    if dimension == "platform":
        for name, pattern in PLATFORM_MAP:
            if pattern.search(text):
                return name
        return re.sub(r"\s+", "", text).lower() or None
    if dimension == "interface":
        for name, pattern in INTERFACE_MAP:
            if pattern.search(text):
                return name
        return re.sub(r"\s+", "", text).lower() or None
    # permission / acceptance: exact normalized text
    s = re.sub(r"[\s，。；、,.;:：()（）]+", "", text).lower()
    return s or None


def _source(obs: dict) -> dict:
    src = obs.get("source") or {}
    return {
        "file": src.get("file") or obs.get("file") or "unknown",
        "source_type": src.get("source_type") or obs.get("source_type") or "unknown",
        "locator": src.get("locator"),
        "occurred_at": src.get("occurred_at") or obs.get("occurred_at"),
    }


def _question(dimension: str, a: dict, b: dict) -> str:
    label = LABELS.get(dimension, dimension)
    if dimension == "scope":
        entity = (a["normalized"].split(":", 1)[0] if ":" in a["normalized"] else "该范围")
        return f"范围在“{entity}”上出现包含与不包含两种口径，请确认以哪个为准。"
    return f"{label}出现“{a['raw']}”与“{b['raw']}”两种口径，请确认以哪个为准。"


def detect(observations: list[dict], context: dict, tasks: list[dict] | None = None) -> dict:
    context = context or {}
    tasks = tasks or []
    project_default = context.get("project") or {"id": "p_unknown", "name": "未命名项目"}
    customer_default = context.get("customer") or {"id": "c_unknown", "name": "未命名客户"}
    projects = {p["id"]: p for p in context.get("projects") or []}
    customers = {c["id"]: c for c in context.get("customers") or []}
    requirements = {r["id"]: r for r in context.get("requirements") or []}
    requirements.update({r.get("key"): r for r in context.get("requirements") or [] if r.get("key")})

    groups: dict[tuple, list[dict]] = {}
    for obs in observations:
        dim = obs.get("dimension")
        if dim not in DIMENSIONS:
            continue
        norm = normalize_value(dim, obs.get("value"), obs.get("raw"))
        if norm is None:
            continue
        pid = obs.get("project_id") or project_default.get("id")
        scope_key = obs.get("requirement_key") or obs.get("requirement_id") or "project"
        groups.setdefault((pid, dim, scope_key), []).append({**obs, "_norm": norm})

    conflicts = []
    for (pid, dim, scope_key), obs_list in groups.items():
        values = {}
        for obs in obs_list:
            values.setdefault(obs["_norm"], obs)
        if len(values) < 2:
            continue
        ordered = sorted(obs_list, key=lambda o: (_source(o).get("occurred_at") or "", _source(o)["file"]))
        a = ordered[0]
        b = next(o for o in ordered if o["_norm"] != a["_norm"])
        project = projects.get(pid, project_default)
        customer = customers.get(project.get("customer_id"), customer_default)
        req = requirements.get(scope_key) if scope_key != "project" else None

        task_ids = []
        for o in obs_list:
            for t in o.get("task_ids") or []:
                if t not in task_ids:
                    task_ids.append(t)
        for t in tasks:
            if req and (t.get("requirement_id") == req.get("id") or t.get("requirement_key") == req.get("key")):
                if t["id"] not in task_ids:
                    task_ids.append(t["id"])
            elif not req and t.get("project_id") == pid:
                if t["id"] not in task_ids:
                    task_ids.append(t["id"])

        values_list = []
        for norm, obs in values.items():
            values_list.append({
                "normalized": norm,
                "raw": obs.get("raw") or obs.get("value"),
                "source": _source(obs),
            })

        conflict = {
            "id": f"K{len(conflicts) + 1}",
            "dimension": dim,
            "dimension_label": LABELS.get(dim, dim),
            "status": "must_confirm",
            "value_a": {
                "raw": a.get("raw") or a.get("value"),
                "normalized": a["_norm"],
                "source": _source(a),
            },
            "value_b": {
                "raw": b.get("raw") or b.get("value"),
                "normalized": b["_norm"],
                "source": _source(b),
            },
            "all_values": values_list,
            "extra_value_count": max(0, len(values_list) - 2),
            "question": _question(dim, {"raw": a.get("raw") or a.get("value"), "normalized": a["_norm"]},
                                  {"raw": b.get("raw") or b.get("value"), "normalized": b["_norm"]}),
            "customer": {"id": customer.get("id"), "name": customer.get("name")},
            "project": {"id": project.get("id"), "name": project.get("name")},
            "requirement": ({"id": req.get("id"), "key": req.get("key"), "title": req.get("title")}
                            if req else None),
            "task_ids": task_ids,
            "evidence": [_source(o) for o in ordered],
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "resolution": None,
            "selected_value": None,
            "model_choice": None,
            "auto_resolved": False,
            "write_blocked": True,
            "apply_policy": "requires_user_confirmation",
        }
        conflicts.append(conflict)

    conflicts.sort(key=lambda c: (DIMENSIONS.index(c["dimension"]), c["project"]["id"], c["id"]))
    for i, c in enumerate(conflicts, 1):
        c["id"] = f"K{i}"
    return {
        "schema": "clientgraph.conflicts.v1",
        "conflicts": conflicts,
        "stats": {
            "observations": len(observations),
            "conflicts": len(conflicts),
            "must_confirm": sum(1 for c in conflicts if c["status"] == "must_confirm"),
            "dimensions": sorted({c["dimension"] for c in conflicts}),
            "multi_value": sum(1 for c in conflicts if c["extra_value_count"] > 0),
        },
    }


def observations_from_evidence(items: list[dict]) -> list[dict]:
    """Best-effort observations from evidence text; manual observations are recommended."""
    out = []
    for item in items:
        text = item.get("text") or ""
        src = {
            "file": item.get("source_file") or "unknown",
            "source_type": item.get("source_type") or "unknown",
            "locator": (item.get("sources") or [{}])[0].get("locator"),
            "occurred_at": item.get("occurred_at"),
        }
        base = {"source": src, "requirement_key": item.get("requirement_key"),
                "requirement_id": item.get("requirement_id"),
                "task_ids": item.get("task_ids") or []}

        if re.search(r"预算|报价|总价|合同金额", text):
            m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(万|万元|元|块)", text)
            if m:
                out.append({**base, "dimension": "budget", "value": m.group(0), "raw": m.group(0)})
        for m in re.finditer(r"20\d{2}\s*[-/年.]\s*\d{1,2}\s*[-/月.]\s*\d{1,2}", text):
            out.append({**base, "dimension": "timeline", "value": m.group(0), "raw": m.group(0)})
        m = re.search(r"负责人\s*[:：]\s*([^\s，。；、]{2,8})", text)
        if m:
            out.append({**base, "dimension": "owner", "value": m.group(1), "raw": m.group(1)})
        for name, pattern in PLATFORM_MAP:
            if pattern.search(text):
                out.append({**base, "dimension": "platform", "value": name, "raw": name})
                break
        for name, pattern in INTERFACE_MAP:
            if pattern.search(text):
                out.append({**base, "dimension": "interface", "value": name, "raw": name})
                break
        if "验收" in text:
            out.append({**base, "dimension": "acceptance",
                        "value": text.split("：", 1)[-1], "raw": text.split("：", 1)[-1]})
        if re.search(r"审批|统计看板", text):
            entity = "审批流" if "审批" in text else "统计看板"
            mode = "exclude" if re.search(r"不进入|取消|不做|不包含", text) else "include"
            out.append({**base, "dimension": "scope", "value": f"{mode}:{entity}",
                        "raw": text})
    return out
