# -*- coding: utf-8 -*-
"""Unified keyword index across customers, projects, communications,
documents, requirements, tasks and evidence."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

STOP = ["哪些", "哪个", "客户", "项目", "提过", "提到", "什么", "最近", "一次",
        "变更", "记录", "已经", "已", "逾期", "待办", "的", "了", "是", "有",
        "谁", "请", "问题", "一下", "怎么", "多少", "是否", "以及", "和", "与"]


def norm(text) -> str:
    s = unicodedata.normalize("NFKC", str(text or "")).lower()
    return "".join(ch for ch in s if not ch.isspace() and not unicodedata.category(ch).startswith("P"))


def terms(query: str) -> list[str]:
    s = query or ""
    for w in STOP:
        s = s.replace(w, " ")
    s = norm(s)
    out = set()
    for part in re.findall(r"[\u4e00-\u9fa5]+|[a-z0-9]+", s):
        if len(part) == 1:
            out.add(part)
        else:
            out.update(part[i:i + 2] for i in range(len(part) - 1))
    return sorted(out, key=len, reverse=True)


def _snippet(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


class SearchIndex:
    def __init__(self, data: dict):
        self.data = data or {}
        self.customers = {c["id"]: c for c in self.data.get("customers") or []}
        self.projects = {p["id"]: p for p in self.data.get("projects") or []}
        self.records: list[dict] = []
        self._build()

    def _customer(self, cid):
        c = self.customers.get(cid)
        return {"id": cid, "name": c.get("name", cid)} if cid else None

    def _project(self, pid):
        p = self.projects.get(pid)
        return {"id": pid, "name": p.get("name", pid)} if pid else None

    def _latest_locator(self, pid=None, cid=None):
        candidates = []
        for m in self.data.get("communications") or []:
            if pid and m.get("project_id") != pid:
                continue
            if cid and m.get("customer_id") != cid:
                continue
            candidates.append(m)
        candidates.sort(key=lambda x: x.get("occurred_at") or "")
        if candidates:
            return candidates[-1].get("locator") or "communication://" + candidates[-1]["id"]
        return None

    def _add(self, etype, eid, label, text, locator, occurred_at=None,
             customer_id=None, project_id=None):
        n = norm(f"{label} {text}")
        if not n:
            return
        self.records.append({
            "entity_type": etype,
            "entity_id": eid,
            "label": label,
            "text": text,
            "norm": n,
            "locator": locator or f"{etype}://{eid}",
            "occurred_at": occurred_at,
            "customer_id": customer_id,
            "project_id": project_id,
        })

    def _build(self):
        for c in self.data.get("customers") or []:
            loc = self._latest_locator(cid=c["id"]) or f"customer://{c['id']}"
            self._add("customer", c["id"], c.get("name", c["id"]),
                      " ".join([c.get("name", "")] + list(c.get("aliases") or [])),
                      loc, customer_id=c["id"])
        for p in self.data.get("projects") or []:
            loc = self._latest_locator(pid=p["id"]) or f"project://{p['id']}"
            self._add("project", p["id"], p.get("name", p["id"]), p.get("name", ""),
                      loc, project_id=p["id"], customer_id=p.get("customer_id"))
        for m in self.data.get("communications") or []:
            self._add("communication", m["id"], m.get("title", m["id"]),
                      m.get("text", ""), m.get("locator"),
                      m.get("occurred_at"), m.get("customer_id"), m.get("project_id"))
        for d in self.data.get("documents") or []:
            self._add("document", d["id"], d.get("title", d["id"]),
                      d.get("text", ""), d.get("locator"),
                      d.get("occurred_at"), d.get("customer_id"), d.get("project_id"))
        for r in self.data.get("requirements") or []:
            self._add("requirement", r["id"], r.get("title", r["id"]),
                      f"{r.get('title', '')} {r.get('description', '')}",
                      r.get("locator"), r.get("occurred_at"),
                      r.get("customer_id"), r.get("project_id"))
        for t in self.data.get("tasks") or []:
            src = t.get("source") or {}
            self._add("task", t["id"], t.get("title", t["id"]), t.get("title", ""),
                      src.get("locator"), t.get("due_at"),
                      (t.get("customer") or {}).get("id"), (t.get("project") or {}).get("id"))
        for e in self.data.get("evidence") or []:
            self._add("evidence", e["id"], e.get("label") or e["id"], e.get("text", ""),
                      e.get("locator"), e.get("occurred_at"),
                      e.get("customer_id"), e.get("project_id"))

    def search(self, query: str, limit: int = 30,
               types: list[str] | None = None) -> list[dict]:
        ts = terms(query)
        if not ts:
            return []
        compact = norm(query)
        results = []
        for rec in self.records:
            if types and rec["entity_type"] not in types:
                continue
            matched = [t for t in ts if t in rec["norm"]]
            if not matched:
                continue
            score = float(len(matched))
            if compact and compact in rec["norm"]:
                score += 2.0
            results.append({
                "entity_type": rec["entity_type"],
                "entity_id": rec["entity_id"],
                "label": rec["label"],
                "snippet": _snippet(rec["text"]),
                "locator": rec["locator"],
                "occurred_at": rec["occurred_at"],
                "customer": self._customer(rec["customer_id"]),
                "project": self._project(rec["project_id"]),
                "score": round(score, 2),
                "matched_terms": matched,
            })
        results.sort(key=lambda r: (-r["score"], r["occurred_at"] or ""), reverse=False)
        deduped, seen = [], set()
        for r in results:
            key = (r["entity_type"], r["entity_id"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
            if len(deduped) >= limit:
                break
        return deduped
