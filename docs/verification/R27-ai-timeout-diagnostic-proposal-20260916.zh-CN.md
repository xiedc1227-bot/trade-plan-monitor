# R27 单 POST AI 超时诊断方案

英文原版为 `R27-ai-timeout-diagnostic-proposal-20260916.md`，本文是等价中文审阅副本。状态 **OFFLINE_CANDIDATE / LIVE_NOT_RUN / ONE_AI_POST_MAXIMUM / ZERO_MARKET**。

## 目标与边界

R27 只回答一个狭窄问题：不变且已获批准的 `LITERAL` `plan-extract-v5` / 8192 请求，能否通过生产 DeepSeek 供应商与提取链路到达终态；若不能，R26 v2 记录的超时分类是什么？这是提取诊断，不是完整 monitor、行情、语义、人工复核或交易验收。

R27 只允许一次 AI POST 物理启动，重试和重提均为零。包括 `trade_cal=0` 在内的行情调用全部为零；不启动生产 monitor/参考数据生命周期、Web 监听器、券商动作、Webhook 或交易动作。绝不保存或激活计划，也绝不修改持仓。

## 候选身份与固定限额

| ID | 固定值 |
|---|---|
| R27-C01 | 提案 `R27-20260916-AI-TIMEOUT-DIAGNOSTIC-1`；运行 `r27-20260916-a`；在 `data/r27-ai-timeout-diagnostic/` 下使用全新一次性 claim。 |
| R27-C02 | 启动窗口为 Asia/Shanghai `2026-09-16 10:00:00` 至 `12:00:00`。本提取专用诊断不依赖交易时段或行情证书。 |
| R27-C03 | 仅 `LITERAL`；`AI_TOTAL=1`；每输入上限 `LITERAL=1`；全部行情端点上限及 `MARKET_TOTAL` 均为 `0`。 |
| R27-C04 | 现有 provider/HTTPX 超时为 `30` 秒；终态观察额度为 `31` 秒；有界工作硬截止为 `45` 秒，其中协作清理不超过 `15` 秒。 |
| R27-C05 | `deepseek-v4-pro`、`plan-extract-v5`、`max_tokens=8192`、`temperature=0`、`thinking={"type":"disabled"}`、`response_format={"type":"json_object"}`、`stream=false`、一条 user 消息且传输重试为 `0`。 |
| R27-C06 | 目的地为 `POST https://api.deepseek.com/chat/completions`；不允许余额、模型列表或额外探测调用。 |

## 精确外发与授权

原文和唯一 user 提示词与已获批准 R25 包中的 `LITERAL` 子集逐字节相同。其冻结 SHA-256 保持为：

- 原文：`0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`；
- 提示词：`660945f63c48c66c6b115e8bb29a0ccc76fde1df60aca17ba7c74bba2a06ef89`。

先前 R25 精确审阅包哈希为 `6b0d300b0404a24b690281f9336a013f430b72ec9371be069b82c66aab92833d` 与 `4d689c24721901e3de8ee38d1accdfdc6f3f54433c36c446a5dff11ce04a32d0`。用户曾明确批准将那三份精确原文与提示词最多三次发送给 DeepSeek；R25 实际仅物理启动一次 `LITERAL`，随后用户又指示继续本次“一次调用、零行情”的下一步。R27 使用全新 claim 和 operation，但其内容、目的地与请求字段仍在该精确批准范围内。任一字节、字段或目的地变化都会使门禁失效并停止执行。

全新本地审阅副本为 `data/r27-ai-timeout-review/egress-review.md` 与 `egress-review.zh-CN.md`，SHA-256 分别为 `cb0217addc5efde66f5f1a50d6b1eceac2c6b09121a422d92bfe1e0712e23554` 与 `4f282bd6cd384ca24e351c3fd3eae03db23d678ffd349ddff1d386a1a249250b`。文件展示精确原文与提示词，说明诊断目的及可能产生的新费用，并排除凭据。

## 生产链路与隔离

