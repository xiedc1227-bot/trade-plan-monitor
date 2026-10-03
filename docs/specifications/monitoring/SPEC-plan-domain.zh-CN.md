# 冻结计划领域与重放兼容性

> 冻结 Schema 1–4 兼容参考。新实时提取、审核、启用和模拟使用[单一交易计划流程](SPEC-unified-plan.zh-CN.md)、Schema 5 和 `plan-extract-v9`。下文模型与规则语义仅供历史读取和隔离研究重放，不开放旧实时命令，也不授权启用。既有字节、哈希、审核证据及研究身份必须保持不变。

## 公共契约

### 版本化计划

```python
class TradePlan(BaseModel):
    schema_version: Literal[1]
    plan_id: str
    version: int
    symbol: str
    name: str
    market: Literal["SSE", "SZSE", "BSE"]
    metadata: PlanMetadata
    activation: ActivationPolicy
    position: PositionPolicy
    levels: PriceLevels
    entry: EntryPolicy
    reduction: ReductionPolicy
    risk: RiskPolicy
    blockers: BlockerPolicy
    monitoring: MonitoringPolicy
```

激活策略使用带判别字段的联合类型：

- `MANUAL`：持续有效，直到用户明确停用。
- `TRADING_DAY`：只在指定交易日有效。
- `DATE_RANGE`：在起止日期内有效，并以交易日历为准。

`activation_is_eligible_on` 是回放与生产共用的正式日期策略。它使用求值目标携带的市场日期，
而不是延迟任务或重启恢复发生时更晚的墙钟时间。`TRADING_DAY` 按日期精确匹配，
`DATE_RANGE` 两个端点均包含；`MANUAL` 在明确停用前始终有资格。

同一股票最多只有一个活动版本。编辑活动版本时必须生成新草稿，激活新版本时原子地停用旧版本。

### 白名单条件 DSL

监控条件只能是类型化数据，不能是表达式字符串。Schema v1 支持：

- `PRICE_IN_ZONE`
- `NO_NEW_LOW_FOR_BARS`
- `NON_DECREASING_CLOSE`
- `VOLUME_TO_PREVIOUS_LTE`
- `VOLUME_TO_MEDIAN_LTE`
- `VOLUME_TO_MEDIAN_GTE`
- `MACD_HIST_IMPROVEMENT_GTE`
- `PRICE_RECLAIMS_INDICATOR`
- `UPPER_WICK_RATIO_GTE`
- `RETREAT_FROM_SESSION_HIGH_GTE`
- `CLOSE_IN_BAR_LOWER_HALF`
- `CONSECUTIVE_CLOSES_BELOW_LEVEL`
- `OFFICIAL_CLOSE_BELOW_LEVEL`
- `NEXT_TRADING_DAY_RECOVERY`
- `POSITION_BUCKET_AVAILABLE`
- `SELLABLE_QUANTITY_GTE`
- `MANUAL_EVENT_RISK_CLEAR`
- `DISTANCE_FROM_LIMIT_DOWN_GTE`
- `LOWER_BAND_HITS_LTE`

每种条件都有独立的 Pydantic 模型和参数范围。逻辑组合只允许 `ALL` 与 `ANY`，最大嵌套深度为 4，单份计划最多 50 个叶子条件。

`VOLUME_TO_MEDIAN_LTE` 使用 `max_ratio`；`VOLUME_TO_MEDIAN_GTE` 使用 `minimum_ratio`。两者均将最新完整 K 线成交量与指定数量的此前完整 K 线成交量中位数比较。`SELLABLE_QUANTITY_GTE` 必须同时明确 `bucket`（`CORE` 或 `TACTICAL`）和整手 `quantity`，因此一个仓位桶的可卖数量绝不能满足另一个仓位桶的可卖规则。

`PRICE_IN_ZONE` 使用最新有效规范完整分钟收盘价。`PRICE_RECLAIMS_INDICATOR` 将当前精确 5 分钟周期内的每个相邻分钟对与同一个所选当前日期指标值比较，要求至少一个分钟对满足 `previous_price < indicator <= current_price`，且周期结束价仍位于指标之上或与其相等；进入周期时已经位于指标上方不算重新站上。`LOWER_BAND_HITS_LTE` 将每根所选完整 5 分钟 K 线收盘与相同 identity 的 `ta-v1` 5 分钟下轨点逐一比较，并把相等计为命中。`CONSECUTIVE_CLOSES_BELOW_LEVEL` 本身只要求配置数量的相邻完整 K 线收盘严格低于命名价位。压力专用的触价后资格由后续 T023 编排施加，不是隐藏的叶子参数。

配置中的四种压力拒绝备选共同构成不能站稳的完整定义；Schema v1 不新增第五个压力条件。

未知条件、任意公式、脚本、SQL、字段路径、动态导入或外部接口调用均为非法输入。

### 校验规则

校验范围包括：

- A 股代码格式及交易所一致性；
- 合法最小价位、价格精度和整数手数；
- `0 < core_target_qty + tactical_target_qty <= max_qty`；
- 可执行价格区间互不重叠，开闭边界明确；
- 风险线和压力参考价处于合理配置范围；
- 窗口、比例、超时和 K 线数量均为正数且有上限；
- 只使用受支持的指标公式版本与时间周期；
- 激活日期字段完整；
- 每项条件需要的行情证据都能由 `market-data` 提供；
- 激活时不存在未解决的重大 AI 警告或未映射原文。

校验结果统一包含 `code`、`path`、`severity`、`message` 和 `activationBlocking`。错误禁止保存；普通警告允许保存草稿，但激活阻断警告必须先处理。

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
