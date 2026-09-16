# R26 AI 超时离线诊断与修复

英文原版为 `R26-ai-timeout-diagnostics-20260916.md`，本文是等价中文审阅副本。状态 **OFFLINE_COMPLETE / DIAGNOSTIC_GAP_FIXED / HISTORICAL_REMOTE_CAUSE_UNKNOWN / LIVE_NOT_RUN**。

## 范围与安全边界

R26 在不重放请求的前提下调查 R25 首次且唯一一次 AI 超时。本轮 DeepSeek POST、行情调用、余额/模型列表探测、Webhook、券商动作、claim、计划激活及持仓变化均为 **零**。未运行 R25 `--execute`，未复用已消耗的 R25 运行/窗口/额度，未打印凭据，也未在诊断中保留供应商异常正文、Headers、响应内容、原文或提示词。

## 链路还原

冻结的 R25 候选选择 `plan-extract-v5`、`max_tokens=8192`、一条 user 消息、`temperature=0`、`thinking={"type":"disabled"}`、`response_format={"type":"json_object"}`、`stream=false` 和 `max_retries=0`。`AIBudgetTransport` 仅放行一次准确获批的 `LITERAL` 请求，随后委托给 `httpx.AsyncHTTPTransport(retries=0, trust_env=False)`。

生产路径如下：

1. `scripts/r25_extraction_acceptance.py` 通过 `ConfiguredAIWebLifecycle` 提交 `LITERAL`。
2. `extract_plan` 构造 v5 请求并调用 `OpenAICompatibleProvider`。
3. `_request_once` 在 `httpx.AsyncClient.stream(..., timeout=httpx.Timeout(30))` 外嵌套 `asyncio.timeout(30)`。
4. 适配器把内置 `TimeoutError` 和所有 `httpx.TimeoutException` 子类统一折叠为 `AIProviderErrorCode.TIMEOUT`。
5. 因此提取层与诊断 sidecar 最终只能保留 `stage=provider`、`providerErrorCode=TIMEOUT`、`path=unknown`、`attempts=1` 且无 usage。

HTTPX 0.28.1 官方区分连接、读取、写入和连接池等待四类超时异常。Python 3.14 文档说明 `asyncio.timeout()` 会取消所包围的工作，并在上下文外将取消转换为 `TimeoutError`。2026-09-16 核对来源：https://www.python-httpx.org/advanced/timeouts/、https://www.python-httpx.org/exceptions/ 和 https://docs.python.org/3/library/asyncio-task.html#timeouts。

## 证据边界

### 已证明

- R25 完整会话为 30.735763 秒，但 AI 操作本身从 `2026-09-16T09:41:54.912308+08:00` 到 `09:42:24.918282+08:00`，即 30.005974 秒。
- 本地总截止与 HTTPX 的连接/读取/写入/连接池无活动超时均为 30 秒。供应商重试与传输重试均为零。
- 请求仅物理启动一次。R25 未得到已验证的响应信封、结束原因、usage 或返回模型身份；它零重提停止，并保持激活及业务表为空。
- R26 之前的适配器不可逆地折叠了本地可观察的五类超时。已保留的 R25 v1 sidecar 因而无法确定历史阶段。

### 合理推断而非证明

- 30.005974 秒的 AI 时长与某个已配置的本地 30 秒边界触发相符。由于各边界相等且只保留了折叠分类，无法证明究竟哪个边界先触发。
- 未来若记录为 `READ`，只表示在读取间隔内未收到响应体数据块；仍无法区分供应商计算、上游排队或网络接收停滞。`CONNECT` 覆盖连接建立阶段，不能仅凭所保留的异常类型安全地区分 DNS、TCP 与 TLS。

### 未知

R25 无法证明 DeepSeek 是否收到、完成或计费该请求，也无法证明故障发生在连接/TLS、写入、连接池获取、响应读取/远端处理，还是外层本地总截止先触发。成功的 `trade_cal` 仅证明其独立行情链路当次可用，不证明 AI 链路健康。R19 更早的 `finishReason=length` 是已验证响应截断，不是本次超时的证据。

## 修复

已确认的本地缺陷是诊断信息丢失，并非已证明的错误超时阈值或供应商故障。R26 保持现有请求字段、配置超时值、供应商重试策略、传输重试策略、停止行为、幂等、审计和清理语义不变。

脱敏供应商错误现在仅携带：

