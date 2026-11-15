# 规格：monitor-readiness

状态：已批准实施 — 2026-10-27。属于 [plan-monitor-assurance](SPEC-plan-monitor-assurance.zh-CN.md)，依赖 [source-condition-coverage](SPEC-source-condition-coverage.zh-CN.md)。[英文规范版](SPEC-monitor-readiness.md)。

## MRD-S01 — 目标与权威边界

解释准确计划当前是否能得到其自身规则承诺的监控。复用monitor contract2、当前运行所有权／读取／证明服务、原文审核、健康、信号和通知权威，不另建执行器、worker、心跳、补采或交易令牌。`plan-monitor-readiness-v1` 始终包含字面值 `authorityGranted=false`，执行接口不接受其哈希／标记作为批准。

显示真实声明范围：`ALERT_ONLY`、`TRADE_RULES`、`MIXED`。有效单提醒计划可对该提醒就绪，但不会变成完整交易计划。`SUCCEEDED`、`ACTIVE`、HTTP200、页面已连接、历史回放或缓存健康快照均不能单独表示当前就绪。

## MRD-S02 — 六个按依赖判断的轴

逐轴使用 `PASS`、`WAIT`、`BLOCKED`、`UNKNOWN`、`NOT_APPLICABLE`，附准确原因／证据／时间。保留所有失败／等待轴，不返回误导性的单一绿色摘要。

| 轴 | 必需证据 | 重要依赖规则 |
| --- | --- | --- |
| `SOURCE_COVERAGE` | 当前原文／候选／映射／规则版本、完整义务及准确人工绑定 | 历史审核有效但缺当前覆盖时，轴为BLOCKED且原因需重审，摘要为 `NEEDS_REVIEW`，不是损坏或PASS |
| `REVIEW_ACTIVATION` | 准确已审核保存版本、当前启用版本、原文有效期／范围 | 已保存草稿／被替换计划不是当前活动计划 |
| `RUNTIME_OWNERSHIP` | 当前generation／生命周期、新鲜心跳及已有所有权／排空／保护状态 | 服务能访问、旧心跳、另一进程上次结果均不充分 |
| `DATA_EVALUATION` | 官方日历、预期目标、允许来源／口径／公式、完整性／新鲜度、实际评估目标／结果 | FALSE可为完整有效评估；缺输入／首次未评估不能 |
| `INVENTORY_CAPITAL` | 仅规则需要的已知库存／可卖量、费用／收益输入、适用预算／报价／版本 | 纯提醒不需库存／预算；市值上限不需历史成本；BUY专用输入不否决SELL |
| `NOTIFICATION_DELIVERY` | 选中渠道／配置、资格、队列／重试／失败状态，声称送达时须有有效证据 | QUEUED／已读／已生成不是DELIVERED，不自动发测试消息 |

依赖由准确计划／规则决定，不因有某张表就要求全部账户值已知。与规则无关的前提是 `NOT_APPLICABLE`，不是缺数失败。库存、模拟预算、真实持仓、研究余额保持隔离，不为就绪补建或推断。

## MRD-S03 — 评估、等待与执行状态

逐规则显示 `CONDITION_TRUE`、`CONDITION_FALSE`、`WAITING_OFFICIAL_CONFIRMATION`、`AWAITING_FIRST_EVALUATION`、`MISSING_INPUT`、`BLOCKED`、`UNKNOWN`。映射既有运行结果，不改变原公开语义。信号／操作状态另列，包括批准数量、消耗及原执行窗口；监控健康不是当前交易资格。

官方日线收盘规则在日历规定的收盘证据尚未可用前，只有当前所有者／目标调度及前提能证明这是预期情况，才显示正常 `WAITING_OFFICIAL_CONFIRMATION`。不能把未来收盘尚未出现标为供应商故障，也不能用盘中报价补收盘。以前已完成且必需的bar／官方收盘缺失或过时时，显示该故障。既有宽泛字符串 `WAIT_FOR_VERIFIED_INPUT_OR_NEXT_SESSION` 本身不能区分，须用类型化日历／目标／证据原因。

完整当前证据上的 `CONDITION_FALSE` 表示正常检查了未成立条件。`MISSING_INPUT`、无完成评估、过时／不同目标或缓存读取不能变成FALSE。首次真实有效评估前明确其缺失，不编造完成数。等待事件／窗口、信号已消耗或执行窗口已过，不等于监控故障，也不能产生新机会。

摘要状态为 `READY_FOR_MONITORING`、`WAITING_EXPECTED_CONFIRMATION`、`WAITING_REQUIRED_SERVICE`、`NEEDS_REVIEW`、`BLOCKED`、`UNKNOWN`。默认优先级：明确的非审核安全／数据／配置阻断→BLOCKED；否则缺失／过期人工覆盖或审核→NEEDS_REVIEW；否则必需权威不可用／不确定→UNKNOWN；否则已证明的预期服务等待（如待发送）→WAITING_REQUIRED_SERVICE；否则仅日历确认待发生→WAITING_EXPECTED_CONFIRMATION；其余为READY_FOR_MONITORING。底层全部轴仍显示。READY要求全部适用轴当前通过且有符合条件的真实评估证据，等待状态不授予操作权；适用轴未知／失败／未验证时不显示整体READY。T16证明该优先级与边界组合，不由前端自行发明顺序。