候选使用 `ConfiguredAIWebLifecycle`、`extract_plan`、`OpenAICompatibleProvider` 和既有 `AIBudgetTransport`，不创建只为成功的供应商旁路。全新隔离 SQLite 数据库仅用于证明业务状态隔离。成功的已验证提取由内存复核接收器接收，只写入被忽略运行目录中的复核产物；不会持久化到 `plan_extraction_review` 或任何计划、激活、持仓、行情、提醒、投递表。

v2 诊断 sidecar 与隔离数据库同目录。它只保留固定诊断结构，包括 `timeoutKind`、`timeoutElapsedMs`、返回模型匹配、结束原因、尝试次数和可选的已验证 usage。它绝不保留凭据、Headers、原文、提示词、供应商原始内容、原始响应、异常正文或直连 IP。

## 停止规则与结果解释

R27 在首个成功或失败终态后停止。遇到 v2 诊断缺失/无效、回执/查询不确定、模型不匹配、`finishReason=length`、输出非法、字面 oracle 不匹配或清理/隔离失败时，也会停止且不再 POST。同一运行中的后续尝试会被物理尝试预算在联网前拒绝，原子 claim 会阻止候选重新开启。

记录为 `CONNECT`、`READ`、`WRITE`、`POOL`、`OVERALL_DEADLINE` 或 `UNKNOWN`，只表示 R26 仪器观察到的本地边界；不能证明 DeepSeek 是否收到、远端计算状态、是否完成或是否计费。尤其 `READ` 不能区分供应商计算、上游排队或接收停滞；`OVERALL_DEADLINE` 可能遮蔽几乎同时触发的 HTTPX 边界。

即使提取成功，R27 仍要求人工复核，且只证明本次 `LITERAL` 提取与 oracle 结果。它不证明 `SEM-AMB-01`、`SEM-UNS-01`、实时求值、IN_APP 投递、行情、monitor 启动、计划激活或交易。

## 费用与执行前来源核对

Asia/Shanghai `2026-09-16 10:25` 核对时，官方 Chat Completions 参考仍记录 `POST /chat/completions`、`deepseek-v4-pro` 请求别名、非思考模式、JSON 输出及本候选使用的 8,192 Token 请求值。官方价格页同时说明，自北京时间 `2026-09-14 12:00` 起，在 V4.1 Pro 可用前，使用不变 `deepseek-v4-pro` 别名的请求会由服务端路由到 `DeepSeek-V4.1-Flash`，并按 Flash 价格计费。该路由变化不要求改变请求字段或目的地，因此精确获批载荷保持不变。来源：https://api-docs.deepseek.com/api/create-chat-completion/ 和 https://api-docs.deepseek.com/quick_start/pricing/。

当前 Flash 峰值价格为缓存未命中输入 USD `0.30`/M、输出 USD `1.20`/M；非峰值价格分别为 USD `0.15`/M 与 USD `0.60`/M。按保守的 19,000 输入 Token 算术边界与完整 8,192 输出 Token，一次请求估算为峰值 USD `0.0155304` 或非峰值 USD `0.0077652`，均不含税费和账户调整。计划的 Asia/Shanghai 10:00–12:00 窗口位于官方记录的工作日 UTC 01:00–04:00 峰值时段内。真实分词、缓存、输出长度、计费及税费未知。因不允许行情调用，行情费用为零。未调用余额或模型列表 API。

最终执行门禁必须再次读取这些官方页面。若后续路由、请求契约或价格变化需要改变已批准载荷，则记录差异并阻止执行。

## 离线验证与执行门禁

聚焦测试必须覆盖模拟成功、全部六种超时、一次调用计数、第二次调用拒绝、字节/哈希/请求体篡改拒绝、第二次原子 claim 拒绝及清理。R25/R26 提取与诊断回归组、Ruff 和 `git diff --check` 必须通过。精确审阅包必须匹配冻结哈希，仓库必须位于已提交候选的干净基线，全新 claim 必须可用，时间窗口必须有效。

以下干跑与审阅材料生成不会发起网络请求：

```text
python -m scripts.r27_ai_timeout_diagnostic --prepare-egress-review
```

真实执行形式有意由精确授权 Token 与 run ID 门禁。只有以上所有门禁为绿时才可调用一次。无论结果如何，都不自动开启 R28 或重试。
