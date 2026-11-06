# 证据索引 v0.1.0

> 发布日期：2026-11-06
> 仓库：`github.com/Dingh0208/clientgraph-ai`
> 版本标识：tag `v0.1.0`（分支 `main`）
> 原则：只登记本仓库真实存在的文件；不登记截图、密钥、客户资料或未执行的结果。

## 1. 交付物与哈希

| 路径 | 类型 | 字节 | SHA-256 |
|---|---|---|---|
| `prototype/index.html` | 原型（单文件） | 29,746 | `04151a9307331e1a1d1023c9fc6f440bdf04530d9e260985fde81e6b7333c442` |
| `README.md` | 说明 | 3,648 | `5cc57a3e41ba776981489292e9d0b9aac27de93edc72e6411c1557d33de506f4` |
| `docs/PRODUCT-BASELINE.md` | 产品基线 | 3,449 | `d9ba9323ee73ad0e3e86a4601c6a4c1e7f1f765ea60a4a45346e1b6d798346c6` |
| `docs/DATA-DICTIONARY.md` | 数据字典 | 6,731 | `299199757bf165a0503408d9154467179f6818819fe6942ba227ce2afaf58ec9` |
| `docs/ITERATION-LOG.md` | 迭代日志 | 2,474 | `ef75022aa7e17515e2acd19060066d4bf21c273caaa7fb7935211f14ffce3615` |
| `docs/TEST-RECORD.md` | 测试记录 | 4,303 | `8a8b458e0a24c1e5cdd6b0f6b1993e29e6a7ead6581a2c385556642009227237` |
| `docs/CONFIG.md` | 配置说明 | 1,536 | `f6f1c0f054a95fade1b2d9d252d9a41ae05926d767078df663141acbc631686e` |
| `docs/MATERIALS.md` | 资料清单 | 3,323 | `2f8479194f4afe79190c224fe8e17872768aaea89968f51324bb450a660c2a05` |
| `docs/LIMITATIONS.md` | 限制说明 | 2,729 | `d8d3183d7f6ed3a31df11d855837c50d70e16b7ff7f9cbcb46812f5b0d40151b` |
| `tests/smoke-cases.md` | 冒烟用例 | 2,187 | `33b48850a95344c6377f99a3fe55d7a8911da46b5cc1cf63d6b762f5233ee0a8` |
| `LICENSE` | 许可 | 659 | `2458aae63c3211bbaf375b1817978d88fe3de5e4daeb6ab561fdbe93202308a9` |
| `.gitignore` | 忽略规则 | 93 | `a5a07c1388857622a0cf9aa51590c30cf7f6b20138c273e20f55c118115c59a2` |
| `.gitattributes` | 行尾规则 | 19 | `d60f352d0db1404c70afb4bb8b2ca3fd1c610572aa40720e8a0b7baa7885418c` |

校验方式：

```powershell
Get-ChildItem -Recurse -File | ForEach-Object { (Get-FileHash $_.FullName -Algorithm SHA256).Hash + "  " + $_.FullName }
```

## 2. 测试证据

| 项 | 证据 | 结果 |
|---|---|---|
| 冒烟用例 | `docs/TEST-RECORD.md` 第 2 节 | 7 / 7 通过 |
| 控制台 | 同上第 3 节 | 0 error / 0 warning |
| 修复记录 | 同上第 4 节 | D1 / D2 / D3 已修复并复验 |
| 可复现步骤 | `tests/smoke-cases.md` | 7 个用例，含选择器与期望值 |

说明：测试证据为页面文本与 DOM 状态的实际读取结果，**未使用截图**，避免以视觉材料代替断言。

## 3. 数据与合规

| 项 | 状态 |
|---|---|
| 真实客户资料 | 未包含 |
| 个人信息 | 未包含 |
| 平台密钥 / 令牌 | 未包含 |
| 虚构截图 / 演示图片 | 未包含 |
| 演示语料 | 12 份 / 51 个片段，全部内嵌且标注“（虚构）” |
| 网络请求 | 无 |

## 4. 版本对应

- 本索引对应 tag `v0.1.0`；提交哈希以该 tag 指向的提交为准。
- 后续修订请新增版本段落，不覆盖本文件。

## 5. 未登记内容

以下内容不属于本次交付，故不登记：

- 本地设计草稿、需求评审稿与演示数据集二进制；
- 运行环境的临时目录与依赖缓存；
- 任何截图、录屏或浏览器配置文件。

> AI生成