已知交易不符合资格另列：完整评估为假、已知整笔金额超限、已消耗信号、执行窗口关闭，均可与健康监控并存。INVENTORY_CAPITAL检查必需证据可用性／完整性，不要求每笔交易通过金额条件。不能把已知不符合交易资格变成监控故障或自动SELL。

## MRD-S04 — 快照、新鲜度与有界读取

视图拥有 `computedAt`、准确 `planVersionId`、原文／内容／覆盖／审核绑定、启用版本、运行generation、当前scope／target标识、证据／供应商／公式／日历引用、逐轴观察／as-of时间及相关库存／预算版本。`freshUntil` 为适用既有证据过期时间的最早值，无法确定新鲜度时为null。复用已有运行／来源新鲜度政策，不引入放宽的通用超时；客户端时间或缓存成功不续期权威。

当前事实须属于同一一致准入上下文。读取跨越计划启用、证明变化、runtime generation或相关库存／预算版本变化时，返回UNKNOWN／上下文变化，或按既有有界读取所有权政策重试，不能拼新计划与旧评估。沿用CURRENT/CACHED/UNAVAILABLE来源，缓存明确为历史，不当当前PASS。界面在上下文变化后丢弃迟到响应，证据过期后移除就绪声明。

仅数据库审计标为 `PERSISTED_ONLY`，旧心跳／评估行不能证明当前进程所有权。拿不到已运行当前owner服务的合法快照时，运行就绪保持UNKNOWN/NOT_READY。可通过明确配置的本地回环读取取得既有服务快照，但不启动服务或触发供应商补采，也不以持久时间戳代替当前权威。

`GET /api/v1/plan-versions/{version_id}/monitor-readiness` 有界投影既有自有事实，不联网／调用供应商补采、不更新心跳、不迁移、不写outbox、不模拟／审核／启用。缺运行事实为类型化UNKNOWN，缺保证存储为UPGRADE_REQUIRED/UNKNOWN，不自动建表。保留当前计划／树／读取所有权边界、最多10个活动证券、原响应／准入预算及新增视图1MiB上限。大小／可用性失败不能静默省略阻断轴或规则，不在轮询时扫描完整历史。

## MRD-S05 — 通知真相与只读风险可见性

区分已配置、符合资格、待发、重试、失败、被抑制、已送达。声称送达须有dispatcher实际成功渠道结果和绑定回执，不能用outbox意图、已读或无关旧渠道成功代替；报告目标／渠道和回执时间，不泄露秘密。缺当前可信配置／交付验证时为 `DELIVERY_UNVERIFIED`；读取就绪不自动发消息。手动验证消息须另行明确授权并标为测试，不改行情或真实规则来强制触发。

保留准确原文／审核／窗口／当前数据／库存／预算的发送时资格检查。原文／覆盖校正抑制受影响可操作通知，队列历史如实保留。不能因BUY预算／覆盖输入缺失压制独立信息性风险提醒；提醒须标明不确定性／legacy范围，不授权风险模拟或券商操作。

## MRD-S06 — 界面及三种不同验收结论

在计划及逐规则旁使用易懂说明：来源覆盖／审核、监控范围、实际上次评估及目标、正常收盘等待与缺数、适用库存／预算需要、通知状态。保留人工决定，不提供一键“修到就绪”以修条件、批准、补成本或启用计划。显示原文→规则链接及用户需要完成的步骤，不以实现代码作为主要解释。加载、失败、断线／缓存及过期响应各自明确且可访问，验证320/768/1024/1440布局和键盘／错误反馈。

三种验收声明分开：

1. **工程：**隔离情形证明正／负就绪、当前所有权及零业务写入／网络调用。
2. **提取：**准确版本完成获批真实供应商语料验收，该结果不证明当前运行健康。
3. **真实安装：**只读记录实际迁移／schema、保存版本、当前覆盖／审核、启用、所属运行／评估／数据及通知证据。如实BLOCKED/UNKNOWN/NOT_READY可以是正确审计，但不能称真实安装已就绪。

声称真实就绪须有实际前提及已授权观察，声称渠道验证还须有对应证据。审计不自动迁移用户库、审核／启用真实来源、初始化库存／成本或发送测试消息。操作未获批或前提缺失时明确列出，保留NOT_READY，不能修改真实数据制造正向测试。

## MRD-S07 — 验收情形与实施接缝

对应 PMA-A05/A06、A09–A12。必需情形：健康纯提醒但库存未知、市值上限无成本账、成本上限BUY缺成本而独立技术风险SELL不受影响、完整FALSE、当天收盘正常等待、旧官方数据缺失、首次未评估、报价／供应商／日历／证明过时、启用／runtime generation变化、CACHED/UNAVAILABLE、待发／重试／已送达／被抑制、过期／已消耗信号、缺升级、并发读取零副作用。

