# 规格：runtime-status

> RR002 契约已于 2026-09-27 通过第四步隔离实施评审，源自已批准提案 D7，并受 D1–D6 约束。Astra 设计与独立 Sol 评审已批准完整契约；这不关闭 C0/C4，也不启用生产默认路径。英文正本为 `SPEC-runtime-status.md`，本文件为中文审核副本。
> 2026-09-30 正常入口集成：`create_production_app` 与正常安装构建现选择版本 `2`；`create_app` 和显式 v1 夹具保留版本 `1` 兼容性。生命周期在启动前校验实际 v2 读取服务。本次仅启用已批准契约，不改变 RS IDs 或线上字段语义。最终验收见[原第四步报告](../../verification/2026-09-30-runtime-recovery-final-gate.zh-CN.md)；此前明确启用边界保留为历史记录。
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
| 已审核的旧计划维护 | `POST /system/legacy-plan-invalidation`；其只读 GET 预览保留既有契约 |

2026-09-27 评审：经 Astra 设计和独立 Sol 评审，完整 RS01–RS09 契约已冻结，可在第四步隔离环境实施。旧计划维护 POST 改变活动身份，因此必须使用同一版本保护。保护在阻断写入/业务校验和服务调用之前执行，同时保留既有 Origin 与请求体大小安全边界。RR002 已通过评审；接通实现与 C4 验收仍是独立门禁。

第四步使用显式应用级 `monitor_contract_version=2` 注入，默认值为 `1`。每个应用实例仅提供一种监控协议，v2 实例要求注入权威状态/读取服务。其 `runtime-status-preview` 前端构建为独立 `dist-runtime-status` 资源，绝不复制到已安装 Python `web/dist`。资源 manifest 声明固定监控版本；应用组装拒绝不兼容资源。没有清单的既有资源只可由旧 v1 路径接受；v2 必须提供清单。默认应用/构建路径在 RR020 前保持 v1。此临时实施隔离不是公开的双版本 API，也不是生产发布。前置门禁通过后，由 RR020 负责默认切换及移除临时 v1 兼容接线。

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

进展具有独立的所有者控制观测，通过 `runtime/progress.py` 之类的小型跟踪器实现，并注入独立于墙钟 `Clock` 接口的单调时钟 callable。开始有界步骤时捕获所有者 token 并安装真实期限，不改变 `lastProgressAt`。只有同一个仍有效 token 在完成本地事实协调或有界工作单元的校验/持久化后，才能更新 `lastProgressAt` 并安装下一次唤醒。被替代/取消的 token 不能更新进展。多计划或多请求回调必须报告真实完成单元；30 秒不是为整个批次捏造的期限。排队/准入等待或重试等待通过间隔最多 30 秒的真实本地核对处理，不因此新增提供方请求。禁止用独立计时器在拥有的工作卡住时不断触碰跟踪器。

已有 `WORKING` token 时禁止重复开始；安装另一个步骤或调度不能清除 `STALLED`。迟到的已调度唤醒可以开始真实恢复工作，但停滞保持锁存，直到该所有者真实完成工作，或按既有规则替换所有者。若需要子步骤，须先完成前一步，再安装下一步。停止请求维持 `STOPPING`，直到已拥有的物理工作排空且生命周期清理完成，才能报告 `STOPPED`。跟踪器更新和快照使用同一个串行所有者上下文或原子不可变记录。启动获准后必须开始有真实期限的有界拥有步骤，不能无期限地停留在 `STARTING`。

生命周期在启动、调度器/本地维护重新核对、有界工作完成、降级重试维护及停止处提供这些 hook。D8 的持久 `last_alive_at` 写入器保持独立：合法进程所有者可以仍存活，而协调器已经停滞。REST 读取、WebSocket 帧、单独的提供方成功观测及旧 `next_poll_at` 都不能创建进展证据。进展权威缺失或无法读取时返回脱敏 `SERVICE_UNAVAILABLE`，不能改写为健康所有者或已知无所有者。只有权威证明不存在所有者时，才允许 `runtimeGeneration=null` 和停止状态。

