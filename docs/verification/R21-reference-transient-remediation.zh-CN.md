# R21 参考数据暂态错误定位与失败停止修复

英文原版为 `R21-reference-transient-remediation.md`，本文是等价中文审阅副本。状态 **OFFLINE_PASS / HISTORICAL_REMOTE_CAUSE_UNPROVED / PROGRAMMATIC_FAIL_STOP_FIXED / LIVE_NOT_AUTHORIZED**。

## 1. 范围与保留证据

R21 仅离线执行。未调用 Tushare、DeepSeek、余额/模型列表接口、Webhook、券商或任何其他外部服务；未修改真实计划、持仓、凭据、`config/app.yaml`、两份保留数据库、R20 占位或任何早期证据。

R20 不可变事实保持不变：会话于 `2026-09-15T10:40:25.420+08:00` 占位；恰好一次 `trade_cal` 物理启动返回 `REFERENCE_TRANSIENT`；AI 与其他所有行情端点均为零；隔离业务表均为空；外部安全停止最晚于 `10:43:05.864+08:00` 释放 18766 端口。端口关闭只证明监听结束，不证明优雅关停。R20 没有 `audit.json`；保留的 `termination.json` 如实记录 `EXTERNAL_SAFE_STOP` 及正常清理不完整。

本次复核使用的保留制品 SHA-256 为：

- R18 `audit.json`：`7EA21447A5280B8D839FCB280FA24BB88856532E5B8391D219180B54B8EA48FF`。
- R20 `termination.json`：`80A2761AFE8504339B978A05E1E70B803069E2822C013C096B2A725768D93287`。
- R18 隔离数据库：`2C09E29F86EC48DE9A73059497E4D4E2B44C562985B76DE141E0584F65C5C9F7`。
- R20 隔离数据库：`541C241DE35D1E3CCDA2CD53E415D2E469838B5E9821507D0388270A31099159`。

只读计数再次确认 R18 有 399 条日历记录，R20 有零条日历记录。除 R18 日历行外，两库的计划原文/版本/提取复核/激活状态、持仓、分钟/五分钟 K、求值、提醒及投递尝试均为零。

## 2. 实际日历调用链

R20 路径为：

| 层 | 文件与函数 | 相关行为 |
| --- | --- | --- |
| 授权启动器 | `scripts/r20_bounded_acceptance.py:119-120` | 选择 R20 有界生命周期；占位与授权继续保持已消耗。 |
| 共用有界服务 | `scripts/r14_bounded_acceptance.py:672` | 管理回环监听、物理预算、清理与审计。 |
| Web 生命周期 | `src/trade_plan_monitor/web/lifespan.py:119` | 在暴露 AI 与计划服务前启动监控运行时。 |
| 启动编排 | `src/trade_plan_monitor/runtime/service.py:2778` | 先刷新参考数据；普通生产模式捕获参考错误后进入降级只读，而不是终止。 |
| 参考健康边界 | `src/trade_plan_monitor/web/monitor_composition.py:532` | 把请求、缺数据和存储失败映射为脱敏 `REFERENCE_*` 码。 |
| 生产参考刷新 | `src/trade_plan_monitor/runtime/production.py:398` | 总是请求从 `trade_date - 366 days` 到 `trade_date + 32 days` 的 SSE 日历，校验当天后持久化。计划库为空不会跳过此日历请求。 |
| 请求控制器 | `src/trade_plan_monitor/runtime/request_control.py:538` | 准入一次真实请求，应用 15 秒控制器超时及零轮内重试，再映射适配器错误。 |
| Tushare 适配器 | `src/trade_plan_monitor/market_data/tushare.py:330`、`:553`、`:589` | 调用 `trade_cal`、校验 DataFrame、归一化行并脱敏供应商异常。 |
| SDK/直连 HTTPS 传输 | `src/trade_plan_monitor/market_data/tushare_client.py:37`、`:51` | 配置 `connect_ip` 时直连该字面地址，同时保留端点域名用于 SNI、证书断言及 `Host`；要求 CA 校验，禁用 urllib3 重试和重定向，不使用环境代理。 |

