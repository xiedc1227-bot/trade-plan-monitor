# 规格：runtime-status

> RR002 契约审核稿，源自已批准提案 D7，并受 D1–D6 约束。2026-09-21 的实施授权不代表此详细协议已通过 C0/C4、已经实现或成为生产默认路径。英文正本为 `SPEC-runtime-status.md`，本文件为中文审核副本。
> 依赖 [provider-contract](SPEC-provider-contract.zh-CN.md) 和 [runtime-recovery](SPEC-runtime-recovery.zh-CN.md)。任务与验收 ID 引用 `tasks/runtime-recovery-todo.md` 和 `tasks/runtime-recovery-plan.md`。

## RS01 目标与不变量

即使所有计划都没有当前判断，也要公开权威恢复状态。隔离不可用计划及依赖，支持 `TradePlan` 和 `ExplicitTradePlan`，区分传输通畅、协调器真实进展与可操作数据。本契约改变展示和协议兼容性，不改变求值规则、不可变结果字节/哈希、启用身份、提醒投递资格或提供方准入。

版本 2 替换旧的全局 `status`/`readOnly` 关系与精确心跳结构，不是可选字段扩展。`monitorContractVersion=2` 是监控展示协议版本；`/api/v1`、`/ws/v1/monitor`、持久事件 `schemaVersion=1`、计划 Schema 版本及执行版本各自保持独立含义。v2 应用只提供一个监控版本。现有生产行为保持不变，直至 RR020 及其前置门禁通过。

## RS02 版本协商与路由清单

下列既有 REST 路由必须收到且仅收到一个 `X-Monitor-Contract-Version` 请求头，HTTP 解析后的字段值必须是规范 ASCII 字符串 `2`。缺失、重复、逗号合并、不受支持或非规范值（包括 `02`）必须在读取监控投影或调用命令服务之前失败。普通 HTTP 分帧空白由 HTTP 解析器处理；应用不接受额外的版本列表语法。

| 范围 | `/api/v1` 下的既有路径 |
|---|---|
| 变更的监控读取 | `GET /health`、`GET /health/symbols/{symbol}`、`GET /dashboard`、`GET /symbols`、`GET /symbols/{symbol}`、`GET /explicit-plan-runtime/{symbol}` |
| 活动计划变更 | `POST /plan-activations`、`POST /plan-deactivations` |
| 监控库存变更 | `POST /position-lots`、`POST /position-lot-closures`、`POST /position-inventory-closures`、`POST /position-inventory-confirmations` |
| 监控确认与诊断 | `POST /manual-event-risk-confirmations`、`POST /alert-acknowledgements`、`POST /diagnostic-evaluations` |

计划替换通过启用后继不可变版本完成；不存在可凭空新增的删除/替换端点。草稿保存/导入、提取/复核、AI 配置、独立回测、历史行情/事件和其他未变读取保留既有契约。未来改变活动监控状态的路由须审核是否纳入此保护。版本一致不能替代 Origin、幂等、乐观修订或业务校验，也不授权交易。

这些受保护路由的每个响应（含错误）都包含 `X-Monitor-Contract-Version: 2` 和 `Cache-Control: no-store`。包含新监控投影的响应还必须包含整数 `monitorContractVersion: 2`。响应头补充既有命令响应，不改变命令响应体。不兼容请求返回 HTTP `409`、既有 `CONFLICT` 错误信封，以及恰好一个 detail：code 为 `MONITOR_CONTRACT_MISMATCH`，location 为 `["header", "X-Monitor-Contract-Version"]`，固定 message 为 `Reload the application to use monitor contract 2`。不返回投影或命令结果，不产生命令副作用，也不得回显被拒值。既有服务端生成的 `requestId` 和 `X-Request-ID` 仍为必需。

新客户端先验证受保护响应的响应头，再验证需要版本的响应体。旧服务端缺失/错误的响应头、头体版本不一致或 mismatch detail 都进入终止性的本地 `RELOAD_REQUIRED` 状态：撤销当前可操作展示、取消监控读取/事件流/重连、禁用受保护命令提交，并显示无障碍刷新提示。刷新后获取安装版本的带哈希资源并重新协商，不能用同一批不兼容资源无限重试。不受影响的研究/草稿契约不新增业务限制。

