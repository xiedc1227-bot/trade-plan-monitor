# 规格：executable-plan-extension（R08 / F06）

> `SPEC-executable-plan-extension.md` 是英文正式版；本文为语义等价的中文审阅副本。日期：2026-09-12。**R09–R11 已面向隔离可信输入实现；公开 Schema v3 保存与复核现已可用，而导入和启用在 R12 完成前仍关闭。**

## E01. 范围与依据

已授权的 R08 任务允许对 `plan-domain`、`decision-engine`、`strategy-state`、`ai-plan-drafting`、`notification-outbox` 和 `local-web` 进行本项有限扩展，不改变原始验收计划。原文到字段及 S01–S09 预期见 [R08 映射](../../../remediation/R08-mapping.zh-CN.md)；版本及历史兼容见 [ADR 0005](../../decisions/0005-version-explicit-plan-rules.zh-CN.md)。仅对新模式，本文修订既有规格中只描述旧策略的表述。

保留当前调度器、标准化K线、SQLite 工作单元、审核来源、提醒 outbox 和持仓登记，在现有边界增加有限类型分支。不引入新平台、规则脚本语言、供应商、券商或自主交易。所有示例均为合成数据。原文缺失信息成为可见的 `UNRESOLVED` 审核项，不代表建议值已被默认批准。

## E02. 计划分支与有限词表

| 契约 | 存储判别字段 | 执行含义 |
|---|---|---|
| 既有计划 | `schema_version=1` 或 `2`；原字节不变 | 派生展示模式 `LEGACY_LOW_BUY`；当前修复后的实现标识为 `legacy-low-buy-r06`。保留低吸 episode、CORE/TACTICAL、压力拒绝和官方收盘风险。Schema v2 保留既有指数契约。 |
| 新显式计划 | `schema_version=3`、`execution_mode=EXPLICIT_RULES`、`execution_version=explicit-rules-v1` | 在完成的五分钟收盘时判断独立审核的规则。不继承 episode、核心仓优先、仅机动仓、压力触碰、MACD、中位量上限、布林、距离阈值或官方风险锁定状态。 |

Schema v3 保留 `plan_id`、`version`、`symbol`、`name`、`market`、`metadata` 和 `activation` 字段，另含下述 `position`、`monitoring`、`rules` 和 `conflict_policy`。禁止旧 `levels`、`entry`、`reduction`、`risk`、`blockers` 和 `reference_market` 字段。首版显式模式不支持指数条件；共享指数信息展示可以继续，但不成为必需输入。模式切换必须创建并审核新计划版本，不能原地迁移或推断字段。

| 字段 | v3 精确契约 |
|---|---|
| `position` | `{inventory_scope: ALL_REGISTERED, lot_size: 100, max_qty: positive integer multiple of 100}`；无目标仓位或实际持仓字段 |
| `monitoring` | `{timeframe_minutes: 5, indicator_formula_version: ta-v1}`；`ta-v1` 保留标准化标识，不隐含任何指标条件 |
| `rules` | 1–3 条规则；`rule_id` 唯一且使用既有有界 `PlanId` 语法；BUY、SELL、RISK_ALERT 各最多一条 |
| 规则字段 | `rule_id`、`condition`、`action`、`confirmation`、`repeat_policy`、`safety_conditions` |
| `confirmation` | `{kind: COMPLETED_BAR_CLOSE, timeframe_minutes: 5}`；不得替换为完成前或日收盘 |
| `safety_conditions` | 显式可选条件树，或经明确审核的 `null`（没有额外策略阻断）；仅作用于本规则 |
| `conflict_policy` | `{trade_conflict: BLOCK_BOTH, risk_conflict: RISK_ONLY | RISK_WITH_SELL_BLOCK_BUY}`；两字段均须审核 |

条件树仅允许 `ALL`、`ANY` 和下列叶子。复用最大深度 4、所有规则及安全条件树合计最多 50 个叶子的限制；逻辑节点非空、无环、无额外字段。数组顺序用于证据及哈希，不表示时序或买卖优先级。`MANUAL_EVENT_RISK_CLEAR` 仅允许在明确声明的规则安全树内使用。合成计划不自动要求人工事件风险确认。

