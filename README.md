# ClientGraph AI

> 版本：v0.3.0 · 2026-11-06
> 形态：本地单文件原型 + 本地 Python 分析流水线 + 本地诊断服务

ClientGraph AI 面向单人多项目的软件公司经营者，把分散的客户资料聚合成可追溯的工作台：**客户 360、需求抽取与版本、冲突、待办与提醒、关系图、全局搜索**。

本仓库是产品原型与可验证的本地分析代码，不是生产系统。

---

## 1. 模块

| 模块 | 路径 | 能力 |
|---|---|---|
| 交互原型 | `prototype/index.html` | 概览、问答、客户 360、导入、待归档、诊断 |
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

## 2. v0.3.0 集成回归

两个客户（青岚、恒晟）、三个项目、多来源数据：

| 检查 | 结果 |
|---|---|
| 客户 360 | c1 2 项目/2 需求/1 风险/3 待办；c2 1 项目/2 需求/1 风险/1 待办 |
| 时间线 | 倒序，缺失时间排最后 |
| 需求抽取 | c1 设备台账；c2 供应链协同；无串线 |
| 版本演化 | 3 个项目版本；预算 8 万→10 万、工期 11-15→12-01 |
| 冲突 | 2 个，分属 p1/p3，均 `must_confirm` |
| 待办 | 4 条；完成 T1 不影响 T3 |
| 通知 | 到期与无跟进提醒；应用退出不伪造已发送 |
| 关系图 | 27 节点/23 边；无 c1→p3、c2→p1 |
| 全局搜索 | 小程序开发仅 c1；供应链仅 c2；逾期 T1/T3 |
| 检查 | 29 项全部通过 |

详见 `docs/RELEASE-NOTES-v0.3.0.md` 与 `evidence/integration-v0.3.0-2026-11-06.json`。

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
python scripts/verify_extraction.py
python scripts/verify_requirement_history.py
python scripts/verify_conflicts.py
python scripts/verify_tasks.py
python scripts/verify_relationship_view.py
python scripts/verify_unified_search.py
```

## 5. 关键限制

- ASR 为 Mock；Qwen 未联调。
- OCR 依赖本地 RapidOCR，CPU 单页约 3–19 秒。
- `.doc`/`.ppt` 依赖 LibreOffice；压缩包/微信数据库未解析。
- 2.1 GB / 200 页 OCR 为界面模拟，不是真实吞吐。
- 通知策略已实现，真实 Windows Toast 需桌面端接入。
- 关系图为 JSON，无可视化画布。
- 搜索意图为规则识别，换问法可能落关键词兜底。
- 单机单用户，无账号/权限/云同步。

完整清单见 `docs/已知限制-v1.0.md`。

## 6. 文档

- `docs/数据模型-v0.3.0.md`
- `docs/搜索测试矩阵-v1.0.md`
- `docs/失败案例-v0.3.0.md`
- `docs/RELEASE-NOTES-v0.3.0.md`
- `docs/客户360-v1.0.md`
- `docs/需求抽取-v1.0.md`
- `docs/需求版本历史-v1.0.md`
- `docs/冲突检测-v1.0.md`
- `docs/待办与提醒-v1.0.md`
- `docs/关系视图-v1.0.md`
- `docs/统一检索-v1.0.md`
- `docs/解析矩阵-v1.0.md`
- `docs/性能记录-v1.0.md`
- `docs/已知限制-v1.0.md`

## 7. 许可

专有原型，保留所有权利。详见 `LICENSE`。

> AI生成