每个受保护 POST 之前，共用命令适配器必须对 `GET /api/v1/health` 或权威总览刷新完成一次只读预检，并验证其 v2 响应头与响应体。此规则适用于直接进入命令页面、首次提交和结果不确定后的重试；任何路由都不能假定监控外壳挂载时已协商。失败、缺失/错误版本或响应未验证都必须阻止发送 POST。仅检查命令响应版本已经太晚，因为旧后端可能已执行命令。预检须绑定同源和当前客户端请求生命周期；导航、重连、generation 替换或不匹配会使进行中的预检失效。结果不确定但语义相同的命令保留原幂等键。此协议预检不从恢复模式或 `readOnly` 推导命令授权；该决定仍由命令服务负责。协同发布须防止在预检与命令之间降级后端；忽略此版本请求头的旧服务端无法执行新增的原子协商协议。

无法使未修改的缓存 v1 客户端渲染新文案。它的受保护请求会收到兼容旧错误信封的 `409`，连接在发送数据前被拒绝；既有安全失败解析及存活超时必须撤销实时展示。即使旧屏幕短暂保留陈旧按钮，服务端保护也拒绝其提交。这才是保证的旧客户端安全属性，不声称每个历史版本都会显示新刷新文案。

带正确请求头的 `GET /health` 在缺少投影、提供方错误、范围阻断及待机时仍可读取。协议不匹配不进入普通提供方重试政策。真实存储/组合故障仍可返回既有脱敏 `SERVICE_UNAVAILABLE`；权威数据源无法读取时不能伪造健康状态。

## RS03 共用状态与生命周期

`RuntimeStatusView` 是封闭对象，所有下列字段（包括显式 null）均必需。外层响应负责 `monitorContractVersion`、`runtimeGeneration`、`observedAt`，以及总览快照的已提交 `sequence`。

| 字段 | 类型与含义 |
|---|---|
| `lifecycle` | `STARTING`、`RUNNING`、`STOPPING` 或 `STOPPED`；仅表示资源所有权。提供方失败不停止所有者。 |
| `mode` | `RECOVERING`、`MONITORING`、`STANDBY`、`DEGRADED` 或 `BLOCKED`；聚合描述，不是求值/投递许可。 |
| `reasonCode` | RS05 中的固定代码，仅 `MONITORING` 可为 null。 |
| `nextWakeAt` | 可空的规范上海时间，表示下一次协调器重新核对时间，包含维护唤醒。 |
| `nextRetryAt` | 可空的当前最早已安排范围重试时间；这是准入时间，不承诺提供方开始/完成时间。 |
| `lastProgressAt` | 可空的最近一次完成有界协调步骤时间；REST 读取或 socket 帧绝不能更新它。 |
| `coordinator` | 精确 `{state, progressDueAt}`；state 为 `STARTING`、`SCHEDULED`、`WORKING`、`STALLED` 或 `STOPPED`，deadline 为可空上海时间。 |
| `scopes` | 最多 32 个按唯一 `scopeKey` 排序的 RS04 条目，不能为截断数组而丢弃活动计划。 |

创建运行时所有者时分配 UUIDv4 `runtimeGeneration`，包括 `STARTING`、恢复和待机阶段。范围故障、重试及普通模式转换保持同一值；仅 D5 下的所有者/配置替换改变它。只有不存在运行时所有者时才为 null。已停止的所有者可保留 generation 供诊断，但不代表存活。缺少判断不能抹去已有 generation。

所有时间使用既有规范 `Asia/Shanghai` 契约：`+08:00`，输入接受 0–6 位小数，输出六位。数据截止、已完成目标时间及 `lastProgressAt` 不得晚于 `observedAt`。时长/期限由注入的单调时钟执行；墙钟时间用于解释当前调度，并在休眠唤醒或时钟变化后重算。时钟回拨后，仅比较墙钟不能恢复存活。

`SCHEDULED` 要求已知 `nextWakeAt` 和 `progressDueAt`；`WORKING` 要求当前拥有的有界操作对应的 `progressDueAt`。期限由已批准的运行时所有者计算：本地重新核对间隔最多 30 秒、物理超时 15 秒，以及既有准入/冷却和工作线程完成规则。本规格不增加超时宽限、整体恢复 SLA 或释放仍在运行工作线程的权限。预期退避、冷却或权限等待通过真实本地重新核对保持存活。正常空闲待机检查只有在协调器确实核对事实并安装下一次唤醒后才算进展。

