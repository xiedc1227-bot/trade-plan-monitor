# R29 单 POST plan-extract-v6 验收方案

英文原版为 `R29-v6-extraction-proposal-20260916.md`，本文是等价中文审阅副本。提案 `R29-20260917-V6-LITERAL-ACCEPTANCE-1`；运行 `r29-20260917-a`。状态 **OFFLINE_CANDIDATE / EXACT_EGRESS_REVIEW_READY / LIVE_NOT_AUTHORIZED / CLAIM_UNCONSUMED / ZERO_EXTERNAL_CALLS**。

## 目标与证据边界

R29 只回答一个狭窄问题：不变的合成 `LITERAL` 原文配合新审阅的 `plan-extract-v6` 提示词，经生产 DeepSeek 供应商、提取、严格 schema、映射校验与字面 oracle 链路后，能否到达 `SUCCEEDED / completed / NONE` 并产生仅供复核的产物？

这不是完整工作流验收。它不覆盖两个语义样例、行情、monitor 启动、实时求值、IN_APP 投递、人工复核、计划保存/激活、持仓、委托、成交或交易。即使成功，状态仍为 `humanReviewStatus=REQUIRED_NOT_PERFORMED` 且 `activationAllowed=false`。

## 固定候选契约

| ID | 固定值 |
|---|---|
| R29-C01 | 在 `data/r29-v6-extraction-acceptance/` 下使用全新原子 claim；准备或干跑不会创建它。 |
| R29-C02 | 启动窗口为 Asia/Shanghai `2026-09-17 09:00:00` 至 `18:00:00`。提取不依赖交易时段；错过窗口即停止，不创建后台等待或定时任务。 |
| R29-C03 | 仅 `LITERAL`；AI 物理 POST 上限 `1`；重试/重提 `0`；全部行情上限为 `0`，包括 `trade_cal=0`。 |
| R29-C04 | 既有 provider/HTTPX 超时 `30` 秒；终态观察额度 `31` 秒；总硬边界 `45` 秒，其中协作清理最多 `15` 秒。 |
| R29-C05 | 模型别名 `deepseek-v4-pro`；`plan-extract-v6`；`max_tokens=8192`；`temperature=0`；`thinking={"type":"disabled"}`；`response_format={"type":"json_object"}`；`stream=false`；恰好一条 user 消息。 |
| R29-C06 | 目的地 `POST https://api.deepseek.com/chat/completions`；不探测余额、模型列表或其他账户/API。 |
| R29-C07 | 原文 SHA-256 `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`；v6 提示词 SHA-256 `7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba`；提示词为 `19,359` UTF-8 字节。 |

旧的 `19,000` 字节传输上限会在联网前拒绝完整 v6 提示词。因此，共享传输层增加了可配置上限，同时默认值仍保持 `19,000`。只有 R29 传入精确的 `19,359`，而传输层仍要求冻结提示词哈希、精确端点、请求体字段和一次尝试预算。该修改不会放行任意更长提示词，也不改变 R25/R27 冻结的提示词、哈希、claim 或证据。

## 精确外发与变化后的批准范围

完整原文、完整唯一 v6 user 提示词、全部固定请求字段、已省略凭据的 Header 范围、目的地、用途、v5/v6 哈希比较、当前价格快照及包哈希位于：

- `data/r29-v6-extraction-review/egress-review.md`；
- `data/r29-v6-extraction-review/egress-review.zh-CN.md`；
- `data/r29-v6-extraction-review/egress-material.json`；
- `data/r29-v6-extraction-review/manifest.json`。

按 `egress-material.json`、`egress-review.md`、`egress-review.zh-CN.md` 顺序串联计算的包 SHA-256 为 `328620ea1d51a7b5b15128ca5f1741825478e46ec1fd6eef0f4abd271c8579f9`。组件哈希冻结在脚本与 manifest 中。凭据、完整本地配置、响应内容、异常正文、供应商返回 Header 和直连 IP 均被排除。