真实配置只通过安全字段检查。其 SHA-256 为 `89923ea019712573B0F8118164EDA1EE2A8371C4EE57FAF2A2AD48FD6B8AB428`（大小写不敏感）；行情主机为 `api.quicksync.cn`；存在 `connect_ip`，其 SHA-256 为 `8d1ba852627d0eade60ccdabd94e5bbc0f7b2e6d6163dad1b3511e25a8bf171a`；传输超时配置为 30 秒；Tushare SDK 为 1.4.29。R18/R20 没有保留逐次配置或 `connect_ip` 哈希，因此当前哈希不能证明两次历史启动时配置逐字节一致。

## 3. 已确认缺陷与历史证据边界

已确认的分类缺陷是：直连客户端把 urllib3 超时转换为 `requests.Timeout`，但 `TushareMarketDataProvider._safe_provider_error` 随后把 `requests.Timeout` 与 `requests.ConnectionError` 一并归入 `TushareErrorCode.TRANSIENT`。因此，控制器已有的 `TIMEOUT` 分支无法从真实供应商适配链到达。TLS 与其他 urllib3 连接失败也都表现为连接错误。另有 HTTP 408/5xx，以及含固定暂态标记的供应商应用消息，也会映射为 `TRANSIENT`。

因此，R20 保留的 `REFERENCE_TRANSIENT` 能证明失败发生在取得可用日历数据、日期窗口校验或持久化之前，但无法在以下情况中作出区分：

- 传输超时；
- TLS 失败或直连 IP 连接失败；
- HTTP 408/5xx；
- 被归类为暂态的供应商应用状态。

R18 在同日更早时成功得到 399 行。R18 提交 `c74a718` 到 R20 提交 `4f62110` 之间，行情适配器、直连客户端、请求控制器和参考组合层没有代码变化；该区间的 R20 变化属于启动器/AI 契约。间歇性外部条件因此是合理怀疑，但仍不能确定是哪一种外部条件。更早成功不能复用为 R20 成功。

日历日期可用性、响应归一化及 SQLite 持久化不是解释保留 `REFERENCE_TRANSIENT` 的合理原因：R17 之后，这些阶段分别具有 `REFERENCE_DATA_UNAVAILABLE`、`REFERENCE_INVALID_RESPONSE` 与 `REFERENCE_STORAGE_ERROR` 分类。它们通常仍可能失败，但 R20 的错误码不能证明这些阶段发生了失败。

## 4. 修复

- `TushareErrorCode.TIMEOUT` 现在可穿过适配器到达 `RequestControlErrorCode.TIMEOUT`，真实供应商超时会在健康状态中报告 `REFERENCE_TIMEOUT`。
- 固定 `TushareFailureKind` 可区分 `TRANSPORT_TIMEOUT`、`TRANSPORT_TLS`、`TRANSPORT_CONNECTION`、`HTTP_STATUS`、`PROVIDER_STATUS`、`RESPONSE_DECODE`、`RESPONSE_SCHEMA`、`DOMAIN_VALIDATION` 与 `UNCLASSIFIED`。HTTP 元数据只允许 `HTTP_3XX`、`HTTP_4XX` 或 `HTTP_5XX`。不保留原始异常、远端消息、响应体、请求头、查询字符串、Token 或原文。
- R20 策略现在显式选择在首次 `trade_cal` 物理失败及更高层参考边界失败时程序化停止。高层钩子还覆盖 HTTP 成功后的响应/领域失败、缺少当天数据及存储失败。普通生产与历史启动默认不启用该策略，继续保留既有恢复行为。
- 一个共享停止事件同时关闭 AI 与行情准入。首次参考失败后，后续 AI、并发/排队行情工作及后台重试都会在另一物理启动前被拒绝。真实控制器继续零重试；未改变生产全局重试策略。
- `physical-attempts.json` 在每次允许的物理启动前原子更新，只含提案/运行 ID、固定上限/计数、停止状态、首个有界行情失败及脱敏参考码。若日志持久化失败，本次准入会回滚并在联网前拒绝。正常清理会原子写入 `audit.json`、停用隔离测试计划、关闭监听、恢复供应商工厂，然后在日志中标记 `normalAuditPresent=true`。
- 强杀进程、断电或操作系统故障仍可能阻止正常清理与 `audit.json`；用户态实现无法在这类终止后保证最终写入。预调用日志使已准入物理计数仍可恢复，并明确保留 `normalAuditPresent=false`；不会把强停改写成优雅关停。