`STALLED` 表示已安装的单调进展期限超时；要求 `mode=BLOCKED`、`reasonCode=COORDINATOR_STALLED`、所有计划 `readOnly=true`，且没有当前盘中可操作展示。旧唤醒/期限可以保留逾期时间供诊断。只有真实完成协调步骤或受监督替换才能恢复进展。`STOPPED` 要求 `progressDueAt=null`、`nextWakeAt=null`、`nextRetryAt=null`，以及 `mode=BLOCKED`/`reasonCode=RUNTIME_STOPPED`。资源启动/停止失败根据情况使用 `RUNTIME_STARTING`/`RUNTIME_STOPPING` 或 `RUNTIME_FAULT`，不得伪装为依赖重试。

## RS04 范围就绪状态与两类计划

每个范围都包含且仅包含公共字段 `scopeKey`、`kind`、`status`、`reasonCode`、`requiredTarget`、`dataCutoff`、`nextRetryAt`、`progress`。`scopeKey` 是服务端生成的非敏感标识，长度 1–128，字符集为 `[A-Za-z0-9._:-]`；对该依赖/启用身份稳定，不得使用原始端点、凭证、异常或不断变化的分钟目标。`kind` 为 `PLAN | INDEX | PROVIDER | CALENDAR`。计划条目额外要求 `symbol`、`planFamily`、`planVersionId`、`planHash`、`activationRevision`、`readOnly`；指数条目额外要求 `indexCode`；提供方和日历条目没有其他字段。身份字段保留既有规范格式及 JavaScript 安全修订范围。

`planFamily` 区分 `LEGACY_LOW_BUY`（`TradePlan`）和 `EXPLICIT_RULES`（`ExplicitTradePlan`）。尚不能确定合格已完成目标时 `requiredTarget` 为 null；否则精确为 `{"kind":"INTRADAY","targetEnd":<上海时间>}` 或 `{"kind":"OFFICIAL_CLOSE","tradeDate":<YYYY-MM-DD>}`。后端依据 D3 选择实际所需目标；已完成分钟采集目标不自动成为可求值的五分钟边界。`dataCutoff` 是该范围所表示的最近一次经校验且已持久化的数据时间，或 null；它本身不能证明连续覆盖、参考数据或状态完整。

`progress` 精确为 `{requiredCount, completedCount}`，值是可空非负安全整数。所需义务集合未知时两者都为 null；否则两者都存在且 `completedCount <= requiredCount`。计数表示当前范围/目标经过验证的必需单位，不是提供方尝试次数或百分比。目标/启用/依赖要求变化可重置计数，但须连同身份/目标一致更新。盘前 `0/0` 要求可以完整，不得捏造分钟。单次调用成功或返回空数组不能证明完成。

| `status` | 必须表达的含义 |
|---|---|
| `WAITING` | 当前没有到期合格工作，或首个结果/启动准备尚未进入准入。必须有具体等待原因，不宣称正在恢复。 |
| `RECOVERING` | 已知缺失输入/状态存在真实待执行/已拥有的恢复工作或已安排重试；必须有具体原因，已知目标时须给出目标。 |
| `READY` | 所述范围/目标所需的精确持久输入及状态均可用。`reasonCode=null`、`nextRetryAt=null`；已知计数必须完整。不等同于盘中数据新鲜。 |
| `BLOCKED` | 必需依赖/状态当前无法准入或无法证明。必须有具体原因；政策允许时给出合格复查时间，否则给出需要的操作。 |

版本 2 删除旧的全局 `readOnly`，不得悄悄重新定义或与 `mode` 并行输出。仅保留 `PLAN.readOnly`：`false` 表示后端在启用、依赖、generation 及适用的新鲜度/状态保护后，认定此计划当前可对其精确目标求值；`true` 表示不具备资格。`false` 要求 `status=READY`、非空合格目标及存活协调器。休市待机或没有到期求值时，`READY` 仍可搭配 `readOnly=true`。官方收盘/状态重建目标不会因 `readOnly=false` 成为盘中交易机会。