复用 `web/runtime_status_models.py`、`runtime/health.py`、当前monitor读取／证明服务、`runtime/daily_service.py`和dispatcher投影。建议聚焦接缝为 `web/plan_readiness_models.py`、`web/plan_readiness_service.py`及原计划路由／工作台适配。不为绿色标记放宽当前运行健康。未来测试／API／生成／界面切片由任务表定义，本草案不改运行或前端代码。

## MRD-S08 — 类型化事实字段附录

### MRD-S08.1 — 增量形状与所有权

本附录只定义事实形状，不增加读取装配、资格求值器、dispatch、队列、存储、批准token或自动测试发送。`RuleReadinessFacts.money`、`RuleReadinessFacts.notification` 和 `RuleReadinessFacts.risk` 缺省为null，null时省略。下列五个新增可空执行字段遵循相同省略规则。a6/a7既有字段及其既有null键保持序列化不变；新增字段缺省时，真实readiness JSON预像须逐字节往返一致。

新投影继承既有闭合、冻结、严格的 `ApiValue` 契约与camelCase别名；嵌入的原生capital/economics结果保留原字段名和验证。准确保留六个轴、最多76个owner、最多50个完整原生条件叶、字面值 `authorityGranted=false`，以及既有全null新鲜度／摘要优先级。仅提供事实不会提升任何轴，也不推导交易／发送资格。

复用父规则owner、已准入读取上下文及下列既有 `ReadinessObservation`，不增加重复owner/hash/provenance包装。上下文相等不能证明原风险cause；后继reader仍须独立验证准确原属来源及其适用新鲜度。无唯一原属signal/event或无可信结果时保持null／省略，不猜测批准、失败、pending或原生 `NONE`／`PASS` 结果。

### MRD-S08.2 — 金额

`ReadinessMoneyFacts` 包含下列字段：

| 字段 | 类型／可空性 | 含义 |
| --- | --- | --- |
| `inputs` | 必需 `AxisReadiness`；`axis` 必须为 `INVENTORY_CAPITAL` | 逐规则输入可用性、既有原因及 `ReadinessObservation`；保留原轴约束 |
| `capital` | `CapitalAssessment` 或null；null省略 | 复制准确原生冻结资本结果，包括phase、policy hash、quantity、版本、blockers及evidence hash |
| `economics` | `EconomicsResult` 或null；null省略 | 复制准确原生 `NONE`／`PASS`／`FAIL`／`UNKNOWN` 结果；缺失不是 `NONE` |

验证原生值，不重新计算费用、经济性、资本或数量。保留Python严格验证及原生JSON读取入口，使序列化tuple数组可以往返；这不允许将bool／字符串强转为数值字段。原生 `FAIL` 可与 `inputs.state=PASS` 并存：已知整笔交易不满足，不是监控输入故障。`capital.quantity` 和 `economics.quantity` 是被检查量，不是获批量，不能填入 `execution.approvedQuantity`。null结果不声称已有可信判定；原生结果值及嵌套snake_case字段名保持不变。

### MRD-S08.3 — 原属执行事实

扩展既有 `ReadinessExecutionState`，保留 `approvedQuantity`、`consumed`、`executionWindow`、`windowState`、`eligible` 和 `reason` 不变。

| 新JSON字段（Python字段） | 类型／可空性 | 含义 |
| --- | --- | --- |
| `signalId` (`signal_id`) | 既有有界 `Reference` 或null | 准确原属signal，与其revision一起提供 |
| `signalRevision` (`signal_revision`) | 既有 `Revision` 或null | 与 `signalId` 配对；整数0–9007199254740991，不能为bool |
| `executionDate` (`execution_date`) | 日期或null | 原属已知执行日期，不推断日历 |
| `observation` | `ReadinessObservation` 或null | 准确观察的执行事实及其原始时间／引用 |
| `blockers` | 完整既有 `Reference` tuple，最多128项，或null | null表示没有可信列表；空列表不证明符合资格；不能截断 |

两个signal引用字段须同时null／省略，或同时提供；仅有引用本身不验证来源所有权。不要求旧a6合法调用者追补新增引用。`consumed` 与 `eligible` 保持独立true／false／null事实，不从字段组合推导许可。原获批量只取已验证原signal的最终数量，不能用 `q0`、candidate quantity、静态rule quantity或risk target替代。每个 `Reference` 仍为1–256字符，不另建执行框架。

### MRD-S08.4 — 准确事件与渠道事实

`ReadinessNotificationFacts` 提供可空 `eventId` (`event_id`，UUID)、`causeId` (`cause_id`，`Reference`)、`target`（既有 `EvaluationTarget`）、`createdAt` (`created_at`，原始上海时间戳)和 `observation` (`ReadinessObservation`)，这些null字段省略。`channels` 为最多3项的 `ReadinessNotificationChannel` tuple，按既有 `DeliveryChannel` 枚举唯一：`IN_APP`、`CONSOLE`、`WEBHOOK`。空tuple表示未提供渠道事实，不表示渠道关闭。事件元数据、历史资格分类与attempt须绑定准确原始 `eventId`；没有事件时仍可观察配置。

