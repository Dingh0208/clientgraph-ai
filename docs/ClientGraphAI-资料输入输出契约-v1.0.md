# ClientGraph AI 资料输入输出契约

> 文档版本：V1.0
> 文档日期：2026-11-06
> 文档状态：设计基线（待并入主 PRD 第 5.3、6.2 节）
> 产品简称：ClientGraph AI
> 依据文档：《客户信息聚合工作台》PRD V1.2、《客户需求澄清助手》PRD
> 目标读者：开发实现人员、验收人员
> 配套文档：《ClientGraph AI 用户旅程设计》V1.0

---

## 1. 范围与原则

本文定义 ClientGraph AI 对以下来源的最小输入输出契约：音频、视频、微信聊天、邮件、PDF、扫描件、Word、Excel、PPT、图片、压缩包、TXT、HTML、JSON。

三条总原则：

1. **原始文件不可覆盖**：原件只读，任何转换产物另存并记录来源。
2. **解析与理解分离**：本地解析只回答“资料里写了什么”，模型只回答“这意味着什么”。
3. **没有定位就没有证据**：任何文本片段都必须能通过定位符回到原件位置，否则不进入摘要、需求或澄清问题。

---

## 2. 三层数据模型与不可覆盖原则

### 2.1 三层结构

| 层 | 内容 | 谁写 | 可变性 | 失效条件 |
|---|---|---|---|---|
| 原始层 `files` | 原件、SHA-256、原名、大小、MIME、存储路径、导入时间 | 仅导入器 | **只读**，任何解析/转换/重命名都不得回写 | 内容哈希变化 = 视为新资料，旧记录不覆盖 |
| 解析层 `parse_runs` / `parse_blocks` | 本地提取的文本、结构块、时间、位置、警告 | 本地解析器 | **追加版本**，重跑生成新 run，旧 run 保留 | 解析器版本或参数变化时新建 run，不原地改 |
| AI 层 `ai_results` | 摘要、需求抽取、聊天分析、画像、澄清问题、转写 | 模型 / 人工 | **版本化**，人工版优先；重新生成需确认 | 模型、提示词、输入哈希任一变化即新版本 |

### 2.2 三条硬规则

1. `files.stored_path` 在数据库层标记只读；切片、转码、解压、OCR 中间图一律写 `derived/`，并记 `derived_from`，绝不写回原路径。
2. 解析层只存“资料里写了什么”，AI 层只存“我们判断出什么”。AI 结论不得写进 `text_plain`，避免下次重解析时把模型猜测当原文。
3. 删除资料默认软删除，原件与解析结果保留可恢复；物理清理必须二次确认，且不得级联删掉已引用它的澄清单快照。

### 2.3 写入权限与生命周期

| 动作 | 原始层 | 解析层 | AI 层 |
|---|---|---|---|
| 导入 | 新增 | — | — |
| 重新解析 | 不变 | 新增 run，旧 run 保留 | 不自动重跑 |
| 重新生成摘要 | 不变 | 不变 | 新增版本，人工版需确认才覆盖 |
| 人工编辑 | 禁止 | 禁止 | 新增 `human_edited` 版本 |
| 删除资料 | 软删除，可恢复 | 随资料隐藏，不物理删 | 随资料隐藏，历史澄清单保留快照 |

---

## 3. 公共字段契约

### 3.1 输入信封（所有来源必填）

```text
file_id, content_hash(sha256), original_name, mime, size_bytes,
source_kind, source_subtype, imported_at, import_batch_id,
origin(channel), operator_note?, manual_customer_id?, manual_project_id?
```

- `source_kind` 只允许：`audio / video / chat / email / pdf / scan / word / excel / ppt / image / archive / text / html / json`。
- `manual_customer_id`、`manual_project_id` 必须原样保留，任何自动匹配都不得覆盖手选归属。

### 3.2 解析结果信封

```text
parse_id, file_id, parser_name, parser_version, params_hash,
status, started_at, finished_at, attempt,
text_plain, text_hash, char_count, lang,
blocks[], time_info{}, media_base, warnings[],
error_code?, error_detail?, supersedes_parse_id?
```

`blocks[]` 的结构：

```text
{ index, type, text, locator,
  page?, sheet?, row?, col?, slide?, para?,
  start_ms?, end_ms?, speaker?, speaker_role?, ts?, bbox?, attachment_ref? }
```

