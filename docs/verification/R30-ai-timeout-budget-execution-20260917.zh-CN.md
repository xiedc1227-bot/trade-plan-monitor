# R30 执行门禁记录：当前官方价格阻止派发

英文原版为 `R30-ai-timeout-budget-execution-20260917.md`，本文是等价中文审阅副本。状态 **NOT_RUN_OFFICIAL_PRICE_GATE_FAILED / ZERO_EXTERNAL_CALLS / CLAIM_UNCONSUMED / PACKAGE_UNCHANGED**。

## 已授权范围

用户已明确批准精确 R30 审阅包，并接受其中披露的潜在费用。绑定包 SHA-256 为 `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`；规范请求体 SHA-256 为 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`。授权范围为向 `https://api.deepseek.com/chat/completions` 发送一次非流式 `LITERAL` POST，零重试、零行情，并接受税费及账户调整未知前 USD `0.01582704` 的保守披露估算。

## 本地门禁

在 `2026-09-17T10:03:59+08:00`，任何 claim 或网络派发之前：

- 分支 `codex/r30-ai-timeout-budget` 在 `99ff581246f95b97ec44abcb4d5b3ae9e923c27a` 上干净，并保留 R29 提交 `d7279155b8965423d55fc71adfe6d50b4079fa06` 为祖先；
- 显式只读原配置匹配 SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`，并选择 `api.deepseek.com` 与 `deepseek-v4-pro`；
- 审阅包重算摘要与已授权值一致；
- 真实 R29/R30 原文、提示词和请求体字节相等；
- 原文 SHA-256 为 `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`，提示词 SHA-256 为 `7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba`；
- 日期窗口有效，claim 不存在；
- 离线预检返回 `ready=true`，但仍要求执行前立即复核官方路由/价格。

## 官方价格门禁失败

搜索提取对同一 DeepSeek 官方价格页返回两个互相冲突的快照。已批准审阅包采用的规范结果显示 `DeepSeek-V4-Pro`、缓存未命中输入 USD `0.435`/M、输出 USD `0.87`/M；另一个官方快照显示较旧且更高的峰值/非峰值价格。

由于该冲突会改变已批准的费用边界，本轮通过只读浏览器直接打开规范官方页面。约在 `2026-09-17T10:04+08:00`，实际页面显示：

- 模型别名 `deepseek-v4-pro`，模型版本 `DeepSeek-V4-Pro-0813`；
- 峰值缓存未命中输入 USD `1.32`/M，峰值输出 USD `3.96`/M；
- 非峰值缓存未命中输入 USD `0.66`/M，非峰值输出 USD `1.98`/M；
- 峰值时段为周一至周五 UTC `01:00-04:00` 与 `06:00-10:00`；
- OpenAI 格式 base URL 为 `https://api.deepseek.com`。

来源：https://api-docs.deepseek.com/quick_start/pricing/。

按固定 `20,000` 输入 Token 算术边界和不变的 `8,192` 输出 Token 上限计算，当前官方峰值估算为 USD `0.05884032`，非峰值估算为 USD `0.02942016`；两者均高于已批准审阅包的 USD `0.01582704`。真实分词、缓存拆分、输出长度、计费、税费及账户调整仍未知。

请求路由和模型别名仍兼容，但已审阅的价格/模型版本元数据与保守费用上限不再匹配。这触发强制派发前门禁失败。本轮未尝试改变窗口、配置、请求体或授权范围。

## 停止结果与记账

派发决策：`NOT_RUN_OFFICIAL_PRICE_GATE_FAILED`。

- DeepSeek 物理 POST 启动：`0`；
- 重试/重提：`0`；
- 行情调用（包括 `trade_cal`）：`0`；
- 余额/模型列表/账户探测：`0`；
- 创建或消耗真实 claim：`0`；
- 创建隔离运行数据库或业务行：`0`；
- 供应商响应、finish reason、返回模型与 usage：因未发送请求而不可用；
- 严格 schema、映射 oracle 与复核产物：未运行；
- 生命周期清理：未启动执行生命周期，因此无需清理；
- 审阅包、R29 证据、真实配置、持仓和 main 工作树：均未改变。

先前批准不覆盖按新观察到的费用边界呈现的请求。未来尝试需要新的费用审阅说明与明确用户授权。不得自动开启 R31。