| 渠道JSON字段（Python字段） | 类型／可空性 | 含义 |
| --- | --- | --- |
| `channel` | 必需既有 `DeliveryChannel` | 准确渠道，不能借用其他渠道成功 |
| `configured`、`enabled` | 严格bool或null；null省略 | 独立验证的配置／启用状态；未验证不等于false |
| `eligible` | 严格bool或null；null省略 | 仅复制当前资格；false不能制造历史 `SUPPRESS` |
| `historicalStatus` (`historical_status`) | 既有 `RecoveryDeliveryStatus` 或null | 原属 `ELIGIBLE`／`HOLD`／`SUPPRESS` 分类，与当前资格分开 |
| `historicalUpdatedAt` (`historical_updated_at`) | 上海时间戳或null | 原分类更新时间，与 `historicalStatus` 一起提供 |
| `latestAttempt` (`latest_attempt`) | `ReadinessDeliveryAttempt` 或null；null省略 | 准确最新可信event/channel attempt；无attempt表示没有该记录 |

配置、当前资格、历史分类和attempt历史可独立变化，不能互相推导。`IN_APP` 送达仅证明该渠道实际回执，不能验证 `WEBHOOK`。无event／attempt不自动表示失败、排队或pending。DTO不重新计算发送时资格，也不改变任何终态抑制策略。

### MRD-S08.5 — 无秘密attempt及时间形状验证

`ReadinessDeliveryAttempt` 是既有无秘密 `DeliveryAttemptRecord` 的闭合等价投影。准确字段为 `id` (`Reference`)、`eventId` (`event_id`，UUID)、`channel` (`DeliveryChannel`)、`attempt`（严格整数1–9007199254740991）、`status` (`DeliveryAttemptStatus`)、`responseCode` (`response_code`，null或严格整数100–599)、`nextRetryAt` (`next_retry_at`，可空上海时间戳)、`deliveredAt` (`delivered_at`，可空上海时间戳)和 `errorCode` (`error_code`，可空既有 `ChannelErrorCode`)。attempt记录的可空字段保留原生null。复用 `CLAIMED`、`DELIVERED`、`RETRY_PENDING`、`FAILED` 和原有闭合安全错误枚举，不另建判定／dispatch枚举或原始错误文本。

嵌套attempt须同时匹配通知的准确 `eventId` 和所在 `channel`。仅 `status=DELIVERED` 可携带非null `deliveredAt`，且不能带error或retry deadline。`CLAIMED`、重试、排队意图和已读确认不能表示送达。原创建／观察时间已知时，事件创建／target、历史更新和送达时间须在其中正确排序，具体须满足 `createdAt <= historicalUpdatedAt <= observation.observedAt`。提供的全部时间戳须为带时区的上海值。未知时间保持null，DTO验证不读取时钟或续期。这些形状检查只是必要条件，不能证明真实发送成功，后继reader仍须解析原dispatcher回执。

禁止未注册字段、endpoint、token、approval token及原始错误，验证不得把不安全错误字符串复制到 `errorCode`。不序列化渠道秘密，也不从这些可选事实推导正向交付／就绪声明。验收覆盖旧字节省略兼容、原生结果身份／无重算、严格／null／不可变边界、成对signal引用、原owner／条件叶上限、重复渠道、错误event／channel绑定、非法送达时间、安全错误枚举及event／attempt缺失语义。

### MRD-S08.6 — 风险比较、义务、原属与维护

可空、缺省省略的 `RuleReadinessFacts.risk` 包含闭合、冻结、严格的 `ReadinessRiskFacts`，仅属于准确的 `RISK_BRANCH` owner，且 `side=SELL`：

| 字段 | 类型／可空性 | 含义 |
| --- | --- | --- |
| `current` | 原生 `DailyRiskEvaluation` 或null；null省略 | 复制本次实际severe条件证据或普通风险 `ordinary_close`，保留原生snake_case字段名、owner、target和时间。缺失不等于FALSE。 |
| `obligation` | `ReadinessRiskObligation` 或null；null省略 | 实际当前RISK的 `riskId`、`revision`、`kind`、`status`、`confirmedTradeDate`、`earliestExecutionDate`、`fulfilledAt`、`blockers`；不含数量或许可。 |
| `origin` | `ReadinessRiskOrigin` 或null；null省略 | 原属不可变 `evaluationId`、`planVersionId`、`contentHash`、`reviewId`、`activationRevision`、`evaluatedAt`，及 `birth` 中的原生 `DailyRiskBirth`；仅在 `read_risk_origin()` 验证后提供。 |
| `maintenance` | 必需既有 `AxisReadiness`；`axis=DATA_EVALUATION` | 实际维护状态及自身的 `ReadinessObservation`，与是否发生新比较分开。 |

使用唯一组件 `ReadinessRiskObligation`，不复用／修改旧公开 `DailyRiskState`，不导入report/backtest模型。投影字段使用既有 `ApiValue` 的camelCase别名；`current` 与 `birth` 保留原生字段名和原生Python/JSON验证。原属ID和blockers使用 `Reference`（1–256字符）；revision为严格整数0–9007199254740991，activation revision为1–9007199254740991，blockers保留最多128项完整tuple。义务的三个可空日期／时间字段保留null，不推断缺失值。