| 叶子 | 必需参数 | 含义 |
|---|---|---|
| `COMPLETED_CLOSE_IN_RANGE` | `low_fen`、`high_fen` 为正整数，`include_low`、`include_high` 为严格布尔值 | 当前完成五分钟收盘在指定区间。复用 `PriceZone` 比较；拒绝倒置或不包含任何有效价格刻度的区间。边界标记必须提供，不在草稿中默认补齐。 |
| `VOLUME_TO_MEAN_GTE` | `window_bars` 为 1–500 整数；`minimum_ratio` 为 `(0,10]` 内规范有限十进制字符串；`history_scope=CONTIGUOUS_TRADING_BARS` | 当前完成五分钟量至少为恰好前述数量完成K线算术均量的指定倍数，排除当前根。 |
| `COMPLETED_CLOSE_BELOW` | `price_fen` 为正整数 | 当前完成五分钟收盘严格低于阈值。 |
| `MANUAL_EVENT_RISK_CLEAR` | 无新参数 | 复用 R07 明确无风险 / 有风险 / 未知输入，范围见 E08。 |

固定字面量、数值边界和首版数量限制是实现约束，不声称来自原文交易指令。额外指标、任意公式字符串、`NOT`、跨规则引用、移动止损、每日重置变体、分批和先后关系均不在本模式范围。不得把不支持的要求硬塞入最接近的叶子。保留原文区段，报告 `UNSUPPORTED_SEMANTICS`，阻止整个受影响计划激活，直到用户明确提供可支持的替代要求。仅勾选已读不支持警告不算解决。

## E03. 精确完成K线与算术语义

目标 `t` 必须有一根结束于 `t` 的经认证完成五分钟K线；其五根标准化分钟输入与收盘必须符合既有目标/cutoff 契约。未完成K线、仅最高/最低触碰而无所需收盘、更新的报价、未来数据或临时日收盘均不能满足规则。复用既有新鲜度及有效市场目标保护，包括当前实时新鲜度上限 90 秒；不增加新的交易阈值。

对于 `window_bars=N`，选择精确有序、交易时序相邻的 `b[t-N]...b[t-1]`。午休和非交易日只能按既有规范交易时段/日历邻接证明跳过。`CONTIGUOUS_TRADING_BARS` 允许前交易日数据；不得跳过缺失的应有K线、前向填充、补零或缩短窗口。审核中必须展示这一跨时段含义；原计划没有明确选择每日重置。如用户要求仅当日重置，v1 不支持且保留为未映射。存储/认证历史不足时为 `MISSING_INPUT`，即使后续供应商请求可能补齐，也不能提前当成已知。

设 `S=sum(prior.volume_shares)`、`V=current.volume_shares`。使用不依赖环境 Decimal 精度的精确整数/Decimal 系数算术比较 `V*N >= minimum_ratio*S`。均量展示为 `S/N`；四舍五入后的展示比例绝不作为比较输入。验收量 `[100,100,100,100,600]` 得到 `S=1000`、`N=5`、均量 `200`、中位数 `100`：`minimum_ratio="1.5"` 时，`V=299` 失败，`300`、`301` 通过；`V=200` 是特意区分均量和中位数的反例。当前根不加入 `S`。

经认证的零成交量是数据：若前 N 根确实全部为零，算术阈值就是零，直接应用不等式（含相等）；展示中的除法比例为空而非无穷。缺失成交量不是经认证的零。不得继承中位数求值器对零基线的拒绝，也不得增加未声明的正成交量下限。证据包含 N 根及当前根的身份、`sum_volume_shares`、`window_bars`、`mean_volume_shares`、`minimum_ratio`、阈值和结果；在既有证据预算内分页/展示，不能把 500 个事实塞入单条限 16 项的记录。

`ALL`：任一假则假；否则有缺失则缺失；否则真。`ANY`：任一真则真；否则有缺失则缺失；否则假。保留各分支证据；假/缺失的备选不能成为全局阻断。仅明确适用的安全树可以按同一三值语义否决自身规则。

