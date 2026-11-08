# ClientGraph AI

> 版本：v0.5.0 · 2026-11-08
> 形态：Windows 单机单用户 Web 稳定性候选版
> 构建：`build_id=223ac2617119ec17`

ClientGraph AI 面向单人多项目的软件公司经营者，把分散的客户资料聚合成可追溯的工作台：**客户 360、需求抽取与版本、冲突、待办与提醒、关系图、全局搜索、需求澄清、Web 上传**。

本仓库是产品原型与可验证的本地分析代码，不是生产系统。

---

## 1. 模块

| 模块 | 路径 | 能力 |
|---|---|---|
| 交互原型 | `prototype/index.html` | 概览、问答、客户 360、导入、待归档、缺口、诊断 |
| 设置 / 登录 | `prototype/settings.html`、`login.html` | 单人访问保护、个人信息、导入偏好、模型、通知、隐私备份、版本 |
| 上传任务 | `prototype/upload.html` | 文件/邮件/聊天/微信上传，五阶段状态 |
| 客户 360 | `customer360/` | 身份、项目、需求、风险、待办、时间线、证据 |
| 需求抽取 / 版本 | `extraction/`、`requirement_history/` | 需求、预算、工期、验收；追加式版本 |
| 冲突 / 待办 / 关系图 / 搜索 | `conflict_detection/`、`task_center/`、`relationship_view/`、`unified_search/` | 冲突、提醒、关系、检索 |
| 解析 | `audio_pipeline/`、`media_pipeline/`、`document_pipeline/` | 音频、视频、PDF/OCR、Office/邮件/聊天 |
| 需求澄清 | `clarification/` | 选材、分批、证据问题、优先级、状态、追问、工作单、导出 |
| 回答回写 | `writeback/` | 目标选择、字段预览、人工确认、版本快照 |
| Web 服务 | `ops/` | 单人认证、设置、上传任务、诊断、存储迁移 |

## 2. v0.5.0 发布验证

| 项 | 结果 |
|---|---|
| 构建 | `clientgraph-ai-0.5.0`，114 文件，build_id `223ac2617119ec17` |
| 部署 | Windows 单机，`127.0.0.1:8140`，配置目录在仓库外 |
| 健康检查 | `/api/health` 返回 version 0.5.0 + build_id |
| 浏览器确认 | 标题与正文显示 v0.5.0，控制台 0 错误 |
| 存储迁移 | JSON schema 1→2，10 项通过，密钥/设置/任务不变 |
| 回滚演练 | v0.5.0 → v0.4.0 → v0.5.0，健康与版本均恢复 |
| Web 跨模块矩阵 | 19/19；Chromium/Chrome/Edge；三档视口 |
| 性能 | health p50 12.6–15.0 ms，p95 21.0–24.0 ms，首页 266–458 ms |

> 目标环境无关系型数据库，迁移对象为 `secure.json` 与 `data/jobs/*.json`，不是 SQL 数据库迁移。

## 3. 快速开始

```bash
python -m ops.server --port 8140
# 打开 http://127.0.0.1:8140/
```

局域网/公网：

```bash
python -m ops.server --set-password
python -m ops.server --host 0.0.0.0 --port 8140 --require-auth --secure-cookie
```

## 4. 验证

```bash
python scripts/verify_deployment.py --base http://127.0.0.1:8140 --version 0.5.0
python scripts/verify_web_matrix.py
python scripts/verify_web_access_settings.py
python scripts/verify_web_uploads.py
python scripts/verify_storage_migration.py
python scripts/verify_clarification_e2e.py
python scripts/verify_question_plan.py
python scripts/verify_question_status.py
python scripts/verify_writeback.py
python scripts/verify_clarification_records.py
```

## 5. 文档

- `docs/Web部署说明-v1.0.md`
- `docs/存储迁移-v1.0.md`
- `docs/性能记录-v0.5.0.md`
- `docs/服务诊断-v0.5.0.md`
- `docs/演示路径-v0.5.0.md`
- `docs/Web跨模块回归矩阵-v1.0.md`
- `docs/已知限制-v0.5.0.md`
- `docs/RELEASE-NOTES-v0.5.0.md`
- `docs/验收矩阵-v0.4.0.md`

## 6. 安全

- 发布物不含 `.env`、`secure.json`、数据库、`data/`、客户资料、部署凭证、桌面安装包；
- 模型密钥只在服务端配置/环境变量；
- 演示数据均为虚构；
- 局域网/公网必须密码 + `--require-auth` + HTTPS。

## 7. 已知限制

- 无 SQL 数据库；单机单用户；无容器/集群/多租户；
- 390×844 主工作台横向溢出约 570 px；
- 需求演化、待办无独立 Web 页面；
- Firefox/Safari 未自动化；
- 未发布桌面安装包。

完整清单见 `docs/已知限制-v0.5.0.md`。

## 8. 许可

专有原型，保留所有权利。详见 `LICENSE`。

> AI生成
