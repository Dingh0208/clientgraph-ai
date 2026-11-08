# Web 单人访问保护与设置 v1.0

> 日期：2026-11-08
> 范围：第 33 轮部署决定——保留单老板使用，不增加团队、角色或多租户
> 代码：`ops/auth.py`、`ops/secure_store.py`、`ops/server.py`
> 页面：`prototype/login.html`、`prototype/settings.html`
> 证据：`evidence/web-access-settings-2026-11-08.json`（64 项检查通过）

## 1. 部署决定

| 场景 | 访问规则 |
|---|---|
| 仅本机使用（绑定 `127.0.0.1` / `::1`） | 可以免登录，直接打开设置与原型 |
| 局域网或公网可达（绑定 `0.0.0.0` 或非回环地址） | **必须先验证老板密码**，否则拒绝启动 |
| 反向代理对外 | 启动加 `--require-auth`，即使回环也强制登录 |

只有一个老板账号，没有团队、角色、多租户、邀请或权限分级。

启动：

```bash
# 仅本机
python -m ops.server --port 8123

# 首次设置密码（写入服务端安全配置）
python -m ops.server --set-password

# 局域网 / 公网可达
python -m ops.server --host 0.0.0.0 --port 8123

# 反向代理后面（本地回环也强制登录）
python -m ops.server --require-auth --secure-cookie --port 8123
```

未设置密码时绑定非回环地址会直接退出，并提示先执行 `--set-password`；不会以“无保护”状态启动。

## 2. 身份验证

- 密码使用 PBKDF2-HMAC-SHA256（240,000 次）加随机盐，只保存哈希；
- 会话为 HMAC 签名令牌，绑定 `session_epoch`；修改密码会递增 epoch，旧会话全部失效；
- Cookie：`HttpOnly`、`SameSite=Lax`、`Path=/`、12 小时；HTTPS 部署加 `--secure-cookie` 启用 `Secure`；
- 登录失败按 IP 限速（默认 10 分钟 5 次），超限返回 `E_RATE_LIMITED`；
- 登录错误统一返回“密码不正确”，不区分用户是否存在；
- 退出登录清除 Cookie；当前为无状态令牌，已泄露的旧令牌在过期前仍可能有效，需改密码使 epoch 失效；
- 未登录访问页面跳转 `/login?next=...`，访问 API 返回 401 JSON；`next` 只接受站内路径，防开放重定向。

CSRF：

- 所有写操作要求 `X-Requested-With: XMLHttpRequest`；
- 若请求带 `Origin`，其 host 必须与当前 `Host` 一致；
- 设置接口只接受 `application/json`，普通表单无法直接提交。

## 3. 密钥与敏感配置

服务端安全配置默认位置：

- Windows：`%APPDATA%\ClientGraphAI\secure.json`
- 其他：`~/.config/clientgraph-ai/secure.json`
- 可用 `--config-dir` 或 `CG_CONFIG_DIR` 覆盖（不要放进代码仓库）

文件保存：密码哈希、会话密钥、模型 API Key、设置项；目录权限 700、文件 600。环境变量 `CG_TEXT_API_KEY` / `CG_SPEECH_API_KEY` 优先于文件，且不会被页面覆盖或清除。

密钥边界：

- 设置接口只返回 `{configured, source}`，不回显任何密钥字符；
- 页面密文输入框保存后清空，不写入 DOM 文本；
- 不写入 `localStorage` / `sessionStorage` / Cookie / URL；
- 不写入前端 bundle，不写入访问日志（服务器不记录请求行、不记录请求体）；
- 设置备份只导出非敏感设置，不含密码、会话密钥、模型密钥。

注意：安全配置在磁盘上未加密，依赖本机账户与文件权限；多人共用一台电脑时应使用独立系统账户或磁盘加密。

## 4. 设置页

入口：原型左侧导航“设置”，地址 `/settings`。六个区块：

