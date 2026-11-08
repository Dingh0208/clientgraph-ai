# Web 部署说明 v1.0

> 版本：v0.5.0 · 2026-11-08
> 目标环境：Windows 单机单用户，127.0.0.1:8140
> 形态：Python Web 服务 + 静态原型，不含桌面安装包

## 1. 目标环境

| 项 | 值 |
|---|---|
| 操作系统 | Windows 10/11 x64 |
| Python | 3.12 |
| 访问地址 | `http://127.0.0.1:8140/`（本地单用户） |
| 数据库 | 无关系型数据库；状态文件为 `secure.json` 与 `data/jobs/*.json` |
| 配置目录 | `D:\code\clientgraph-ai-deploy\config`（不进入仓库） |
| 数据目录 | 配置目录下的 `data/`（不进入仓库） |
| 认证 | 本地回环免登录；局域网/公网部署必须设置老板密码并加 `--require-auth` |
| 桌面安装包 | 不构建、不发布 |

## 2. 构建

```bash
python scripts/build_web_release.py --zip
```

产物：

- `.temp/release-build/clientgraph-ai-0.5.0/`
- `.temp/release-build/clientgraph-ai-0.5.zip`
- `BUILD-MANIFEST.json`：版本、build_id、文件 SHA256、构建时间

本次：

| 项 | 值 |
|---|---|
| version | 0.5.0 |
| build_id | 223ac2617119ec17 |
| files | 114 |
| commit | unknown（开发目录非 Git 仓库） |

构建排除 `.env`、`secure.json`、`data/`、`demo-data/`、数据库、部署凭证与桌面安装包。

## 3. 存储迁移

目标环境没有关系型数据库，因此“数据库迁移”落为本地状态 schema 迁移：

```bash
python -m ops.storage_migration --config-dir D:\code\clientgraph-ai-deploy\config
```

结果：

- `secure.json` schema 1 → 2；
- `data/jobs/*.json` 增加 `schema_version=2` 与 `stage_count`；
- 原文件备份为 `secure.v1.bak.json`、`*.v1.bak`；
- 迁移幂等，第二次运行返回 `already_current`；
- 迁移报告 `migration-v2.json` 不含密钥值。

详见 `evidence/deployment-migration-v0.5.0.json` 与 `docs/存储迁移-v1.0.md`。

## 4. 部署

```powershell
# 1. 复制产物到部署目录（保留 config 与 data）
Copy-Item .temp\release-build\clientgraph-ai-0.5.0 D:\code\clientgraph-ai-deploy\current -Recurse

# 2. 启动（本地单用户）
Set-Location D:\code\clientgraph-ai-deploy\current
python -m ops.server --port 8140 --config-dir D:\code\clientgraph-ai-deploy\config
```

生产/局域网：

```bash
python -m ops.server --host 0.0.0.0 --port 8140 --require-auth --secure-cookie
```

启动前必须已设置密码；否则服务拒绝启动。

## 5. 健康检查

```bash
curl http://127.0.0.1:8140/api/health
curl http://127.0.0.1:8140/api/version
```

期望：

```json
{"ok":true,"service":"clientgraph-ops","auth_required":false,
 "version":"0.5.0","build_id":"223ac2617119ec17"}
```

浏览器实测：

- 标题：`ClientGraph AI · v0.5.0`
- 页面可见 `v0.5.0`
- 控制台 0 错误、0 页面异常
- 首屏加载 265–458 ms（本地）

证据：`evidence/deployment-v0.5.0.json`、`evidence/deployment-v0.5.0-restored.json`。

## 6. 回滚演练

本次真实执行：

1. 停止 v0.5.0；
2. 用 `git archive v0.4.0` 生成上一版目录；
3. `current` 切换到 v0.4.0，启动 8140；
4. `/api/health` 返回 200，`VERSION` 为 0.4.0；
5. 停止 v0.4.0，恢复 v0.5.0 产物；
6. 再次健康检查，`version=0.5.0`、`build_id=223ac2617119ec17`，浏览器可见 v0.5.0。

记录：`evidence/rollback-drill-v0.5.0.json`。

注意：v0.4.0 的 health 接口没有 `version` 字段，回滚验证以 HTTP 200 + `VERSION` 文件为准；v0.5.0 起 health 返回版本与 build_id。

## 7. 发布确认

发布后浏览器实际访问的是本次版本，依据：

- `/api/health` 的 `build_id` 与 `BUILD-MANIFEST.json` 一致；
- 页面标题与正文显示 `v0.5.0`；
- 部署目录 `VERSION` 为 0.5.0；
- Playwright 实际加载页面并读取正文，控制台无异常。

## 8. 安全与脱敏

- 发布物不含 `.env`、`secure.json`、数据库、`data/`、客户资料、部署凭证、桌面安装包；
- 模型密钥只在服务端配置/环境变量，不进入页面、URL、浏览器存储或日志；
- 演示数据均为虚构；
- 配置目录与部署目录均在仓库外，不随 Git 提交。

## 9. 限制

- 无数据库，因此没有 SQL 迁移；只迁移 JSON 状态；
- 单进程部署，无容器编排、无反向代理配置；
- 本机回环可免登录，LAN/公网必须加认证；
- 无桌面安装包，符合本次发布范围。

> AI生成
