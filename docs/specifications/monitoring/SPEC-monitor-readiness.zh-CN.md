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