| 区块 | 内容 |
|---|---|
| 个人信息 | 显示名称、邮箱、时区、界面语言 |
| 导入偏好 | 默认客户/项目、重复资料策略、自动待归档、日期格式 |
| 默认文本/语音模型 | 模型名、接口地址、密钥（只写）、检查配置、探测接口 |
| 通知 | 桌面通知、每日摘要、摘要时间、免打扰时段、只提醒逾期 |
| 隐私与备份 | 自动备份开关、备份目录、保留天数、对外隐藏内部信息、导出设置备份 |
| 版本信息 | 应用版本、配置结构、配置文件路径、访问模式 |

页面打开只执行两个只读请求：`GET /api/settings` 与 `GET /api/auth/session`；不会自动保存、不会自动测试、不会拉取邮件、不会调用模型。

## 5. 操作与副作用

| 操作 | 接口 | 副作用 |
|---|---|---|
| 打开设置页 | `GET /settings` | 无邮件、无模型调用 |
| 读取设置 | `GET /api/settings` | 无 |
| 保存设置 | `PUT /api/settings` | 只写服务端配置；无邮件、无模型调用 |
| 检查配置 | `POST /api/settings/test` `{target, live:false}` | 只校验密钥与字段；无网络、无模型调用 |
| 探测接口 | 同上 `live:true` | 仅对配置的接口地址发 `HEAD`；**不发送模型请求** |
| 导出备份 | `GET /api/settings/backup` | 只导出非敏感设置 |
| 退出登录 | `POST /api/auth/logout` | 清除 Cookie |

代码内置 `SIDE_EFFECTS = {email_fetch, model_call, model_probe}` 计数器用于回归：打开、保存、检查配置后，前两项必须为 0；只有显式 `live:true` 才增加 `model_probe`。本项目没有邮件拉取接口，设置流程也不会触发导入或诊断组件。

接口错误返回 `{"error":{"code","message"}}`，常见错误：

| 错误码 | 含义 |
|---|---|
| `E_AUTH_REQUIRED` | 未登录 |
| `E_BAD_CREDENTIALS` | 密码错误 |
| `E_RATE_LIMITED` | 登录尝试过多 |
| `E_CSRF` | 缺少同源校验头或 Origin 不符 |
| `E_INVALID_SETTING` / `E_INVALID_EMAIL` / `E_INVALID_TIME` | 设置校验失败 |
| `E_KEY_MANAGED_BY_ENV` | 密钥由环境变量管理，页面不能改 |
| `E_NO_ENDPOINT` | 探测时未配置接口地址 |
| `E_CONFIG_CORRUPT` | 安全配置无法读取（不会静默重置） |

## 6. 验证结果

`python scripts/verify_web_access_settings.py`，64 项全部通过，覆盖：

- 本机免登录可访问；强制认证模式下页面跳登录、API 401；
- 正确/错误密码、Cookie 的 HttpOnly/SameSite/Secure/Path、篡改令牌、退出后 401；
- 未设置密码时非回环绑定拒绝启动；
- CSRF 缺失与跨源 Origin 拒绝；
- 设置保存、校验、备份、路径穿越防护；
- 密钥不出现在响应、页面、备份，只存在服务端配置文件；
- 打开页面、读取、保存后 `email_fetch=0`、`model_call=0`；
- 只有显式 `live:true` 才增加 `model_probe`，且不调用模型；
- 设置页包含六个区块，页面无浏览器存储、URL 无密钥。

## 7. 限制

- 单人密码，无二次验证、找回密码、账号锁定后的管理员解锁流程；
- 登录限速在内存中，进程重启后清零；
- 会话为无状态令牌，退出只清浏览器 Cookie，不维护服务端吊销列表；改密码会通过 epoch 使旧令牌失效；
- 安全配置文件未加密，依赖文件权限与操作系统账户；
- `live` 探测会对设置中的任意 http(s) 地址发 HEAD，属于老板主动操作；生产环境应限制可配置地址或走白名单；
- 未内置 HTTPS，公网部署必须由反向代理终止 TLS，并配合 `--secure-cookie`；
- 设置中的默认文本/语音模型尚未接入实际 ASR/抽取流水线，当前只做服务端保存与配置检查；
- 导入偏好与通知开关已持久化，但尚未接入导入中心与提醒引擎；
- 设置页不提供团队、角色、多用户管理，这是产品决定，不是缺失。

> AI生成