时钟回拨不能延长单调期限或改写内部真实进展记录。`nextWakeAt`/`progressDueAt` 按冻结的单调目标重投影：当前墙钟加目标单调值与当前单调值之差；保留负差，以显示逾期。若旧真实 `lastProgressAt` 晚于当前 `observedAt`，仅公开值为 null，表示旧墙钟基准暂不可表示；内部原记录不改。若墙钟后来使旧记录可表示，再次显示它只是公开历史，不是新进展事件。只有真实完成才能记录新进展。不能令时间戳等于当前读取时间或清除 `STALLED`。若持久范围截止或结果仍晚于 `observedAt`，完整投影返回脱敏 `SERVICE_UNAVAILABLE`，直到可信事实允许合法快照；不能重写历史来恢复 200，也不进入协议 `RELOAD_REQUIRED`。

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

就绪权威来自真实生命周期及生产管线的冻结观测，不是另一套求值器。在所有者事件循环捕获所有者/generation/配置权威及单调进展；在同一个 SQLite 读取快照中读取活动身份、所需持久覆盖、参考/日历事实、适用的待收盘/状态义务及已提交结果。既有 `recovery_targets.py` 目标/覆盖工具、生产管线捕获的依赖要求与恢复调度、指数恢复状态及历史收盘读取器提供事实。`RecoverySchedule.READY`、一次成功提供方调用、完整分钟片段或旧结果都不能单独认证整个 PLAN 范围。未知义务集合报告 null/null 计数，绝不能令 `readOnly=false`。适用目标必须是真实求值目标，不能使用任意最新采集分钟。

公开窄而不可变的所有者/管线观测 hook，不在工作线程读取可变私有字段。组装投影后重新检查所有者/权威 token 和活动身份；所有者/配置/启用变化必须丢弃混合读取。最多允许一次全新组装重试，之后返回脱敏 `SERVICE_UNAVAILABLE`。读取不重新同步恢复队列、不请求提供方、不安装配置、不修改投递 receipt。观测器必须对每个公开范围持有证据；正常缺少结果使用 RS06 不可用联合，而损坏的持久记录仍为校验/存储失败。

提供方范围使用真实操作身份，包括相互独立的 `provider:idx_mins` 与 `provider:rt_idx_min_daily`；旧合并权限阻断使两者都显示受阻，直到各自独立证明成功。不能从另一端点推导权限。只有安装配置实际需要的依赖或展示工作进入聚合判断。未使用/未验证操作可以留在资源诊断中，不能阻断无关计划。范围 key 不含端点 URL 或凭证。既有 32 个范围上限必须容纳全部活动计划；溢出时明确失败，不能静默丢弃范围。

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
| 范围阻断 | `CREDENTIAL_MISSING`、`PERMISSION_DENIED`、`SEMANTICS_INCOMPATIBLE`、`CONFIGURATION_INVALID`、`HISTORY_UNAVAILABLE`、`STATE_UNAVAILABLE`、`GENERATION_CHANGED`、`NEEDS_RESTART`、`LEGACY_PLANS_REQUIRE_REVIEW` |
| 聚合混合 | `SCOPED_DEPENDENCY_FAILURE` |

后端把这些代码映射为有界界面文案；原始提供方/存储异常和密钥没有可输出字段。`SCOPED_DEPENDENCY_FAILURE` 仅用于聚合，范围必须保留实际原因。提供方失败保留 D4 重试所有权：瞬态退避 30/60/120/300 秒、共享冷却至少 300 秒、每个操作的权限复查每 300 秒至多一次。缺失凭证不能发送提供方请求；本地维护检查已安装配置，并将漂移标为 `NEEDS_RESTART`，绝不重新加载或安装新编辑的凭证。可空重试时间不能成为不解释失败的借口：界面必须显示已安排重试/本地核对，或固定的所需操作说明。

