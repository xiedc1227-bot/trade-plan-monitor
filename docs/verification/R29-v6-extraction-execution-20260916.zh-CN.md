# R29 单 POST plan-extract-v6 执行记录

英文原版为 `R29-v6-extraction-execution-20260916.md`，本文是等价中文审阅副本。提案 `R29-20260917-V6-LITERAL-ACCEPTANCE-1`；保留运行标签 `r29-20260917-a`。状态 **LIVE_ATTEMPT_COMPLETE / PROVIDER_TIMEOUT_OVERALL_DEADLINE / CLAIM_CONSUMED / ONE_AI_ZERO_MARKET / ORACLE_NOT_RUN / FULL_WORKFLOW_NOT_PROVEN**。

## 授权与最终门禁

用户明确批准将 SHA-256 为 `328620ea1d51a7b5b15128ca5f1741825478e46ec1fd6eef0f4abd271c8579f9` 的精确包发送一次，随后要求立即运行。只有本地启动窗口改为 Asia/Shanghai `2026-09-16 13:30–15:00`；原文、唯一 v6 提示词、目的地、请求字段及包哈希均逐字节不变。

派发前立即复查时，DeepSeek 官方页面仍记录 `POST /chat/completions`、`deepseek-v4-pro`、禁用思考、JSON object 输出及已批准字段。价格页仍记录 `DeepSeek-V4-Pro-0813` 和已审阅的 Pro 费率。未调用余额或模型列表端点。来源：https://api-docs.deepseek.com/api/create-chat-completion/ 与 https://api-docs.deepseek.com/quick_start/pricing/。

首次提升权限的进程因提升后的 Windows 账户无法通过 Git 安全目录检查，在 claim 创建与联网前被拒。仅对该进程设置 Git 安全目录值后，只读检查恢复；未修改全局 Git 配置、载荷或候选预算。再次预检为 `ready=true`，且唯一真实尝试前 claim 仍不存在。

## 终态结果

真实运行于 `2026-09-16T13:48:02.208937+08:00` 启动，于 `13:48:32.440774+08:00` 结束，`boundedWorkElapsedMs=30232`。恰好一次 DeepSeek POST 物理启动。在边界内未收到响应信封或已验证 usage。

提取终态为 `PROVIDER_ERROR`，v2 诊断为 `provider / PROVIDER_ERROR / TIMEOUT / OVERALL_DEADLINE / 30009 ms`，`attempts=1`、`finishReason=unknown`，返回模型匹配不可用。该结果只标识本地 30 秒整体边界，不能证明 DeepSeek 是否收到请求、远端计算进度、稍后是否产生响应或请求是否计费。

字面 oracle 未运行（`oracleStatus=NOT_RUN`），内存复核接收器收到零个结果，`validated-review-result.json` 的 `result` 为 null。因此，R29 没有验证 v6 字面提取，也没有产生可供人工复核的草稿。

## 有界执行证据

| ID | 观察结果 |
|---|---|
| R29-E01 | AI 物理启动 `1/1`：`LITERAL=1`；重试 `0`；联网前拒绝 `0`；operation ID 为 `c4659985-de29-4a37-abc0-b19a63f0000d`。 |
| R29-E02 | 行情调用 `0/0`，包括 `trade_cal=0`；未启动行情/参考数据生命周期。 |
| R29-E03 | 清理 `COMPLETE`；耗时 `30232` ms；原子 claim 与额度已消费。 |
| R29-E04 | 隔离数据库全部业务表为零行，包括提取复核、计划、激活、持仓、行情、求值、提醒、投递及交易日历。 |
| R29-E05 | 复核接收器回执 `0`；已验证复核结果为 null；激活始终不允许。 |
| R29-E06 | 真实配置 SHA-256 仍为 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`；配置未复制到 worktree。 |

## 证据完整性

- `audit.json`：`405fb02a919a7e5ee116ceb29747ec7952d2a2ea7bc65b99f6e3558d8e4fceb8`。
- `physical-attempts.json`：`93e11783daaf22b14e99fc266d0e3e8099c4cc0cb2500b95e42162913367fa7a`。
- `monitor.ai-extraction-diagnostics.jsonl`：`5991b8ff19a838b712dd0fb69d5b4e46caac5cf193fd4cff5fe8973260b218a6`。
- `validated-review-result.json`：`90fed53d8811a3ae0638ce95f4e983297aee62a570f262e02e6a171965c5bd29`。
- `monitor.sqlite3`：`6a843beb818d6f1e52f05947eb094fe47630ce743d0e1010895e1c2b9992f283`。
- `monitor.sqlite3-shm`：`fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb`。
- `monitor.sqlite3-wal`：实际为空文件，SHA-256 为 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。

被忽略的证据目录为 `data/r29-v6-extraction-acceptance/r29-20260917-a/`。本文不包含凭据、Authorization Header、原文、提示词、供应商原始内容、原始响应、异常正文或直连 IP。

## 费用与结论边界

已验证 usage 不可用，因此无法计算实际费用。已审阅峰值算术上限为 USD `0.05884032`，但该估算和超时都不能证明发生收费。税费、缓存状态、账户调整与计费仍未知。

R29 满足了获批的一次 POST/零行情边界，但终止于本地整体超时。它不证明 v6 提取成功、字面 oracle 接受、人工复核、语义样例行为、monitor 启动、实时求值、IN_APP 投递、计划保存/激活或交易。不得重放本 claim，也不得自动开启 R30。任何后续外部请求都需要全新有界候选、重新展示精确包并取得明确授权。