## E04. 动作与实际持仓

| 动作 | 精确形状及效果 |
|---|---|
| BUY | `{type: BUY, quantity: positive integer multiple of 100}` -> 提醒 `BUY_READY`，数量严格等于所填值 |
| SELL | `{type: SELL, quantity: positive integer multiple of 100, inventory_scope: ALL_REGISTERED}` -> 从普通可卖持仓提醒 `SELL_READY`，数量严格等于所填值 |
| RISK_ALERT | `{type: RISK_ALERT}` -> `RISK_ALERT` 纯提醒；无数量、分仓、目标 lot 或成交 |

BUY 要求已知且登记完整的当前持仓，并满足 `total_qty + quantity <= max_qty`。SELL 要求在经认证日历/T+1 事实下已知可卖量且 `sellable_qty >= quantity`。不得取整、截断、分批或静默替换数量。`ALL_REGISTERED` 包括合格 CORE、TACTICAL 及普通期初余额；只有 CORE 100 股也可满足 SELL 100。规则不含目标 lot 优先级；表单如需分配，由用户另行选择并校验。超过最大仓位只阻止新增买入，不掩盖实际持仓，也不抑制合格卖出/风险提醒。

原文“已有100股，当日可卖100股”是**独立的人工确认持仓声明**，不是 `position.core_target_qty=100`、不是 AI 创建的成交、也不是空列表默认值。在当前持仓仓储中扩展：

- `inventory_confirmation`：股票、明确的完整登记声明、`as_of_trade_date`、`confirmed_at`、`inventory_revision` 及已登记余额/lot 引用；缺失为 `UNKNOWN`。明确空仓需要显式零声明。确认时间不得晚于求值 cutoff。
- 只知道原有已可卖持仓时，增加普通 `opening_balance`：身份、股票、原始及剩余数量、`sellable_from`（已确认交易日）、来源/审计和 revision。首版支持已确认全部可卖的余额及显式零；部分已结算/结算未知的期初持仓仍待解决。不得为满足旧 lot 构造器而编造成交成本或购入日期，也不得把普通持仓标成 TACTICAL。既有 CORE/TACTICAL lot 字节不变。
- 既有已登记 lot 与期初余额形成一个快照：`status=KNOWN|UNKNOWN`、可空 `total_qty` / `sellable_qty`、revision、as-of/cutoff 和缺失原因。期初余额只计一次。确认引用整个当前账本；未确认的外部调整使完整性失效。后续明确买入/减仓登记原子更新账本与 revision。推进到经认证交易日时重新计算可卖量；缺日历是未知而非零。展示上次确认时间，不擅加按经过时长失效的期限。

期初登记允许没有活动计划，防止激活/登记循环依赖。即使总量超过候选计划上限，也应记录真实持仓；计划限额无权改写持仓。复用明确且带审计的命令、revision 和幂等检查，减记被引用的 `LOT` 或 `OPENING_BALANCE`；后者通过扩展既有减仓服务处理。对已有 lot 的期初确认必须识别已计入数量，只新增未表示余额，不得把同一100股导入两次。求值期间持仓变化使候选提交失效，须重算后才能提醒。登记失败或不可读绝不变成已知零。

提醒、重试、送达、“已读”、风险确认和计划激活均不改变或预留持仓。只有单独的实际持仓命令才能形成成交。RISK_ALERT 不依赖持仓就绪，不创建旧 `risk_state`、`RISK_PENDING`、卖出、退出、恢复或自动买入阻断。其共现效果仅来自审核后的冲突政策。

## E05. 首次触发、重复与冲突

每条规则必须有 `repeat_policy`：

- `{mode: ONCE_PER_ACTIVATION}`：激活时点及以后首个合格完成目标发出提醒；该激活 revision 内之后满足的目标均抑制此规则。重启、已读、条件变假、换日及登记成交均不重置。
- `{mode: EACH_QUALIFYING_BAR}`：每个不同的合格完成目标各可提醒一次，包括尚未登记成交时。不隐含持仓预留、每日次数上限、防抖、重新入区要求或冷却。预览必须说明重复提醒不表示累计已成交数量。