此逐计划字段是求值保护的诊断投影，不是手工持仓/计划/确认命令的授权，也不是通知资格。命令保留各自后端政策；当前提醒展示与投递保留 D5，包括跨日风险例外和逐计划恢复屏障。一个暂时阻断的计划不能阻断其他计划或独立支持的展示指数。股票提供方失败不能压制其他合格指数展示，包括支持的隐藏成交额成分 `399107.SZ`；延期支持的 `899050.BJ` 不得通过此视图变成可请求。

## RS05 模式选择与公开原因

按以下顺序从当前所需范围及真实工作决定模式。历史缓存年龄不是聚合故障判据。

1. 无可用所有者、所有者停止/停滞/故障或全局本地资源故障：`BLOCKED`。
2. 一部分所需工作阻断/失败，而另一个独立所需范围能够继续：`DEGRADED`；健康计划仍可具备资格。若所有所需范围都无法继续，使用 `BLOCKED`。
3. 否则，存在真实待执行/已拥有的恢复或重试工作：`RECOVERING`。
4. 否则，至少一个当前交易时段监控范围已就绪且有到期工作：`MONITORING`。
5. 否则：`STANDBY`，并给出下次已安排核对，例如首分钟之前、午休、休市或无活动计划。待完成收盘/参考修复优先于待机。

仅行情陈旧不能证明 `RECOVERING`，必须存在协调器记录的工作。休市且展示事实完整、没有义务时为 `STANDBY`，即使盘中新鲜度为 false。未使用/延期支持的指数不是所需求值依赖。投递/数据库/提供方明细继续在 `/system` 可见，但不能把无关计划的就绪变为全局判断。

本修订固定 `reasonCode` 词汇：

| 类别 | 代码 |
|---|---|
| 生命周期/进展 | `RUNTIME_STARTING`、`RUNTIME_STOPPING`、`RUNTIME_STOPPED`、`RUNTIME_FAULT`、`COORDINATOR_STALLED`、`STORAGE_UNAVAILABLE` |
| 正常等待 | `BEFORE_FIRST_MINUTE`、`SESSION_BREAK`、`SESSION_CLOSED`、`NO_ACTIVE_PLANS`、`AWAITING_FIRST_EVALUATION` |
| 可恢复工作 | `CALENDAR_UNKNOWN`、`REFERENCE_PENDING`、`COVERAGE_INCOMPLETE`、`CLOSE_PENDING`、`PUBLICATION_PENDING`、`PROVIDER_UNAVAILABLE`、`RATE_LIMITED` |
| 范围阻断 | `CREDENTIAL_MISSING`、`PERMISSION_DENIED`、`SEMANTICS_INCOMPATIBLE`、`CONFIGURATION_INVALID`、`HISTORY_UNAVAILABLE`、`STATE_UNAVAILABLE`、`GENERATION_CHANGED` |
| 聚合混合 | `SCOPED_DEPENDENCY_FAILURE` |

后端把这些代码映射为有界界面文案；原始提供方/存储异常和密钥没有可输出字段。`SCOPED_DEPENDENCY_FAILURE` 仅用于聚合，范围必须保留实际原因。提供方失败保留 D4 重试所有权：瞬态退避 30/60/120/300 秒、共享冷却至少 300 秒、每个操作的权限复查每 300 秒至多一次。缺失凭证不能发送提供方请求；本地维护重新检查配置。可空重试时间不能成为不解释失败的借口：界面必须显示已安排重试/本地核对，或固定的所需操作说明。

## RS06 REST 投影与部分可用

所有变更的监控响应包含整数 `monitorContractVersion=2`、可空 `runtimeGeneration` 和 `observedAt`。总览和股票集合快照还保留权威已提交 `sequence`；分页保持不变。健康响应包含 `runtimeStatus` 以及既有资源/明细字段 `startedAt`、`stoppedAt`、`lastCompletedMinute`、`lastCompletedMinuteAgeSeconds`、`latestEvaluationAt`、`latestEvaluationAgeSeconds`、`gaps`、`cooldownUntil`、`providers`、`executor`、`database`、`delivery`。旧根字段 `status`、`readOnly`、`nextPollAt`、`nextRetryAt` 被 `runtimeStatus` 替换；资源明细校验及非敏感边界继续有效。无所有者时生命周期时间为 null；已知所有者的停止时间继续满足顺序约束。根聚合分钟/求值年龄仅供诊断，不能授予逐计划新鲜度。

