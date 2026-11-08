# -*- coding: utf-8 -*-
"""Industry-ordered clarification question plan.

Only relevant dimensions, or dimensions with an explicit/known gap, are shown.
Each question asks exactly one fact.

Every question carries:
- a three-tier priority: must_confirm (blocks scope/quote/schedule),
  important (affects solution or cost), later (can wait until delivery/ops);
- the source excerpt, file, time and why it is asked;
- a fact / inference / unknown marker plus a confidence score;
- a low-confidence hint when the basis is weak;
- both sides' evidence when the sources conflict (never auto-resolved).
"""
from __future__ import annotations

DIMENSIONS = [
    {
        "id": "goals", "order": 1, "label": "业务目标/指标",
        "fields": [
            ("business_goal", "业务目标", "请问这个项目最希望优先达成的业务目标是什么？"),
            ("metrics", "衡量指标", "请问一期用哪些指标衡量目标达成？"),
        ],
    },
    {
        "id": "users", "order": 2, "label": "用户与流程",
        "fields": [
            ("users_roles", "使用角色", "请问一期主要使用角色有哪些？"),
            ("core_flow", "核心流程", "请问核心业务流程从发起到结束经过哪些环节？"),
        ],
    },
    {
        "id": "scope", "order": 3, "label": "一期范围",
        "fields": [
            ("scope_in", "本期包含", "请问一期必须包含哪些功能？"),
            ("scope_out", "本期不包含", "请问哪些功能明确不在一期范围？"),
        ],
    },
    {
        "id": "platform", "order": 4, "label": "平台与交互",
        "fields": [
            ("platform", "平台", "请问一期运行在哪个平台（如微信小程序、Web、App）？"),
            ("interaction", "交互规范", "请问有没有必须遵循的交互或界面规范？"),
        ],
    },
    {
        "id": "migration", "order": 5, "label": "数据迁移",
        "fields": [
            ("migration_source", "来源系统", "请问需要迁移的历史数据来自哪个系统？"),
            ("migration_scope", "迁移范围", "请问需要迁移哪些历史数据范围？"),
        ],
    },
    {
        "id": "interfaces", "order": 6, "label": "接口与第三方",
        "fields": [
            ("interfaces", "外部接口", "请问一期需要对接哪些外部系统或接口？"),
            ("third_party", "第三方服务", "请问是否需要引入第三方服务（如支付、短信、地图）？"),
        ],
    },
    {
        "id": "governance", "order": 7, "label": "权限/安全/合规",
        "fields": [
            ("roles", "角色权限", "请问需要哪些角色和权限边界？"),
            ("security", "安全要求", "请问对数据加密、审计或脱敏有什么要求？"),
            ("compliance", "合规要求", "请问项目需要满足哪些行业合规要求？"),
        ],
    },
    {
        "id": "quality", "order": 8, "label": "性能/可靠性",
        "fields": [
            ("performance", "性能指标", "请问一期最关键的性能指标是什么（如并发量或响应时间）？"),
            ("reliability", "可用性", "请问系统可用性或故障恢复的目标是什么？"),
        ],
    },
    {
        "id": "commercial", "order": 9, "label": "工期/预算/合同",
        "fields": [
            ("schedule", "上线日期", "请问一期期望的上线日期是哪一天？"),
            ("budget", "预算", "请问一期预算上限是多少？"),
            ("contract", "合同主体", "请问合同签约主体是哪一方？"),
        ],
    },
    {
        "id": "delivery", "order": 10, "label": "验收/上线/运维/售后",
        "fields": [
            ("acceptance", "验收标准", "请问一期以哪些可验证条件作为验收标准？"),
            ("launch", "上线批准", "请问上线需要谁批准？"),
            ("ops", "运维责任", "请问上线后由谁负责日常运维？"),
            ("after_sales", "质保期", "请问质保期多长？"),
            ("support", "售后响应", "请问售后响应时限是多少？"),
        ],
    },
]

