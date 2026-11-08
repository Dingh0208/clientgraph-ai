# 需求澄清助手 API 与流程 v1.0

> 版本：v0.4.0 · 2026-11-08
> 适用代码：`clarification/`、`writeback/`
> 数据：全部为本地内存对象，不连接外部服务；示例数据均为虚构

## 1. 模块边界

| 模块 | 文件 | 职责 |
|---|---|---|
| 问题计划 | `clarification/questions.py` | 固定行业顺序、相关性过滤、三档优先级、证据与冲突字段 |
| 问题状态 | `clarification/question_lifecycle.py` | 待问/已问/已回答/不适用、多次回答快照、显式追问 |
| 分批分析 | `clarification/planner.py`、`processor.py` | 按字数分批、取消、重试、追加、去重、冲突不覆盖 |
| 工作单 | `clarification/workspace.py` | 六态生命周期、筛选、归档、复制、增量、删除、导出入口 |
| 回写 | `writeback/converter.py` | 目标选择、字段预览、人工确认、版本与操作快照 |
| 导出 | `clarification/exporters.py` | 文本、Word（OOXML）、PDF（本机浏览器打印） |

## 2. 端到端流程

```
1  选材        选择客户/项目/资料，不可读资料阻止发送
2  确认范围    confirm_scope() 记录 confirmed_scope_at
3  分批        按 max_input_chars 拆批，只包含未分析资料
4  分析        逐批 complete_batch() / fail_batch()
5  问题        每题带证据、来源时间、事实/推断/未知、低置信度提示
6  冲突        冲突题保留双方证据，不自动裁定
7  回答        标记已问 → 追加回答（原问题与证据快照）→ 已回答
8  追问        仅在老板显式调用 generate_followup() 时生成
9  回写预览    build_preview() 只预填回答明确支持的字段
10 人工确认    apply_preview(confirm=True) 写新需求/新版本/项目字段
11 增量        追加新资料 → 显式 start_analysis() 只跑新增部分
12 导出        文本/Word/PDF；对外版隐藏内部理由与证据
```

状态与结论：

- 已问未答不算完成；已回答或不适用才算处理结论；
- 工作单六态：草稿 → 分析中 → 部分完成 / 未完成 / 已完成；可归档与恢复；
- 新需求固定“待确认”；需求 P0/P1/P2 由独立规则判断，不继承问题优先级。

## 3. 主要 API

### 3.1 问题计划

```python
plan_questions({
    "project": {"id": "p1", "name": "..."},
    "facts": {...},
    "gaps": [{"dimension": "scope", "field": "scope_out", "reason": "..."}],
    "evidence": {"scope_out": [{"text": "...", "file": "...", "locator": "...",
                                "occurred_at": "..."}]},
    "conflicts": [{"dimension": "timeline", "value_a": {...}, "value_b": {...}}],
}) -> {
    "questions": [{
        "id": "Q1", "text": "请问…？", "priority": "must_confirm",
        "priority_label": "必须先确认", "priority_basis": "...",
        "conclusion_type": "fact|inference|unknown",
        "evidence": [...], "source_time": "...", "confidence": 0.9,
        "low_confidence": False, "confidence_note": None,
        "conflict_evidence": [...] | None,
    }],
    "hidden_dimensions": [...],
    "stats": {...},
}
```

### 3.2 问题状态

| 方法 | 输入 | 结果 / 错误 |
|---|---|---|
| `mark_asked(qid, at, operator, channel)` | 问题编号 | 已问；已有结论时 `E_ALREADY_RESOLVED` |
| `add_answer(qid, text, evidence, answered_at, operator)` | 回答与证据 | 追加回答；未问 `E_NOT_ASKED`；无证据 `E_NO_EVIDENCE`；不适用 `E_NOT_APPLICABLE` |
| `mark_not_applicable(qid, reason, at)` | 原因 | 不适用；无原因 `E_REASON_REQUIRED` |
| `generate_followup(qid, text, operator)` | 已回答问题 | 新建待问子问题；未回答 `E_NOT_ANSWERED` |

回答记录包含：`question_text`、`question_priority`、`question_evidence`、`answered_at`、`recorded_at`、`snapshot_at`、`evidence`、`sequence`。

### 3.3 工作单

```python
ws = ClarificationWorkspace()

record = ws.create_record(
    scope={"customers": [{"id": "c1", "name": "..."}],
           "projects": [{"id": "p1", "name": "..."}]},
    materials=[{"source_id": "m1", "name": "...", "type": "chat",
                "locator": "chat://m1", "text": "...", "sha256": "..."}],
    model={"max_input_chars": 2000},
)

ws.confirm_scope(record["id"])
ws.start_analysis(record["id"])              # -> {"round": 1, "batches": [...]}
ws.complete_batch(record["id"], "R1-B1", questions=[...])
ws.fail_batch(record["id"], "R1-B1", "E_MODEL_TIMEOUT", "批次超时")
ws.retry_failed(record["id"])                # 失败批次重置为待执行
ws.append_materials(record["id"], [new_material])
ws.start_analysis(record["id"])              # 只分析未分析资料
```

