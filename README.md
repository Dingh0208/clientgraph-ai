# ClientGraph AI

> 版本：v0.2.0 · 2026-11-06
> 形态：本地单文件原型 + 本地 Python 流水线 + 本地诊断服务

ClientGraph AI 面向单人多项目的软件公司经营者，把分散的客户资料聚合成可追溯的工作台：**资料问答、跨模态证据、客户/项目概览、导入中心、待归档、缺口与冲突、本地诊断**。

本仓库是产品原型与可验证的本地处理代码，不是生产系统。

---

## 1. 本版包含

| 模块 | 路径 | 能力 |
|---|---|---|
| 交互原型 | `prototype/index.html` | 概览、问答、客户/项目、导入中心、待归档、缺口、本地诊断 |
| 长音频 | `audio_pipeline/` | 16kHz 单声道、ffmpeg 切片、并发 ASR、超时/重试、合并时间戳 |
| 视频/PDF/OCR | `media_pipeline/` | 视频只提音轨、PDF 文本层优先、扫描页 OCR、页码/bbox/置信度 |
| 文档解析 | `document_pipeline/` | DOCX/XLSX/XLS/PPTX/EML/TXT/HTML/JSON/聊天导出，表格行列与 PPT 页码 |
| 证据归一化 | `evidence_layer/` | 统一证据字段、跨来源合并、客户/项目/时间隔离 |
| 本地诊断 | `ops/` | Sidecar/微信/ffmpeg/OCR/ASR 检测、手动启动、日志、失败策略 |
| 回归验证 | `scripts/verify_*.py` | 7 音频 + 8 媒体 + 13 文档 + 22 证据检查 |

## 2. 快速开始

```bash
# 原型 + 诊断 API（推荐）
python -m ops.server --port 8123
# 打开 http://127.0.0.1:8123/

# 仅静态原型（诊断页会提示启动命令）
python -m http.server 8123 --directory prototype
```

原型无需构建。流水线依赖：

```bash
pip install -r media_pipeline/requirements.txt
pip install -r document_pipeline/requirements.txt
# audio_pipeline 使用 ffmpeg/ffprobe，需在 PATH 中
```

## 3. 核心行为

### 导入中心

- 20 个文件独立任务，并发 2；阶段进度、预计剩余、失败原因、重试；
- 单文件失败不阻塞其他文件；原件只读保留；
- 大文件（2.1 GB）、62 分钟音频、200 页 OCR 为界面负载模拟。

### 待归档

- 手机号/邮箱/微信精确匹配优先；多候选或无匹配停留待归档；
- 逐条确认、批量确认客户/项目/负责人、新建客户、忽略与恢复；
- 每次归档记录操作人、时间、来源。

### 本地诊断

- 真实检测 5 个组件，失败给出端口、日志、修复步骤；
- 手动启动 Sidecar/微信引擎（需配置命令）；
- 最多 2 次尝试、冷却 3 秒、端口冲突不重复拉起；
- 不以“服务不可用，请重试”代替具体原因。

## 4. 验证与证据

```bash
python scripts/verify_audio_pipeline.py
python scripts/verify_media_pipeline.py
python scripts/verify_document_pipeline.py
python scripts/verify_evidence_layer.py
```

回归汇总：`docs/回归记录-09-15.md`、`evidence/regression-09-15-2026-11-06.json`。

## 5. 关键限制

- ASR 为 **Mock**；Qwen 未配置、未联调，不能宣称真实转写。
- OCR 依赖 PyMuPDF/Pillow/RapidOCR；未安装时诊断会真实显示“未安装”。
- `.doc`/`.ppt` 需要 LibreOffice；当前环境未安装，走失败与另存建议。
- 压缩包只登记不解压；微信本地数据库未接入。
- 2.1 GB / 200 页 OCR 为界面模拟，不代表真实吞吐。
- 单机单用户，无账号、权限、云同步；审计存 localStorage/本地日志。
- 仓库与演示数据均为虚构，不含真实客户资料或平台密钥。

完整清单见 `docs/已知限制-v1.0.md`。

## 6. 文档

- `docs/解析矩阵-v1.0.md`
- `docs/性能记录-v1.0.md`
- `docs/已知限制-v1.0.md`
- `docs/回归记录-09-15.md`
- `docs/待归档处理-v1.0.md`
- `docs/性能与本地诊断-v1.0.md`
- `docs/长音频处理流程-v1.0.md`
- `docs/视频与PDF-OCR流程-v1.0.md`
- `docs/文档解析流程-v1.0.md`
- `docs/证据归一化-v1.0.md`

## 7. 许可

专有原型，保留所有权利。详见 `LICENSE`。

> AI生成
