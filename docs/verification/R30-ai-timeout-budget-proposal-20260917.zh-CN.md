# R30 隔离 AI 超时预算验收方案

英文原版为 `R30-ai-timeout-budget-proposal-20260917.md`，本文是等价中文审阅副本。提案 `R30-20260917-V6-LITERAL-TIMEOUT-BUDGET-1`；运行 `r30-20260917-a`。状态 **AUTHORIZED / PRIOR_ZERO_CALL_STOP_RECORDED / CLAIM_UNCONSUMED / EXACT_EXECUTION_PENDING**。

批准后更正：执行前立即复核的官方价格页面显示更高的 `DeepSeek-V4-Pro-0813` 峰值/非峰值价格，对应 USD `0.05884032` 的峰值估算与 USD `0.02942016` 的非峰值估算，而冻结估算为 USD `0.01582704`。首次尝试在创建 claim 前停止，未发送请求；该记账仍有效，但 USD `0.01582704` 是披露的估算，不是账单保证或用户设定的金额上限。用户批准了一次请求并接受其可能费用；路由、原文、提示词、请求体和物理调用上限均未改变。详见 `R30-ai-timeout-budget-execution-20260917.zh-CN.md`。

## 目标与证据边界

R30 只回答一个狭窄问题：R29 本地 30 秒整体截止是否阻止了其余内容不变的非流式 v6 请求到达终态响应？本轮以一个更长且有硬上限的客户端等待预算，经生产供应商、提取、严格 schema、映射校验与字面 oracle 链路验证。

这是受控假设，不是远端供应商修复。R29 仅证明在 `30009` ms 记录 `OVERALL_DEADLINE`，未证明 DeepSeek 是否收到、完成或计费。R27 曾在 `29.542` 秒返回已验证响应，与原 30 秒边界只差 `0.458` 秒，但一次历史成功不能建立吞吐上限；输出 Token 容量也不能决定生成耗时。

即使 R30 成功，结果仍仅供复核：`humanReviewStatus=REQUIRED_NOT_PERFORMED` 且 `activationAllowed=false`。本轮不覆盖两个语义样例、行情、monitor 启动、实时求值、IN_APP 投递、人工确认、计划保存/激活、持仓、委托、成交或交易。

## 超时嵌套及依据

| ID | R29 | R30 | 依据 |
|---|---:|---:|---|
| R30-T01 连接/写入/连接池无活动 | 30 秒 | 30 秒 | R29 未识别这些阶段为胜出边界，没有放大依据。 |
| R30-T02 读取无活动 | 30 秒 | 60 秒 | 允许响应或响应块晚于原 30 秒边界到达；HTTPX 将其定义为逐块无活动时间，而非整次请求总时长。 |
| R30-T03 provider 整体截止 | 30 秒 | 65 秒 | 在读取额度之上保留 5 秒硬边界，并限制完整请求。 |
| R30-T04 终态观察 | 31 秒 | 66 秒 | 允许一次观察 provider 终态，不重提。 |
| R30-T05 协作清理 | 最多 15 秒 | 最多 15 秒 | 清理上限不变。 |
| R30-T06 候选总硬边界 | 45 秒 | 81 秒 | `66 + 15`，无后台等待且无重试。 |

HTTPX 0.28.1 文档区分连接、读取、写入和连接池超时。Python 3.14 文档说明 `asyncio.timeout()` 会取消逾期工作，并在上下文外暴露 `TimeoutError`。核对时间 `2026-09-17T09:43:04+08:00`；来源：https://www.python-httpx.org/advanced/timeouts/ 和 https://docs.python.org/3/library/asyncio-task.html#timeouts。

生产默认与真实配置保持不变。`AIProviderConfig` 新增可选的传输/读取预算，两者默认均为 `None`，继续让所有阶段沿用 `timeout_seconds`。只有 R30 有界工厂显式传入 `transport=30`、`read=60`、`overall=65`。

## 固定候选契约