## RS06 REST 投影与部分可用

所有变更的监控响应包含整数 `monitorContractVersion=2`、可空 `runtimeGeneration` 和 `observedAt`。总览和股票集合快照还保留权威已提交 `sequence`；分页保持不变。健康响应包含 `runtimeStatus` 以及既有资源/明细字段 `startedAt`、`stoppedAt`、`lastCompletedMinute`、`lastCompletedMinuteAgeSeconds`、`latestEvaluationAt`、`latestEvaluationAgeSeconds`、`gaps`、`cooldownUntil`、`providers`、`executor`、`database`、`delivery`。旧根字段 `status`、`readOnly`、`nextPollAt`、`nextRetryAt` 被 `runtimeStatus` 替换；资源明细校验及非敏感边界继续有效。无所有者时生命周期时间为 null；已知所有者的停止时间继续满足顺序约束。根聚合分钟/求值年龄仅供诊断，不能授予逐计划新鲜度。

总览根字段精确为 `monitorContractVersion`、`sequence`、`runtimeGeneration`、`observedAt`、`runtimeStatus`、`counts`、`symbols`、`marketIndexes`、`marketTurnover`。移除旧的聚合 `connectionStatus` 业务存活捷径；传输连接状态由浏览器管理。保留既有指数/成交额结构与六个计数字段名。`symbols` 最多包含 10 个唯一活动计划条目，包括等待首个结果的计划。空数据库/无活动计划返回 HTTP `200`、空 `symbols`、零计数及诚实的 `runtimeStatus`；单个结果缺失绝不能使整个总览替换为 `UNAVAILABLE`。真实读取/校验失败仍安全失败。

每个活动计划条目是封闭联合，公共字段为 `symbol`、`name`、`planFamily`、`planVersionId`、`planHash`、`activationRevision`、`observedAt`、`availability`、`scope`、`currentActionable`。`scope` 必须与 `runtimeStatus.scopes` 中的 PLAN 范围精确匹配。

- `availability=UNAVAILABLE`：额外包含 `projectionState=WAITING|RECOVERING|BLOCKED`（与范围状态一致）和 `reasonCode`；不得包含 `decision`、`explicitRuntime`、结果哈希、捏造的信号、价格或补零证据。若输入就绪但首个求值尚未提交，使用 `projectionState=WAITING`/`reasonCode=AWAITING_FIRST_EVALUATION`，而范围可以为 `READY`。`currentActionable=false`。
- `availability=CURRENT|CACHED`、`planFamily=LEGACY_LOW_BUY`：额外包含既有已校验 `AuthoritativeDecisionView` 类型的 `decision`，以及既有 `riskDistanceFen`、`satisfiedConditionCount`、`totalConditionCount`、`referenceMarket` 和必需可空的 `actionableUntil`。按精确计划/启用身份读取旧结果仓库，不覆盖其不可变 `dataHealth` 伪装恢复成功。
- `availability=CURRENT|CACHED`、`planFamily=EXPLICIT_RULES`：额外包含既有 `ExplicitPlanRuntimeView` 类型的 `explicitRuntime`，要求 `status=CURRENT`、精确计划/启用身份及已持久化 `ruleOutcomes`，另有外层 `resultHash`、`ruleEligibility` 和 `actionableRuleIds`；不得包含旧 `decision`、zone/episode 或旧计数。按精确活动计划哈希及启用修订读取 `ExplicitDecisionRepository.latest(...)`，使用规则结果前验证每个 `ExplicitEvaluationResult`。不得用旧加载器或合成单信号代替多条显式规则。

