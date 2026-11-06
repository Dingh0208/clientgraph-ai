# 证据索引 v0.2.0

> 发布日期：2026-11-06
> 仓库：`github.com/Dingh0208/clientgraph-ai`
> 版本标识：tag `v0.2.0`（分支 `main`）
> 原则：只登记本仓库真实存在的文件；不登记截图、密钥、客户资料或未执行的结果。

## 1. 回归证据

| 文件 | 内容 | 结论 |
|---|---|---|
| `evidence/audio-pipeline-2026-11-06.json` | 长音频/短音频/空音频/切片失败/超时/部分重试 | 7/7 |
| `evidence/media-pipeline-2026-11-06.json` | 视频音轨、PDF 文本层、扫描 OCR、低清/空白/失败 | 8/8 |
| `evidence/document-pipeline-2026-11-06.json` | DOCX/XLSX/XLS/PPTX/EML/TXT/HTML/JSON/聊天 | 13/13 |
| `evidence/evidence-layer-2026-11-06.json` | 证据归一化与合并隔离 | 22/22 |
| `evidence/archive-workflow-2026-11-06.json` | 待归档逐条/批量/忽略恢复/审计 | 通过 |
| `evidence/performance-diagnostics-2026-11-06.json` | 性能采样与本地诊断/启动策略 | 通过 |
| `evidence/regression-09-15-2026-11-06.json` | 第 09–15 轮汇总 | 通过 |

## 2. 代码与文档

| 路径 | 内容 |
|---|---|
| `prototype/index.html` | 交互原型（导入、待归档、诊断等） |
| `audio_pipeline/` | 长音频切片与 ASR |
| `media_pipeline/` | 视频音轨、PDF/OCR |
| `document_pipeline/` | Office/邮件/文本/聊天解析 |
| `evidence_layer/` | 证据归一化与合并 |
| `ops/` | 本地诊断与 API 服务 |
| `scripts/verify_*.py` | 四组可复现验证 |
| `docs/解析矩阵-v1.0.md` | 输入类型、保留内容、错误码 |
| `docs/性能记录-v1.0.md` | 实测耗时与界面估算 |
| `docs/已知限制-v1.0.md` | 当前限制汇总 |
| `docs/回归记录-09-15.md` | 真实输入输出与失败案例 |

## 3. 原则

- 测试证据为实际运行的 JSON 输出，不使用截图代替断言。
- 未执行的 Qwen ASR、LibreOffice 转换、压缩包解压、微信数据库均明确标为未完成。
- 仓库不包含真实客户资料、平台密钥、浏览器配置或本地运行目录。
- 证据中的文件路径均为相对名称或运行目录内的派生名。

> AI生成