总览根字段精确为 `monitorContractVersion`、`sequence`、`runtimeGeneration`、`observedAt`、`runtimeStatus`、`counts`、`symbols`、`marketIndexes`、`marketTurnover`。移除旧的聚合 `connectionStatus` 业务存活捷径；传输连接状态由浏览器管理。保留既有指数/成交额结构与六个计数字段名。`symbols` 最多包含 10 个唯一活动计划条目，包括等待首个结果的计划。空数据库/无活动计划返回 HTTP `200`、空 `symbols`、零计数及诚实的 `runtimeStatus`；单个结果缺失绝不能使整个总览替换为 `UNAVAILABLE`。真实读取/校验失败仍安全失败。

每个活动计划条目是封闭联合，公共字段为 `symbol`、`name`、`planFamily`、`planVersionId`、`planHash`、`activationRevision`、`observedAt`、`availability`、`scope`、`currentActionable`。`scope` 必须与 `runtimeStatus.scopes` 中的 PLAN 范围精确匹配。

- `availability=UNAVAILABLE`：额外包含 `projectionState=WAITING|RECOVERING|BLOCKED`（与范围状态一致）和 `reasonCode`；不得包含 `decision`、`explicitRuntime`、结果哈希、捏造的信号、价格或补零证据。若输入就绪但首个求值尚未提交，使用 `projectionState=WAITING`/`reasonCode=AWAITING_FIRST_EVALUATION`，而范围可以为 `READY`。`currentActionable=false`。
- `availability=CURRENT|CACHED`、`planFamily=LEGACY_LOW_BUY`：额外包含既有已校验 `AuthoritativeDecisionView` 类型的 `decision`，以及既有 `riskDistanceFen`、`satisfiedConditionCount`、`totalConditionCount`、`referenceMarket`。按精确计划/启用身份读取旧结果仓库，不覆盖其不可变 `dataHealth` 伪装恢复成功。
- `availability=CURRENT|CACHED`、`planFamily=EXPLICIT_RULES`：额外包含既有 `ExplicitPlanRuntimeView` 类型的 `explicitRuntime`，要求 `status=CURRENT`、精确计划/启用身份及已持久化 `ruleOutcomes`，另有外层 `resultHash`、`ruleEligibility` 和 `actionableRuleIds`；不得包含旧 `decision`、zone/episode 或旧计数。按精确活动计划哈希及启用修订读取 `ExplicitDecisionRepository.latest(...)`，使用规则结果前验证每个 `ExplicitEvaluationResult`。不得用旧加载器或合成单信号代替多条显式规则。

`ruleEligibility` 按相同顺序为每条展示的显式规则提供且仅提供一个条目，最多 3 条。每条精确包含 `ruleId`、`action`、`currentActionable`、`reasonCode`；规则 ID/action 必须与该规则持久结果匹配。外层 `resultHash` 是未改变的 `ExplicitEvaluationResult.result_hash`；结果、`explicitRuntime`、活动身份及当前 generation 验证必须一致。`actionableRuleIds` 是资格为 true 的有序无重复子集；行级 `currentActionable` 等于此子集是否非空。规则为 true 时要求 `reasonCode=null`；为 false 时要求固定展示原因：`NO_CURRENT_SIGNAL`、`INTRADAY_EXPIRED`、`RECOVERY_HOLD`、`RISK_NO_LONGER_VALID`、`CURRENT_STATE_UNVERIFIED` 或 `CACHED_RESULT`。这些原因概括既有 D5 检查，不创建新信号或投递政策。未知/矛盾原因、未知 ID、action 不匹配或子集不一致都安全失败。不可用显式条目没有结果/资格字段；缓存显式条目的子集为空，且全部规则为 false、原因 `CACHED_RESULT`。

逐规则资格是不可变 `ruleOutcomes` 与结果哈希之外的当前后端投影，根据按信号区分的有效性及适用已提交状态/意图派生。例如，过期 BUY 与仍有效 `RISK_ALERT` 可以共存：只有风险规则出现在 `actionableRuleIds`，即使行级布尔值为 true。组件使用明确子集，不得把行布尔值应用于每条规则。恢复屏障可暂缓风险规则而不使其过期；后来已解除的风险继续为 false。渲染器不得仅从条件满足推断资格，也不能修改持久结果来迎合当前资格。