`fulfilledAt` 可以属于先前cause：原生新起因重置会保留旧履行／cutover历史，当前status可成为 `CLEAR`、`PENDING` 或 `CONFIRMED`，新 `confirmedTradeDate` 可为null或晚于旧时间戳。保留这一真实组合。旧时间戳既不代表新cause已履行，也不能证明skip。只有普通风险支持 `PENDING`；`CONFIRMED`／`FULFILLED` 保留非null实际确认日期。

既有父级 `RuleReadinessFacts.observation` 描述当前比较，`maintenance.observation` 描述实际维护。不增加第三份重复观察。origin可属于不同的原版本／审核／启用，不能重绑到活动 `ReadinessContext`；相同context／ID本身既不能验证cause，也不能验证维护。

### MRD-S08.7 — 风险形状一致性与边界

当前比较、义务及birth保留同一risk kind；current／birth的 `risk_identity` 匹配父owner。提供的父级比较时间／target及完整根须匹配原生 `current`。普通风险 `ordinary_close` 不转换为条件根／树。当前severe FALSE可与旧 `CONFIRMED` 并存，互不改写，也不解除义务。缺origin可与独立有效的当前比较及持久义务并存，原属／维护保持未验证。旧 `technical_evidence` 不能填入 `current`。

`current=null` 时不提供完整TRUE／FALSE根／叶、比较时间或已评估target。适用时保留定义派生的 `UNKNOWN`／`MISSING_INPUT` 诊断叶；无条件的普通风险自然没有这些叶子。`maintenance=PASS` 要求 `CURRENT` 观察、已知 `asOf`、准确义务，以及非 `CLEAR` 义务的origin。没有 `current` 时，仅普通 `CONFIRMED`／`FULFILLED` 符合设计内skip形状。这些检查不能证明producer行为、来源身份、原属所有权或读取一致性。origin须标识birth收盘后的不可变评估，不能为evaluation-head指针；提供的历史不能晚于已知维护观察。父级 `CURRENT` 比较匹配准入plan／content／activation；比较与维护观察不能混用context。

保留六轴、76 owners、50叶、1MiB、既有新鲜度政策和字面值 `authorityGranted=false`。嵌入的原生风险树也计入50叶：每owner取父级诊断叶与原生current条件叶的较大值，不重复计算同一投影。本形状片不实现装配、`changed_readiness()`、摘要适用性或READY。

### MRD-S08.8 — 后继consumer的窄范围普通风险设计内skip规则

后继consumer仅可把已证明的普通 `CONFIRMED`／`FULFILLED` 设计内skip，从表示适用权威缺失的UNKNOWN规则中排除。必须全部验证：

1. 当前owned immutable EVAL、准确target、generation/configuration、新鲜度及维护路径全部必需来源。缺观察字段本身不能证明skip，不需要新增producer标记。
2. 当前SQL RISK完整payload/revision与该EVAL中唯一准确RISK一致，包括 `origin_evaluation_id`；`read_risk_origin()` 验证原始cause。所有原属来源绑定参加第二次读取。
3. 实际原生skip成立，且无新birth、待处理新cause、要求比较的cutover或适用新比较。`FULFILLED` 后的新cause不能借旧履行／origin或相同risk ID取得豁免。
4. 实际 `maintenance=PASS` 及既有过期时间，不补造 `current`、完整根／叶或比较时间。其他规则与六轴照常参与。

这收窄适用性，保持摘要优先级不变。来源缺失／过期、RISK／origin变化、未记录原生风险事实的旧快照、新birth、实际比较缺证仍为UNKNOWN／失败；真实 `MISSING_INPUT` 保持原优先级。未知通知／交付仍适用。`changed_readiness()` 须清除新增当前／维护声明并保留诊断叶；DATA_EVALUATION与摘要都只能消费已验证维护及其过期时间。这需要后续窄范围consumer／摘要实现和真实production／竞态测试；本模型片不实现或验收这些行为。

后续消费普通风险 `ordinary_close` 时，仅按MRD-S03映射实际原生分支，不补造条件根／叶：完整 `CLEAR`／`OBSERVATION` 且 `below=False`、无输入缺口，包括实际第二收盘 `below=False` 转入 `OBSERVATION`，可展示 `CONDITION_FALSE`；实际 `confirmation_close_used` 且转入 `CONFIRMED` 可展示 `CONDITION_TRUE`。首跌、早到收盘或重启相邻对的 `PENDING`，不能凭 `below=True` 声称双收盘成立。只有实际更新后的第二收盘日期（`second_close_date_after`，并保留 `expected_second_close_date` 作为先前比较上下文）、官方日历、owner调度及必需先前输入完整，且该事件仍在未来，才可建立 `WAIT`；否则保持 `UNKNOWN`。真实缺数保持原 `MISSING_INPUT` 优先级。这一原生字段映射由后续consumer验收，本模型片不实现。