# field -> (tier, why this tier). Tiers:
#   must_confirm: blocks scope, quote or schedule
#   important:    affects the solution or cost
#   later:        can be confirmed during delivery or operations
PRIORITY_RULES = {
    "business_goal": ("must_confirm", "决定一期范围边界，范围未定则报价与工期无法成立"),
    "metrics": ("important", "影响验收口径与方案设计，但不阻塞范围与报价"),
    "users_roles": ("important", "影响权限模型与前端工作量，属于方案成本项"),
    "core_flow": ("important", "影响方案设计与工作量估算"),
    "scope_in": ("must_confirm", "直接决定一期范围，进而决定报价与工期"),
    "scope_out": ("must_confirm", "直接决定一期范围，避免范围蔓延影响报价"),
    "platform": ("must_confirm", "平台选择决定技术方案、工作量与报价"),
    "interaction": ("important", "影响界面方案与前端成本"),
    "migration_source": ("must_confirm", "来源系统决定迁移可行性与工作量，直接影响工期"),
    "migration_scope": ("must_confirm", "迁移数据量决定工期与报价"),
    "interfaces": ("must_confirm", "外部接口的数量与难度直接影响报价与工期"),
    "third_party": ("important", "第三方服务影响采购成本与方案选型"),
    "roles": ("important", "影响权限设计与实施成本"),
    "security": ("important", "影响技术方案与实施成本"),
    "compliance": ("important", "影响方案与合规改造成本"),
    "performance": ("important", "影响架构选型与成本"),
    "reliability": ("important", "影响架构与运维方案"),
    "schedule": ("must_confirm", "直接决定工期，是报价与排期的前置条件"),
    "budget": ("must_confirm", "直接决定报价边界与方案取舍"),
    "contract": ("must_confirm", "签约主体影响报价口径与合同条款"),
    "acceptance": ("important", "影响范围界定与验收方案"),
    "launch": ("later", "可在交付阶段确认，不影响当前范围与报价"),
    "ops": ("later", "可在上线阶段确认，不影响当前范围与报价"),
    "after_sales": ("later", "属交付后服务条款，可留到合同签订前确认"),
    "support": ("later", "属交付后服务条款，可留到运维阶段确认"),
}

PRIORITY_LABELS = {
    "must_confirm": "必须先确认",
    "important": "重要",
    "later": "后续确认",
}

CONCLUSION_LABELS = {
    "fact": "事实",
    "inference": "推断",
    "unknown": "未知",
}

# A conflict record may come from conflict_detection, whose dimension names
# differ from the question field keys.
CONFLICT_FIELD_MAP = {
    "budget": "budget",
    "timeline": "schedule",
    "scope": "scope_in",
    "platform": "platform",
    "interface": "interfaces",
    "permission": "roles",
    "acceptance": "acceptance",
}

MISSING = {None, "", "待确认", "未定", "TBD", "不详", "待补充", "未提及"}

# Always relevant for a software delivery project.
ALWAYS = {"goals", "users", "scope", "platform", "commercial", "delivery"}

LOW_CONFIDENCE_THRESHOLD = 0.6


def _missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in MISSING
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _relevant(dim_id: str, facts: dict, gaps: dict) -> bool:
    if dim_id in gaps:
        return True
    if dim_id in ALWAYS:
        return True
    if dim_id == "migration":
        return bool(facts.get("legacy_data")) or not _missing(facts.get("migration_source"))
    if dim_id == "interfaces":
        return not _missing(facts.get("interfaces")) or not _missing(facts.get("third_party"))
    if dim_id == "governance":
        return (not _missing(facts.get("roles")) or bool(facts.get("personal_data"))
                or bool(facts.get("regulated")))
    if dim_id == "quality":
        return (not _missing(facts.get("performance")) or
                not _missing(facts.get("reliability")) or bool(facts.get("public")))
    return True


def _field_applicable(dim_id: str, field: str, facts: dict) -> bool:
    if dim_id == "commercial" and field == "contract":
        return bool(facts.get("contract_required", True))
    return True


def _evidence_item(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or raw.get("excerpt") or "").strip()
    if not text:
        return None
    item = {
        "text": text[:300],
        "file": raw.get("file") or raw.get("source_file") or "unknown",
        "source_type": raw.get("source_type") or "unknown",
        "locator": raw.get("locator"),
        "occurred_at": raw.get("occurred_at") or raw.get("source_time"),
        "confidence": None,
    }
    conf = raw.get("confidence")
    if isinstance(conf, (int, float)):
        item["confidence"] = round(float(conf), 4)
    return item


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for item in items:
        key = (item.get("file"), item.get("locator"), item.get("text"))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _evidence_index(context: dict) -> dict:
    """Collect per-field evidence from a dict or a flat fragment list."""
    raw = context.get("evidence") or {}
    index = {}
    if isinstance(raw, dict):
        for field, items in raw.items():
            if isinstance(items, dict):
                items = [items]
            index[field] = _dedupe([e for e in map(_evidence_item, items or []) if e])
    elif isinstance(raw, list):
        for entry in raw:
            field = (entry or {}).get("field")
            item = _evidence_item(entry)
            if field and item:
                index.setdefault(field, []).append(item)
        index = {k: _dedupe(v) for k, v in index.items()}
    return index


