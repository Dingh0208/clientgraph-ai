# ClientGraph AI v0.5.0 发布说明

> 日期：2026-11-08
> 主题：Web 稳定性候选版
> 构建：`0.5.0` / `build_id=223ac2617119ec17`
> 目标：Windows 单机单用户 Web，127.0.0.1:8140

## 1. 本次内容

- Web 单人访问保护与设置入口
- 文件/邮件/聊天 Web 上传与服务端分阶段任务
- 需求澄清助手完整闭环（选材、分批、证据问题、冲突、回答、追问、回写、历史、增量、重试、导出）
- 跨模块 Web 回归矩阵（Chromium/Chrome/Edge，三档视口）
- 本地状态 schema 迁移（无关系型数据库）
- 部署、健康检查与真实回滚演练

## 2. 构建与部署

| 项 | 值 |
|---|---|
| 构建命令 | `python scripts/build_web_release.py --zip` |
| 产物 | `clientgraph-ai-0.5.0/` + `BUILD-MANIFEST.json` |
| 文件数 | 114 |
| 部署目录 | `D:\code\clientgraph-ai-deploy\current` |
| 配置目录 | `D:\code\clientgraph-ai-deploy\config`（仓库外） |
| 健康检查 | `GET /api/health` → version/build_id |
| 浏览器确认 | 标题与正文显示 v0.5.0，控制台 0 错误 |

## 3. 迁移与回滚

- 存储迁移：`python -m ops.storage_migration --config-dir <config>`，schema 1 → 2；密钥、设置、任务结果不变；备份与幂等验证 10/10。
- 回滚演练：v0.5.0 → v0.4.0 → v0.5.0，健康检查与 VERSION 均符合预期。
- 证据：`evidence/deployment-migration-v0.5.0.json`、`evidence/rollback-drill-v0.5.0.json`。

## 4. 回归与性能

| 套件 | 结果 |
|---|---|
| Web 跨模块矩阵 | 19/19 通过；Chrome/Edge 各 11 项冒烟通过 |
| 访问与设置 | 64 项通过 |
| Web 上传 | 53 项通过 |
| 问题计划/优先级 | 52 项通过 |
| 问题状态 | 57 项通过 |
| 回写 | 64 项通过 |
| 工作单生命周期 | 56 项通过 |
| 存储迁移 | 10 项通过 |
| 性能 | health p50 12.6–15.0 ms，p95 21.0–24.0 ms，首页 266–458 ms |

## 5. 文档

- `docs/Web部署说明-v1.0.md`
- `docs/存储迁移-v1.0.md`
- `docs/性能记录-v0.5.0.md`
- `docs/服务诊断-v0.5.0.md`
- `docs/演示路径-v0.5.0.md`
- `docs/Web跨模块回归矩阵-v1.0.md`
- `docs/已知限制-v0.5.0.md`
- `docs/验收矩阵-v0.4.0.md`（澄清模块延续）

## 6. 安全

- 发布物不含 `.env`、`secure.json`、数据库、`data/`、客户资料、部署凭证、桌面安装包；
- 模型密钥只在服务端配置/环境变量；
- 演示数据均为虚构；
- 局域网/公网部署必须密码 + `--require-auth` + HTTPS。

## 7. 已知限制

- 无 SQL 数据库，迁移仅覆盖 JSON 状态；
- 单机单用户，无容器/集群/多租户；
- 390×844 主工作台横向溢出约 570 px；
- 需求演化、待办无独立 Web 页面；
- Firefox/Safari 未自动化；
- 未发布桌面安装包。

完整清单见 `docs/已知限制-v0.5.0.md`。

## 8. 复现

```bash
python -m ops.server --port 8140 --config-dir <config>
python scripts/verify_deployment.py --base http://127.0.0.1:8140 --version 0.5.0
python scripts/verify_web_matrix.py
```

> AI生成
