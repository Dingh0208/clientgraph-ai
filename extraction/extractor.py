# -*- coding: utf-8 -*-
"""Rule-based requirement extraction from citable evidence items.

No model is called. A deadline is written only when the evidence contains an
explicit calendar date or the user has confirmed one; vague expressions become
pending questions instead of guessed dates.
"""
from __future__ import annotations

import re
from datetime import datetime

EXPLICIT_DATE = re.compile(r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})\s*日?")
PARTIAL_DATE = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日")
VAGUE = re.compile(r"\d{1,2}\s*月\s*底|月底|尽快|下周[一二三四五六日天]?|本月|下个月|之后|晚点|越快越好")
BUDGET = re.compile(r"(?:预算|报价|总价|合同金额)[^0-9]{0,10}([\d,]+(?:\.\d+)?)\s*(万|万元|元|块)")
OWNER = re.compile(r"负责人\s*[:：]\s*([^\s，。；、]{2,8})|由\s*([\u4e00-\u9fa5]{2,4})\s*负责")
PROPOSER = re.compile(r"提出人\s*[:：]\s*([^\s，。；、]{2,8})")
ACCEPT = re.compile(r"验收|以.{0,12}为准")
CUE = re.compile(r"需要|要求|必须|希望|要能|支持|增加|加上|新增|改成|实现|提供|上线|审批|台账|巡检|统计|看板|二维码|异常|上报")

KEY_RULES = [
    ("设备台账", re.compile(r"台账|二维码|设备档案|扫码看档案")),
    ("巡检计划", re.compile(r"巡检计划|计划配置|巡检任务")),
    ("扫码巡检", re.compile(r"扫码巡检|巡检记录|巡检拍照")),
    ("统计看板", re.compile(r"统计看板|完成率|报表")),
    ("审批流", re.compile(r"审批")),
    ("异常上报", re.compile(r"异常上报|异常工单|异常处理")),
    ("上线时间", re.compile(r"上线|工期|交付时间")),
    ("售后工单", re.compile(r"售后工单")),
]