两种模式中，被阻断/抑制的候选不消耗规则次数。同目标重试不是新机会；晚到人工输入仅作用于之后未被占用的目标。新审核版本再次激活形成新 activation revision，并可见地重启重复范围。同次激活内重新布防、每日一次、等待成交、假转真重新触发、“先A再B”及分批执行均不在 v1 范围。原文出现这些要求时列为未映射；不得用数组顺序替代先后关系。原始输入未提供 repeat/rearm 值，因此在逐规则明确选择前保持待解决。

冲突根据**当前满足的条件和安全树根**判断，先于重复抑制。风险条件仍为真时，即使自身提醒已经发出，仍影响冲突政策。若 BUY 与 SELL 在同目标同时合格，`trade_conflict=BLOCK_BOTH` 抑制两者并记录 `TRADE_RULE_CONFLICT`，不按数组顺序任意选先。风险不能被交易去重键吞掉：

| `risk_conflict` | 同目标风险 + BUY | 同目标风险 + SELL |
|---|---|---|
| `RISK_ONLY` | 风险候选；抑制 BUY | 风险候选；抑制 SELL |
| `RISK_WITH_SELL_BLOCK_BUY` | 风险候选；抑制 BUY | 独立风险与 SELL 候选 |

“候选”仍遵守各自重复政策。可能冲突的风险/交易条件未知时不得当假：以 `CONFLICT_INPUT_UNKNOWN` 暂停受影响交易；已知风险仍可提醒，无关成交量缺失不得抑制它。持仓检查仅用于交易候选；持仓缺失不能隐藏纯风险。安全条件未知只影响依赖它的规则。对同一有效收盘，合成计划的区间使同目标冲突不可能发生，但完整政策仍是可见的必选项，不是未公开默认值。

## E06. 结果、持久化与失效

使用仅适用于 v3 的结果分支 `ExplicitEvaluationResult`，包括 `result_schema_version=decision-result-v2`、`execution_version=explicit-rules-v1`、既有行情/求值身份事实、`activation_revision`、被消费时的 `inventory_revision`、被消费时的人工风险 revision、`rule_results` 和 `signal_intents`（0–3）。逐规则结果记录条件/安全证据、结果、阻断、重复状态、抑制原因、精确动作和下一步。不得原地放宽旧结果的单意图校验。共享快照可选一个主要展示标签，但所有规则结果/意图必须可查询，所有发出的提醒必须可见。本模式不存在的状态应缺省，不编造 CLEAR 旧风险或虚构 episode。

新实时求值身份在既有键上增加执行版本与激活 revision：`(plan_hash, symbol, INTRADAY, bucket_end, ta-v1, explicit-rules-v1, activation_revision)`。持久化 kind 和完整目标。在新的 `decision-result-v2` NUL 分隔哈希域中复用规范序列化器的精确数字规则；所有语义字段和被消费 revision 参与哈希。保留旧结果的 `decision-result-v1` 字节和哈希。

持久规则状态键为 `(plan_hash, activation_revision, rule_id)`，记录首次发出目标（如有）和最后处理目标；它不是 episode。提醒去重使用独立 `explicit-rule-alert-v1` 域和 `(plan_hash, activation_revision, rule_id, action_type, occurrence, quantity_or_null)`，occurrence 为 `ONCE_PER_ACTIVATION` 或规范 bucket end。payload 保留原始触发 cutoff。投递失败重试同一 eventId，不形成新的规则发生次数。提醒清理后仍保留发生身份，避免清理导致重新布防。

既有短工作单元必须原子完成求值占用、重检活动计划/hash/activation revision 和 R01 目标有效期、校验已消费的持仓/人工风险 revision、存储结果及规则状态、推进投影，并入队**每个**保留意图。任何不匹配/部分失败均全部回滚。原文/行情 I/O 保持在事务外。已提交的重复/乱序目标不能新增提醒或覆盖更新规则进度；修正数据不能把已消费身份重放成新交易。之后未占用的有效目标正常求值。