`ruleEligibility` 按相同顺序为每条展示的显式规则提供且仅提供一个条目，最多 3 条。每条精确包含 `ruleId`、`action`、`currentActionable`、`reasonCode`、`actionableUntil`、`sourceAlert`；规则 ID/action 必须与该规则持久结果匹配。外层 `resultHash` 是未改变的最新 `ExplicitEvaluationResult.result_hash`；结果、`explicitRuntime`、活动身份及当前 generation 验证必须一致。`actionableRuleIds` 是资格为 true 的有序无重复子集；行级 `currentActionable` 等于此子集是否非空。显式行没有行级 `actionableUntil`：一条规则到期不能使另一条规则到期。规则为 true 时要求 `reasonCode=null`；为 false 时要求固定展示原因：`NO_CURRENT_SIGNAL`、`INTRADAY_EXPIRED`、`RECOVERY_HOLD`、`RISK_NO_LONGER_VALID`、`CURRENT_STATE_UNVERIFIED` 或 `CACHED_RESULT`。这些原因概括既有 D5 检查，不创建新信号或投递政策。未知/矛盾原因、未知 ID、action 不匹配或子集不一致都安全失败。不可用显式条目没有结果/资格字段；缓存显式条目的子集为空，且全部规则为 false、原因 `CACHED_RESULT`。

`actionableUntil` 投影既有投递分类，不创建新到期规则。资格为 true 的 `INTRADAY_ACTIONABLE` 提醒使用已校验的既有 `expires_at`，必须严格晚于快照 `observedAt`；相等即过期。资格为 true 的 `STATE_RISK` 提醒为 null，表示有效性仍依赖当前已提交状态及恢复屏障。尤其旧计划 `RISK_EXIT_READY`、`RISK_EXIT_PENDING_SETTLEMENT` 属于状态风险提醒，不能因名称与卖出有关而另套 90 秒分类。所有 false 资格及缓存旧计划行的 `actionableUntil` 为 null。不可用行不包含结果专属的期限字段。所需到期元数据缺失/无效时不能产生 true 资格。

`sourceAlert` 为 null 或精确 `{eventId, resultHash, evaluatedAt, dataCutoff}`。`eventId` 沿用既有 UUID 格式，不新增 UUIDv4 限制；`resultHash` 是规范 SHA-256 哈希，两项时间为规范上海时间并满足 `dataCutoff <= evaluatedAt <= observedAt`。所有 true 显式资格都要求来源非空。后端必须用原始 payload 身份，证明已持久源事件及原结果与活动计划/启用、规则 ID/action 和不可变信号意图匹配。false/缓存条目可以保留已证明来源用于解释。不能从满足条件合成来源。若风险首次在 R1 发出，而最新结果 R2 报告 `ONCE_ALREADY_EMITTED`，外层结果/`explicitRuntime` 描述 R2，`sourceAlert` 保留 R1 的哈希与日期。界面分别标明当前证据与原提醒日期。

逐规则资格是不可变 `ruleOutcomes` 与结果哈希之外的当前后端投影，根据按信号区分的有效性及适用已提交状态/意图派生。例如，过期 BUY 与仍有效 `RISK_ALERT` 可以共存：只有风险规则出现在 `actionableRuleIds`，即使行级布尔值为 true。组件使用明确子集，不得把行布尔值应用于每条规则。恢复屏障可暂缓风险规则而不使其过期；后来已解除的风险继续为 false。渲染器不得仅从条件满足推断资格，也不能修改持久结果来迎合当前资格。

`CURRENT` 要求当前安装的 generation、活动身份及适用目标与已提交结果匹配；它本身不代表存在 BUY/SELL 信号。`CACHED` 是身份有效的历史投影，显示原始截止与求值日期，且始终 `currentActionable=false`。前次启用或其他计划哈希不能填入当前活动计划条目；该结果仅能通过历史读取获得。`currentActionable` 由后端负责，要求 `CURRENT`，并应用既有按信号区分的 D5 有效性/屏障检查。不得从 `mode`、socket 状态、`readOnly` 或新的统一 90 秒规则推导它；风险状态例外继续有效。状态读取不得变更结果或发送提醒。

