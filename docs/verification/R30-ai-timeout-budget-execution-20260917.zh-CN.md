# R30 执行记录：单次尝试以供应商瞬态错误结束

英文原版为 `R30-ai-timeout-budget-execution-20260917.md`，本文是等价中文审阅副本。状态 **EXECUTED_ONCE / AI_ACCEPTANCE_FAILED / PROVIDER_ERROR_TRANSIENT / CLAIM_CONSUMED / NO_RETRY / CLEANUP_COMPLETE**。

## 已授权范围

用户已明确批准精确 R30 审阅包、向 `https://api.deepseek.com/chat/completions` 发送一次非流式 `LITERAL` POST、零重试、零行情及可能费用。批准问题将约 USD `0.01583` 明确表述为估算，并明确说明它不是账单保证；用户回答为“批准并且接受”。用户没有设定金额硬上限。绑定包 SHA-256 为 `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`；规范请求体 SHA-256 为 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`。

## 本地门禁

在 `2026-09-17T10:03:59+08:00`，任何 claim 或网络派发之前：

- 分支 `codex/r30-ai-timeout-budget` 在 `99ff581246f95b97ec44abcb4d5b3ae9e923c27a` 上干净，并保留 R29 提交 `d7279155b8965423d55fc71adfe6d50b4079fa06` 为祖先；
- 显式只读原配置匹配 SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`，并选择 `api.deepseek.com` 与 `deepseek-v4-pro`；
- 审阅包重算摘要与已授权值一致；
- 真实 R29/R30 原文、提示词和请求体字节相等；
- 原文 SHA-256 为 `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`，提示词 SHA-256 为 `7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba`；
- 日期窗口有效，claim 不存在；
- 离线预检返回 `ready=true`，但仍要求执行前立即复核官方路由/价格。

## 官方价格复核与先前解释错误

搜索提取对同一 DeepSeek 官方价格页返回两个互相冲突的快照。已批准审阅包采用的规范结果显示 `DeepSeek-V4-Pro`、缓存未命中输入 USD `0.435`/M、输出 USD `0.87`/M；另一个官方快照显示较旧且更高的峰值/非峰值价格。

由于该冲突会改变已批准的费用边界，本轮通过只读浏览器直接打开规范官方页面。约在 `2026-09-17T10:04+08:00`，实际页面显示：

- 模型别名 `deepseek-v4-pro`，模型版本 `DeepSeek-V4-Pro-0813`；
- 峰值缓存未命中输入 USD `1.32`/M，峰值输出 USD `3.96`/M；
- 非峰值缓存未命中输入 USD `0.66`/M，非峰值输出 USD `1.98`/M；
- 峰值时段为周一至周五 UTC `01:00-04:00` 与 `06:00-10:00`；
- OpenAI 格式 base URL 为 `https://api.deepseek.com`。

来源：https://api-docs.deepseek.com/quick_start/pricing/。

按固定 `20,000` 输入 Token 算术边界和不变的 `8,192` 输出 Token 上限计算，当前官方峰值估算为 USD `0.05884032`，非峰值估算为 USD `0.02942016`；两者均高于冻结审阅包的 USD `0.01582704` 估算。真实分词、缓存拆分、输出长度、计费、税费及账户调整仍未知。

请求路由和模型别名仍兼容。首次尝试仍把冻结估算解释为用户设定的费用上限，并在创建 claim 前停止。这是代理的保守解释，不是程序门禁，也不是对用户批准的准确理解。价格冲突与零调用停止事实继续保留，而“先前批准已经失效”的不正确结论被撤销。审阅包字节、请求体、窗口、配置、调用上限与授权范围均未改变。

## 上次停止结果与记账

上次派发决策：`NOT_RUN_AGENT_AUTHORIZATION_INTERPRETATION`；它记录历史停止，不代表当前程序或用户授权失败。

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