STAGES = [
    ("已签约", re.compile(r"合同|签约|签订")),
    ("交付中", re.compile(r"上线|实施|开发|交付")),
    ("报价中", re.compile(r"报价|方案|预算")),
    ("需求中", re.compile(r"需求|评审|范围")),
    ("线索", re.compile(r"预研|初步|了解")),
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _clauses(text: str):
    for line in str(text or "").splitlines():
        for part in re.split(r"[。；;！!？?]", line):
            part = part.strip(" ，,、-")
            if not part:
                continue
            if "：" in part and "、" in part.split("：", 1)[1]:
                prefix, rest = part.split("：", 1)
                for sub in rest.split("、"):
                    sub = sub.strip()
                    if sub:
                        yield (prefix + "：" + sub) if prefix else sub
            else:
                yield part


def _canonical(clause: str) -> tuple[str, str]:
    for name, pattern in KEY_RULES:
        if pattern.search(clause):
            return name, name
    key = _norm(clause)[:40]
    return key, clause[:40]


def _is_requirement(clause: str) -> bool:
    if ACCEPT.search(clause):
        return False
    if re.match(r"^(负责人|提出人|预算|报价|总价|合同金额)\s*[:：]", clause):
        return False
    if BUDGET.search(clause) and not re.search(r"台账|巡检|审批|看板|功能", clause):
        return False
    return bool(CUE.search(clause))


def _explicit(clause: str) -> list[str]:
    out = []
    for m in EXPLICIT_DATE.finditer(clause):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            out.append(datetime(y, mo, d).strftime("%Y-%m-%d"))
        except ValueError:
            continue
    return out


def _vague(clause: str) -> list[str]:
    return [m.group(0) for m in VAGUE.finditer(clause)]


def _budget(clause: str):
    m = BUDGET.search(clause)
    if not m:
        return None
    raw_num = m.group(1).replace(",", "")
    try:
        num = float(raw_num)
    except ValueError:
        return None
    unit = m.group(2)
    amount = int(num * 10000) if unit in ("万", "万元") else int(num)
    return {"raw": m.group(0), "amount": amount, "unit": unit}


def _owner(text: str):
    m = OWNER.search(text)
    if not m:
        return None
    return m.group(1) or m.group(2)


def _proposer(item: dict):
    explicit = item.get("proposer")
    if explicit:
        return str(explicit)
    m = PROPOSER.search(item.get("text") or "")
    if m:
        return m.group(1)
    sources = item.get("sources") or []
    meta = (sources[0].get("meta") or {}) if sources else {}
    sender = meta.get("sender")
    if isinstance(sender, list):
        sender = sender[0] if sender else None
    if sender:
        return re.sub(r"\s*<.*>$", "", str(sender)).strip()
    from_list = meta.get("from")
    if isinstance(from_list, list) and from_list:
        return re.sub(r"\s*<.*>$", "", str(from_list[0])).strip()
    if item.get("source_type") == "asr":
        return None
    return None


def _evidence(item: dict) -> dict:
    sources = item.get("sources") or []
    locator = (sources[0] or {}).get("locator") if sources else None
    return {
        "file": item.get("source_file") or item.get("file") or "unknown",
        "source_type": item.get("source_type") or "unknown",
        "locator": locator,
        "occurred_at": item.get("occurred_at"),
        "text": (item.get("text") or "")[:400],
    }


def extract(items: list[dict], context: dict | None = None,
            confirmed_dates: dict | None = None) -> dict:
    context = context or {}
    confirmed_dates = confirmed_dates or {}
    project_id = context.get("project_id") or "p_unknown"
    project_name = context.get("project_name") or "未命名项目"

    def ev_dedupe(evs):
        seen, out = set(), []
        for e in evs:
            key = (e.get("file"), e.get("locator"), e.get("text"))
            if key in seen:
                continue
            seen.add(key)
            out.append(e)
        return out

    reqs: dict[str, dict] = {}
    budgets: list[dict] = []
    acceptances: list[dict] = []
    all_evidence: list[dict] = []

    for item in items:
        ev = _evidence(item)
        all_evidence.append(ev)
        text = item.get("text") or ""
        proposer = _proposer(item)
        owner = _owner(text)
        b = _budget(text)
        if b:
            budgets.append({**b, "evidence": ev})

        for clause in _clauses(text):
            if ACCEPT.search(clause):
                body = clause.split("：", 1)[-1] if "：" in clause else clause
                acceptances.append({"text": body.strip(), "evidence": ev})
                continue
            if not _is_requirement(clause):
                continue
            key, title = _canonical(clause)
            req = reqs.setdefault(key, {
                "key": key,
                "title": title,
                "descriptions": [],
                "evidence": [],
                "proposers": [],
                "owners": [],
                "explicit": [],
                "vague": [],
            })
            if clause not in req["descriptions"]:
                req["descriptions"].append(clause)
            req["evidence"].append(ev)
            if proposer and proposer not in req["proposers"]:
                req["proposers"].append(proposer)
            if owner and owner not in req["owners"]:
                req["owners"].append(owner)
            req["explicit"].extend(_explicit(clause))
            req["vague"].extend(_vague(clause))

    # Project stage: latest evidence whose text carries a stage cue.
    stage_value, stage_ev = None, None
    ordered = sorted(items, key=lambda x: x.get("occurred_at") or "")
    for item in reversed(ordered):
        text = item.get("text") or ""
        for name, pattern in STAGES:
            if pattern.search(text):
                stage_value, stage_ev = name, _evidence(item)
                break
        if stage_value:
            break

    # Budget status
    amounts = {b["amount"] for b in budgets}
    if not budgets:
        budget = {"status": "missing", "values": [], "evidence": []}
    elif len(amounts) == 1:
        budget = {"status": "explicit", "values": budgets, "evidence": [b["evidence"] for b in budgets]}
    else:
        budget = {"status": "conflict", "values": budgets, "evidence": [b["evidence"] for b in budgets]}

    requirements = []
    pending = []
    pid = 0

    def add_pending(ptype, question, req_id=None, evidence=None):
        nonlocal pid
        pid += 1
        entry = {
            "id": f"P{pid}",
            "type": ptype,
            "question": question,
            "requirement_id": req_id,
            "evidence": evidence or [],
        }
        pending.append(entry)
        return entry["id"]

    ordered_reqs = sorted(reqs.values(), key=lambda r: (r["key"]))
    for idx, req in enumerate(ordered_reqs, 1):
        rid = f"R{idx}"
        explicit = sorted(set(req["explicit"]))
        vague = sorted(set(req["vague"]))
        confirmed = confirmed_dates.get(req["key"]) or confirmed_dates.get(rid)
        pending_ids = []

        if confirmed:
            deadline = {"value": confirmed, "status": "user_confirmed",
                        "raw": confirmed, "evidence": req["evidence"]}
        elif explicit:
            deadline = {"value": explicit[0], "status": "explicit",
                        "raw": explicit[0], "evidence": req["evidence"]}
        elif vague:
            deadline = {"value": None, "status": "pending_vague",
                        "raw": "、".join(vague), "evidence": req["evidence"]}
            pending_ids.append(add_pending(
                "deadline_vague",
                f"“{vague[0]}”不是明确日期，请确认“{req['title']}”的具体截止时间（年-月-日）。",
                rid, req["evidence"],
            ))
        else:
            deadline = {"value": None, "status": "missing", "raw": None, "evidence": req["evidence"]}

        if explicit and vague and not confirmed:
            pending_ids.append(add_pending(
                "deadline_mismatch",
                f"资料同时出现明确日期 {explicit[0]} 与模糊表达“{vague[0]}”，请确认“{req['title']}”以哪个为准。",
                rid, req["evidence"],
            ))

        owner = req["owners"][0] if req["owners"] else None
        if not owner:
            pending_ids.append(add_pending(
                "owner_missing",
                f"“{req['title']}”未指定负责人，请确认由谁负责。",
                rid, req["evidence"],
            ))

        requirements.append({
            "id": rid,
            "title": req["title"],
            "canonical_key": req["key"],
            "description": req["descriptions"][0] if req["descriptions"] else req["title"],
            "proposer": req["proposers"],
            "owner": owner,
            "deadline": deadline,
            "evidence": ev_dedupe(req["evidence"]),
            "merged_count": len(ev_dedupe(req["evidence"])),
            "pending_ids": pending_ids,
        })

    # Project-level pending items
    if budget["status"] == "missing":
        add_pending("budget_missing", "资料未给出预算，请确认预算区间或上限。", None,
                    [e for e in all_evidence][:3])
    elif budget["status"] == "conflict":
        vals = "、".join(sorted({f"{b['amount']:,} 元" for b in budgets}))
        add_pending("budget_conflict", f"预算出现 {vals} 两种口径，请确认以哪个为准。", None,
                    [b["evidence"] for b in budgets])

    if not acceptances:
        add_pending("acceptance_missing", "资料未给出验收标准，请补充可验证的验收条件。", None,
                    [e for e in all_evidence][:3])
    if not stage_value:
        add_pending("stage_unknown", "项目阶段不明确，请确认当前阶段。", None,
                    [e for e in all_evidence][:3])

    return {
        "schema": "clientgraph.extraction.v1",
        "project": {
            "id": project_id,
            "name": project_name,
            "stage": {"value": stage_value, "evidence": stage_ev},
            "budget": budget,
            "acceptance_criteria": acceptances,
            "evidence_count": len(all_evidence),
        },
        "requirements": requirements,
        "pending": pending,
        "stats": {
            "items": len(items),
            "requirements": len(requirements),
            "merged_requirements": sum(1 for r in requirements if r["merged_count"] > 1),
            "pending": len(pending),
            "explicit_deadlines": sum(1 for r in requirements if r["deadline"]["status"] == "explicit"),
            "user_confirmed_deadlines": sum(1 for r in requirements if r["deadline"]["status"] == "user_confirmed"),
            "pending_deadlines": sum(1 for r in requirements if r["deadline"]["status"] == "pending_vague"),
        },
    }