对仍有效的历史风险通知，`CURRENT` 投影要求当前 generation 下最新风险状态及已完成逐计划恢复屏障的权威证据。原风险结果/哈希/日期保持不变；该证据不能重新认证历史行情为新鲜，也不创建新求值/意图。仅加载历史结果仍为 `CACHED`。待机期间因为没有新求值到期而 `PLAN.readOnly=true`，本身不使另有证据证明有效的风险通知失效。

其余 v2 读取根对象为封闭结构，精确字段如下。此处 `statusEnvelope` 指四个必需根字段 `monitorContractVersion`、`runtimeGeneration`、`observedAt`、`runtimeStatus`；这是文档记号，不是嵌套 JSON 字段。`snapshotEnvelope` 指这四个字段加安全的已提交 `sequence`。

| 路由/结果 | 精确根字段与约束 |
|---|---|
| `GET /health` | `statusEnvelope` 加 `startedAt`、`stoppedAt`、`lastCompletedMinute`、`lastCompletedMinuteAgeSeconds`、`latestEvaluationAt`、`latestEvaluationAgeSeconds`、`gaps`、`cooldownUntil`、`providers`、`executor`、`database`、`delivery`。全部字段必需。旧 `status`、`readOnly`、`blockReason`、`degradedReason`、`nextPollAt`、`nextRetryAt`、`recoveryIssues` 不存在；适用原因进入 `runtimeStatus`/范围。 |
| `GET /symbols` | `snapshotEnvelope` 加 `items`、`offset`、`limit`、`total`。`items` 使用相同计划条目联合；保留既有分页边界/排序。空/无活动计划是 `total=0` 的普通空页，不是不可用集合。 |
| `GET /symbols/{symbol}`，活动 | `snapshotEnvelope` 加 `summary`、`legacyDetails`。`summary` 是精确计划条目联合，包括首结果不可用条目。显式或不可用条目的 `legacyDetails` 为 null。旧计划当前/缓存条目则精确为 `{positionLots, referenceMarket, indexConditionEvidence}`，沿用既有详情类型，以及与该 summary 不可变判断对应的身份/数量/证据一致性规则。 |
| `GET /symbols/{symbol}`，已知未启用 | `snapshotEnvelope` 加 `symbol`、`availability:"UNAVAILABLE"`、`reasonCode:"NO_ACTIVE_PLAN"`；不含 summary、结果、范围或捏造的计划身份。 |
| `GET /health/symbols/{symbol}`，活动 | `statusEnvelope` 加 `scope`；它与 `runtimeStatus.scopes` 中匹配的 PLAN 范围精确一致，包括首个结果之前。未启用/未知股票返回 `NOT_FOUND`。 |
| `GET /explicit-plan-runtime/{symbol}` | 相同活动详情信封（`snapshotEnvelope`、`summary`、`legacyDetails:null`），限于 `EXPLICIT_RULES`；已知未启用股票使用相同 `NO_ACTIVE_PLAN` 信封。活动旧计划或未知股票返回 `NOT_FOUND`。不使用独立就绪来源或旧计划加载器。 |

存在的外层/内层观测、股票、计划哈希/版本、启用修订和范围必须一致。复制到条目的范围，经规范序列化后必须与状态中的匹配范围字节一致。所有快照来自同一个已提交读取观测，不能拼接独立获取的行。历史缓存标签使用原旧计划 `decision.marketDataAt`/`evaluatedAt` 或显式 `targetBucketEnd`/`evaluatedAt`；更晚的范围 `dataCutoff` 不能替代这些时间。

资格读取复用纯当前状态事实读取器和 `classify_explicit_risk_delivery`/`classify_legacy_risk_delivery`，以及既有盘中身份/修订/到期检查。GET 或心跳不能调用 `CurrentDeliveryAdmission.__call__` 或仓库初始化/分类/到期写入器；这些路径可能修改 receipt。已存储 eligible receipt 本身不是新的权威。显式来源须通过加载精确原结果并重建匹配的不可变提醒 payload 来证明，不能未经规则/启用身份核对就选择某股票最新事件。

