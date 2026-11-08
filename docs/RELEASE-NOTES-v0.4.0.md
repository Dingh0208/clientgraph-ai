# ClientGraph AI v0.4.0 发布说明

> 日期：2026-11-08
> 主题：需求澄清助手完整闭环
> 证据：`evidence/clarification-e2e-2026-11-08.json`、`evidence/clarification-failures-2026-11-08.json`

## 1. 版本定位

v0.4.0 在 v0.3.0 的客户情报与需求分析之上，补齐“需求澄清”闭环：

```
选材确认 → 分批分析 → 证据问题 → 冲突 → 回答 → 手动追问
        → 回写预览 → 人工确认 → 版本历史 → 增量分析 → 失败重试 → 对外导出
```

## 2. 新增能力

| 能力 | 模块 | 要点 |
|---|---|---|
| 问题计划与优先级 | `clarification/questions.py` | 10 维固定顺序；三档优先级；每题证据/时间/理由/事实-推断-未知/低置信度；冲突双方证据 |
| 问题状态 | `clarification/question_lifecycle.py` | 待问/已问/已回答/不适用；多次回答快照；追问显式触发 |
| 工作单 | `clarification/workspace.py` | 六态生命周期；客户/项目/日期/未回答/已完成筛选；归档恢复；复制草稿；增量；删除保留原件 |
| 回写 | `writeback/` | 目标选择；字段级预览；新需求待确认；P0/P1/P2 独立；确认 + 令牌 + 指纹；版本与操作快照 |
| 导出 | `clarification/exporters.py` | 文本/Word/PDF；按客户/项目分组；对外版隐藏内部理由与证据 |

## 3. 回归结果

| 套件 | 检查数 | 结果 |
|---|---|---|
| 端到端连续回归 | 48 | 全部通过（23 步） |
| 问题计划与优先级 | 52 | 全部通过 |
| 问题状态 | 57 | 全部通过 |
| 回答回写 | 64 | 全部通过 |
| 工作单生命周期 | 56 | 全部通过 |
| 澄清分批 | 27 | 全部通过 |

失败案例 7 个，全部保留：

- F1 `E_UNREADABLE`：不可读资料阻止发送，工作单保留；
- F2 `E_MODEL_TIMEOUT`：批次超时，重试后完成；
- F3 `E_NOT_ANSWERED`：未回答不能生成追问；
- F4 `E_CONFIRM_REQUIRED`：未确认不能保存；
- F5 `E_PREVIEW_TAMPERED`：预览被改拒绝保存；
- F6 `E_TARGET_CHANGED`：目标变化拒绝保存；
- F7 `E_ALREADY_APPLIED`：同一预览不能重复保存。

## 4. 文档

- `docs/需求澄清助手-API与流程-v1.0.md`
- `docs/验收矩阵-v0.4.0.md`
- `docs/测试记录-v0.4.0.md`
- `docs/失败案例-v0.4.0.md`
- `docs/已知限制-v0.4.0.md`
- `docs/问题计划-v1.0.md`、`docs/问题优先级-v1.0.md`、`docs/问题状态-v1.0.md`
- `docs/回答回写-v1.0.md`、`docs/澄清单生命周期-v1.0.md`
- `docs/需求澄清选材-v1.0.md`、`docs/澄清分批处理-v1.0.md`

## 5. 已知问题

- 澄清助手关键操作尚未接到原型按钮，当前为 Python API；
- 工作单数据在内存中，未接持久化；
- PDF 依赖本机 Edge/Chrome；
- 字段识别与优先级均为规则，不覆盖复杂句式与行业差异；
- 对外导出只做内容裁剪，不替代人工脱敏审查。

完整清单见 `docs/已知限制-v0.4.0.md`。

## 6. 升级与兼容

- v0.3.0 的客户 360、需求抽取、版本、冲突、待办、关系图、搜索、解析与诊断保持不变；
- 新增 `clarification/`、`writeback/` 目录与对应验证脚本；
- 数据字典已同步：澄清单状态改为 draft/analyzing/partial/incomplete/completed/archived；问题 `conclusion_type` 为 fact/inference/unknown，冲突独立记录；
- 发布仓库演示数据仍为虚构，可直接运行验证脚本。

## 7. 复现

```bash
python scripts/verify_clarification_e2e.py
python scripts/verify_question_plan.py
python scripts/verify_question_status.py
python scripts/verify_writeback.py
python scripts/verify_clarification_records.py
python scripts/verify_clarification_batching.py
```

> AI生成