def _conflict_index(context: dict) -> dict:
    """field -> list of conflicts, keeping both sides untouched."""
    index = {}
    for conflict in context.get("conflicts") or []:
        if not isinstance(conflict, dict):
            continue
        field = conflict.get("field") or CONFLICT_FIELD_MAP.get(conflict.get("dimension"))
        if not field:
            continue
        side_a = conflict.get("value_a") or {}
        side_b = conflict.get("value_b") or {}
        src_a = side_a.get("source") or {}
        src_b = side_b.get("source") or {}
        item = {
            "id": conflict.get("id"),
            "dimension": conflict.get("dimension"),
            "value_a": {
                "raw": side_a.get("raw"),
                "normalized": side_a.get("normalized"),
                "text": side_a.get("text") or conflict.get("excerpt_a"),
                "file": src_a.get("file") or side_a.get("file"),
                "locator": src_a.get("locator") or side_a.get("locator"),
                "occurred_at": src_a.get("occurred_at") or side_a.get("occurred_at"),
            },
            "value_b": {
                "raw": side_b.get("raw"),
                "normalized": side_b.get("normalized"),
                "text": side_b.get("text") or conflict.get("excerpt_b"),
                "file": src_b.get("file") or side_b.get("file"),
                "locator": src_b.get("locator") or side_b.get("locator"),
                "occurred_at": src_b.get("occurred_at") or side_b.get("occurred_at"),
            },
            "resolution": None,
            "write_blocked": True,
        }
        index.setdefault(field, []).append(item)
    return index


def _conclusion_type(evidence: list[dict], conflict: bool, has_reason: bool) -> str:
    if conflict:
        return "unknown"
    if evidence:
        return "fact"
    if has_reason:
        return "inference"
    return "unknown"


def _confidence(evidence: list[dict], ctype: str, conflict: bool) -> float:
    if conflict:
        return 0.3
    if ctype == "unknown":
        return 0.2
    if ctype == "inference":
        return 0.5
    score = 0.7
    if evidence and all(e.get("occurred_at") for e in evidence):
        score += 0.1
    if evidence and all(e.get("locator") for e in evidence):
        score += 0.1
    if len(evidence) >= 2:
        score += 0.05
    weak = [e["confidence"] for e in evidence
            if isinstance(e.get("confidence"), (int, float))
            and e["confidence"] < LOW_CONFIDENCE_THRESHOLD]
    if weak:
        score = min(score, 0.55)
    return round(min(score, 0.95), 2)


def _confidence_note(ctype: str, conflict: bool, evidence: list[dict],
                    low: bool) -> str | None:
    if conflict:
        return "资料存在冲突且尚未确认，双方证据均保留，未自动选择任何一方"
    if ctype == "unknown":
        return "资料中未找到相关原文，该问题基于维度清单提出"
    if ctype == "inference":
        return "由既有资料推断，缺少直接原文"
    if low:
        weak = [e["confidence"] for e in evidence
                if isinstance(e.get("confidence"), (int, float))]
        if weak:
            return f"原文来自转写或识别，置信度 {min(weak):.2f}，建议核对原件"
        return "证据不完整，建议核对原件后再确认"
    if any(not e.get("occurred_at") for e in evidence):
        return "部分原文缺少时间信息，建议补充资料来源时间"
    return None


def _source_time(evidence: list[dict], conflict_items: list[dict]) -> str | None:
    times = [e.get("occurred_at") for e in evidence if e.get("occurred_at")]
    for c in conflict_items:
        for side in ("value_a", "value_b"):
            if (c.get(side) or {}).get("occurred_at"):
                times.append(c[side]["occurred_at"])
    if not times:
        return None
    return max(times)


def _excerpt(evidence: list[dict], conflict_items: list[dict]) -> str | None:
    if evidence:
        return evidence[0]["text"]
    for conflict in conflict_items:
        a = conflict["value_a"].get("text") or conflict["value_a"].get("raw")
        b = conflict["value_b"].get("text") or conflict["value_b"].get("raw")
        if a or b:
            return " / ".join(str(v) for v in (a, b) if v)
    return None


