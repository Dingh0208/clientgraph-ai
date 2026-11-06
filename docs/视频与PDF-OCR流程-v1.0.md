# 视频与 PDF / 图片处理流程 v1.0

> 日期：2026-11-06
> 状态：实现并验证（8 个场景全部通过）
> 代码：`media_pipeline/`、`scripts/verify_media_pipeline.py`
> 证据：`evidence/media-pipeline-2026-11-06.json`

## 1. 目标与边界

- 视频：**只提取音轨**，复用长音频流水线做 ASR，不做画面 OCR；
- PDF：**优先读取文本层**；无文本层的扫描页渲染成图片后 OCR；
- 图片：直接 OCR；
- 所有结果保留页码、图片区域或时间定位、OCR 置信度、原图引用；
- 失败必须给出可解释的错误码、页码/区域与处理建议，不能静默成功。

明确不做：版面还原、表格结构重建、手写体识别、说话人分离、真实 ASR 联调。

## 2. 视频：音轨提取 → ASR

```text
视频（mp4/mov/avi/mkv/webm）
 → ffprobe 检查是否存在音频流
 → ffmpeg -vn -map 0:a:0 -ac 1 -ar 16000 -c:a pcm_s16le 提取为 audio.wav
 → 复用 audio_pipeline（切片、并发、超时、重试、合并）
 → 段落时间映射回视频时间轴
```

规则：

- 没有音频流直接失败 `E_VIDEO_NO_AUDIO`，不尝试读画面；
- 不生成关键帧、不做画面 OCR；结果中固定 `stats.frame_ocr=false`；
- 段落定位为 `video://<文件名>#t=start-end`（毫秒），并裁剪到视频总时长；
- 原视频只读，提取的 `audio.wav` 是派生文件。

## 3. PDF：文本层优先

处理顺序（逐页判断）：

1. `page.get_text("text")` 字符数 ≥ 20 → 使用文本层；
2. 否则渲染页面（200 DPI）→ 判断是否空白 → OCR；
3. 空白页跳过 OCR，记 `W_EMPTY_PAGE`；
4. OCR 失败只影响该页，其他页继续。

文本层输出：

- 行级文本与 `bbox`（PDF 点坐标）；
- 页码从 1 开始；
- 不产生 OCR 置信度（`confidence=null`），不伪造；
- 定位：`pdf://<文件>#page=1&bbox=x0,y0,x1,y1`。

扫描页输出：

- 渲染图保存为 `images/page_001.png`，记录文件名与 SHA-256；
- 行级 `bbox_px`（像素）与换算后的 `bbox`（点）；
- 逐行 `confidence`（0–1）与页级平均置信度；
- 定位：`pdf://<文件>#page=1&bbox=...&ocr=1`；
- 原图引用：`source.image_ref` + `source.image_sha256`。

文本层中的 `\xa0` 会归一化为普通空格，避免英文句子因不换行空格搜不到。

## 4. 图片：直接 OCR

- 支持 png/jpg/jpeg/webp/bmp/tif/tiff；
- 保留原始文件名、SHA-256、像素尺寸；
- 行级 `bbox`（像素）与 `confidence`；
- 定位：`img://<文件>#bbox=x0,y0,x1,y1`；
- 空白图跳过 OCR，记 `W_EMPTY_PAGE`。

## 5. 统一输出

```json
{
  "schema": "clientgraph.media.run.v1",
  "source": {"name": "scan_skew.pdf", "kind": "pdf", "sha256": "…", "unchanged": true},
  "status": "completed | partial | failed",
  "text": "可搜索文本",
  "blocks": [
    {
      "id": "p001o000",
      "type": "ocr",
      "text": "设备巡检记录",
      "page": 1,
      "bbox": [20.1, 25.4, 210.6, 48.2],
      "bbox_px": [56, 71, 585, 134],
      "confidence": 0.9978,
      "locator": "pdf://scan_skew.pdf#page=1&bbox=20.1,25.4,210.6,48.2&ocr=1",
      "source": {
        "file": "scan_skew.pdf",
        "kind": "pdf",
        "page": 1,
        "method": "ocr",
        "image_ref": "images/page_001.png",
        "image_sha256": "…"
      }
    }
  ],
  "pages": [
    {"page": 1, "method": "ocr", "block_count": 3, "ocr_confidence": 0.9978,
     "image_ref": "images/page_001.png", "blank": false}
  ],
  "errors": [],
  "warnings": [],
  "stats": {"page_count": 1, "text_layer_pages": 0, "ocr_pages": 1, "block_count": 3}
}
```

`search(result, query)` 对 `blocks[].text` 做大小写不敏感匹配，返回带定位的区块，用于“可搜索文本”。