激活、停用、替换和到期同时以目标有效期及当前计划/revision 约束提交和延迟投递。旧事件保留为历史，`currentActionable=false`，不自动预填持仓操作。已确认事件仍保留历史证据。R01 对跨日官方收盘 `RISK_BREACH` 的投递例外仅适用于旧模式；v3 五分钟 RISK_ALERT 不得进入该分支。盘中重启追赶不能发出陈旧历史交易提醒。任一编解码、审核、持仓、结果、outbox 或消费者不能处理新模式时，保持新模式能力禁用，绝不回退为旧策略执行。

## E07. 草稿审核、哈希与 API 边界

v1/v2 保持当前 `planHash=SHA256(canonical UTF-8 plan JSON)` 不变，v3 沿用精确文档规则。它包含 `version` 和 metadata，因此**不是**语义内容哈希。仅对新 v3 审核增加服务端计算的 `contentHash`：域 `plan-review-content-v1`、NUL，以及 v3 计划只排除 `version`、`name`、`metadata`、`plan_id` 后的规范 JSON。包含股票、市场、Schema、执行版本、有效期、全部数量/条件/标记/安全/重复/冲突选择；不得静默丢弃未知字段。另行绑定精确原文 UTF-8 `sourceHash`、映射/问题快照哈希 `reviewEvidenceHash`、`planVersionId` 和审核 revision；相同内容换原文/计划不能自动获批。

保留 R04 提取快照及 R05 `AI_EDITED`/`AI_REIMPORT`/`LEGACY_PENDING` 证据，其旧 draft hash 仍为精确文档哈希。版本号递增可保留语义比较，但不能把旧记录重标为已按内容审核。R11 增加针对**当前**服务端快照的可信确认，使编辑后的 AI 草稿能够真正完成重审；复制客户端 resolved 问题永远不能做到这一点。交易内容改变使批准失效。只改名称/metadata/版本时语义哈希相等，但激活仍须明确新不可变版本和当前 activation revision。禁止跨计划复用批准。

v3 草稿与可执行模型是不同的类型视图。草稿允许缺失必需选择/参数使用类型化 null，并派生服务端 `UNRESOLVED` 问题；可执行模型要求所有值齐全。保存/查询可以在非活动 `plan_version` 中保留有界的部分草稿；激活和运行时只解析完整可执行分支。结构错误、未知键/枚举或不安全文档仍拒绝保存。不支持语义留在审核来源中，绝不作为可执行字符串。v1/v2 编解码及函数签名保持原行为；增加分派辅助函数，不放宽旧校验器。

复用既有 `/api/v1/plan-drafts`、`/plan-imports`、`/plan-versions`、`/plan-activations` 和提取路由，增加判别化 v3 草稿/读取分支。仅在旧命令无法表达意图时增加以下有界命令/读取契约（所有路径均带 `/api/v1`）：

| 边界 | 必需请求 / 响应字段 |
|---|---|
| `POST /plan-review-confirmations` | `planVersionId`、`contentHash`、`sourceHash`、`reviewEvidenceHash`、`expectedRevision`、按服务端 `issueId` 标识的显式解决记录；响应 `reviewId`、绑定哈希/版本、`revision`、`confirmedAt`、未解决问题及 `canActivate` |
| `GET /position-inventory?symbol=...&asOfTradeDate=...` | E04 的类型化 KNOWN/UNKNOWN 持仓快照；未知数字可空，包含确认和账本 revision |
| `POST /position-inventory-confirmations` | `symbol`、`asOfTradeDate`、`expectedRevision`、`totalQuantity`、`sellableQuantity`、`includedLotIds`、明确完整登记声明；响应权威快照及可能产生的期初余额身份、审计回执 |
| `POST /position-inventory-closures` | 幂等的 `LOT` 或 `OPENING_BALANCE` 来源 identity、整手数量、减记交易日和来源 `expectedRevision`；响应精确的操作前/后数量及权威库存 revision |

