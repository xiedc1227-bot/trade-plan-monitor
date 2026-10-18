# 实际原文真实 AI 计划准备验证 — 2026-10-16

英文规范版本：[2026-10-16-real-ai-preparation.md](2026-10-16-real-ai-preparation.md)。本文件为中文审阅副本。

## LIVE-V01. 授权与输入

用户明确授权对四份实际 TXT 原文调用真实 AI，并确认了下列生效交易日。完整文本读取自 `data/research/shengxin-plan-extraction-20261010/`，未改写原文。`plans.json` 和 `entry-fields.json` 未作为计划、上下文或补充材料。成文时间与历史可用时间保持 null。

| 原文 | 已确认生效交易日 | 首份提取请求字符数 |
|---|---|---:|
| `01-20260924-104506.txt` | 2026-09-24 | 44,927 |
| `02-20260928-092555.txt` | 2026-09-28 | 44,260 |
| `03-20260930-095728.txt` | 2026-09-30 | 45,822 |
| `04-20261009-091956.txt` | 2026-10-09 | 47,746 |

`127.0.0.1:8765` 的 Web 服务未运行。验证直接使用当前正式代码中的 `ConfiguredAIWebLifecycle`、`PreparationService`、提取函数和 HTTP 适配器，独立 SQLite 存储位于 `data/verification/2026-10-16-real-ai/`。未修改业务中的准备记录或应用配置。模型使用配置中的 `deepseek-flash`；五次已完成 HTTP 调用全部访问真实提供方，未使用模拟响应。未记录 API 密钥或授权请求头。

## LIVE-V02. 使用当前配置验证有序计划集

当前设置为 `max_input_chars=50000`、`max_output_tokens=4096`、`timeout_seconds=30`、`max_retries=2`。四个已确认日期全部通过计划集前置检查。第一份请求于上海时间 2026-10-16 16:15:13 发出，收到 HTTP 200，`finish_reason=length`，消耗 15,282 输入 tokens 和 4,096 输出 tokens。完整请求通过了未调整的输入长度限制，但提供方响应被输出预算截断。

准备记录 `shengxin-real-ai-2f694787-e1f0-4555-87d4-c3d29c86c806` 最终为 `FAILED`：第 1 项记录一次失败尝试，错误码为 `AI_OUTPUT_TRUNCATED`；第 2–4 项保持 `WAITING`，尝试次数均为零。任务占用已释放。读取冻结计划被拒绝，错误码为 `REVIEW_REQUIRED`。未批准任何审核，也未提交回测。

## LIVE-V03. 独立的完整输出诊断

为检查四份实际原文在消除截断后的情况，随后每份各调用一次 `extract_loop_plan`，作为**独立首份原文诊断**，仅在内存中临时使用 `max_output_tokens=16384`、`timeout_seconds=120`、`max_retries=0`。输入限制仍为 50,000，原文、模型及提供方保持不变。这些调用不是后继计划提取，也不证明连续计划链已经有效。

四份均在上海时间 16:16–16:18 返回 HTTP 200 和 `finish_reason=stop`，但均未产生通过校验的候选：

| 原文 | 输出 tokens | 结果 | 首个阻塞证据 |
|---|---:|---|---|
| 第 1 份 | 7,275 | `AI_OUTPUT_INVALID` | 多出顶层字段 `type: "json_object"`，Schema 禁止额外字段。 |
| 第 2 份 | 6,538 | `AI_FIELD_EVIDENCE_INVALID` | `BACKGROUND requires a registered exact scope exclusion`；59 个背景片段缺少已登记的排除范围，首个为标题 `## 1. 当前结论与行情摘要`。 |
| 第 3 份 | 7,976 | `AI_OUTPUT_INVALID` | `bindings[8].unit`、`bindings[9].unit`、`bindings[10].unit` 返回 `FEN`，不在允许的单位枚举中。 |
| 第 4 份 | 8,716 | `AI_OUTPUT_INVALID` | 多出顶层字段 `type: "json_object"`，Schema 禁止额外字段。 |

离线检查第 1 份时，仅移除多出的 `type` 字段后，同样触发第 2 份的背景排除校验错误。该诊断性修改从未作为有效候选保存，说明仅忽略额外字段也无法打通提取流程。

五次真实调用共报告 77,788 输入 tokens、34,601 输出 tokens，合计 112,389 tokens。未继续进行付费重试。完整响应、Schema 错误位置、请求元数据和计划集记录保存在本地 `data/verification/2026-10-16-real-ai/`，其中 `expanded-output-diagnostics/` 保存四份独立诊断结果。文件包含原文及模型输出，不包含凭据。结果模型在普通序列化时排除 `diagnostic` 字段；本报告的错误细节来自已保存的提供方响应和离线 Schema／映射校验，不是根据序列化中的 null 推断没有诊断信息。

## LIVE-V04. 结论与剩余工作

**这四份原文的流程目前仍不能继续回测。** 日期确认与输入预算修复已在真实路径生效。当前输出预算导致第一份响应截断；提高预算后，又暴露出 Schema 和原文映射校验问题。这不代表已确认日期仍然缺失，也不代表必须改写原文。

要打通流程，需要让输出预算与时限支持完整响应，使提取指令／输出处理满足严格字段及单位约束，并让背景文本处理与原文保真校验一致，同时不能丢弃交易条件。之后仍需验证真实后继计划上下文，处理确实未知的策略／账户信息，并完成显式审核与冻结。本次验证未补造缺失事实、放宽校验、批准计划，也未证明历史回放成功。
