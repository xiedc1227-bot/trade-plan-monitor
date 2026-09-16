# R27 单 POST AI 超时诊断执行记录

英文原版为 `R27-ai-timeout-diagnostic-execution-20260916.md`，本文是等价中文审阅副本。提案 `R27-20260916-AI-TIMEOUT-DIAGNOSTIC-1`；运行 `r27-20260916-a`。状态 **LIVE_ATTEMPT_COMPLETE / INVALID_OUTPUT_SCHEMA / CLAIM_CONSUMED / ONE_AI_ZERO_MARKET / FULL_WORKFLOW_NOT_PROVEN**。

## 结果

R27 候选已在提交代码上完成准备与验证，最终真实预检在干净 HEAD `6393e2aebc577901ab9a659c2d1f15876473ab8a` 上返回 `ready=true`。首次派发请求因外部执行审批器未在本任务中识别到直接授权，在进程创建前被拒；该次拒绝未消耗 claim 或调用。随后用户在本任务中直接明确批准按冻结字段，将 R27 精确 `LITERAL` 原文与唯一提示词一次发送至 `POST https://api.deepseek.com/chat/completions`，并知悉可能产生费用。

获批派发前立即复查时，DeepSeek 官方页面再次记录该端点、`deepseek-v4-pro` 别名、非思考模式、JSON 输出与固定请求字段；同时仍说明该别名当前由服务端路由到 `DeepSeek-V4.1-Flash`，并按 Flash 价格计费。未调用余额或模型列表 API。来源：https://api-docs.deepseek.com/api/create-chat-completion/ 和 https://api-docs.deepseek.com/quick_start/pricing/。

全新运行于 `2026-09-16T10:30:23.639967+08:00` 启动，于 `10:30:53.181944+08:00` 结束，`boundedWorkElapsedMs=29542`。恰好一次 DeepSeek POST 物理启动。请求返回了已验证的供应商信封：`finishReason=stop`、返回模型匹配为 `true`，且包含 usage。随后本地提取 schema 在 `field_bindings[4]` 以 `schemaErrorType=value_error` 拒绝输出。终态为 `INVALID_OUTPUT`、`stage=schema`、`reason=SCHEMA`；`providerErrorCode`、`timeoutKind` 与 `timeoutElapsedMs` 均不存在。字面 oracle 未运行，也未保留已验证复核结果。

## 结果分析

R27 证明本次新请求**没有**命中 R25 的超时条件：它在不变的 30 秒边界内收到完整供应商响应，仅尝试一次且没有重试。该事实不能追溯性地确定 R25 的超时阶段、供应商接收、完成或计费情况。

安全证据把第五个 `field_bindings` 条目标识为 schema 失败位置，并把 `value_error` 标识为 Pydantic 错误类别。证据有意排除模型原始响应和验证器异常正文，因此无法从已保留证据确定具体违反了哪条字段绑定不变量。不能把本结果称为字面 oracle 不匹配：提取从未到达 `SUCCEEDED`，且 `oracleStatus=NOT_RUN`。

已验证 usage 为输入 `5161`、输出 `4340`、合计 `9501` Token。按官方工作日峰值 Flash 价格：缓存未命中输入 USD `0.30`/M、输出 USD `1.20`/M，并把全部输入视为缓存未命中，保守算术上界为税费/账户调整前 USD `0.0067563`。已保留 usage 不包含缓存命中明细，因此实际计费仍未知。行情调用为零，故行情费用为零。

## 有界执行证据

| ID | 观察结果 |
|---|---|
| R27-E01 | AI 物理启动 `1/1`：`LITERAL=1`；重试 `0`；联网前拒绝 `0`；operation ID 为 `0fb05b25-3d4d-4fc7-ac11-50a7ddf0e9be`。 |
| R27-E02 | 行情调用 `0/0`，其中 `trade_cal=0`；未启动行情/参考数据生命周期。 |
| R27-E03 | v2 sidecar 记录 `INVALID_OUTPUT / schema / SCHEMA / field_bindings[4] / value_error`、`finishReason=stop`、模型匹配 `true`、usage 可用，且无超时元数据。 |
| R27-E04 | 清理状态为 `COMPLETE`；一次性 claim 与额度已消耗；运行目录已保留且不得复用。 |
| R27-E05 | 隔离数据库全部业务表均为零行，包括 `plan_extraction_review`、全部计划/激活/持仓/行情/求值/提醒/投递表及 `trading_calendar`。复核接收器回执为 `0`，复核产物结果为 `null`。 |
| R27-E06 | 真实 `config/app.yaml` SHA-256 仍为 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`，与 R25 相同。 |

## 证据完整性

- `audit.json`：`0d738f4242f20a20c209b1129b188f0dd4ffe591cdaf95993546f37c986bf555`。
- `physical-attempts.json`：`41566ac3e2def5aa8c68762729bda61d341498356db92dd2d56949d113bf93f0`。
- `monitor.ai-extraction-diagnostics.jsonl`：`7cf5cd52295bbbd419464a8c823f11c691be059437c3b1122e2bbaae4007602c`。
- `validated-review-result.json`：`c60cc3755c251fc1edaae678d02f2bbeb0a41ec2fe35338cd4e20e8eff4133c2`。
- `monitor.sqlite3`：`6a843beb818d6f1e52f05947eb094fe47630ce743d0e1010895e1c2b9992f283`。

被忽略的证据目录为 `data/r27-ai-timeout-diagnostic/r27-20260916-a/`。本文不包含凭据、Authorization Header、原文、提示词、供应商原始内容、原始响应、异常正文或直连 IP。

## 离线验证

真实运行前，R27 聚焦测试 **15/15** 通过；R27/R25/R26 加供应商、提取与诊断回归组 **108/108** 通过，另有一个既存 Starlette/httpx 弃用警告。Ruff 与 `git diff --check` 通过。真实运行期间未修改代码。

## 结论边界

R27 已完成单 POST/零行情诊断：真实结果是非超时的供应商完成，但在 `field_bindings[4]` 被本地 schema 拒绝。它没有产生已验证字面提取、oracle 结果、人工复核、语义用例证据、monitor 启动、实时求值、IN_APP 投递、计划保存/激活或交易证据。claim 与额度已消耗。不得重放 R27 或自动开启 R28；未来任何真实请求都需要全新有界候选与授权。
