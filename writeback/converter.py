# -*- coding: utf-8 -*-
"""Turn a client answer into a requirement or a project update.

Safety rules:
- the caller must pick the target customer/project first; nothing is inferred;
- only fields explicitly supported by the answer are pre-filled, everything
  else is left untouched;
- a new requirement is always created as "待确认";
- requirement P0/P1/P2 is judged by its own rules, never copied from the
  clarification question priority;
- nothing is written until a human confirms the preview, and every write keeps
  a before/after snapshot plus an append-only requirement version.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone

DATE = re.compile(r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})\s*日?")
VAGUE_DATE = re.compile(r"月底|月初|尽快|下周[一二三四五六日天]?|本月|下个月|之后|晚点|越快越好|左右")
AMOUNT = re.compile(r"(?:预算|报价|总价|合同金额|费用|价格)[^0-9]{0,6}([\d,]+(?:\.\d+)?)\s*(万|万元|元|块)")
OWNER = re.compile(r"负责人\s*[:：]\s*([^\s，。；、]{2,8})|由\s*([\u4e00-\u9fa5]{2,4})\s*负责")
SCOPE_OUT = re.compile(r"(?:不包含|不包括|不做|不进入|范围外|排除|砍掉)[:：]?\s*([^，。；、\s]{2,20})")
SCOPE_IN = re.compile(r"(?<!不)(?:包含|包括|要做|需要|上线)[:：]?\s*([^，。；、\s]{2,20})")
REQ_CUE = re.compile(r"要|需要|支持|包含|不做|改成|增加|新增|上线|对接|迁移|导出|审批")
PLATFORMS = [
    ("微信小程序", re.compile(r"微信小程序|小程序")),
    ("App", re.compile(r"\bapp\b|安卓|ios", re.I)),
    ("H5", re.compile(r"\bh5\b|网页|web", re.I)),
    ("钉钉", re.compile(r"钉钉")),
    ("企业微信", re.compile(r"企业微信")),
]

PRIORITY_LABELS = {"P0": "P0 阻塞上线/签约", "P1": "P1 核心需求", "P2": "P2 可延后"}

FIELD_LABELS = {
    "title": "标题",
    "description": "描述",
    "due_text": "截止时间",
    "owner": "负责人",
    "status": "状态",
    "budget": "预算",
    "schedule": "工期",
    "platform": "平台",
    "scope_in": "本期包含",
    "scope_out": "本期不包含",
}

REQUIREMENT_STATUS = "待确认"


class WritebackError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _iso(at) -> str:
    if isinstance(at, str):
        return at
    if at is None:
        at = datetime.now(timezone.utc)
    return at.isoformat()


def _find(rows, key, value):
    return next((r for r in rows or [] if r.get(key) == value), None)


def _fingerprint(record) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _explicit_date(text: str) -> str | None:
    m = DATE.search(text or "")
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, d).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _amount(text: str):
    m = AMOUNT.search(text or "")
    if not m:
        return None
    try:
        num = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = m.group(2)
    value = int(num * 10000) if unit in ("万", "万元") else int(num)
    return {"amount": value, "raw": f"{m.group(1)} {unit}".strip()}


def _owner(text: str) -> str | None:
    m = OWNER.search(text or "")
    if not m:
        return None
    return m.group(1) or m.group(2)


def _platform(text: str) -> str | None:
    for name, pattern in PLATFORMS:
        if pattern.search(text or ""):
            return name
    return None


def suggest_requirement_priority(text: str) -> dict:
    """Requirement P0/P1/P2 by its own rules.

    This deliberately ignores the clarification question tier: a "later"
    question can still describe a P0 requirement, and a "must_confirm"
    question can end with a P2 nice-to-have.
    """
    body = text or ""
    if re.search(r"二期|以后|后续|优化|可选|不急|暂不|最好|锦上添花", body):
        return {"value": "P2", "label": PRIORITY_LABELS["P2"],
                "basis": "回答明确指向二期/优化/可延后"}
    if re.search(r"上线前|必须|合同|合规|安全|阻塞|验收必需|不能少|红线", body):
        return {"value": "P0", "label": PRIORITY_LABELS["P0"],
                "basis": "回答含上线/合同/合规等硬约束，缺失会阻塞交付"}
    return {"value": "P1", "label": PRIORITY_LABELS["P1"],
            "basis": "属于正常一期需求，未出现硬约束或延后信号"}


def _change(field: str, before, after, evidence: list[dict], supported_by: str) -> dict:
    return {
        "field": field,
        "label": FIELD_LABELS[field],
        "before": copy.deepcopy(before),
        "after": copy.deepcopy(after),
        "supported_by": supported_by,
        "evidence": copy.deepcopy(evidence),
    }


def _resolve_target(target: dict, catalog: dict) -> dict:
    if not isinstance(target, dict):
        raise WritebackError("E_TARGET_REQUIRED", "必须先选择目标客户和项目")
    kind = target.get("kind")
    if kind not in ("requirement", "project"):
        raise WritebackError("E_TARGET_KIND", "目标类型只能是 requirement 或 project")
    customer_id = _clean(target.get("customer_id"))
    project_id = _clean(target.get("project_id"))
    if not customer_id or not project_id:
        raise WritebackError("E_TARGET_REQUIRED", "必须先选择目标客户和项目")

    customer = _find(catalog.get("customers"), "id", customer_id)
    if customer is None:
        raise WritebackError("E_CUSTOMER_NOT_FOUND", f"客户不存在：{customer_id}")
    project = _find(catalog.get("projects"), "id", project_id)
    if project is None:
        raise WritebackError("E_PROJECT_NOT_FOUND", f"项目不存在：{project_id}")
    if project.get("customer_id") not in (None, customer_id):
        raise WritebackError("E_TARGET_MISMATCH", "项目不属于所选客户")

    requirement = None
    if kind == "requirement" and target.get("requirement_id"):
        requirement = _find(catalog.get("requirements"), "id", target["requirement_id"])
        if requirement is None:
            raise WritebackError("E_REQUIREMENT_NOT_FOUND",
                                 f"需求不存在：{target['requirement_id']}")
        if requirement.get("project_id") not in (None, project_id):
            raise WritebackError("E_TARGET_MISMATCH", "需求不属于所选项目")

    return {
        "kind": kind,
        "customer": customer,
        "project": project,
        "requirement": requirement,
        "action": ("update_requirement" if requirement is not None
                   else "create_requirement" if kind == "requirement"
                   else "update_project"),
    }


def _requirement_fields(answer: dict, requirement: dict | None) -> tuple[list[dict], list[dict]]:
    text = _clean(answer.get("text"))
    evidence = answer.get("evidence") or []
    fields, skipped = [], []
    date = _explicit_date(text)
    owner = _owner(text)

    if requirement is None:
        label = _clean(answer.get("question_field_label"))
        structured = _explicit_date(text) or _owner(text) or _platform(text) or _amount(text)
        if isinstance(structured, dict):
            structured = structured["raw"]
        summary = re.sub(r"[。；;，,]+$", "", structured or text)
        if len(summary) > 18:
            summary = summary[:18]
        title = f"{label}：{summary}" if label else summary
        fields.append(_change("title", None, title, evidence, text))
        fields.append(_change("description", None, text, evidence, text))
    elif len(text) >= 6 and REQ_CUE.search(text):
        fields.append(_change("description", requirement.get("description"), text,
                              evidence, text))
    else:
        skipped.append({"field": "description", "label": FIELD_LABELS["description"],
                        "reason": "回答不是需求描述，未覆盖原描述"})

    before_due = requirement.get("due_text") if requirement else None
    if date:
        fields.append(_change("due_text", before_due, date, evidence, date))
    elif VAGUE_DATE.search(text):
        skipped.append({"field": "due_text", "label": FIELD_LABELS["due_text"],
                        "reason": "回答只有模糊时间，未预填截止时间"})
    else:
        skipped.append({"field": "due_text", "label": FIELD_LABELS["due_text"],
                        "reason": "回答未给出明确日期"})

    before_owner = requirement.get("owner") if requirement else None
    if owner:
        fields.append(_change("owner", before_owner, owner, evidence, owner))
    else:
        skipped.append({"field": "owner", "label": FIELD_LABELS["owner"],
                        "reason": "回答未明确负责人"})

    skipped.append({"field": "status", "label": FIELD_LABELS["status"],
                    "reason": "状态不自动回填；新需求固定待确认"})
    return fields, skipped


def _project_fields(answer: dict, project: dict) -> tuple[list[dict], list[dict]]:
    text = _clean(answer.get("text"))
    evidence = answer.get("evidence") or []
    fields, skipped = [], []

    amount = _amount(text)
    if amount:
        before = project.get("budget")
        if before != amount:
            fields.append(_change("budget", before, amount, evidence, amount["raw"]))
    else:
        skipped.append({"field": "budget", "label": FIELD_LABELS["budget"],
                        "reason": "回答未给出明确预算金额"})

    date = _explicit_date(text)
    if date:
        before = project.get("schedule")
        if before != date:
            fields.append(_change("schedule", before, date, evidence, date))
    elif VAGUE_DATE.search(text):
        skipped.append({"field": "schedule", "label": FIELD_LABELS["schedule"],
                        "reason": "回答只有模糊时间，未预填工期"})
    else:
        skipped.append({"field": "schedule", "label": FIELD_LABELS["schedule"],
                        "reason": "回答未给出明确日期"})

    platform = _platform(text)
    if platform:
        before = project.get("platform")
        if before != platform:
            fields.append(_change("platform", before, platform, evidence, platform))
    else:
        skipped.append({"field": "platform", "label": FIELD_LABELS["platform"],
                        "reason": "回答未明确平台"})

    out = SCOPE_OUT.search(text)
    if out:
        entity = out.group(1)
        current = list(project.get("scope_out") or [])
        if entity not in current:
            fields.append(_change("scope_out", current, current + [entity], evidence, entity))
    incl = SCOPE_IN.search(text)
    if incl:
        entity = incl.group(1)
        current = list(project.get("scope_in") or [])
        if entity not in current:
            fields.append(_change("scope_in", current, current + [entity], evidence, entity))

    return fields, skipped


def _token(preview: dict) -> str:
    core = {
        "preview_id": preview["preview_id"],
        "target": {"kind": preview["target"]["kind"],
                   "customer_id": preview["target"]["customer_id"],
                   "project_id": preview["target"]["project_id"],
                   "requirement_id": preview["target"]["requirement_id"]},
        "action": preview["action"],
        "fields": preview["fields"],
        "suggested_priority": preview["suggested_priority"],
        "answer_id": preview["answer"]["id"],
        "target_fingerprint": preview["target_fingerprint"],
    }
    payload = json.dumps(core, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_preview(answer: dict, target: dict, catalog: dict, at=None) -> dict:
    if not isinstance(answer, dict) or not _clean(answer.get("text")):
        raise WritebackError("E_ANSWER_REQUIRED", "缺少甲方回答原文")
    if not answer.get("evidence"):
        raise WritebackError("E_NO_EVIDENCE", "回答没有引用证据，不能回写")

    resolved = _resolve_target(target, catalog)
    action = resolved["action"]
    if action == "create_requirement":
        fields, skipped = _requirement_fields(answer, None)
    elif action == "update_requirement":
        fields, skipped = _requirement_fields(answer, resolved["requirement"])
    else:
        fields, skipped = _project_fields(answer, resolved["project"])

    # Drop no-op changes; keep only fields the answer really moves.
    fields = [f for f in fields if f["before"] != f["after"]]

    stamp = _iso(at)
    target_record = resolved["requirement"] if resolved["requirement"] else resolved["project"]
    preview = {
        "schema": "clientgraph.writeback_preview.v1",
        "preview_id": "PV-" + hashlib.sha1(
            f"{answer.get('id')}|{target_record.get('id')}|{stamp}".encode("utf-8")
        ).hexdigest()[:8],
        "created_at": stamp,
        "action": action,
        "target": {
            "kind": resolved["kind"],
            "customer_id": resolved["customer"]["id"],
            "customer_name": resolved["customer"].get("name"),
            "project_id": resolved["project"]["id"],
            "project_name": resolved["project"].get("name"),
            "requirement_id": (resolved["requirement"] or {}).get("id"),
            "requirement_title": (resolved["requirement"] or {}).get("title"),
        },
        "target_fingerprint": _fingerprint(target_record),
        "answer": {
            "id": answer.get("id"),
            "question_id": answer.get("question_id"),
            "question_text": answer.get("question_text"),
            "question_priority": answer.get("question_priority"),
            "text": answer.get("text"),
            "answered_at": answer.get("answered_at"),
            "operator": answer.get("operator"),
            "evidence": copy.deepcopy(answer.get("evidence") or []),
        },
        "fields": fields,
        "skipped": skipped,
        "suggested_priority": None,
        "new_requirement": None,
        "requires_confirmation": True,
        "confirmed": False,
        "writes": False,
    }

    priority = suggest_requirement_priority(answer.get("text"))
    priority["source"] = "requirement_rule"
    priority["independent_of_question_priority"] = True
    priority["question_priority_ignored"] = answer.get("question_priority")
    preview["suggested_priority"] = priority

    if action == "create_requirement":
        preview["new_requirement"] = {
            "status": REQUIREMENT_STATUS,
            "priority": priority["value"],
            "review_state": "pending",
        }
    preview["token"] = _token(preview)
    return preview


def _require_confirmation(preview: dict, confirmed_by: str, confirm: bool,
                          token: str | None):
    if not confirm:
        raise WritebackError("E_CONFIRM_REQUIRED", "必须人工确认后才能保存")
    operator = _clean(confirmed_by)
    if not operator:
        raise WritebackError("E_CONFIRMER_REQUIRED", "必须记录确认人")
    if token is not None and token != preview.get("token"):
        raise WritebackError("E_PREVIEW_CHANGED", "预览已变化，请重新生成预览")
    if preview.get("token") != _token(preview):
        raise WritebackError("E_PREVIEW_TAMPERED", "预览内容被修改，拒绝保存")
    return operator


def _check_fresh(preview: dict, catalog: dict):
    resolved = _resolve_target(preview["target"], catalog)
    record = resolved["requirement"] if resolved["requirement"] else resolved["project"]
    if _fingerprint(record) != preview["target_fingerprint"]:
        raise WritebackError("E_TARGET_CHANGED", "目标记录已变化，请重新预览")


def _next_id(rows: list[dict], prefix: str) -> str:
    nums = []
    for row in rows:
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", str(row.get("id") or ""))
        if m:
            nums.append(int(m.group(1)))
    return f"{prefix}{max(nums) + 1 if nums else 1}"


def apply_preview(preview: dict, store: dict, confirmed_by: str,
                  confirm: bool = False, token: str | None = None,
                  at=None) -> dict:
    """Write after human confirmation; returns the operation snapshot."""
    operator = _require_confirmation(preview, confirmed_by, confirm, token)
    if preview.get("action") == "create_requirement" and preview["target"].get("requirement_id"):
        raise WritebackError("E_INVALID_PREVIEW", "新建需求不能带需求编号")

    catalog = {
        "customers": store.get("customers") or [],
        "projects": store.get("projects") or [],
        "requirements": store.get("requirements") or [],
    }
    _check_fresh(preview, catalog)

    applied = store.setdefault("applied_previews", [])
    if preview["preview_id"] in applied:
        raise WritebackError("E_ALREADY_APPLIED", "该预览已保存过，不能重复提交")

    stamp = _iso(at)
    action = preview["action"]
    requirement_row = None
    version_row = None
    project_row = None

    if action == "create_requirement":
        requirements = store.setdefault("requirements", [])
        data = {f["field"]: f["after"] for f in preview["fields"]}
        requirement_row = {
            "id": _next_id(requirements, "R"),
            "customer_id": preview["target"]["customer_id"],
            "project_id": preview["target"]["project_id"],
            "title": data.get("title") or preview["answer"]["text"][:30],
            "description": data.get("description") or preview["answer"]["text"],
            "status": REQUIREMENT_STATUS,
            "priority": preview["suggested_priority"]["value"],
            "priority_source": "requirement_rule",
            "due_text": data.get("due_text"),
            "owner": data.get("owner"),
            "current_version": 1,
            "origin": "clarification",
            "review_state": "pending",
            "confirmed_at": None,
            "source_question_id": preview["answer"]["question_id"],
            "source_answer_id": preview["answer"]["id"],
            "source_excerpt": preview["answer"]["text"][:200],
            "evidence": copy.deepcopy(preview["answer"]["evidence"]),
            "created_at": stamp,
            "updated_at": stamp,
        }
        requirements.append(requirement_row)
        versions = store.setdefault("versions", [])
        version_row = {
            "id": _next_id(versions, "V"),
            "requirement_id": requirement_row["id"],
            "version": 1,
            "content_json": copy.deepcopy(requirement_row),
            "change_reason": "由澄清回答创建",
            "source_question_id": preview["answer"]["question_id"],
            "source_answer_id": preview["answer"]["id"],
            "adopted_at": stamp,
            "created_at": stamp,
        }
        versions.append(version_row)
        before = None
        after = copy.deepcopy(requirement_row)

    elif action == "update_requirement":
        requirement_row = _find(store.get("requirements"), "id",
                                preview["target"]["requirement_id"])
        if requirement_row is None:
            raise WritebackError("E_REQUIREMENT_NOT_FOUND", "需求已不存在")
        before = copy.deepcopy(requirement_row)
        for change in preview["fields"]:
            requirement_row[change["field"]] = copy.deepcopy(change["after"])
        next_version = max([v["version"] for v in store.get("versions") or []
                            if v["requirement_id"] == requirement_row["id"]] or [0]) + 1
        requirement_row["current_version"] = next_version
        requirement_row["updated_at"] = stamp
        after = copy.deepcopy(requirement_row)
        versions = store.setdefault("versions", [])
        version_row = {
            "id": _next_id(versions, "V"),
            "requirement_id": requirement_row["id"],
            "version": next_version,
            "content_json": copy.deepcopy(requirement_row),
            "change_reason": "由澄清回答更新：" + "、".join(f["label"] for f in preview["fields"]),
            "source_question_id": preview["answer"]["question_id"],
            "source_answer_id": preview["answer"]["id"],
            "adopted_at": stamp,
            "created_at": stamp,
        }
        versions.append(version_row)

    else:
        project_row = _find(store.get("projects"), "id", preview["target"]["project_id"])
        if project_row is None:
            raise WritebackError("E_PROJECT_NOT_FOUND", "项目已不存在")
        before = copy.deepcopy(project_row)
        for change in preview["fields"]:
            project_row[change["field"]] = copy.deepcopy(change["after"])
        project_row["updated_at"] = stamp
        after = copy.deepcopy(project_row)

    operations = store.setdefault("operations", [])
    operation = {
        "id": _next_id(operations, "W"),
        "preview_id": preview["preview_id"],
        "action": action,
        "customer_id": preview["target"]["customer_id"],
        "project_id": preview["target"]["project_id"],
        "requirement_id": (requirement_row or {}).get("id"),
        "question_id": preview["answer"]["question_id"],
        "answer_id": preview["answer"]["id"],
        "question_text": preview["answer"]["question_text"],
        "answer_text": preview["answer"]["text"],
        "answer_at": preview["answer"]["answered_at"],
        "evidence": copy.deepcopy(preview["answer"]["evidence"]),
        "changes": copy.deepcopy(preview["fields"]),
        "priority": (copy.deepcopy(preview["suggested_priority"])
                     if action == "create_requirement" else None),
        "status_after": (requirement_row or {}).get("status"),
        "confirmed_by": operator,
        "confirmed_at": stamp,
        "target_before": before,
        "target_after": after,
        "applied": True,
    }
    operations.append(operation)
    applied.append(preview["preview_id"])

    return {
        "operation": copy.deepcopy(operation),
        "requirement": copy.deepcopy(requirement_row),
        "project": copy.deepcopy(project_row),
        "version": copy.deepcopy(version_row),
    }