| 方法 | 说明 | 主要错误 |
|---|---|---|
| `create_record` | 建草稿，客户/项目至少一个 | `E_SCOPE_REQUIRED` |
| `confirm_scope` | 记录发送前确认时间 | — |
| `start_analysis` | 为未分析资料建批次 | `E_SCOPE_NOT_CONFIRMED`、`E_NOTHING_TO_ANALYZE`、`E_UNREADABLE`、`E_ARCHIVED` |
| `complete_batch` | 批次完成并合并问题 | `E_BATCH_NOT_FOUND`、`E_BATCH_STATE` |
| `fail_batch` | 记录失败原因，保留错误历史 | `E_BATCH_NOT_FOUND` |
| `retry_failed` | 失败批次重置，状态回到分析中 | `E_NO_FAILED_BATCH` |
| `append_materials` | 去重追加，只登记不分析 | `E_DELETED`、`E_ARCHIVED` |
| `archive` / `restore` | 归档隐藏 / 恢复 | `E_ALREADY_ARCHIVED`、`E_NOT_ARCHIVED` |
| `delete_record(confirm=True)` | 软删工作单，资料保留 | `E_CONFIRM_REQUIRED`、`E_ALREADY_DELETED` |
| `copy_as_draft` | 复制范围与资料，问题重置待问 | `E_DELETED` |
| `list_records` | 客户/项目/日期/未回答/已完成筛选 | — |
| `render_text` | 按客户或项目分组输出文本 | — |
| `export_docx` / `export_pdf` | 导出 Word / PDF | `E_PDF_*` |

### 3.4 回写

```python
preview = build_preview(
    answer,                                   # 问题状态模块的回答记录
    {"kind": "requirement",                   # requirement | project
     "customer_id": "c1", "project_id": "p1",
     "requirement_id": "R1"},                 # 新建时不传
    {"customers": [...], "projects": [...], "requirements": [...]},
)
# preview["fields"] 仅含回答明确支持的字段；preview["skipped"] 说明未预填原因
result = apply_preview(preview, store, confirmed_by="老板", confirm=True,
                       token=preview["token"])
```

| 方法 | 说明 | 主要错误 |
|---|---|---|
| `build_preview` | 生成字段变更、证据与优先级建议 | `E_TARGET_REQUIRED`、`E_TARGET_MISMATCH`、`E_NO_EVIDENCE` |
| `apply_preview` | 人工确认后写入并生成快照 | `E_CONFIRM_REQUIRED`、`E_CONFIRMER_REQUIRED`、`E_PREVIEW_TAMPERED`、`E_PREVIEW_CHANGED`、`E_TARGET_CHANGED`、`E_ALREADY_APPLIED` |

## 4. 数据结构

### 4.1 工作单状态

`draft` 草稿、`analyzing` 分析中、`partial` 部分完成、`incomplete` 未完成、`completed` 已完成、`archived` 已归档。

状态由批次与问题结论推导：存在待执行批次 → 分析中；全部问题有结论 → 已完成；有部分结论 → 部分完成；无结论 → 未完成。

### 4.2 回答快照

| 字段 | 说明 |
|---|---|
| `question_text` / `question_priority` / `question_evidence` | 原问题快照 |
| `text` / `answered_at` / `recorded_at` | 回答原文与两个时间 |
| `evidence` | 本条回答引用的证据 |
| `sequence` | 第几次回答，只追加 |

### 4.3 回写操作快照

| 字段 | 说明 |
|---|---|
| `action` | create_requirement / update_requirement / update_project |
| `target_before` / `target_after` | 完整前后快照，新建时 before 为 null |
| `changes` | 字段、前后值、依据原文、证据 |
| `answer_id` / `question_id` | 来源问答 |
| `confirmed_by` / `confirmed_at` | 人工确认痕迹 |

需求版本只追加：新建写版本 1，更新写 `current_version + 1`，旧版本不改。

## 5. 错误码

| 错误码 | 含义 |
|---|---|
| `E_SCOPE_REQUIRED` | 未选择客户或项目 |
| `E_SCOPE_NOT_CONFIRMED` | 未确认范围就发送分析 |
| `E_UNREADABLE` | 资料不可读 |
| `E_NOTHING_TO_ANALYZE` | 没有未分析资料 |
| `E_BATCH_STATE` | 批次状态不允许当前操作 |
| `E_NO_FAILED_BATCH` | 没有可重试的失败批次 |
| `E_NOT_ASKED` | 未标记已问就回答 |
| `E_NO_EVIDENCE` | 回答或回写缺少证据 |
| `E_NOT_ANSWERED` | 未回答就生成追问 |
| `E_ALREADY_RESOLVED` | 已有结论仍尝试改状态 |
| `E_CONFIRM_REQUIRED` | 删除或保存未人工确认 |
| `E_PREVIEW_TAMPERED` | 预览内容被修改 |
| `E_TARGET_CHANGED` | 预览后目标记录变化 |
| `E_ALREADY_APPLIED` | 同一预览重复保存 |
| `E_PDF_ENGINE` | 未找到 Edge/Chrome，无法生成 PDF |

完整错误返回格式为异常对象的 `code` 与 `message`，不返回“服务不可用，请重试”。

## 6. 失败与重试

- 模型批次失败：`fail_batch` 保留 `error`、`batch_errors`；工作单进入未完成或保持部分完成；
- `retry_failed` 只重置失败批次，已成功批次不重跑；
- 追加资料不会自动复活已完成单，必须显式 `start_analysis` 开始增量轮次；
- 失败案例在回归记录中保留，不删除，用于对照。

## 7. 导出与脱敏

- 内部版：问题、优先级、回答、提问理由、证据、不适用原因；
- 对外版：隐藏提问理由、证据、置信度与内部模型参数；
- Word 为最小 OOXML，无第三方依赖；
- PDF 由本机 Edge/Chrome 无头模式打印，使用系统字体；无浏览器时明确报 `E_PDF_ENGINE`。

> AI生成