def _priority(field: str) -> tuple[str, str]:
    return PRIORITY_RULES.get(field, ("important", "影响方案或成本"))


def plan_questions(context: dict) -> dict:
    context = context or {}
    facts = context.get("facts") or {}
    gaps = {}
    for gap in context.get("gaps") or []:
        gaps.setdefault(gap.get("dimension"), {})[gap.get("field")] = gap.get("reason") or "资料存在缺口"

    evidence_index = _evidence_index(context)
    conflict_index = _conflict_index(context)

    # An unresolved conflict is itself a reason to show the dimension and ask.
    for field, items in conflict_index.items():
        for dim in DIMENSIONS:
            if any(key == field for key, _label, _text in dim["fields"]):
                gaps.setdefault(dim["id"], {}).setdefault(
                    field, "资料存在冲突，需人工确认")
                break

    shown, hidden, questions = [], [], []

    for dim in DIMENSIONS:
        dim_gaps = gaps.get(dim["id"], {})
        relevant = _relevant(dim["id"], facts, dim_gaps)
        if not relevant and not dim_gaps:
            hidden.append({"id": dim["id"], "label": dim["label"]})
            continue

        dim_questions = []
        statuses = []
        for key, label, text in dim["fields"]:
            if not _field_applicable(dim["id"], key, facts):
                statuses.append("not_applicable")
                continue
            gap_reason = dim_gaps.get(key)
            if _missing(facts.get(key)) or gap_reason:
                if gap_reason:
                    reason = gap_reason
                elif facts.get(key) is None:
                    reason = "资料未提及"
                else:
                    reason = "当前值为空或未确认"
                qid = f"Q{len(questions) + 1}"
                evidence = list(evidence_index.get(key) or [])
                conflict_items = list(conflict_index.get(key) or [])
                conflict = bool(conflict_items)
                ctype = _conclusion_type(evidence, conflict, bool(gap_reason))
                confidence = _confidence(evidence, ctype, conflict)
                low = confidence < LOW_CONFIDENCE_THRESHOLD
                tier, basis = _priority(key)
                question = {
                    "id": qid,
                    "dimension": dim["id"],
                    "dimension_label": dim["label"],
                    "field": key,
                    "field_label": label,
                    "text": text,
                    "reason": reason,
                    "priority": tier,
                    "priority_label": PRIORITY_LABELS[tier],
                    "priority_basis": basis,
                    "conclusion_type": ctype,
                    "conclusion_label": CONCLUSION_LABELS[ctype],
                    "evidence": evidence,
                    "excerpt": _excerpt(evidence, conflict_items),
                    "source_time": _source_time(evidence, conflict_items),
                    "confidence": confidence,
                    "low_confidence": low,
                    "confidence_note": _confidence_note(ctype, conflict, evidence, low),
                    "conflict_evidence": conflict_items or None,
                }
                questions.append(question)
                dim_questions.append(qid)
                statuses.append("gap")
            else:
                statuses.append("clear")

        if not dim_questions and "clear" in statuses:
            status = "clear"
        elif "gap" in statuses and "clear" in statuses:
            status = "partial"
        elif "gap" in statuses:
            status = "missing"
        else:
            status = "not_applicable"

        shown.append({
            "id": dim["id"],
            "order": dim["order"],
            "label": dim["label"],
            "relevance": "gap" if dim["id"] in dim_gaps else "relevant",
            "status": status,
            "questions": dim_questions,
        })

    shown.sort(key=lambda d: d["order"])
    priorities = {tier: sum(1 for q in questions if q["priority"] == tier)
                  for tier in ("must_confirm", "important", "later")}
    conclusions = {ctype: sum(1 for q in questions if q["conclusion_type"] == ctype)
                   for ctype in ("fact", "inference", "unknown")}
    return {
        "schema": "clientgraph.question_plan.v1",
        "project": context.get("project"),
        "dimensions": shown,
        "questions": questions,
        "hidden_dimensions": hidden,
        "stats": {
            "shown_dimensions": len(shown),
            "hidden_dimensions": len(hidden),
            "clear_dimensions": sum(1 for d in shown if d["status"] == "clear"),
            "questions": len(questions),
            "priorities": priorities,
            "conclusion_types": conclusions,
            "low_confidence": sum(1 for q in questions if q["low_confidence"]),
            "conflicts": sum(1 for q in questions if q["conflict_evidence"]),
        },
    }