有界消费者已在 `7c4404c` 交付，验证和运行限制见 [PMA-R86](../../verification/2026-10-27-plan-monitor-assurance.zh-CN.md#pma-r86--实际风险读取与严格证明的维护)。默认盘中复用旧日线时，在建立完整当前接纳前仍为 UNKNOWN；本次不增加 producer 刷新或调度行为。


## MRD-S09 — 限定范围的当前 IN_APP 服务验证

本节落实 MRD-S02/03/05 对监控服务、发送资格及成功送达的区分，不增加策略、自动测试发送或新审批流程。R87/R88 提供实际配置和准确历史回执，二者本身不构成当前服务 PASS。

当前服务检查只能由既有真实 dispatcher/生产 deadline 路径记录。仅保留一份有界、最近的不可变检查，绑定实际唯一原生 `InAppChannel` 实例、既有 runtime generation/configuration 及准确的既有 completion 上下文（最多10个计划）。记录原始开始/完成时间、确实成功检查 IN_APP 存储的证据，以及原始适用 owner/target 期限。已关闭/禁用 dispatcher 返回空元组不算检查成功。缺少已证明评估上下文的启动恢复不能认证计划。getter 和 readiness GET 不执行工作，也不刷新时间。

新检查开始、未完成/失败/取消、存储异常、实例替换、关闭、配置/代次变化或相关 completion 上下文改变，均撤销上一份当前检查。之后无关进度或重复 GET 不能延长其已记录期限。复用既有一致性读取和最早时效限制，不增加通用 TTL、逐事件缓存、worker 或历史扫描。

对于实际唯一原生 IN_APP 配置，当前检查成功，加上独立验证的完整当前 FALSE 评估及不存在适用投递义务，可以在无事件时证明通知服务 PASS。无义务须来自准确原生评估及适用的原始 SIGNAL/RISK/candidate 事实，不能来自空 event IDs、有界扫描或 FALSE 单一事实；义务不确定时仍为 UNKNOWN。准确 IN_APP 事件已有 DELIVERED 回执，且当前服务验证及归属成立时，可表达该条义务已完成；这不使当前 eligible 变为 true，也不许可再次发送。首片可仅验收可证明子集，但必须明确列出剩余 UNKNOWN 场景。

不得把零事件证明推广到 WEBHOOK、CONSOLE 或枚举名相同的自定义通道。扫描游标/limit 可能跳过既有事件，检查过存储不等于队列为空或覆盖全部事件。当前 WAIT/资格需要另有真实调度/依赖事实证明，历史 CLAIMED/RETRY_PENDING 或较早的 allowed 判断不充分。验证缺失或不确定时保留 UNKNOWN/DELIVERY_UNVERIFIED，保留准确历史事实，不得为了变绿制造信号。验收要求实际生产者/dispatcher 工作、当前完整 FALSE/无义务成功、潜在义务、错误/缺失/过期上下文、失败/关闭/替换实例、GET 无副作用及历史/API 边界不变。

### MRD-S09.1 — 准确验收的消费者子集

以下两个子集均保留相同的实际唯一原生 IN_APP 服务检查、准确当前 owner/completion/configuration、原始期限、撤销及两次读取门禁。其他适用轴必须为 PASS/NOT_APPLICABLE；两个子集均不产生发送许可，也不改变 summary 优先级。

1. **纯 ALERT_ONLY 义务履行。** 原生 alerts 与计划规则一一对应，不得缺失或重复 owner。每条当前规则都是真正完整的 CONDITION_TRUE 或 CONDITION_FALSE，并与其原生 SATISFIED/UNSATISFIED 结果一致。每条 SATISFIED 规则都须独立具有既有准确 `NotificationRead`、原始 cause/rule/生产 version/hash/review/activation/evidence 和实际确认 target，以及该准确 event 最新的 IN_APP DELIVERED 回执。通知 target 必须等于规则实际 evaluated 及 expected target。其他 owner、target、event 或 channel 不能替代履行。每条 FALSE 规则保留完整无义务校验。signals、risks 和 exception candidates 仍须为空，`risk_action` 必须是准确的原生无动作状态。全部义务都须已履行；一条已送达提醒不能满足两条 TRUE 规则。
2. **Schema5 无信号且完整 FALSE。** `schema_version` 必须恰好为5，至少存在一条 ordinary rule，且不接纳 risk branch 或例外机制。每条 ordinary rule 及可选 alert rule 都必须是真正完整的当前 FALSE。原生 `signals`、`risks` 和 `exception_candidates` 必须完全为空，`risk_action` 为准确无动作且无 cause。数量为零及 terminal signal 不等于为空；更高 schema 的 ordinary rule 不在本子集内。这依赖已核查 Schema5 producer 对 READY/SIGNAL、不可变 EVAL 及 head 的原子提交闭包，不声称能覆盖任意外部数据库写入。不增加历史扫描、生命周期重算或新事实 producer。

准确原生 dedup key 复用可以为同一义务保留更早的 event 和 delivery 时间；不得要求 event 评估时间等于最新 EVAL，也不得刷新原始 `createdAt`/回执时间。义务履行仍使 `eligible` 保持 null/省略，历史通知 observation 保持 PERSISTED_ONLY，绝不许可再次发送。回执缺失、歧义、channel/target 错误或未履行时仍为 UNKNOWN。当前 WAIT/资格、更广的 ordinary/risk/candidate 履行及其他 channel 仍不在这两个子集内。验收使用实际生产、原生发送 guard 和 IN_APP 回执，涵盖 TRUE+FALSE、两条 TRUE 仅一条送达、同键复用、准确绑定/竞态失败及 GET 零副作用。

## MRD-S10 — 已验证分段规则的确认等待

仅将既有 Schema5 简单确认等待门禁扩展到具有已验证完成前驱的 `AFTER_RULE_COMPLETED`。后继必须已有真实完整的原生 FALSE 根及完整叶子，且自身没有 occurrence。保留既有当前 owner/来源/审核、日期有效性、无人工输入、简单资金输入、官方日历、部分分钟完整性及过期限制。原生跳过评估、缺历史或不支持的动态准入不能变成等待。

按 `prior_rule_id` 选择唯一前驱，并匹配计划中唯一的 `ONCE_PER_RULE` 普通规则。仅使用该原生 owner 已准确点读的 SIGNAL：核对原始 ID/kind/symbol/lineage、rule/side、plan version/review、occurrence mode、完整 evidence/basis 及 revision。其完整原生值须与产生后继 FALSE 时消费的前驱快照一致，并满足 `state=SIMULATED`、`simulated_qty == planned_qty > 0`、`executable_qty=0` 及已知 `execution_date`。原始行的 `updated_at` 不得晚于该 FALSE 的评估时间；之后才发生的模拟或变更不能倒补准入。原始记录缺失、歧义或不匹配时不准许等待。复用这些记录既有的两次读取绑定；变化会撤销声明或消耗既有有界重试。

后继实际确认日期不得早于前驱的 `execution_date`。支持该日的官方收盘比较；分钟比较必须在之后的日期。同日分钟准入原生要求 `simulated_at`，而 SIGNAL 未保留这一字段。不得以 `updated_at` 替代、查询 SIMULATION/历史、补造比较，或修改 producer 来提供成功事实。缺少该实际根时保留 UNKNOWN。

验收使用公开整笔模拟、真实 producer 随后的 FALSE，以及尚未到达的未来确认。验证官方收盘及之后日期的分钟等待、准确原始记录不匹配、不完整/较晚消费、真实原生日期/时间提前返回、后继已有 occurrence、部分历史缺失、日期限制及两次读取变化。保留原 FALSE 时间/target/evidence 及既有新鲜度边界。这只是逐后继 WAIT：已消费且没有新比较的前驱、未验证的通知服务仍为 UNKNOWN。不增加维护/通知 WAIT 或整体 READY。不修改模型、摘要、查询、表/索引、策略、采集或公开契约。

既有人工输入排除回归为 `tests/integration/test_plan_readiness_confirmation.py::test_real_missing_human_leaf_is_not_relabelled_as_future_wait`：真实接纳的 `ONCE_PER_RULE` 规则具有原生 FALSE 根及缺失人工叶，保持 `MISSING_INPUT` 且不产生未来等待。它覆盖未改动的共用人工输入门禁，不代表端到端 `AFTER_RULE_COMPLETED` 人工来源场景。本片未验收此类已获来源接纳的人工场景；依赖人工的等待仍被保守排除。不得补造来源审批来扩大这一验收声明。

## MRD-S11 — PBS 只读持续禁买投影

已批准的 [PBS 规格](SPEC-plan-buy-suspension.zh-CN.md)在既有 `GET /api/v1/plan-versions/{version_id}/monitor-readiness` 响应中增加可选的 `snapshot.buySuspension`。没有适用扩展时省略该字段，旧的无扩展载荷保持原有结构。保留 `plan-monitor-readiness-v1`、六轴、76个 owner、50个叶子、1MiB 响应上限及字面量 `authorityGranted=false`。T10负责两种生成的公共契约及增量兼容检查，T11负责既有审核／就绪组件。本投影不增加公共冻结格式、页面或解锁操作。

`ReadinessBuySuspension` 保留原生定义、原始 `ownerPlanVersionId`／`ownerHash` 及 `birthActivationRevision`、可选的原生 `state` 及正数 `stateRevision`、由当前日历确定的 `target`、观察结果 `outcome`、`maintenance`、`blocker`、确切 `skippedRules`、`strategyEffectiveFrom` 及可选原生 `replacement` 凭据。嵌入的原生值保留自身字段名和校验。`outcome` 为 `UNVERIFIED`、`CLEAR_THROUGH_TARGET` 或 `LATCHED`；明确废止且没有新保护时为 null。建立当前证明前，存储中的通过状态只是历史证据。即使不能认证当前监控，历史有效触发仍保持 `LATCHED`。

通过 `resolve_buy_suspension_context` 分别解析实际启用前序和原保护 owner；普通续版读取原 owner 的记录、定义及出生修订。核对原生 content／source／review／definition 与该 owner 一致，并保留 `guard_owner_hash`。定义存在但没有 `BUY_SUSPENSION` 行时为未核实：state及求值修订均为 null，包括日历尚不能确定首个 target 的情形。GET不初始化记录。接替凭据表达前序记录缺失时，则严格使用 `predecessor_state_revision=0` 及 `predecessor_state_hash=null`，并明确确认原未核实区间；两种表达不能混淆。单独审核不能接替当前前序。明确废止启用后仍保留 `strategyEffectiveFrom`，不能在该起点前允许BUY。

确切原生 `BUY_SUSPENSION_LATCHED` 抑制，或已有证明的未来接替策略起点，可以得到逐规则 `BUY_SUSPENDED`。核对实际 owner、仓储修订、当前完整K线 target、启用审核／版本、runtime generation和既有不可变 completion proof，以及确切原生 `buy_suspension_*` 字段和被跳过的BUY身份。保留缺失的比较时间／根及未知诊断叶子，不能补造TRUE／FALSE或预期确认。其他规则保留自身条件和执行事实。即使提供的 maintenance 观察为PASS，守护证明缺失／未核实仍计为UNKNOWN，且 `freshUntil` 为null；不改变独立SELL的比较。守护已核查通过只表示通过本保护，不授予交易权限。

对Schema10普通规则，MRD-S09的唯一原生IN_APP服务子集进一步允许原生动作集合为空，且各规则为真正完整FALSE或确切证明的 `BUY_SUSPENDED`。仍须满足全部原有当前服务／configuration／completion／expiry校验、signals／risks／exception candidates为空及确切无风险动作检查。单独跳过BUY不能证明服务健康；投递义务未解决或仍存在时保持UNKNOWN。不推导新的发送或投递资格。

GET使用既有归属SQL快照和有界启用解析器。前后读取绑定包括前序／原owner身份、出生／当前启用修订、definition／source／review绑定、保护记录存在性／修订／state hash、当前target及日历行、策略起点、接替凭据和原生抑制字段。相关变化消耗既有有界重试；重试耗尽后撤销当前性并清除当前跳过声明，同时保留历史触发证据。临时 `DailyRepository` 读取器使用 `id_factory=None`，不注册为失效写入者。刷新前精确拒绝保护行待提交的修改／删除／改名，不覆盖会话改动。GET不采集、不恢复、不转移状态、不执行业务SQL写入、不补记录、不续期游标，也不调用BUY提交谓词；不增加分钟历史扫描。

隔离验收覆盖两种公共契约、拦截SQL／网络／状态转移并比对全部表及结构的重复相同GET、原owner继承、缺状态／日历、真实SELL比较、只审核未启用的接替、零修订凭据、未来废止起点、owner停止后的历史及真实保护修订竞争。PBS工程证据不关闭原始03/04的其他来源义务、F083/C05或历史PMA门禁。

## MRD-S12 — 当前计划审核与BUY保护展示

现有 `PlanWorkbench` → `PlanSourceReview` 流程接收确切的 `schema_version=10` / `CONDITION_PLAN` / `condition-plan-v6` 组合，并选择 `buySuspensionCandidateSchema`。保存版本读取保留规范计划JSON及原文／内容／审核绑定。不匹配的当前版本头，包括字符串类型的schema编号，不能回退旧版准入。默认 `plan-extract-v12` 保持不变；`plan-extract-v13` 通过显式配置路线使用，不增加类型选择器，也不修改用户配置。

在现有就绪界面显示：完整5分钟收盘严格低于所示阈值、明确核查起点、连续核查截止及当前目标。等于阈值、仅盘中最低价跌破均不触发。存在时展示历史触发收盘／结束／观察时间、来源证据、可比价格基准日期／因子、原owner、缺数据原因及接替策略起点。监控健康与本计划全部后续BUY禁令分别判断。即使维护项PASS，`UNVERIFIED`仍阻断；历史LATCHED证据也不代表当前监控健康。保护已核查至目标不授予交易许可。SELL与独立风险保留各自条件，不补造BUY比较时间或TRUE/FALSE结果。

澄清原文要求的保护时，先在现有编辑器定义缺失字段并保存。在来源审核区使用“读取本原文全部禁买义务与当前启用依据”。客户端读取现有 `source-coverage` 资源全部分页，检查一致的保存原文／内容／计划绑定，并选择真实服务端义务ID。独立登记将当前保护四个字段连同 `source_hash`、`obligation_id` 和 `ALL_PLAN_BUY_REVIEWED_REPLACEMENT_ONLY` 保存，不把无关义务标为完成。字段缺失、原文变化、分页未读完整或缺少归属依据，均不能通过勾选变成许可。

明确接替时，从新原文逐字粘贴唯一完整接替声明，填写理由及带 `+08:00` 的明确策略起点，再单独登记意图。只有原文明示废止旧保护才选择废止。仅在展示实际服务端读取的前序未核实区间时，才能确认接受该区间；依据不可得时不能声称已确认。客户端不能选择前序owner。普通补充保留服务端已登记的接替意图。登记、保存新版本、独立审核和明确启用保持独立操作；已审核候选仍未启用，同时显示实际启用版本。启用由服务端再次核验权限，本身不产生交易。不新增页面或解锁控件。

换版本、修改原文或候选内容时，清除未提交保护输入并使其owner绑定失效；迟到读取不能恢复已被替换的选择。就绪刷新仍仅GET。前端组件／类型／构建证据由PBS-T11负责；隔离真实浏览器流程及320/768/1024/1440 × 900视口验收仍由PBS-T12负责。原始03/04其他义务及F083/C05保持未完成；这些工程界面检查不是原文直接正例验收。
