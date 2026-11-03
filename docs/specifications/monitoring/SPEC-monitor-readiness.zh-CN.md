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

本附录只定义事实形状，不增加读取装配、资格求值器、dispatch、队列、存储、批准token或自动测试发送。`RuleReadinessFacts.money` 和 `RuleReadinessFacts.notification` 缺省为null，null时省略。下列五个新增可空执行字段遵循相同省略规则。a6既有字段及其既有null键保持序列化不变；新增字段缺省时，真实a6 readiness JSON预像须逐字节往返一致。

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
