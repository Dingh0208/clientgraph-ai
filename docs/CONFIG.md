# 运行配置

> 记录 v0.3.0 实际使用的环境与配置；不含任何密钥、账号或客户数据。

## 1. 运行环境

| 项 | 值 |
|---|---|
| 操作系统 | Windows 10/11 x64 |
| 浏览器 | Chromium 156.0.0.0（Playwright 内置） |
| 视口 | 996 × 938 |
| 语言 / 时区 | zh-CN / Asia/Shanghai |
| Node.js（测试驱动） | v24.18.0 |
| Python（静态服务） | 3.12.13 |
| Git | 2.50.0.windows.1 |

## 2. 启动

```bash
python -m ops.server --port 8123
```

浏览器访问 `http://127.0.0.1:8123/index.html`。仅静态原型可改用 `python -m http.server 8123 --directory prototype`，但诊断页会提示启动 ops 服务。

## 3. 应用配置

| 项 | 值 | 说明 |
|---|---|---|
| 模型 | 未配置 / Mock ASR | 原型问答为本地检索；ASR 为 Mock |
| API Key | 无 | 仓库与页面均不含密钥；Qwen 需外部环境变量 |
| 网络请求 | 仅本地 `/api/diagnostics` | 不加载外部字体、脚本、统计 |
| 存储 | localStorage | 导入队列、待归档状态 |
| 数据源 | 内置常量 | 12 份虚构资料 + 9 条待归档 |
| 端口 | 8123 | 仅本地回环 |

## 4. 验证

```bash
curl -I http://127.0.0.1:8123/index.html
# HTTP/1.0 200 OK
```

## 5. 发布配置（脱敏）

| 项 | 值 |
|---|---|
| 仓库 | `github.com/Dingh0208/clientgraph-ai` |
| 分支 | `main` |
| 标签 | `v0.3.0` |
| 认证 | 通过运行时环境变量注入，未写入仓库、`.git/config` 或日志 |
| 提交内容 | 原型、流水线、诊断服务、文档、回归证据、许可与忽略规则 |

> 本文件不记录任何令牌、密钥、Cookie 或私有地址；发布用的凭据在会话结束后不保留。

> AI生成