`CURRENT` 要求当前安装的 generation、活动身份及适用目标与已提交结果匹配；它本身不代表存在 BUY/SELL 信号。`CACHED` 是身份有效的历史投影，显示原始截止与求值日期，且始终 `currentActionable=false`。前次启用或其他计划哈希不能填入当前活动计划条目；该结果仅能通过历史读取获得。`currentActionable` 由后端负责，要求 `CURRENT`，并应用既有按信号区分的 D5 有效性/屏障检查。不得从 `mode`、socket 状态、`readOnly` 或新的统一 90 秒规则推导它；风险状态例外继续有效。状态读取不得变更结果或发送提醒。

对仍有效的历史风险通知，`CURRENT` 投影要求当前 generation 下最新风险状态及已完成逐计划恢复屏障的权威证据。原风险结果/哈希/日期保持不变；该证据不能重新认证历史行情为新鲜，也不创建新求值/意图。仅加载历史结果仍为 `CACHED`。待机期间因为没有新求值到期而 `PLAN.readOnly=true`，本身不使另有证据证明有效的风险通知失效。

`GET /symbols` 使用相同联合及既有分页。`GET /symbols/{symbol}` 返回相同计划鉴别字段和投影可用性，以及适用的既有详情数据；已知但未启用的股票返回类型化 `NO_ACTIVE_PLAN` 缺失。`GET /health/symbols/{symbol}` 即使尚无首个判断，也公开精确 PLAN 范围。`GET /explicit-plan-runtime/{symbol}` 使用相同显式投影权威与状态信封，不建立另一套就绪来源。合法但未知的股票保留 `NOT_FOUND`。

六个总览计数继续是后端展示计数，不是互斥分组或权限门禁。既有旧计划分类保留业务含义；显式结果不获得旧低吸区分类。`actionable` 统计 `currentActionable=true` 的唯一条目；不可用条目仅在范围被阻断时计入 `blocked`，绝不能用捏造证据计入 actionable/normal/risk。精确结果身份、安全序号和快照数据必须一致捕获；组装期间所有者变化应重试/失败，而不是混合 generation。消费者拒绝无效兄弟条目，不猜测健康回退；正常投影缺失使用声明的联合，而不是畸形数据。

## RS07 WebSocket 与传输/进展区分

仅在验证 v2 总览快照后连接：`/ws/v1/monitor?after=<sequence>&monitorContractVersion=2`。两个查询参数都必须恰好出现一次；版本同样遵循规范 `2` 语法。在读取/回放事件之前验证 Origin、版本和游标。缺失/错误版本只接受连接以返回关闭码 `1008`、原因 `MONITOR_CONTRACT_MISMATCH`，不得发送任何数据帧；畸形游标仍为 `1008`。缺少注入服务仍为 `1013`；不可信/不安全持久序号仍为 `1011`。不提供旧版本回退事件流。

已提交事件信封与 payload 保持逐字节 `schemaVersion=1`；不向持久事件添加 `monitorContractVersion`。`monitor_sequence` 仍是唯一单调高水位域，保留既有回放窗口、页上限、范围校验与快照失效行为。不需要新增已提交事件类型。

v2 心跳精确字段为 `type`、`monitorContractVersion`、`sequence`、`runtimeGeneration`、`observedAt`、`runtimeStatus`。`type=heartbeat`、整数版本 `2`，`runtimeStatus` 使用 RS03 封闭结构。移除旧 `runtimeLive` 和 `runtimeStartedAt`；恢复/待机时 generation 仍存在。此帧是当前状态观察，不是判断快照，也不是持久事件。`sequence` 是该 socket 已送达的服务端回放游标；状态读取不能推进它。

v2 恢复帧精确为 `{type:"snapshot.required", monitorContractVersion:2, sequence:<安全整数>, reason:"REPLAY_UNAVAILABLE"}`，之后正常关闭并恢复权威快照。兼容状态帧也不能修补事件缺口或代替总览快照。

保留 20 秒心跳、20 秒快照/连接期限、40 秒静默检测及既有封顶抖动重连。已接受、有序、结构正确且匹配已应用 generation/游标的心跳，即使模式为 `BLOCKED`、`DEGRADED`、`RECOVERING` 或 `STANDBY`，也可以刷新传输静默计时；但不能刷新 `lastProgressAt`、清除 `STALLED`、恢复陈旧操作或升级缓存判断。重复/过期观察不重置传输静默。同一已接受观察流内 `observedAt` 不下降；相同观察视为重复。时钟回拨先触发权威快照恢复，再接受新的时间基线，不由浏览器计算数据新鲜度。

