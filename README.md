# ClientGraph AI

> 版本：v0.4.0 · 2026-11-08
> 形态：本地单文件原型 + 本地 Python 分析流水线 + 需求澄清工作单

ClientGraph AI 面向单人多项目的软件公司经营者，把分散的客户资料聚合成可追溯的工作台：**客户 360、需求抽取与版本、冲突、待办与提醒、关系图、全局搜索、需求澄清**。

本仓库是产品原型与可验证的本地分析代码，不是生产系统。

---

## 1. 模块

| 模块 | 路径 | 能力 |
|---|---|---|
| 交互原型 | `prototype/index.html` | 概览、问答、客户 360、导入、待归档、诊断、需求澄清选材 |
| 客户 360 | `customer360/` | 身份、项目、需求、风险、待办、时间线、证据、提醒 |
| 需求抽取 | `extraction/` | 项目/阶段/需求/提出人/负责人/截止/预算/验收/待确认 |
| 版本演化 | `requirement_history/` | 追加式版本，首次出现/修改/确认/取消，前后证据 |
| 冲突 | `conflict_detection/` | 预算/工期/范围/负责人/平台/接口/权限/验收 |
| 待办 | `task_center/` | 明确动作生成待办、完成/延期/重开/批量、提醒策略 |
| 关系图 | `relationship_view/` | 8 类实体关系，直接证据/语义相似/人工确认 |
| 全局搜索 | `unified_search/` | 关键词检索 + 客户提及/项目变更/逾期待办问答 |
| 证据归一 | `evidence_layer/` | 统一证据字段与跨来源合并 |
| 解析 | `audio_pipeline/`、`media_pipeline/`、`document_pipeline/` | 音频、视频、PDF/OCR、Office/邮件/聊天 |
| 诊断 | `ops/` | Sidecar/微信/ffmpeg/OCR/ASR 检测与启动策略 |
| **需求澄清** | `clarification/` | 选材、分批、证据问题、三档优先级、状态、追问、工作单生命周期、导出 |
| **回答回写** | `writeback/` | 目标选择、字段预览、人工确认、需求版本与操作快照 |

## 2. v0.4.0 需求澄清闭环

```
选材确认 → 分批分析 → 证据问题 → 冲突 → 回答 → 手动追问
        → 回写预览 → 人工确认 → 版本历史 → 增量分析 → 失败重试 → 对外导出
```

关键约束：

- 已问未答不算完成；已回答或不适用才形成结论；
- 冲突保留双方证据，不自动裁定；
- 追问只在老板点击“基于回答生成追问”时生成；
- 回写只预填回答明确支持的字段，新需求默认“待确认”；
- 需求 P0/P1/P2 独立判断，不继承问题优先级；
- 保存必须人工确认，保留版本与 before/after 操作快照；
- 对外版隐藏提问理由、证据与内部置信度。

回归结果：

| 套件 | 检查数 | 结果 |
|---|---|---|
| 端到端连续回归 | 48（23 步） | 全部通过 |
| 问题计划与优先级 | 52 | 全部通过 |
| 问题状态 | 57 | 全部通过 |
| 回答回写 | 64 | 全部通过 |
| 工作单生命周期 | 56 | 全部通过 |
| 澄清分批 | 27 | 全部通过 |

失败案例 7 个全部保留：不可读资料、批次超时、未回答追问、未确认保存、预览篡改、目标变化、重复提交。详见 `docs/失败案例-v0.4.0.md`。

## 3. 快速开始

```bash
python -m ops.server --port 8123
# 打开 http://127.0.0.1:8123/
```

流水线依赖：

```bash
pip install -r media_pipeline/requirements.txt
pip install -r document_pipeline/requirements.txt
# audio_pipeline 需要 ffmpeg/ffprobe
```

## 4. 验证

```bash
python scripts/verify_integration_v030.py
python scripts/verify_clarification_e2e.py
python scripts/verify_question_plan.py
python scripts/verify_question_status.py
python scripts/verify_writeback.py
python scripts/verify_clarification_records.py
python scripts/verify_clarification_batching.py
python scripts/verify_extraction.py
python scripts/verify_requirement_history.py
python scripts/verify_conflicts.py
python scripts/verify_tasks.py
python scripts/verify_relationship_view.py
python scripts/verify_unified_search.py
```

## 5. 关键限制

- 单机单用户；无账号、权限、云同步。
- 澄清工作单目前为内存对象，未接 SQLite；关键操作尚未接到原型按钮。
- 问题、优先级、字段识别均为规则，不按行业细分；复杂句式会漏识别。
- ASR 为 Mock；Qwen 未联调。OCR 依赖本地 RapidOCR。
- PDF 导出依赖本机 Edge/Chrome；Word 为零依赖 OOXML。
- 对外导出只做内容裁剪，不替代人工脱敏审查。

完整清单见 `docs/已知限制-v0.4.0.md`。

## 6. 文档

- `docs/PRD摘要-v0.4.0.md`
- `docs/需求澄清助手-API与流程-v1.0.md`
- `docs/验收矩阵-v0.4.0.md`
- `docs/测试记录-v0.4.0.md`
- `docs/失败案例-v0.4.0.md`
- `docs/已知限制-v0.4.0.md`
- `docs/RELEASE-NOTES-v0.4.0.md`
- `docs/问题计划-v1.0.md`、`docs/问题优先级-v1.0.md`、`docs/问题状态-v1.0.md`
- `docs/回答回写-v1.0.md`、`docs/澄清单生命周期-v1.0.md`
- `docs/需求澄清选材-v1.0.md`、`docs/澄清分批处理-v1.0.md`
- `docs/RELEASE-NOTES-v0.3.0.md`（历史）

## 7. 许可

专有原型，保留所有权利。详见 `LICENSE`。

> AI生成