所有写入要求既有 `Idempotency-Key`/请求哈希/revision 机制；相同重试返回相同回执，同键异体返回 422，进行中或陈旧 revision 返回 409。不从模型输出直接接受批准或持仓状态。首版 v1 范围中，减去已纳入的已知 lot 后，期初确认只能声明 total=sellable 或零；余量结算未知阻止完成。重试或重新确认不得自动重复新增余额。

v3 激活要求 `planVersionId`、`reviewId`、`contentHash`、`expectedRevision`（活动指针 revision）及当前服务端批准，并原子递增 active revision。草稿完整性/审核控制 `canActivate`；持仓和人工风险可用性控制独立 `executionReadiness` 及缺失原因。已批准计划可激活并等待运行时输入，但在已知前不得发出依赖它们的交易提醒；UI 必须展示区别。待选择/不支持语义永远不能激活。尚不能表示 v3 的实现应报告能力不可用，不能仅称“等待数据”。

### 双向证据与可信解决记录

R11 的 v4 审核封装包括 `mapping_version=plan-mapping-v1`、`source_clauses` 和 `field_bindings`。每个条款具有稳定 `clause_id`、精确原文的 Python Unicode 码点 `start`/`end`、匹配引用、`MAPPED|UNRESOLVED|UNSUPPORTED` 状态及目的 `paths`。每个绑定具有服务端校验的存储计划 path、类型化值、单位（`FEN|SHARES|BARS|MINUTES|RATIO|NONE`）和 `origin=SOURCE|USER_SUPPLEMENT|CONTRACT`。SOURCE 引用 clause ID；USER_SUPPLEMENT 引用持久用户补充值/选择及时间；CONTRACT 指向技术 Schema 字面量或服务端生成身份。UI 展示来源标签。契约字面量和人工修正不能引用无关原文子串冒充依据。

每个重要原文条款必须已映射或可见地待解决/不支持；每个非空可执行叶子必须有一个与当前实际值一致的绑定，包括比较符、包含标记、时机、数量和政策。规则及逻辑组也保留结构绑定，防止仅因数字匹配就误以为 AND/OR 或父子归属编辑已有证据。偏移、path、类型及值相等是确定性检查，不代表子串匹配能证明语义。完整原文/映射人工审核和独立语料仍是语义正确性的必要条件。缺失/未上报条款不能靠客户端空列表免除。

`reviewEvidenceHash` 使用域 `plan-review-evidence-v1`、NUL，以及映射版本、有序条款/绑定、持久用户补充、服务端必需问题身份/原因的规范 JSON。审核本身的解决状态及确认时间排除，以免确认改变哈希原像；来源补充的时间戳仍参与。原文/映射/值/必需问题集变化使审核失效。服务端问题 ID 在该快照内稳定；客户端省略仍使必需问题保持未解决。

解决记录包含 `issueId`、`resolution=CONFIRM_MAPPING|CONFIRM_POLICY|REPLACED_BY_REVIEWED_CONTENT`，以及当前绑定/补充的引用。修改值必须先存为新不可变草稿，再确认该版本。`REPLACED_BY_REVIEWED_CONTENT` 要求明确人工原文补充和受支持替代映射，不能仅 `resolved=true`；原不支持条款留在历史中。用户批准删除条款会改变计划范围，不能算作未改动原验收预期通过。重新确认在事务内校验全部哈希、版本和审核 revision 后才能签发 `reviewId`。

## E08. 与 R07 人工风险的关系

R07 的 `plan_hash` 实际为精确规范计划哈希（含版本），不是新增的 `contentHash`。保留此范围。只针对活动精确 planHash 确认；不能因为 `contentHash` 碰巧相同，就跨版本轮换迁移 CLEAR 声明。同计划/hash 重启保留仍有效的声明；过期、哈希不符、无记录或确认晚于 cutoff 均为未知。Activation revision 独立约束执行和重复，绝不意味着人工风险已重新确认。再次激活不能为不同精确内容复活旧声明。

