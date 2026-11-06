# 证据索引 v0.3.0

> 发布日期：2026-11-06
> 仓库：`github.com/Dingh0208/clientgraph-ai`
> 版本标识：tag `v0.3.0`（分支 `main`）
> 原则：只登记本仓库真实存在的文件；不登记截图、密钥、客户资料或未执行的结果。

## 1. 回归证据

| 文件 | 内容 | 结论 |
|---|---|---|
| `evidence/integration-v0.3.0-2026-11-06.json` | 2 客户/3 项目/多来源集成 | 29 项通过 |
| `evidence/customer360-2026-11-06.json` | 客户 360 多项目/多来源 | 通过 |
| `evidence/extraction-2026-11-06.json` | 需求/预算/工期/验收抽取 | 23 项通过 |
| `evidence/requirement-history-2026-11-06.json` | 三次沟通版本演化 | 28 项通过 |
| `evidence/conflicts-2026-11-06.json` | 八类冲突 | 22 项通过 |
| `evidence/tasks-2026-11-06.json` | 待办/延期/重开/提醒 | 28 项通过 |
| `evidence/relationship-view-2026-11-06.json` | 关系图/同名/共享文件 | 26 项通过 |
| `evidence/unified-search-2026-11-06.json` | 三类自然语言问答 | 27 项通过 |
| `evidence/audio-pipeline-2026-11-06.json` | 长音频/切片/超时 | 7/7 |
| `evidence/media-pipeline-2026-11-06.json` | 视频音轨/PDF/OCR | 8/8 |
| `evidence/document-pipeline-2026-11-06.json` | Office/邮件/聊天解析 | 13/13 |
| `evidence/evidence-layer-2026-11-06.json` | 证据归一化 | 22/22 |
| `evidence/archive-workflow-2026-11-06.json` | 待归档 | 通过 |
| `evidence/performance-diagnostics-2026-11-06.json` | 性能/诊断 | 通过 |
| `evidence/regression-09-15-2026-11-06.json` | 09–15 轮汇总 | 通过 |

## 2. 代码与文档

| 路径 | 内容 |
|---|---|
| `customer360/` | 客户 360 聚合 |
| `extraction/` | 需求抽取 |
| `requirement_history/` | 版本演化 |
| `conflict_detection/` | 八类冲突 |
| `task_center/` | 待办与提醒策略 |
| `relationship_view/` | 可解释关系图 |
| `unified_search/` | 统一检索与问答 |
| `ops/` | 本地诊断 |
| `docs/数据模型-v0.3.0.md` | 实体、关系、隔离规则 |
| `docs/搜索测试矩阵-v1.0.md` | 关键词/自然语言/跨客户矩阵 |
| `docs/失败案例-v0.3.0.md` | 真实失败路径与已修复缺陷 |
| `docs/RELEASE-NOTES-v0.3.0.md` | 版本说明 |

## 3. 原则

- 测试证据为实际运行的 JSON 输出，不使用截图代替断言。
- 未执行的 Qwen ASR、LibreOffice 转换、压缩包解压、微信数据库均明确标为未完成。
- 仓库不包含真实客户资料、平台密钥、浏览器配置或本地运行目录。
- 证据中的文件路径均为相对名称或运行目录内的派生名。

> AI生成