## 6. 错误与警告

| 代码 | 场景 | 是否继续 | 说明 |
|---|---|---|---|
| `E_VIDEO_OPEN_FAILED` | 视频无法读取 | 否 | 原件保留 |
| `E_VIDEO_NO_AUDIO` | 无音频流 | 否 | 明确提示只处理音轨 |
| `E_VIDEO_EXTRACT_FAILED` | 音轨提取失败 | 否 | 建议重新编码 |
| `E_PDF_OPEN_FAILED` | PDF 损坏 | 否 | — |
| `E_PDF_ENCRYPTED` | PDF 加密 | 否 | 需密码 |
| `E_PAGE_RENDER_FAILED` | 页面渲染失败 | 是（其他页继续） | 记录页码 |
| `E_OCR_FAILED` | OCR 引擎异常 | 是（其他页继续） | 带页码、原因、建议 |
| `E_IMAGE_OPEN_FAILED` | 图片损坏 | 否 | — |
| `W_PDF_NO_TEXT_LAYER` | 该页转 OCR | 是 | 说明为何走 OCR |
| `W_EMPTY_PAGE` | 空白页 | 是 | 不调用 OCR |
| `W_OCR_NO_TEXT` | OCR 无结果 | 是 | 保留原图 |
| `W_OCR_LOW_CONFIDENCE` | 平均置信度 < 0.6 | 是 | 建议核对 |
| `W_PARTIAL` | 部分页失败 | 是 | 结果部分可用 |

`E_OCR_FAILED` 示例：

```json
{
  "code": "E_OCR_FAILED",
  "message": "第 2 页 OCR 失败：模拟 OCR 引擎异常",
  "page": 2,
  "hint": "可提高扫描分辨率、纠正倾斜后重试；原图已保留。",
  "recoverable": true
}
```

## 7. 验证结果

环境：Windows x64、Python 3.12.13、PyMuPDF、RapidOCR（ONNX，本地）、Mock ASR。所有场景原始文件 SHA-256 前后一致。

| 场景 | 结果 | 关键数据 |
|---|---|---|
| 视频 6 秒（含 AAC 音轨） | completed | 提取 16kHz 单声道；3 段：0–1924、1924–4330、4330–6000 ms；`frame_ocr=false` |
| PDF 文本层（中英混排，2 页） | completed | 4 个文本块；文本层 2 页、OCR 0 页；约 0.1–0.3 秒；未调用 OCR |
| 扫描件倾斜 2.5° | completed | 1 页 3 块；平均置信度 0.9978；文本含“设备巡检记录 / Inspection Record 2026” |
| 低清模糊图片（320×200，模糊 3.0） | completed | 0 块；`W_OCR_NO_TEXT`；OCR 已尝试但无结果 |
| 空白页 | completed | 0 块；`W_EMPTY_PAGE`；未调用 OCR |
| 混合中英文图片 | completed | 2 块；平均置信度 0.9965；中英文均可搜 |
| OCR 失败（第 2 页注入） | partial | 第 1 页 2 块保留；`E_OCR_FAILED` 带页码与建议；`W_PARTIAL` |
| 视频无音轨 | failed | `E_VIDEO_NO_AUDIO`；不产生任何 ASR 段 |

补充：

- 文本层页面没有 OCR 置信度，`confidence=null`，不编造；
- 倾斜扫描页仍能识别，但置信度是**该合成样本**的单次观测，不代表所有倾斜件；
- 低清样本的结论是“明确无结果”，不是“识别成功”。

## 8. 限制

- ASR 使用 Mock，Qwen 未联调；视频转写只验证了链路与时间映射，不代表真实识别质量。
- OCR 为本地 RapidOCR，单页约 3–19 秒（CPU，单次观测），未做批量性能优化。
- 倾斜只测了 2.5°；更大角度、透视变形、装订阴影未覆盖。
- 低清样本为严重模糊图，输出“无文字”警告，未验证低置信度文本的修复能力。
- OCR 失败为引擎层注入，未覆盖磁盘损坏、内存不足等系统故障。
- 版面只到行级 bbox，不还原表格、段落层级或阅读顺序的复杂情况。
- PDF 扫描页的“原图”是 200 DPI 渲染图，不是 PDF 内嵌的原始图像对象。
- 文本层阈值 20 字符：少于 20 字符的页面会转 OCR，可能丢失原有文本层。

## 9. 复现

```bash
set PYTHONPATH=.;.temp\pylibs
python scripts/verify_media_pipeline.py

python -m media_pipeline.cli --input sample.pdf --out runs/pdf
python -m media_pipeline.cli --input sample.mp4 --out runs/video --asr-provider mock
```

> AI生成