`type` 只允许：`paragraph / heading / table / cell / message / ocr_line / transcript_segment / slide / note / attachment_ref`。

### 3.3 时间信息（必须带来源与置信度）

```text
occurred_at, occurred_at_source:
  message | mail_header | exif | doc_props | filename | file_mtime | manual | none
occurred_at_confidence: high | medium | low
timezone（默认 +08:00）, duration_ms?, time_range?
```

禁止把文件修改时间直接当成沟通时间；使用 `file_mtime` 时必须标 `low`，界面显示“时间可能不准，点击修正”。

### 3.4 媒体定位符（Evidence 可跳转的唯一凭据）

| 来源 | 定位符 | 说明 |
|---|---|---|
| 音频/视频 | `file://<file_id>#t=1200-4800` | 毫秒；跨切片后仍指向原文件绝对时间 |
| 聊天 | `chat://<comm_id>#msg=<stable_id>` | 优先稳定消息 ID，退化为 `#idx=120` |
| 邮件 | `mail://<comm_id>#part=text` / `#attach=<name>` | 正文与附件分开 |
| PDF/扫描件 | `pdf://<file_id>#page=3&char=120-260` / `#bbox=x,y,w,h` | 文本层用字符区间，OCR 用框 |
| Word | `doc://<file_id>#para=12` / `#table=2&row=3&col=1` | 段落与表格单元格 |
| Excel | `xls://<file_id>#sheet=报价单&cell=B12` | 用表名而非索引，避免插表错位 |
| PPT | `ppt://<file_id>#slide=4` | 页序 |
| 图片 | `img://<file_id>#bbox=x,y,w,h` | OCR 行级框 |
| 压缩包 | `zip://<file_id>#entry=<path>!<child locator>` | 父子两级 |
| TXT/HTML/JSON | `txt://<file_id>#char=` / `#line=` / `#json=$.messages[12]` | JSON 用 JSONPath |

定位符必须**跨重解析稳定**：页、表名+单元格、幻灯片序号、消息稳定 ID、毫秒时间都是稳定锚点；不要用“第 3 段”这类会随解析器升级漂移的序号作为唯一凭据（可作为回退）。

### 3.5 客户/项目候选

```text
candidates[] {
  customer_id?, project_id?,
  basis: phone|email|wechat|nickname|participant|signature|filename|content_mention,
  matched_value, method: exact|suggested, score, requires_confirm
}
```

规则沿用主 PRD 5.4：

- 手机号、邮箱、微信号唯一精确匹配才自动关联；
- 多字段指向不同客户进“待确认”，并列候选；
- 姓名、公司、正文提及只作建议，不自动合并；
- 批量导入逐条独立匹配，无法匹配统一进待归档。

---

## 4. 状态机

### 4.1 解析状态

| 状态 | 含义 | 允许的下一步 |
|---|---|---|
| `pending` | 已登记，等解析 | parsing |
| `parsing` | 解析中 | parsed / partial / failed / cancelled |
| `parsed` | 全部成功 | 可进 AI |
| `partial` | 部分页/块/条目成功，已有可用文本 | 可预览、可分析，标注缺失范围 |
| `failed` | 无可提取文本 | 重试 / 改参数 / 手工备注 |
| `unsupported` | 格式或内容不支持 | 保留原件，可手工补录 |
| `skipped_duplicate` | 命中同哈希 | 可强制重新解析 |
| `cancelled` | 用户取消 | 续跑剩余部分 |

### 4.2 AI 状态

`not_started / queued / running / succeeded / failed / cancelled / skipped`（AI 开关关闭即 `skipped`）。

### 4.3 能力位

解析与 AI 状态不能直接给界面用，必须派生四个能力位：

```text
preview_ready, text_searchable, ai_analyzable, clarification_usable
```

界面与需求澄清只认这四个能力位，避免出现“状态是成功但正文为空”的误报。

---

## 5. 各来源最小契约