generation 变化、事件缺口、畸形兼容帧或 `snapshot.required` 会撤销当前可操作展示，然后合并为一次总览刷新，再用精确游标重新连接。generation/游标相同的模式/进展变化就地更新权威状态，不重连也不改变判断 payload。generation 身份、协调器进展或所需状态就绪丧失时，使受影响的当前展示失效并合并触发权威投影刷新；恢复必须依赖该投影及适用 D5 检查。仅因没有到期求值而变化的 `readOnly` 不能实现新的风险通知过期规则。当前信号有效性可能改变时，状态观察合并触发投影刷新；Vue 不从时间戳或范围计数重新计算信号有效性。普通 `system.health.updated` 仍是失效提示。协议不匹配进入终止性 `RELOAD_REQUIRED`，不进入此重连循环。

## RS08 线上消息示例与拒绝案例

有效的新请求与协商响应头：

```http
GET /api/v1/health HTTP/1.1
X-Monitor-Contract-Version: 2
Accept: application/json

HTTP/1.1 200 OK
X-Monitor-Contract-Version: 2
Cache-Control: no-store
```

有效完整心跳：午间协调器存活，未错误声称有恢复工作。本示例没有所需计划/指数范围。

```json
{
  "type": "heartbeat",
  "monitorContractVersion": 2,
  "sequence": 42,
  "runtimeGeneration": "b2f55d82-8d98-4c5e-a3bc-18529f84e982",
  "observedAt": "2026-09-21T12:00:00.000000+08:00",
  "runtimeStatus": {
    "lifecycle": "RUNNING",
    "mode": "STANDBY",
    "reasonCode": "NO_ACTIVE_PLANS",
    "nextWakeAt": "2026-09-21T12:00:20.000000+08:00",
    "nextRetryAt": null,
    "lastProgressAt": "2026-09-21T11:59:50.000000+08:00",
    "coordinator": {
      "state": "SCHEDULED",
      "progressDueAt": "2026-09-21T12:00:20.000000+08:00"
    },
    "scopes": []
  }
}
```

显式计划缺少覆盖的有效完整 PLAN 范围；它可与 `READY` 的旧计划兄弟条目共存于一个总览中。这是范围对象，不是完整总览或捏造结果。

```json
{
  "scopeKey": "plan:003043.SZ:7",
  "kind": "PLAN",
  "status": "RECOVERING",
  "reasonCode": "COVERAGE_INCOMPLETE",
  "requiredTarget": {
    "kind": "INTRADAY",
    "targetEnd": "2026-09-21T10:05:00.000000+08:00"
  },
  "dataCutoff": "2026-09-21T10:03:00.000000+08:00",
  "nextRetryAt": "2026-09-21T10:05:30.000000+08:00",
  "progress": {"requiredCount": 5, "completedCount": 3},
  "symbol": "003043.SZ",
  "planFamily": "EXPLICIT_RULES",
  "planVersionId": "41699c9c-8c65-4ab8-9740-20efdd45e3d9",
  "planHash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "activationRevision": 7,
  "readOnly": true
}
```

旧客户端不带版本的 `GET /api/v1/dashboard` 被拒绝；受保护 POST 在执行命令前获得完全相同的协商结果：

```json
{
  "error": {
    "code": "CONFLICT",
    "message": "Request conflicts with current state",
    "details": [{
      "location": ["header", "X-Monitor-Contract-Version"],
      "code": "MONITOR_CONTRACT_MISMATCH",
      "message": "Reload the application to use monitor contract 2"
    }],
    "requestId": "aabbccddeeff00112233445566778899"
  }
}
```

同一身份有效显式结果中两条展示规则的有效资格子对象：BUY 已在其源截止 + 90 秒后过期，而当前已提交风险状态及完成的恢复屏障仍证明风险通知有效。此示例展示外层资格字段，不是完整计划条目；引用的规则 ID/action 还必须出现在其 `explicitRuntime.ruleOutcomes` 中。

```json
{
  "currentActionable": true,
  "ruleEligibility": [
    {"ruleId": "buy-entry", "action": "BUY", "currentActionable": false, "reasonCode": "INTRADAY_EXPIRED"},
    {"ruleId": "risk-watch", "action": "RISK_ALERT", "currentActionable": true, "reasonCode": null}
  ],
  "actionableRuleIds": ["risk-watch"]
}
```