R09 必须把被消费的人工风险 revision 带入 v3 结果/提交保护，防止并发 CLEAR -> RISK_PRESENT 后仍提交陈旧 BUY。若没有规则声明该安全叶子，其缺失/到期不阻断显式计划。价格风险、计划语义审核、实际持仓确认、人工事件风险核对、提醒已读仍是不同概念与 API 操作。

## E09. 错误与能力门禁

保留既有 API 错误封装和 `ValidationIssue(code,path,severity,message,activationBlocking)` 形状；下列为新增领域原因码，不是任意异常字符串。v3 输出分支必须在 OpenAPI、生成客户端及投影中一致表达新增的就绪、审核及规则明细。

| 错误码 | 边界及后果 |
|---|---|
| `UNSUPPORTED_PLAN_VERSION` / `UNSUPPORTED_EXECUTION_VERSION` | 导入、激活、运行时或回放拒绝未知版本；不降级/回退 |
| `UNRESOLVED_EXECUTION_POLICY` / `UNMAPPED_MATERIAL_SOURCE` | 可保存有界草稿，`canActivate=false`；path 指向缺失的 repeat/rearm、时机、历史范围、冲突、有效期或其他含义 |
| `UNSUPPORTED_SEMANTICS` | 保留原文区段；整个受影响计划不可激活，包括不支持的先后关系 |
| `REVIEW_CONTENT_CHANGED` / `REVIEW_EVIDENCE_CHANGED` | 重新审核当前服务端内容；陈旧确认/激活返回 409 |
| `EXECUTION_CAPABILITY_UNAVAILABLE` | 必需 v3 消费者缺失；拒绝激活/求值，不转换为旧规则 |
| `ROLLING_VOLUME_WINDOW` / `TRADING_CALENDAR` | 既有缺失输入含义，仅作用于依赖规则 |
| `POSITION_UNKNOWN` / `SELLABLE_QUANTITY_UNKNOWN` | 事实为空并阻断依赖交易；不得为零 |
| `MAX_POSITION_EXCEEDED` / `INSUFFICIENT_SELLABLE_QUANTITY` | 已知交易保护不满足；保留精确请求数量 |
| `TRADE_RULE_CONFLICT` / `CONFLICT_INPUT_UNKNOWN` | 保留全部规则证据，仅抑制受影响交易 |
| `RULE_ALREADY_EMITTED` | 可见重复抑制，不是行情错误 |
| `STATE_REVISION_CHANGED` | 中止事务并按新输入重算；无部分提交事件 |
| `UNSUPPORTED_BACKTEST_PLAN_VERSION` | 既有回测 runner 只支持旧模式时，拒绝 v3 研究成交任务 |

## E10. 交付分片与验收

R09 负责 v3 领域/编解码分派、改共享模型前保护旧提示词、精确均量/区间求值、首个合格 BUY、已知持仓、重复状态、被消费状态保护，以及足以离线验证 BUY 的结果/outbox 接线。R10 增加普通 SELL 和纯 RISK_ALERT、全部审核冲突/多意图、统一批次/期初余额减记，并保留旧风险回归。R09 与 R10 已面向隔离且明确的可信审核输入实现并验证。R11 已通过独立 v4 解析器/提示词、类型化部分草稿持久化、双向原文映射、服务端派生必审问题及精确当前内容重审完成实现。R12 负责普通表单、明确政策选择、完整预览和权威缺失状态展示。公开 Schema v3 保存与复核现已可用，而导入和启用在 R12 实施并验证前仍保持阻断；因此 `GET /plan-capabilities` 继续返回 `publicActivationAvailable=false`，并只报告 `ORDINARY_PLAN_FORMS` 待完成。

必需测试预期、精确消费位置和待确认业务项见 [R08 映射](../../../remediation/R08-mapping.zh-CN.md)。R13 独立从未改动原文出发，把新增人工确认 fixture 输入单独标记。原文没有政策时，仅原文提取必须保持阻断；补齐的合成测试 fixture 必须证明每项新增政策为何已知。除非另有版本化回测契约支持本模式，否则离线回放不生成研究模拟成交。R14 真实供应商/用户可见证据仍须另行授权，且尚未验证。
