# Web 上传与任务处理 v1.0

> 日期：2026-11-08
> 代码：`ops/uploads.py`、`ops/server.py`
> 页面：`prototype/upload.html`
> 证据：`evidence/web-uploads-2026-11-08.json`（53 项检查通过）

## 1. 范围

把文件、邮件、聊天导出通过 Web 上传，交给服务端分阶段处理：

```
上传 → 解析 → 转写 → OCR → 匹配
```

单老板使用；沿用 Web 访问保护，局域网/公网实例必须先登录。微信资料必须带用户已选择的会话与日期范围，服务端不扫描微信数据库，也不因改 Web 扩大访问权限。

## 2. 大小与类型

- 单文件默认上限 50 MB，可通过 `--max-upload-mb` 调整；
- 先看 `Content-Length` 超限直接 413，不落盘；读取过程中超限同样拒绝并删除临时文件；
- 空文件拒绝；PDF 校验文件头 `%PDF-`；
- 文件名做路径穿越清洗，只保留文件名并截断长度。

| 来源类型 | 允许扩展名 |
|---|---|
| `file` | pdf/docx/doc/txt/md/rtf/xlsx/xls/pptx/ppt/csv、mp3/wav/m4a/amr/aac/flac/ogg、png/jpg/jpeg/webp/bmp/tif/tiff |
| `email` | eml/msg/txt/html/htm |
| `chat` | txt/html/htm/json/csv |
| `wechat` | txt/html/htm/json/csv |

可执行文件、压缩包、无扩展名文件直接拒绝（`E_FILE_TYPE` / 415）。

## 3. 微信导入范围

微信上传必须带 `X-Wechat-Scope`（Base64 编码 JSON），包含：

- `selected_by_user: true`（用户已确认）；
- `contact_id`、`conversation_id`；
- `date_from`、`date_to`（YYYY-MM-DD）。

服务端检查文件内消息时间戳，任何一条超出范围即拒绝（`E_WECHAT_OUT_OF_SCOPE` / 422）。没有选择范围、范围未确认、日期缺失或颠倒都拒绝。微信数据库、聊天记录目录、图片缓存不在服务端扫描范围内。

## 4. 阶段状态

每个任务固定包含五个阶段，按顺序执行：

| 阶段 | 说明 | 不适用时 |
|---|---|---|
| upload | 上传完成、文件落盘 | 不会跳过 |
| parse | 文本/邮件/Office/PDF 元数据解析 | — |
| transcribe | 音频转写 | 非音频跳过 |
| ocr | 图片/PDF 识别 | 非图片/PDF 跳过 |
| match | 客户/项目匹配 | 未选目标跳过 |

阶段状态：`pending / running / done / failed / skipped / cancelled`。
任务状态：`queued / running / completed / partial / failed / cancelled`。

- ASR 未配置时转写阶段标记 `skipped`、原因 `E_ASR_NOT_CONFIGURED`，不伪造转写文本；任务为“部分完成”；
- OCR 未安装时同理；
- 阶段失败会保留此前已完成阶段的结果，任务为部分完成或失败。

## 5. 长任务与页面离开

- 任务在服务端线程中执行，页面关闭不中断；
- 页面每 2 秒轮询 `/api/jobs`，只读查询；重新打开页面或换连接仍能看到任务；
- 任务与文件持久化在 `--config-dir` 下的 `data/jobs`、`data/uploads`；
- 服务重启时，正在运行的阶段标记失败 `E_SERVICE_RESTART`，已完成阶段结果保留；任务可重试。

## 6. 重试、取消与重复提交

- 重试：从第一个失败/取消/不可用阶段继续，已完成阶段不重跑；
- 取消：队列中立即取消；运行中在阶段边界停止；已完成阶段结果保留；
- 重复：同一文件哈希 + 来源类型 + 客户/项目 + 微信范围返回原任务（`duplicate=true`），不新建；
- 幂等键：同一 `X-Idempotency-Key` 重复提交返回原任务；同一键对应不同文件返回 `E_IDEMPOTENCY_CONFLICT`（409）；
- 网络中断：读取字节数少于 `Content-Length` 返回 `E_UPLOAD_INCOMPLETE`，不创建任务。

## 7. 接口

### 上传

```http
POST /api/uploads
X-File-Name: <percent-encoded name>
X-Source-Type: file|email|chat|wechat
X-Customer-Id: c1            # 可选
X-Project-Id: p1             # 可选
X-Wechat-Scope: <base64>     # wechat 必填
X-Idempotency-Key: <key>     # 可选
X-Requested-With: XMLHttpRequest
Content-Type: application/octet-stream

<原始文件字节>
```

返回 201（新建）或 200（重复）；响应为任务 JSON。

### 查询与操作

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/jobs` | 任务列表，按创建时间倒序 |
| GET | `/api/jobs/{id}` | 单任务与阶段状态 |
| POST | `/api/jobs/{id}/retry` | 重试 |
| POST | `/api/jobs/{id}/cancel` | 取消 |
| GET | `/upload` | 任务页 |

除健康检查与登录外，全部沿用 Web 单老板登录与 CSRF 校验。

## 8. 验证结果

`python scripts/verify_web_uploads.py`，53 项全部通过：

- 未登录访问任务 API 返回 401；
- 文本、邮件、聊天、微信（范围内）上传并完成；
- 音频进入转写阶段，非图片任务 OCR 跳过；
- 图片 OCR 失败后任务部分完成，重试只重跑 OCR，解析结果保留；
- 取消后已完成阶段保留，重试可继续；
- 服务重启后中断阶段标记 `E_SERVICE_RESTART`，已完成结果保留，可重试；
- 同一文件重复提交返回同一任务；幂等键生效；
- 大文件 413、类型不符 415、空文件拒绝、网络中断 400 且不建任务；
- 微信缺范围与超范围分别拒绝；
- 离开页面后新连接仍能查询任务与列表。

## 9. 限制

- 解析为本地轻量实现：PDF 不做正文抽取、Office 只取文本节点；复杂版式可能丢失结构；
- ASR/OCR 未配置时按“跳过”展示，不生成假结果；
- 上传与任务目录未加密，依赖本机文件权限；
- 单进程线程执行，未做多进程队列与限流；大并发会排队；
- 重复判断以文件哈希与目标为键，暂无“重新上传覆盖”入口；
- 微信范围只校验元数据与文件内时间戳，不验证导出文件是否真属于该会话；
- 任务页不提供批量上传与断点续传。

> AI生成