| 来源 | 输入约束 | 最小文本输出 | 时间信息 | 定位 | 客户/项目候选 | 典型失败与重试 |
|---|---|---|---|---|---|---|
| **音频** | mp3/m4a/wav/amr/aac/flac；≤2GB（建议）；超 30 分钟切 5 分钟、重叠 5 秒 | 本地无文本；ASR 后 `segments{text,start_ms,end_ms,speaker_role,stable_id}` + `full_text` | 通话时间（用户输入/文件名/元数据），`duration_ms` | `file://#t=` | 文件名号码、手选、通话时间邻近客户 | `E_ASR_TIMEOUT` `E_SPEAKER_UNSUPPORTED`；按切片重试，已完成片不重跑 |
| **视频** | mp4/mov/avi/mkv；只提音轨，不做画面 OCR | 同音频（音轨转写）；画面文字明确不产出 | 录制时间 EXIF（中）、`duration_ms` | `file://#t=` 指向原视频 | 文件名、手选 | `E_NO_AUDIO` `E_FFMPEG`；只重跑音轨提取或转写 |
| **微信聊天** | TXT/HTML/JSON/CSV 导出、粘贴、截图、原生库（V2）；账号+会话 username | `messages[]`：稳定 ID、时间、发送人、角色、类型、正文、附件引用 | 消息时间（高）；缺失则按顺序+导入时间（低） | `chat://#msg=` | 账号+username 精确；昵称/备注仅建议 | `E_CHAT_FORMAT` `E_ENCODING`；增量续导，坏行保留 `parse_warning` 不中断 |
| **邮件** | .eml；IMAP 单账号；From/To/Date/Subject/Message-ID | 正文（HTML 转文本）、附件清单、`thread_id`、引用层级 | Date 头（高）；缺失用接收时间（中） | `mail://#part=text` / `#attach=` | From/To 精确邮箱；签名电话仅建议 | `E_MAIL_NO_BODY` `E_ENCODING`；单封重解析，附件独立成条 |
| **PDF（有文本层）** | .pdf；建议 ≤2,000 页 | 按页 blocks（段落/表格），保留阅读顺序 | 文档内日期（中，不自动当沟通时间） | `pdf://#page=&char=` | 正文精确手机号/邮箱/公司名 | `E_CORRUPT` `E_PASSWORD` `E_PARSE_TIMEOUT`；按页重试 |
| **扫描件** | 无文本层 PDF / 拍照页；逐页 OCR | 每页 `ocr_line` + 行置信度 + 页面图引用 | 基本无；用 `file_mtime`（低） | `pdf://#page=&bbox=` | OCR 出的精确联系方式 | `E_NO_TEXT_LAYER` `E_OCR_LOW_QUALITY`；单页重 OCR，成功页保留 |
| **Word** | .docx/.doc；旧 doc 先转换 | 段落、表格、有序列表；可选页眉页脚 | core properties（中） | `doc://#para=` / `#table=` | 正文精确联系方式 | `E_CORRUPT` `E_CONVERT`；转换副本保留后重试 |
| **Excel** | .xlsx/.xls；建议 ≤50 sheet / 50 万单元格 | 每 sheet 的表头、单元格、合并区提示 | 工作簿 modified（中）；单元格日期不当沟通时间 | `xls://#sheet=&cell=` | 正文/单元格精确客户名、联系方式 | `E_SHEET_TOO_LARGE` `E_CORRUPT`；按 sheet 重试 |
| **PPT** | .pptx/.ppt | 每页文字 + 备注 + 页序 | core properties（中） | `ppt://#slide=` | 正文精确联系方式 | `E_CORRUPT` `E_CONVERT`；按页重试 |
| **图片** | png/jpg/jpeg/webp/bmp；截图/照片 | OCR 行；聊天截图额外判气泡方向并映射角色 | EXIF 拍摄时间（高）；否则 mtime（低） | `img://#bbox=` | 截图内精确微信号/手机号；聊天截图按会话 | `E_OCR_LOW_QUALITY` `E_NO_TEXT`；单图重 OCR 或转手工备注 |
| **压缩包** | zip/rar/7z；≤2GB、≤2,000 件、支持密码 | 自身不产文本；`children[]` 各按自身契约解析 | 条目时间（中）/包时间（低） | `zip://#entry=!` | 继承子项最佳候选，父包不单独归属 | `E_PATH_TRAVERSAL` `E_SIZE_LIMIT` `E_COUNT_LIMIT` `E_PASSWORD`；解压级重试，子项失败互不影响 |
| **TXT** | .txt；编码探测 UTF-8/GBK/UTF-16 | 纯文本 + 段落块；识别为聊天格式则走聊天契约 | 文件名/正文时间（中）；mtime（低） | `txt://#char=` | 正文精确联系方式 | `E_ENCODING`；换编码重试 |
| **HTML** | .html/.htm；聊天导出或网页 | 去脚本样式后的正文，表格保留；含消息结构走聊天契约 | meta/时间标签（中） | `html://#char=` 或 `chat://` | 同上 | `E_ENCODING` `E_PARSE`；降级纯文本后重试 |
| **JSON** | .json；聊天导出或业务数据 | 展平可读文本并保留结构；`messages[]` 识别为聊天 | 字段时间（高） | `json://#json=$.messages[12]` | 字段精确值 | `E_JSON_INVALID`；结构修复或降级纯文本，原文件不动 |