有效兼容 socket：`/ws/v1/monitor?after=42&monitorContractVersion=2`。旧 socket `/ws/v1/monitor?after=42`，以及无效版本 `monitorContractVersion=02` 或重复 `monitorContractVersion=2&monitorContractVersion=2`，必须在任何回放/心跳之前以 `1008` 和 `MONITOR_CONTRACT_MISMATCH` 关闭。新客户端收到没有版本的旧五字段心跳时拒绝并要求刷新；不得将 `runtimeLive=true` 当作 v2 协商成功。

| 无效示例或对上述有效示例的修改 | 必需结果 |
|---|---|
| 心跳 `monitorContractVersion: "2"` 或缺少版本 | 拒绝；不得升级为实时/可操作。缺失/不支持的协议要求刷新。 |
| 心跳增加根 `readOnly:false` 或 `runtimeLive:true` | 拒绝不符合封闭 v2 结构的数据，不作可选兼容解释。 |
| `coordinator.state=STALLED` 但 `mode=MONITORING` | 拒绝矛盾状态；socket 持续发送也不能恢复操作。 |
| 恢复中 PLAN 范围仅把 `readOnly` 改为 false | 拒绝；不完整覆盖不能授权求值。 |
| `completedCount=6` 而 `requiredCount=5` | 拒绝不可能的进展。 |
| 显式条目含 `decision`，或旧条目含 `explicitRuntime` | 拒绝计划类型不匹配，不运行回退加载器。 |
| 不可用条目 `currentActionable=true`，或缓存条目收到心跳后变可操作 | 拒绝；必须有权威且身份匹配的当前投影及 D5 有效性。 |
| 资格示例把 `buy-entry` 加入 `actionableRuleIds`，或将 true 的行标志应用于该 BUY | 拒绝；逐规则资格和子集必须一致。 |
| 新命令页面尚未验证任何 v2 健康/总览预检就提交 POST | 客户端违反契约；绝不能向未协商的旧后端发送 POST。 |
| 待机具有旧展示截止且 `readOnly=true` | 义务完整时有效；不能仅因年龄展示陈旧恢复横幅。 |

## RS09 UI、验收与发布

使用现有 `/` 和 `/system` 页面，分别展示传输断开/重连与后端模式。待机不显示陈旧数据恢复警告；恢复展示目标/进展；失败范围展示固定原因及重试/重新核对时间或所需操作。保留可见的缓存截止和历史风险日期。不增加立即重试按钮、令牌页面、登录、静默提供方认证刷新或客户端交易计算。

| 验收 | 关闭对应门禁前必需的离线证据 |
|---|---|
| A06 / RR016 | 两类计划共存；等待/阻断计划不隐藏健康兄弟；不受支持的可选指数不阻断无关工作；显式结果来自其专属仓库。 |
| A11 / RR015、RR018–RR019 | 协调器逾期时正常心跳不能证明进展；待机保持诚实；generation 在降级/待机状态保留。 |
| A12 / RR017–RR018 | 新旧客户端/服务端矩阵、直接进入命令页面连接旧服务端且 POST 调用为零、重复/缺失版本及游标、安全不匹配错误、缺少投影、序号缺口、generation 替换、时钟回拨及缓存资源刷新。 |
| D5 / RR016、RR018 | 缓存/首结果/旧启用投影不能仅靠状态变成当前；显式过期 BUY/当前风险混合、风险状态例外及恢复屏障在展示层保持。 |

RR015–RR019 必须分有界批次更新后端模型/保护、OpenAPI、生成类型、严格运行时解析器、共用受保护命令适配器、监控 store/stream 和 UI。通过生成器更新产物，禁止手改生成类型。受保护路由不增加 REST 路径。后端与带哈希前端资源作为同一本地版本发布，HTML 入口不得陈旧，不得存在混合版本默认路径。RR020 仅在 C0–C4 前置条件满足后启用替代路径；真实迁移、真实提供方验收及部署继续单独授权。

审核须在 RR017 实施前确定精确协商/请求头保护清单、状态联合、范围 `readOnly`、计划类型投影及全部消息示例。本稿记录供审核的具体选择，本身不关闭 RR002 或任何检查点。