由于披露的 USD `0.01582704` 明确是估算而非硬上限，在披露较高估算后，现有批准仍适用于该精确单次请求包。任何执行仍须在启动前通过全部不变的正向程序门禁，并在网络 I/O 前永久消耗一次性 claim。不得自动开启 R31。

## 已授权单次执行

授权解释更正以 `71bd09cd757b4cf78788ec3d086f5a2462e5650d` 提交后，再次直接打开官方页面。页面仍显示 `POST https://api.deepseek.com/chat/completions`、别名 `deepseek-v4-pro`、模型版本 `DeepSeek-V4-Pro-0813` 及较高的峰值/非峰值价格。在 `2026-09-17T10:22:27.399234+08:00`，候选预检返回 `ready=true`，并确认：

- R30 分支干净且已提交，本地日期有效；
- 显式只读原配置 SHA-256 匹配，密钥/模型/主机配置就绪；
- 包 SHA-256 为 `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`；
- 原文、提示词与规范请求体哈希不变，其中请求 SHA-256 为 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`；
- claim 新鲜，旧运行目录不存在；
- AI 物理尝试上限一次、零重试、零行情、65 秒 provider 截止与 81 秒总硬边界。

已授权 launcher 于 `2026-09-17T10:23:06.465672+08:00` 启动，在进入供应商路径前原子消耗 claim，并启动唯一一次 AI 物理尝试。它于 `2026-09-17T10:23:06.726004+08:00` 结束，有界工作耗时 `261` 毫秒，结果为 `AI_ACCEPTANCE_FAILED`。

安全诊断记录供应商阶段 `PROVIDER_ERROR`，`providerErrorCode=TRANSIENT`、`attempts=1`，无超时分类、finish reason 未知、usage 不可用，也无法判定返回模型是否匹配。没有可用的供应商响应，因此严格 schema 校验、映射校验与字面 oracle 均未运行；`oracleStatus=NOT_RUN`、复核结果为 null、复核接收数为零。证据无法确定 DeepSeek 是否收到该尝试或是否计费。禁止重试或重提。

## 最终记账与安全核验

- AI 物理尝试：`1`；重试/重提：`0`；网络前拒绝：`0`；
- 行情调用（包括 `trade_cal`）：`0`；行情生命周期启动：`false`；
- 余额/模型列表/账户探测：`0`；
- 真实 claim：已消耗并保留；运行目录：已保留；
- 清理：`COMPLETE`；launcher 退出后无候选进程残留；
- 允许激活：`false`；人工复核状态：`REQUIRED_NOT_PERFORMED`；
- 独立查询的全部 `38` 张业务表为空，仅存在本地 schema 元数据行；
- audit 与物理尝试 journal 的状态和计数一致；journal 记录 `normalAuditPresent=true`；
- 真实配置只读且未复制；审阅包、请求字节、持仓和原 main 工作树均未改变。

## 证据完整性

- `audit.json`：`9e5fb96e316fbef9b8b11c811f2a11b78e16941080718e5a459948a871a2e048`；
- `physical-attempts.json`：`9d4cef6722a70d690c06a1240b2ff30631719f244dc35e512361ac5094d2fa7d`；
- `monitor.ai-extraction-diagnostics.jsonl`：`b96aa8f4607315f57fbf00496bf03521c024bb3822d37b33ce98735b508fab40`；
- `validated-review-result.json`：`d64c4b1b55899621b50240fc3c961366e3393931705b80fa859f5a20b989338e`；
- `monitor.sqlite3`：`237a0911e2f6b6adfafcf6d1b4a5430af1d224936ce0b52b053407843310c255`；
- `monitor.sqlite3-shm`：`fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb`；
- `monitor.sqlite3-wal`：空文件 SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。

保留的忽略证据目录为 `data/r30-ai-timeout-budget-acceptance/r30-20260917-a/`。报告排除了凭据、Authorization Header、原文/提示词文本、供应商原始内容、异常正文及直连 IP。

由于没有获得终态模型响应，R30 未验证超时预算假设。已消耗的 claim 禁止再次尝试 R30。未开启 R31。