> 说明：建议值与已定值区分标注。已定值来自主 PRD（音频切片、聊天 5,000/100,000 条、压缩包 2GB/2,000 件）；标注“建议”的容量上限需在实现前确认。

---

## 6. 三类易混来源的判定规则

### 6.1 PDF 与扫描件

同一 `.pdf` 先看文本层：

- 整页可提取字符 → PDF 契约；
- 整页无字符 → 转扫描件契约走 OCR；
- 部分页有、部分页无 → `partial`，有文本页用文本层、无文本页补 OCR，逐页记录来源。

不允许整份按一种方式处理，也不允许把 OCR 结果写回 PDF 文本层。

### 6.2 TXT / HTML / JSON 的双语义

按结构探测，不按扩展名猜：

1. 命中“时间 + 发送人 + 内容”三要素，或文件含导出标记、消息数组达到阈值（建议 ≥20 条）→ 走聊天契约；
2. 否则走文档文本契约；
3. 判定失败时降级为文档并记 `downgraded=true`、`subtype_guess`，允许老板手动改判。

改判只影响解析层，不重传原件、不重建文件记录。

### 6.3 压缩包

压缩包是容器不是内容类型：

- 父记录只保留密码、条目清单、解压日志；
- 每个子条目生成独立 `files` 记录，各自走契约；
- 路径穿越、绝对路径、符号链接、解压炸弹（压缩比异常）必须拒绝并隔离，不能“尽力解压”；
- 密码错误与条目损坏分别报错，不阻塞同包其他条目。

---

## 7. 错误码与重试策略

### 7.1 错误码

| 错误码 | 含义 | 自动重试 | 手动入口 |
|---|---|---|---|
| `E_UNSUPPORTED_FORMAT` | 格式不支持 | 否 | 转手工备注 / 换格式 |
| `E_CORRUPT` | 文件损坏 | 否 | 重新导出原件 |
| `E_PASSWORD` | 加密未提供密码 | 否 | 补密码 |
| `E_ENCODING` | 编码无法识别 | 是（换编码族 1 次） | 指定编码 |
| `E_NO_TEXT_LAYER` | PDF 无文本层 | 否 | 转 OCR |
| `E_OCR_LOW_QUALITY` | OCR 置信度低 | 否 | 重 OCR / 手工校对 |
| `E_ASR_TIMEOUT` | 转写超时 | 是（切片级 ≤2 次） | 切片重试 |
| `E_SPEAKER_UNSUPPORTED` | 无说话人分离 | 否 | 人工校正角色 |
| `E_PARSE_TIMEOUT` | 解析超时 | 是（≤1 次） | 单页/单 sheet 重试 |
| `E_SIZE_LIMIT` / `E_COUNT_LIMIT` | 超容量 | 否 | 拆分后重导 |
| `E_PATH_TRAVERSAL` | 压缩包路径异常 | 否 | 隔离，仅人工处理 |
| `E_JSON_INVALID` / `E_JSON_TRUNCATED` | 模型或文件 JSON 非法 | 是（纠正 1 次） | 重跑该批次 |
| `E_MODEL_NOT_CONFIGURED` | 未配置模型 | 否 | 去设置 / 用 Mock |
| `E_AUTH` / `E_NETWORK` | 认证失败 / 网络异常 | 认证否，网络是（≤2 次） | 修配置 / 恢复后重试 |

### 7.2 重试原则