六个总览计数继续是后端展示计数，不是互斥分组或权限门禁。既有旧计划分类保留业务含义；显式结果不获得旧低吸区分类。`actionable` 统计 `currentActionable=true` 的唯一条目；不可用条目仅在范围被阻断时计入 `blocked`，绝不能用捏造证据计入 actionable/normal/risk。精确结果身份、安全序号和快照数据必须一致捕获；组装期间所有者变化应重试/失败，而不是混合 generation。消费者拒绝无效兄弟条目，不猜测健康回退；正常投影缺失使用声明的联合，而不是畸形数据。

每个活动条目在每个类别内最多计数一次，每项计数在零与活动条目数之间。类别可以重叠：受阻缓存行同时计入 `stale` 和 `blocked`；当前已证明的旧计划状态风险结果可以保留陈旧行情，而风险指示本身并未过期。精确判据为：

| 计数 | 判据 |
|---|---|
| `actionable` | 任一计划类型的 `currentActionable=true`。 |
| `blocked` | PLAN 范围为 `BLOCKED`，或 `CURRENT` 旧计划判断的 `dataHealth.status` 等于 `BLOCKED` 或 `GAPPED`。显式条件未满足本身不构成依赖阻断。 |
| `stale` | `availability=CACHED`；或 `CURRENT` 旧计划判断的数据健康不属于 `LIVE`、`BLOCKED` 或 `GAPPED`；或 `CURRENT` 显式条目至少有一项 `INTRADAY_EXPIRED` 资格。这是展示类别，不宣称存在恢复工作。 |
| `risk` | `CURRENT` 旧计划结果具有已证明的非 `CLEAR` 风险状态；或 `CURRENT` 显式条目具有 true `RISK_ALERT` 资格。缓存结果及仅满足的历史风险条件不计入。 |
| `lowZoneWatch` | 仅限 `CURRENT` 旧计划条目，且 PLAN 范围为 `READY`、判断数据健康为 `LIVE`、信号为 `LOW_ZONE_WATCH`。 |
| `normal` | PLAN 范围为 `READY` 的 `CURRENT` 条目，无 true 当前资格，且不满足上述 blocked/stale/risk/low-zone 判据。此外，旧计划数据健康必须为 `LIVE`，信号不能属于既有 `ActionableSignalType`；显式资格原因必须全部为 `NO_CURRENT_SIGNAL`。已过期、暂缓或未验证显式规则不能构成正常状态。 |

`UNAVAILABLE` 只通过范围受阻判据计数；`CACHED` 只计入陈旧以及适用时的范围受阻。这些计数判据绝不改变持久结果、范围、资格或求值器分类。

## RS07 WebSocket 与传输/进展区分

仅在验证 v2 总览快照后连接：`/ws/v1/monitor?after=<sequence>&monitorContractVersion=2`。两个查询参数都必须恰好出现一次；版本同样遵循规范 `2` 语法。在读取/回放事件之前验证 Origin、版本和游标。缺失/错误版本只接受连接以返回关闭码 `1008`、原因 `MONITOR_CONTRACT_MISMATCH`，不得发送任何数据帧；畸形游标仍为 `1008`。缺少注入服务仍为 `1013`；不可信/不安全持久序号仍为 `1011`。不提供旧版本回退事件流。

已提交事件信封与 payload 保持逐字节 `schemaVersion=1`；不向持久事件添加 `monitorContractVersion`。`monitor_sequence` 仍是唯一单调高水位域，保留既有回放窗口、页上限、范围校验与快照失效行为。不需要新增已提交事件类型。