可观测性问题被刻意限制为：物理调用是否启动、在哪个有界层失败、后续准入是否全部停止、正常清理是否完成。日志和最终审计回答这些问题，不引入新的通用日志框架或高基数数据。

## 5. 离线验证

回归测试先后在缺少超时分类、缺少 R20 失败停止策略、缺少耐久日志、参考失败仍错误返回成功退出码，以及日志写失败行为上证明失败。最终检查为：

| 检查 | 结果 |
| --- | --- |
| 聚焦诊断与 R20 测试 | 57 项通过；一个既有 Starlette/httpx 弃用警告 |
| 使用 `-m "not live"` 的生产组合、生命周期、Tushare 契约、R14 接线及 R20 失败停止选择 | 252 项通过；一个既有 Starlette/httpx 弃用警告 |
| 定向 Ruff 检查 | 通过 |
| `git diff --check` | 通过；仅有 Git 既存的 LF→CRLF 工作区提示 |

注入式启动器测试发起一次模拟日历请求并返回脱敏超时，确认 AI 为 0、行情仅 `trade_cal=1` 且其他端点为零，观察到程序化退出，确认隔离计划状态为 `INACTIVE`，写入含 `REFERENCE_TIMEOUT` 的 `REFERENCE_FAILED` 审计，并标记日志存在正常审计。其他测试覆盖 TLS、连接、HTTP 状态族、供应商状态、响应解码/结构、日历领域、存储、并发准入停止、日志写失败拒绝及历史生产成功接线。这些是受控离线证明，不证明 Tushare 当前可用。

验证后，真实且被 Git 忽略的 `config/app.yaml` 哈希继续为 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`。未修改真实配置或数据库。

## 6. 下一项需另行授权的真实步骤

R21 未创建新候选、占位、时间门禁、自动化或外部调用授权。建议的分阶段方案是在准备完成且双方确定早盘日期后，使用一个全新隔离日历诊断候选：

- 恰好一次 `trade_cal` 物理启动；零重试；AI 上限 0；其他所有行情端点上限 0；
- 全新一次性占位、全新 SQLite 数据库、全新回环端口，仅 IN_APP，不修改计划/持仓，不发送 Webhook，不连接券商，不下单、不交易；
- 15 秒控制器边界，另加最多 20 秒协作清理；首个参考失败停止全部准入，并写入上述日志/审计；
- 只保留固定诊断枚举/状态族及计数，不保留供应商正文；
- 行情费用如有仍未知；AI 费用为零。

若诊断成功，会额外增加一次行情调用，但可在重新开放最多三次 AI 与 105 次行情启动前隔离验证日历健康。直接重开全套在成功时可省掉这一次预备调用，但会在间歇性前置条件尚未被刻画时立即进入更昂贵流程。两种方案都需要新的明确授权。

R21 时点，股票证书在本地仅有效至 `2026-09-16T14:48:40.405317+08:00`；五指数证书有效至 `2026-09-18T10:20:44.522358+08:00`。过期证据必须如实报告并另行认证，不能静默刷新。一次日历诊断成功只证明该次日历链路；不能证明 R19 的真实 v5/8,192 提取、语义正确性、复核/保存/激活、盘中求值、BUY/SELL/RISK 自然触发或 IN_APP 可见投递。