- `timeoutKind`：固定枚举 `CONNECT`、`READ`、`WRITE`、`POOL`、`OVERALL_DEADLINE` 或 `UNKNOWN`；
- `timeoutElapsedMs`：失败物理尝试的非负单调时钟耗时毫秒数。

提取层将这些字段传入 `ExtractionDiagnostic`。sidecar schema v2 持久化这些字段，不保留原始异常字符串、供应商正文、Headers、凭据、提示词、原文或直连 IP。历史 v1 证据保持不可变且仍可读取。

## 离线验证

TDD 红灯阶段：新聚焦测试最初在收集期失败，因为 `AIProviderTimeoutKind` 尚不存在。完成最小实现后：

- R26 聚焦测试：**9/9 通过**。覆盖四种 HTTPX 超时子类、独立的本地总截止、单调耗时毫秒、向提取层传播、v2 sidecar 持久化、元数据一致性，以及凭据/异常正文排除。
- AI provider、诊断、R17、R19、R25、R26 聚焦回归组：**80/80 通过**，另有一个既存 Starlette/httpx 弃用警告。
- 所有改动 Python 文件的 Ruff 与 `git diff --check`：通过。

这些离线测试通过 mock/fake 证明新的分类行为，不会追溯性地分类 R25，也不证明真实供应商成功。

## 下一轮最小真实验证提案（未授权、未运行）

| ID | 建议边界 |
|---|---|
| R26-N01 | 只回答一个问题：不变的冻结 `LITERAL` v5/8192 请求能否在生产 DeepSeek 链路上到达终态；若不能，新的固定超时分类记录为何？ |
| R26-N02 | 使用全新的候选/运行/claim、全新隔离 SQLite 数据库和 v2 诊断 sidecar。直接使用生产配置的 AI 组合；不启动行情/参考数据生命周期，允许的行情调用数为 **零**。 |
| R26-N03 | 只允许 `LITERAL` **一次** AI POST 物理启动，零重试、零重提。原文、提示词和请求体字段保持不变：`deepseek-v4-pro`、v5、8,192 输出 Token、非思考 JSON、非流式、temperature 0。 |
| R26-N04 | 保持有证据支持的 30 秒 provider/HTTPX 设置不变。候选总时限为 45 秒，其中协作清理最多 15 秒。在没有新证据前不增加阈值、不切换模型、不增加重试。 |
| R26-N05 | 任一成功或失败终态后停止。缺失诊断、回执/查询不确定、模型不匹配、输出非法/截断或字面 oracle 失败均零重提停止。成功时只写隔离复核产物；禁止保存或激活计划，仍须人工复核。 |
| R26-N06 | 生成并展示全新的准确外发审阅包。即使原文/提示词哈希不变，已消耗的 R25 批准/额度也不是新候选的授权；任何 POST 前都必须取得新的内容及目的地精确批准。 |
| R26-N07 | 在实际执行时重新核对官方路由与价格。2026-09-16 快照将 `deepseek-v4-pro` 映射为 `DeepSeek-V4-Pro-0813`，峰值缓存未命中输入价为 USD 1.32/M、输出价为 USD 3.96/M。按保守的 19,000 输入 Token 算术边界和完整 8,192 输出 Token，一次峰值请求估算为税费/账户调整前 USD `0.05752032`，非峰值为 USD `0.02876016`。真实分词、缓存、输出长度、计费和税费仍未知。不包含充值或账户探测。 |
| R26-N08 | 因本提案行情调用为零，既不消耗也不依赖截止于 `2026-09-16T14:48:40.405317+08:00` 的股票证书或截止于 `2026-09-18T10:20:44.522358+08:00` 的五指数证书。后续若扩展至行情验证，必须按真实开始时间重新核对适用证书，且不得静默重新认证。 |

2026-09-16 核对的 DeepSeek 官方页面记录了 `POST /chat/completions`、`deepseek-v4-pro`、非思考模式、JSON 输出、8,192 Token 请求值和当前路由/价格：https://api-docs.deepseek.com/api/create-chat-completion/ 和 https://api-docs.deepseek.com/quick_start/pricing/。

## 结论

R26 已完成所有可做的离线工作：在保持一次性安全和全部业务状态保护的前提下，修复了经证实的本地可观测性缺陷。历史 R25 远端原因仍无法从保留证据中得知，本轮不声称真实成功。下一轮提案仅供审阅，不自动开启 R27。