| ID | 固定值 |
|---|---|
| R30-C01 | 在 `data/r30-ai-timeout-budget-acceptance/` 下使用全新原子 claim；准备和干跑不会创建它。 |
| R30-C02 | 仅在精确批准并要求执行后，于 Asia/Shanghai `2026-09-17` 启动。AI-only 提取不依赖交易时段；错过日期即停止，不创建定时或后台等待。 |
| R30-C03 | 仅 `LITERAL`；AI 物理 POST 上限 `1`；重试/重提 `0`；全部行情上限 `0`，包括 `trade_cal=0`。 |
| R30-C04 | `deepseek-v4-pro`；`plan-extract-v6`；`max_tokens=8192`；`temperature=0`；`thinking={"type":"disabled"}`；`response_format={"type":"json_object"}`；`stream=false`；一条 user 消息。 |
| R30-C05 | 目的地 `POST https://api.deepseek.com/chat/completions`；不探测余额、模型列表或账户。 |
| R30-C06 | 原文 SHA-256 `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`；提示词 SHA-256 `7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba`；提示词为 `19,359` UTF-8 字节。 |
| R30-C07 | 规范请求体 SHA-256 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`；原文、提示词及全部发送字段与 R29 逐字节相同。 |

精确审阅包位于 `data/r30-ai-timeout-budget-review/`，包 SHA-256 为 `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`。它与 R29 包 SHA-256 `328620ea1d51a7b5b15128ca5f1741825478e46ec1fd6eef0f4abd271c8579f9` 对比，并记录发送字段差异为零。审阅包的变化仅包括本地预算、目的和当前官方价格元数据；不含凭据。

## 官方路由与保守费用快照

在 `2026-09-17T09:43:04+08:00`，官方 Chat Completions 页面记录了 `POST /chat/completions`、模型别名 `deepseek-v4-pro`、非思考模式、JSON object 输出与 `max_tokens`。官方价格页将其标为 `DeepSeek-V4-Pro`，缓存未命中输入价为 USD `0.435`/M、缓存命中输入价为 USD `0.003625`/M、输出价为 USD `0.87`/M。这与 R29 较早的 `DeepSeek-V4-Pro-0813` 以及 USD `1.32`/M、USD `3.96`/M 快照不同。来源：https://api-docs.deepseek.com/api/create-chat-completion/ 和 https://api-docs.deepseek.com/quick_start/pricing/。

按向上取整的 `20,000` 缓存未命中输入 Token 与不变的完整 `8,192` 输出 Token 上限计算，一次请求保守估算为 USD `0.01582704`（`20000*0.435/1e6 + 8192*0.87/1e6`）。真实分词、缓存划分、输出长度、计费、税费及账户调整未知。延长本地等待不会增大 `max_tokens`。任何获批派发前立即重查两份官方页面；不充值、不探测账户。

随后直接打开官方页面复核时，路由与别名保持不变，但页面显示峰值输入/输出价格为 USD `1.32`/M 与 USD `3.96`/M，非峰值价格为 USD `0.66`/M 与 USD `1.98`/M。按同一固定算术边界，对应峰值 USD `0.05884032`、非峰值 USD `0.02942016`。该价格冲突作为证据保留；它不改变冻结审阅包字节，也不改变用户对一次请求及其可能费用的批准。

## 执行与停止规则

隔离工作树未复制真实配置。获批执行必须通过显式只读 `--config-path` 使用原配置，并匹配 SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`。

默认调用仅离线。真实执行还要求准确授权令牌 `R30_20260917_LITERAL_ONE_AI_ZERO_MARKET_TIMEOUT_BUDGET_ACCEPTANCE`、运行 ID `r30-20260917-a`、匹配的审阅包/配置哈希、干净已提交的 R30 分支、未使用 claim、有效日期、最新官方路由/价格复核，以及对一次 POST 与所述潜在费用的明确批准。

首个成功或失败终态即停止。连接/读取/写入/连接池/整体超时、诊断缺失、回执/查询未知、非 stop 结束、模型不匹配、JSON/schema/映射/oracle 失败、隔离失败或清理失败均不允许第二次 POST。日志不含原文/提示词全文、供应商响应内容、异常正文、凭据、Headers 或直连 IP。成功仅保留隔离复核产物；全部业务表保持为空。