v2 心跳精确字段为 `type`、`monitorContractVersion`、`sequence`、`runtimeGeneration`、`observedAt`、`runtimeStatus`。`type=heartbeat`、整数版本 `2`，`runtimeStatus` 使用 RS03 封闭结构。移除旧 `runtimeLive` 和 `runtimeStartedAt`；恢复/待机时 generation 仍存在。此帧是当前状态观察，不是判断快照，也不是持久事件。`sequence` 是该 socket 已送达的服务端回放游标；状态读取不能推进它。

v2 恢复帧精确为 `{type:"snapshot.required", monitorContractVersion:2, sequence:<安全整数>, reason:"REPLAY_UNAVAILABLE"}`，之后正常关闭并恢复权威快照。兼容状态帧也不能修补事件缺口或代替总览快照。

保留 20 秒心跳、20 秒快照/连接期限、40 秒静默检测及既有封顶抖动重连。已接受、有序、结构正确且匹配已应用 generation/游标的心跳，即使模式为 `BLOCKED`、`DEGRADED`、`RECOVERING` 或 `STANDBY`，也可以刷新传输静默计时；但不能刷新 `lastProgressAt`、清除 `STALLED`、恢复陈旧操作或升级缓存判断。重复/过期观察不重置传输静默。同一已接受观察流内 `observedAt` 不下降；相同观察视为重复。时钟回拨先触发权威快照恢复，再接受新的时间基线，不由浏览器计算数据新鲜度。

generation 变化、事件缺口、畸形兼容帧或 `snapshot.required` 会撤销当前可操作展示，然后合并为一次总览刷新，再用精确游标重新连接。generation/游标相同的模式/进展变化就地更新权威状态，不重连也不改变判断 payload。generation 身份、协调器进展或所需状态就绪丧失时，使受影响的当前展示失效并合并触发权威投影刷新；恢复必须依赖该投影及适用 D5 检查。仅因没有到期求值而变化的 `readOnly` 不能实现新的风险通知过期规则。当前信号有效性可能改变时，状态观察合并触发投影刷新；Vue 不从时间戳或范围计数重新计算信号有效性。普通 `system.health.updated` 仍是失效提示。协议不匹配进入终止性 `RELOAD_REQUIRED`，不进入此重连循环。

明确刷新规则为：仍有当前状态风险资格为 true 时，每个已接受的新心跳合并一次权威总览刷新；计划目标、启用、必需状态或就绪变化时，撤销该计划受影响的当前展示并刷新；服务端 `actionableUntil` 到期时，仅撤销对应旧计划条目或显式规则并刷新。因此没有事件或模式变化的纯时间到期也不能无限保留 BUY。没有受影响资格的纯 mode/progress 观测原地更新。仅由展示有效性引起的刷新，在已投递游标仍一致时保留兼容 socket；快照序号/generation 改变则使用既有回放/快照恢复边界。

非空期限的客户端剩余时长应保守地由 `actionableUntil - observedAt` 减去整个单调请求耗时算出，并以接收时的单调时钟为基准。不能信任浏览器墙钟、计算源截止 + 90 秒，或通过心跳延长期限。计时器、渲染/操作检查及唤醒检查只能撤销到期展示；只有新验证的权威快照可以恢复它。不可变后端快照值与此本地失效状态分开保存。迟到刷新仍须满足请求代次、generation、序号及启用防护；不能恢复已替换计划、覆盖更新观测或重新安装已到期计时器。状态风险的 null 期限不是无限期权威，仍受心跳刷新、传输静默及 D5 保护。

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
    {"ruleId": "buy-entry", "action": "BUY", "currentActionable": false, "reasonCode": "INTRADAY_EXPIRED", "actionableUntil": null, "sourceAlert": null},
    {
      "ruleId": "risk-watch",
      "action": "RISK_ALERT",
      "currentActionable": true,
      "reasonCode": null,
      "actionableUntil": null,
      "sourceAlert": {
        "eventId": "af63e4d3-8d42-52d6-a738-cf193d1889c2",
        "resultHash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "evaluatedAt": "2026-09-18T10:05:12.000000+08:00",
        "dataCutoff": "2026-09-18T10:05:00.000000+08:00"
      }
    }
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
| true 盘中资格的 `actionableUntil` 为 null/已过期，或心跳延长其计时器 | 拒绝或撤销该展示；只有新权威快照能恢复资格。 |
| 最新风险结果 R2 未有匹配已提交源意图，就替换 `sourceAlert` 的原 R1 日期/哈希 | 拒绝捏造来源；区分当前证据与原始提醒。 |
| 新命令页面尚未验证任何 v2 健康/总览预检就提交 POST | 客户端违反契约；绝不能向未协商的旧后端发送 POST。 |
| 待机具有旧展示截止且 `readOnly=true` | 义务完整时有效；不能仅因年龄展示陈旧恢复横幅。 |