原文字节与 R25/R27 相同，但唯一提示词从 v5 哈希 `660945f63c48c66c6b115e8bb29a0ccc76fde1df60aca17ba7c74bba2a06ef89` 变为上述 v6 哈希。v6 新增规则 12–14，明确来源/引用矩阵、唯一绑定身份、标量类型/值/单位规则、`ALL|ANY` 结构绑定和 SOURCE 双向映射。因此，之前的 v5 批准不授权 R29；执行前必须取得对本精确包和目的地的一次明确批准。

## 生产链路、配置与隔离

R29 使用 `ConfiguredAIWebLifecycle`、`extract_plan`、`OpenAICompatibleProvider`、严格 `PlanExtractionOutputV4`、服务端映射校验及既有字面 oracle，不新增只为成功的供应商或 schema 旁路。

隔离 worktree 有意不包含被忽略的 `config/app.yaml`。准备阶段不复制凭据、配置或数据库。未来获批执行必须显式传入只读 `--config-path`；预检要求该文件 SHA-256 为 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`、选择已配置的 DeepSeek profile 与别名，并且只指向 `https://api.deepseek.com`。证据不记录该路径或配置内容。

只有全部门禁通过且 execute 命令已获授权后，才创建全新隔离 SQLite 数据库及 v2 sidecar。成功结果仅保留在被忽略的本地复核产物和内存回执中。包括计划/提取复核、激活、持仓、行情、求值、提醒、投递和交易日历在内的全部业务表必须保持零行。

## 成功与停止规则

成功必须同时满足：终态 `SUCCEEDED`；诊断 `completed / NONE`；`finishReason=stop`；返回模型匹配为 `true`；原文、提示词版本和操作回执精确匹配；存在时 usage 已验证；字面 oracle 接受；恰好一份仅供复核结果；完整清理；AI 启动最多一次；行情启动为零；隔离数据库全部业务表为零行。

任一供应商错误、超时、非 stop 结束、模型不匹配、JSON/schema/映射失败、字面 oracle 不匹配、sidecar 缺失/无效、回执/查询不确定、隔离失败或清理失败，都会停止且不再 POST。安全 schema 诊断只能暴露固定允许代码，包括 R28 的六个字段绑定代码；原始响应和异常内容仍被排除。任何结果都不能用于反推已省略的 R27 响应。

## 官方契约与保守费用快照

在 `2026-09-16T11:09:28+08:00`，官方 Chat Completions 参考记录 `POST /chat/completions`、`deepseek-v4-pro`、非思考模式、JSON object 输出及本候选使用的固定字段。当前官方价格页把该别名记录为 `DeepSeek-V4-Pro-0813`，峰值缓存未命中输入价格为 USD `1.32`/M、输出价格为 USD `3.96`/M；这与 R27 较早的临时 Flash 路由快照不同。来源：https://api-docs.deepseek.com/api/create-chat-completion/ 与 https://api-docs.deepseek.com/quick_start/pricing/。

按向上取整且刻意保守的 `20,000` 输入 Token 上限及完整 `8,192` 输出 Token 计算，单次请求在官方峰值价格下最多为税费/账户调整前 USD `0.05884032`；非峰值算术值为 USD `0.02942016`。真实分词、缓存拆分、输出长度、计费及税费未知。由于禁止行情调用，行情费用为零。任何获批派发前必须立即再次核对官方路由、契约和价格页；若变化要求修改已批准载荷，则阻止执行。

## 执行门禁

默认调用与审阅材料生成均只离线运行。真实执行还要求：精确授权 Token 与 run ID；显式 `--config-path`；原文/提示词/请求体/包/配置哈希匹配；已提交且干净的 R29 代码；未消费 claim；窗口有效；官方路由/价格复查；以及用户对精确审阅包的明确批准。准备阶段未消耗任何一次性资源。