- **只重跑失败单元**：页、sheet、幻灯片、切片、批次、子条目，不整份重来；已完成单元打检查点。
- **重跑不重传**：全部读本地原件，不重复上传、不重复计费。
- **幂等键** = `content_hash + parser_version + params_hash`；相同则复用解析结果，不同则新建版本并 `supersedes` 旧版。
- **自动重试只给瞬时错误**（网络、超时、临时占用），指数退避 5s / 30s；格式、加密、超限、认证一律不自动重试，避免无效计费。
- **失败不降级为成功**：宁可 `partial` 并列出缺失页/片段，也不能把空文本标成 `parsed`。

---

## 8. AI 结构化结果契约

```text
ai_result_id, target_type(file|communication), target_id,
kind(summary|requirement_extract|chat_analysis|profile|clarification|embedding|transcript),
status, schema_version, model, prompt_version, input_hash,
output_json, confidence, evidence[], warnings[], human_edited, supersedes_id
```

- 每个结论必须带 `evidence[{locator, excerpt, source_time}]`；找不到依据的字段写“未提及”并标 `gap`，不得留空当结论。
- AI 输出不写回解析层；人工编辑生成 `human_edited=true` 的新版本，再次生成需确认且不覆盖人工版。
- 澄清引用资料时冻结 `text_snapshot` 与 `content_hash`，原件后续被改或删除，历史证据仍可读、可跳转（原资料在则跳转，不在则展示快照）。
- 低置信度（<0.6）只作建议，不自动进入需求清单，不自动标记分析完成。

---

## 9. 建议新增的数据表

| 表 | 作用 | 关键字段 |
|---|---|---|
| `files` | 原件 | `content_hash`, `stored_path`, `source_kind`, `manual_customer_id` |
| `derived_assets` | 切片、转码、OCR 图、解压子项 | `derived_from`, `kind`, `path` |
| `parse_runs` | 解析版本 | `file_id`, `parser_version`, `status`, `text_plain`, `supersedes_parse_id` |
| `parse_blocks` | 结构块 | `parse_id`, `type`, `text`, `locator` |
| `ai_results` | AI 结果版本 | `target_type`, `kind`, `output_json`, `human_edited` |
| `ai_evidence` | 证据 | `ai_result_id`, `locator`, `excerpt` |
| `match_candidates` | 归属候选 | `file_id`, `customer_id`, `basis`, `method` |

现有 PRD 的 `files` 表只有归档字段，缺解析版本与定位信息；不补上述表，“来源证据可跳转”和“重解析不覆盖”两条要求无处落地。

---

## 10. 附录

### 10.1 与主 PRD 的差异与需澄清项

| 项 | 主 PRD 现状 | 本契约处理 |
|---|---|---|
| ASR 归属 | 6.2 将转写列入“文件解析”，6.16 又说关闭 AI 不启动 ASR | 契约上归入 AI 层（`kind=transcript`），解析层只产媒体元信息；理由是它受 AI 开关与模型配置控制 |
| 文件表 | 5.3 `files` 无解析字段 | 新增 `parse_runs`、`parse_blocks`、`ai_results` 等 |
| 时间字段 | 仅 `occurred_at` | 增加 `occurred_at_source` 与置信度，禁止把 mtime 当沟通时间 |
| 删除语义 | 仅澄清单删除不删原件 | 资料删除统一软删除 + 可恢复，澄清单快照独立保留 |
| 容量上限 | 仅音频、聊天、压缩包有明确值 | 其余标注“建议”，实现前确认 |

### 10.2 契约自检清单

- [ ] 每类资料都能回答：有没有文本、文本从哪来、时间从哪来、证据怎么跳。
- [ ] 任何解析结果都不含模型判断，任何 AI 结果都不写回 `text_plain`。
- [ ] 重新解析产生新版本，旧版本仍可打开。
- [ ] 原件哈希变化必须新建资料记录，不覆盖。
- [ ] 失败单元可单独重试，部分成功不被标成成功。
- [ ] 所有 evidence 的定位符在原解析器版本变化后仍可解析或可降级展示。
- [ ] 跨客户选材时，候选与归属不串线，未归属结果有独立分区。
- [ ] 删除资料后，历史澄清单快照仍可读。

---

**文档结束**

> AI生成