## RS09 UI、验收与发布

使用现有 `/` 和 `/system` 页面，分别展示传输断开/重连与后端模式。待机不显示陈旧数据恢复警告；恢复展示目标/进展；失败范围展示固定原因及重试/重新核对时间或所需操作。保留可见的缓存截止和历史风险日期。不增加立即重试按钮、令牌页面、登录、静默提供方认证刷新或客户端交易计算。

| 验收 | 关闭对应门禁前必需的离线证据 |
|---|---|
| A06 / RR016 | 两类计划共存；等待/阻断计划不隐藏健康兄弟；不受支持的可选指数不阻断无关工作；显式结果来自其专属仓库。 |
| A11 / RR015、RR018–RR019 | 协调器逾期时正常心跳不能证明进展；待机保持诚实；generation 在降级/待机状态保留。 |
| A12 / RR017–RR018 | 新旧客户端/服务端矩阵、直接进入命令页面连接旧服务端且 POST 调用为零、重复/缺失版本及游标、安全不匹配错误、缺少投影、序号缺口、generation 替换、时钟回拨及缓存资源刷新。 |
| D5 / RR016、RR018 | 缓存/首结果/旧启用投影不能仅靠状态变成当前；显式过期 BUY/当前风险混合、无事件的精确纯时间到期、错误浏览器墙钟、R1 到 R2 重复抑制风险来源、风险状态例外及恢复屏障在展示层保持。 |

RR015–RR019 必须分有界批次更新后端模型/保护、OpenAPI、生成类型、严格运行时解析器、共用受保护命令适配器、监控 store/stream 和 UI。通过生成器更新产物，禁止手改生成类型。受保护路由不增加 REST 路径。后端与带哈希前端资源作为同一本地版本发布，HTML 入口不得陈旧，不得存在混合版本默认路径。RR020 仅在 C0–C4 前置条件满足后启用替代路径；真实迁移、真实提供方验收及部署继续单独授权。

第四步隔离期间，从显式 v2 应用生成 `openapi.runtime-status.json` 和 `web/src/api/generated-runtime-status.ts`；默认 `openapi.json` 与 `web/src/api/generated.ts` 继续绑定 v1。每份产物都有独立生成/检查门禁。预览资源清单为 `monitor-contract.json`，内容精确为 `{"monitorContractVersion":2}`。通过 import 复用既有数值/证据结构，v2 封闭根对象/解析器及预览入口与旧客户端适配器保持独立。运行时解析器不接受 v1/v2 联合。离线浏览器 fixture 必须绑定临时数据库、假 SDK/传输/渠道、可控时钟及真实拥有的运行时/读取/传输边界；仅静态截图或模拟 JSON 不能关闭 C4。提议中的 D9 卖出登记能力与 RR020 完整重启/发布矩阵仍在第四步范围外。

已完成的 RR002 评审确定精确协商/请求头保护清单、状态联合、范围 `readOnly`、计划类型投影及消息示例。实施须满足这些已审核选择；契约评审本身不关闭集成检查点。
