# 规格：decision-engine（确定性决策引擎）

> 中文审阅版。英文权威版为 `SPEC-decision-engine.md`；两份文档必须保持语义一致。

## 目标

使用一份活动计划、一个不可变行情快照和一个策略状态快照，返回可解释判断及拟执行状态迁移，全程不执行 I/O。相同输入必须始终产生相同结果，以支持测试、回放和审计。

该引擎是价格区间、确认条件、阻断项、仓位约束、压力减仓和收盘风险的唯一权威。AI 和 Vue 前端不得复制这些规则。

## 技术栈

- Python 3.14.x（`>=3.14,<3.15`）
- 来自 `plan-domain`、`market-data`、`strategy-state` 的不可变 dataclass/Pydantic 值对象
- 纯函数与 pytest 表驱动测试
- 整数“分”价格比较

## 命令

```powershell
python -m pytest tests/unit/test_decision_engine.py -q
python -m pytest tests/replay/test_decision_replay.py -q
python -m ruff check src/trade_plan_monitor/decision tests/unit/test_decision_engine.py tests/replay
```

## 项目结构

```text
src/trade_plan_monitor/decision/
├── models.py       # 判断上下文、结果、证据和迁移意图
├── conditions.py   # 类型化条件计算器
├── episodes.py     # 低吸事件状态迁移
├── risk.py         # 官方收盘风险迁移
└── engine.py       # 优先级和 evaluate 入口
tests/unit/
└── test_decision_engine.py
tests/replay/
└── test_decision_replay.py
```

## 冻结重放范围

下文单结果、episode、CORE/TACTICAL、低位及正式收盘规则描述冻结 `LEGACY_LOW_BUY` 研究/兼容行为。归并后的[冻结计划参考](SPEC-plan-domain.zh-CN.md) 保留 Schema 1–3 模型及准确显式规则算术/结果身份；Schema 4 读取器保留原存储含义。既有结果哈希和回测输入遵循 [ADR 0005](../../decisions/0005-version-explicit-plan-rules.zh-CN.md)。

当前 Schema 5 条件、确认、纯提醒规则及隔离模拟遵循[单一交易计划流程](SPEC-unified-plan.zh-CN.md)。旧策略要求不能成为当前计划的默认值或额外阻断。任何冻结格式都不能通过当前服务启用或模拟。

## 公共契约

```python
def evaluate(context: EvaluationContext) -> EvaluationResult:
    """纯函数判断：不访问数据库、网络、系统时钟、日志或随机数。"""
```

`EvaluationContext` 显式包含判断时间、活动计划及哈希、完整 K 线、指标与公式版本、实际涨跌停、数据健康、持仓、当前低吸/风险状态和交易日历事实。

`INTRADAY` 目标通过不可变 tuple 提供 `current_day_minutes`；该 tuple 必须精确包含从目标交易日首个规范分钟结束时间到 `target.bucket_end`（含两端）的全部规范完整 `MinuteBar`，且最多 240 个值。序列必须严格递增、同一股票、同一日期，并按照交易日历及规范午休边界保持完整。任何声称盘中数据完整的上下文都必须包含日期匹配且开市的目标日 `TradingDay`；目标日行缺失或休市时不能认证该切片。“分钟价格”、“当前价”和“最新有效价格”均指其最后一根 K 线的 `close_fen`；未完成分钟、系统时钟值、`DailyBar.close_fen` 或另行查询的报价均不合格。所需分钟证据缺失、重复、非规范、过期、来自未来、股票混合或目标不匹配时均失败关闭。结构性 5 分钟条件仍使用完整 `FiveMinuteBar`。

判断标识表示请求的目标，并不制造行情证据。因此，盘中阻断结果可以同时不包含 `market_data_at` 和 `price_fen`。二者存在时，必须表示 `target.bucket_end` 当时或之前最新的真实已认证完整分钟；新鲜且完整的目标必须精确使用 `target.bucket_end`。官方收盘结果只能使用规范 15:00 截止时间的已认证核对官方收盘，否则二者都为空。

`ta-v1` 价格型指标字段使用有限浮点元；`rsi14` 是 0～100 的无量纲值。上下文必须保留窗口不足时的明确 `None`；任何所需指标缺失都会阻断判断，不能推断或替代。

每个当前日期日线指标输入都必须携带显式 `PROVISIONAL` 或 `OFFICIAL` provenance 以及准确的 `source_as_of`。对于 `INTRADAY` 目标，买入动能与重新站上证据使用此前日期官方日线，加上截至 `target.bucket_end` 的唯一确定性当前日期临时日线聚合，且 `source_as_of == target.bucket_end`。截至 15:00 的聚合仍是临时值。对于 `OFFICIAL_CLOSE` 目标，持续恶化证据仅在 `advance_close_risk=True` 时使用核对后的 `official_bar`，provenance 为 `OFFICIAL`，来源截止时间为规范 15:00。股票、交易日、公式版本、provenance、来源截止时间和核对来源必须一致。provenance 缺失、混合、过期或不匹配均失败关闭。证据必须记录 provenance 和来源截止时间；临时证据绝不能推进官方收盘风险或官方持续恶化判断。

`EvaluationResult` 包含：

- 一份权威 `SymbolDecisionSnapshot`；
- 零到多个 `StateTransitionIntent`；
- 零到一个可操作 `SignalIntent`；
- 已满足证据、未满足证据、阻断项和数值事实，使用 DSL `ConditionEvidence` 与非 DSL `RuleEvidence` 的有界联合类型；
- 下一步观察或动作；
- 判断唯一标识和确定性结果哈希。

`RuleEvidence` 保留稳定代码、满足或非满足 outcome、最多 16 个有序强类型事实和最多 4 个显式缺失输入代码，且不虚构条件 DSL 标签。T024 将五种 T022 结构记录以及 `PLAN_INACTIVE`、`PRESSURE_TOUCH`、`RISK_RECOVERY`、`RISK_DETERIORATION` 映射到该共享结果证据，且不重新计算其事实。

运行时在一个事务中应用迁移意图并写入提醒意图。

T038 诊断判断是该同一公共 `evaluate(context)` 契约的只读应用服务用法。请求必须指定恰好一个规范盘中五分钟目标或一个官方收盘交易日，以及预期来源修订。应用服务响应保留未经改变的规范 `EvaluationResult`；HTTP 适配器在投影权威判断前重新校验其自认证 `resultHash` 和内嵌 evaluation identity。内嵌的 `planHash`、股票、kind、强类型目标和 `formulaVersion` 必须同时匹配该结果与请求，且不应用迁移意图、不认领判断账本、不入队提醒、不修改持仓、不读取时钟，也不调用供应商。适配器不能改变优先级、重算结果 hash 或构造第二个判断。唯一可选写入是明确报告的诊断审计。

## 判断优先级

1. 目标全局数据不可用时返回 `BLOCKED_DATA`。
2. 判断适用的官方收盘风险迁移。
3. 判断适用的机动仓压力减仓。
4. 应用仅限买入的阻断项，其中 `BLOCKED_DATA` 优先于 `BLOCKED_RISK`。
5. 判断低吸底仓/机动仓买入信号。
6. 返回 `LOW_ZONE_WATCH` 或中性/区间外 `WAIT`。

适用性由目标类型决定：`INTRADAY` 判断压力和低吸编排，`OFFICIAL_CLOSE` 判断官方风险并保留传入的事件状态。不适用的计算器不得产生人为缺失输入阻断。仅限买入的阻断项绝不能压制降低风险敞口的压力减仓或官方风险动作。

`DATA_NOT_READY`、`DAILY_LIMIT_UNKNOWN`、`EPISODE_HISTORY_GAP` 以及候选动作适用的 DSL `MISSING_INPUT` 证据映射为 `BLOCKED_DATA`。`BEARISH_VOLUME_EXPANSION`、`RISK_PENDING` 以及已知买入安全或仓位可用性失败证据映射为 `BLOCKED_RISK`。逻辑 DSL 根节点保留其已校验的三值语义：已 `SATISFIED` 的 `ANY` 不会因另一备选缺失而被阻断。如果一个处于活动阻断状态的未满足买入安全树同时包含已知失败和嵌套缺失输入，则应用数据优先级，并在 `next_step` 中保留该缺失输入。未激活计划返回 `WAIT`，不创建迁移或信号意图，保留 `PLAN_INACTIVE` 证据，并以 `REVIEW_BLOCKER` 作为下一步。

高优先级结果会压制低优先级信号，但仍保留全部低优先级证据用于界面展示。若压力减仓压制同时满足的买入，返回的事件迁移必须以 `ACTIVE` 保留推导出的低点与游标且不携带已提醒信号；不得以 `ALERTED` 消耗该买点。后续目标周期可以再次判断该活动事件。

## 信号类型

- `WAIT`
- `LOW_ZONE_WATCH`
- `BLOCKED_DATA`
- `BLOCKED_RISK`
- `BUY_CORE_READY`
- `BUY_TACTICAL_READY`
- `PRESSURE_REDUCE_READY`
- `RISK_BREACH`
- `RISK_RECOVERED`
- `RISK_EXIT_READY`
- `RISK_EXIT_PENDING_SETTLEMENT`

默认只有 `BUY_*_READY`、`PRESSURE_REDUCE_READY`、`RISK_BREACH` 和 `RISK_EXIT_*` 产生文字提醒。普通 `WAIT` 和观察进度只更新界面。

## 华亚智能计划规则

### 价格区间

- 低吸区：`[63.00, 64.50]`。
- 观察区：`(64.50, 68.80)`。
- 压力区：`[68.80, 70.20]`。
- 风险线：官方收盘低于 `60.80`。
- 64.50 只属于低吸区，68.80 只属于压力区。

只有规范完整分钟收盘价满足区间 inclusion flags 时才算触及区间。首个命中分钟的 `MinuteBar.bar_end` 为 `touch_at`；仅分钟内高点/低点触及、价格跳过整个区间但没有分钟收盘落入区间，以及未完成分钟均不计为触及。

### 低吸事件

1. 分钟价格首次触及低吸区时建立事件，触价本身不产生买入提醒。
2. `episode_low` 是事件开始后的最低价。
3. 后续完整 K 线低点至少低一个最小价位时，确认进度清零。
4. 最近最低点之后至少两根完整 5 分钟 K 线不创新低，且后一根收盘不低于前一根。
5. 最新成交量不高于前一根，并且不高于此前 20 根中位数的 1.5 倍。
6. 临时日线 MACD 柱改善至少 0.02，或者最新有效价格重新站上日线 EMA10。
7. 所有阻断项均已解除。
8. 没有底仓时可产生一次 100 股 `BUY_CORE_READY`；已有底仓且出现后续独立事件时可产生一次 100 股 `BUY_TACTICAL_READY`；总仓位不超过 200 股。
9. 未提醒事件离开低吸区两根完整 5 分钟 K 线后关闭。已提醒事件保持去重，必须重新进入形成新事件才能再次提醒。

每个事件快照都必须携带 `last_processed_bucket_end`，并表示为 `Asia/Shanghai` 下规范的完整 5 分钟边界。触价周期初始化游标，并仅使用触价收盘以及该周期内触价后的分钟建立 `episode_low`；触价周期不计为确认 K 线。已有 `ACTIVE` 或 `ALERTED` 事件按顺序恰好消费 `(last_processed_bucket_end, target.bucket_end]` 内连续的 K 线。整数分低点严格降低时确认进度清零，低点相等时只推进一次；每个成功消费的目标都推进游标，即使确认进度已饱和或事件已经提醒。`target.bucket_end == last_processed_bucket_end` 是完全无操作：较晚到达的事实不能为已消费周期产生迁移或信号。若在较晚目标首次发现更早触价，同一次判断必须追赶处理至该目标。缺少游标锚点、中间 K 线缺失或无法证明跨交易日相邻关系时失败关闭，且不推进游标。

对于已关闭事件，`last_processed_bucket_end` 精确等于触发关闭的第二根连续区外收盘 K 线。重新进入只搜索严格晚于该关闭游标的分钟收盘，并创建不同的确定性事件 identity。因此恢复处理可以在关闭边界结束旧事件，再把更晚的重新进入作为新事件处理，而不会重放已消费 K 线。

`PRICE_RECLAIMS_INDICATOR` 表示穿越事件，而不是“当前已在指标上方”的状态。必须从 `current_day_minutes` 中选择当前判断周期恰好五个规范完整分钟，并将每个相邻分钟对与同一个所选当前日期日线指标值比较。仅当至少一个分钟对满足 `previous_close_fen / 100 < indicator_yuan <= current_close_fen / 100`，且周期结束分钟仍满足 `bucket_end_close_fen / 100 >= indicator_yuan` 时才满足。穿越时当前价或周期末当前价等于指标算满足；前一价等于指标不算从下方穿越。任一周期分钟或指标缺失时为缺失输入；证据完整但周期内没有穿越，或周期结束价低于指标时为不满足。进入周期时已经位于指标上方不算重新站上。

有限十进制事实与结果比较不依赖外部 Decimal context。整数分转元使用精确两位系数移位；偶数个整数成交量的中位数保留精确半股值；有限阈值乘法和减法保持精确。只有确实不能终止的展示用比例证据使用规范的 50 位有效数字、half-even context；对应结果通过精确系数乘法与 Decimal 直接比较决定，不展开整数比率。

### 买入阻断项

- 所需行情过期或不完整；
- 交易日历或实际涨跌停价未知；
- 阴线 5 分钟成交量超过配置中位数倍数；
- 当前价过于接近实际跌停价；
- 沿布林下轨运行；
- 人工事件风险标记；
- 风险线跌破待确认；
- 指标无效或缺失；
- 已达到最大仓位。

T022 在 DSL 证据之外返回有界结构性阻断记录，使后续结果组装能够保留阻止动作的原因。稳定代码为 `DATA_NOT_READY`、`DAILY_LIMIT_UNKNOWN`、`EPISODE_HISTORY_GAP`、`BEARISH_VOLUME_EXPANSION` 和 `RISK_PENDING`；每条记录都包含非满足 outcome、明确的数值/状态事实，并在 outcome 为 `MISSING_INPUT` 时包含所需缺失输入代码。仅当最新完整 5 分钟 K 线收盘低于开盘，且成交股数严格超过显式合取 `ALL` 买入路径上的 `VOLUME_TO_MEDIAN_LTE` 阈值时，`BEARISH_VOLUME_EXPANSION` 才生效；位于任一 `ANY` 备选下的阈值不是全局阻断。等于阈值或阳线均不激活该结构阻断。华亚样例 blocker 树保持为有序 `ALL`：`MANUAL_EVENT_RISK_CLEAR`、`DISTANCE_FROM_LIMIT_DOWN_GTE(minimum_ratio=0.01)` 和 `LOWER_BAND_HITS_LTE(max_hits=2, window_bars=4)`。T024 负责把这些记录映射为最终 `BLOCKED_DATA`/`BLOCKED_RISK` 结果优先级，不改变 T022 事件进度。

### R07 人工事件风险确认

`MANUAL_EVENT_RISK_CLEAR` 由一条可持久化、可审计的确认记录支持；其范围同时限定为单只股票、当前已启用不可变计划的内容哈希和包含边界的到期交易日。其权威输入严格为三态：明确 `CLEAR` 投影为 `False`，明确 `RISK_PRESENT` 投影为 `True`，缺失、计划已变更、已到期或在 cutoff 后才确认的记录投影为 `None`。`None` 必须保持未知并失败关闭，绝不能默认或强制转换为 `False`。

生产 context 在构造 `EvaluationContext` 前，使用与计划及风险事实相同的 SQLite 工作单元读取该记录。精确计划哈希变更、到期或确认晚于 cutoff 会使输入变为未知；相同哈希且范围仍有效时，重启保留持久确认。R07 的哈希包含计划版本，不是 R08 新增的语义 `contentHash`。每次被接受的确认都会记录 revision、确认时间、到期日期、状态、计划哈希和审计动作；乐观 revision 与幂等机制使同一语义命令的重试返回原有回执，而不产生第二条审计事件。该记录不是官方收盘风险确认，不能削弱该独立且失败关闭的状态。

`LOWER_BAND_HITS_LTE` 选择截至判断目标的最近 `window_bars` 根相邻完整 5 分钟 K 线。每根 K 线必须恰好对应一个具有相同 `(symbol, bar_end, formula_version)` 的 `ta-v1` 5 分钟 `IndicatorPoint`。当 `bar.close_fen / 100 <= point.boll_lower_yuan` 时记一次命中；相等也算命中。禁止复用同一个下轨、使用日线下轨、向前填充，或仅按位置而不核对 identity 对齐。下轨证据缺失、重复、错位或为 `None` 都会阻断判断；否则仅当 `hit_count <= max_hits` 时满足。

`RETREAT_FROM_SESSION_HIGH_GTE` 要求经过认证且无缺口的当日分钟切片。它使用截至目标的全部完整当日 K 线与分钟中的最高价，并且仅在 `(session_high_fen - latest_close_fen) / session_high_fen >= minimum_ratio` 时满足；缺少当日历史时返回 `SESSION_BARS`。任何跨交易日的滚动 5 分钟窗口都必须根据所提供的有界交易日历历史证明相邻关系。缺少当前日期日历行时返回 `TRADING_CALENDAR`；已知日历错配仍属于不完整 K 线窗口。

### 压力减仓

价格必须触及压力区，满足 `SELLABLE_QUANTITY_GTE(bucket=TACTICAL, quantity=100)`，并至少满足以下四种拒绝形态之一。这四种备选形态本身就是“不能站稳压力参考价上方”的完整操作定义；不再要求额外的共同压力收盘条件：

- 上影线占 K 线振幅至少 40%；
- 从当日高点回落至少 1%；
- 满足 `VOLUME_TO_MEDIAN_GTE(minimum_ratio=1.5, window_bars=20)` 且收于 K 线下半部；
- 触价后连续两根完整 K 线收在压力参考价下方。

压力编排根据 `current_day_minutes` 推导出 `pressure_touch_at`。对于 `CONSECUTIVE_CLOSES_BELOW_LEVEL` 替代项，T023 仅选择满足 `bar_end > pressure_touch_at` 的相邻完整 5 分钟 K 线；结束时间相等不属于“之后”。包含更早触价分钟的 K 线可以计数，但结束时间相等、触价前、上一交易日、不完整或不相邻 K 线不能计数。计数 K 线的收盘必须严格低于参考价；等于参考价不满足该备选。其余三种备选可以使用包含触价分钟的完整 K 线。`CONSECUTIVE_CLOSES_BELOW_LEVEL` 仍是通用叶子；触价筛选属于 T023 编排，不是隐藏的 T021 叶子行为。

没有持仓或只有底仓时，只展示压力证据，不产生减仓提醒。

### 官方收盘风险

- 未激活计划绝不创建、清除或推进风险状态。
- 盘中价或临时收盘低于 60.80 不推进风险状态。
- 经核对的官方收盘在已认证开市目标日首次低于 60.80 时产生 `RISK_BREACH`，禁止加仓，并记录原始跌破交易日与收盘价。
- 任一后续已认证开市交易日的经核对官方收盘回到 60.80 及以上时产生 `RISK_RECOVERED` 并清除状态。新建的 `EXIT_PENDING_SETTLEMENT` 状态不会在其转换当日再次解析。
- 若后续官方收盘仍低于 60.80，风险退出还要求相对原始跌破日基准继续恶化：收盘不高于原始跌破日收盘，且成交量不低于原始跌破日成交量或日线 MACD 柱未较原始跌破日改善。基准证据缺失、不一致或并未真正跌破时均失败关闭。
- 退出首先选择剩余量充足的最新机动仓，否则选择剩余量充足的最新底仓；“最新”按买入交易日降序，同日以 `lot_id` 升序打破平局。至少剩余一个计划手数的仓位才合格。
- 若该首选仓位受 T+1 限制，则产生 `RISK_EXIT_PENDING_SETTLEMENT`，且不替换为更早仓位或底仓。后续已认证开市日按相同确定性优先级重新计算；首选目标可卖后产生 `RISK_EXIT_READY`，不新增风险状态。

## 幂等标识

- 盘中判断：`(plan_hash, symbol, completed_5m_bucket_end, formula_version)`。
- 收盘判断：`(plan_hash, symbol, official_trade_date, formula_version)`。
- 提醒：`(plan_hash, trading_date, signal_type, episode_or_risk_transition_id, quantity)`。

重复行情、恢复行情或重启只能补充证据，不能产生第二个相同动作。

纯结果将 `INTRADAY` 与 `OFFICIAL_CLOSE` 保留为显式带判别器的标识类型，因此盘中 15:00 目标与同日官方收盘不是同一个标识。T024 不修改持久化。在 T032 可以认领两类标识之前，判断账本必须通过单独审批增加无损的持久化 kind 判别器；禁止复用盘中 15:00 时间戳表示官方收盘。

## 规范结果哈希

结果哈希前像依次为 ASCII 域 `decision-result-v1`、一个 NUL 字节，以及包含 `EvaluationResult` 除 `result_hash` 外全部字段的紧凑规范 JSON。对象键按字典序排序，数组顺序保持不变，JSON 不含无意义空白，完整前像使用 UTF-8。枚举使用其值，日期和 `Asia/Shanghai` 时间戳使用规范 ISO 形式。有限 Decimal 的正负零均写为 `0`；其他值在去除系数尾零后写为 `<可选负号><系数>e<十进制指数>`，因此 scale、宿主 Decimal context 和负零均不能改变哈希。有效系数最多 10,000 位，并拒绝非有限数。保存值为完整的小写 SHA-256 十六进制摘要。

构造和经过校验的复制更新都会重新计算或验证该摘要，因此任何语义字段变化后结果都不能保留过期哈希。规范完整结果序列化包含 `result_hash`，使用相同 JSON 规则但不添加哈希域前缀。除 `result_hash` 外的每个字段——包括 `evaluated_at`、迁移、证据顺序、下一步和标识 kind——都参与摘要。

压力与风险使用不同的 SHA-256 cause 域。压力 cause 由 `plan_hash`、`symbol` 和首次认证的 `pressure_touch_at` 推导；风险 cause 由 `plan_hash`、`symbol` 和原始 `breach_trade_date` 推导。重放保持相同 cause，且 `RISK_EXIT_PENDING_SETTLEMENT` → `RISK_EXIT_READY` 保留原始风险 cause。

## 代码风格

```python
def evaluate_condition(
    condition: Condition,
    context: EvaluationContext,
) -> ConditionEvidence:
    evaluator = CONDITION_EVALUATORS[type(condition)]
    return evaluator(condition, context)
```

每种 DSL 条件使用独立计算器并返回证据，不修改状态，避免巨型嵌套条件。

## 测试策略

- 覆盖全部信号、阻断项、价格边界和优先级冲突。
- 验证触及低吸区不提醒，创新低会清零。
- 验证持久化游标追赶、低点相等只推进一次、同目标无操作、缺口/日历失败关闭、饱和及已提醒游标推进、精确关闭游标，以及严格晚于关闭游标的重新进入。
- 验证每个结构阻断代码、outcome、缺失输入及数值/状态事实，包括阴线放量的相等与多一股边界。
- 覆盖 64.50、68.80 和一分钱边界变化。
- 覆盖底仓优先、最大仓位、T+1 和只有底仓时不减仓。
- 覆盖首次风险跌破、收回、尚未恶化、恶化退出、官方日线延迟和受限仓位。
- 覆盖精确或缺失的 `current_day_minutes`、分钟收盘价格事实、周期内每个可能位置的重新站上穿越及周期末保持或失守、按时间对齐的下轨相等边界、指标 provenance，以及通用严格低于的连续收盘证据。
- 在 T023 中覆盖压力触价推导、触价前/同时/触价后 K 线资格、包含触价分钟的 K 线、全部四种不能站稳备选，以及不得推断第五个条件。
- 覆盖含缺失备选但已满足的 `ANY`，以及同时包含已知风险和缺失数据证据的未满足买入安全树。
- 重复运行相同上下文并比较结果哈希。
- 覆盖 Decimal 的规范 scale/符号/context 边界、10,000/10,001 位有效系数边界、过期哈希拒绝和证据顺序敏感性。
- 回放有效买点、持续下跌、行情过期、重复/恢复行情、同目标重启和独立事件。

## 边界

- 始终：上下文显式提供时间、日历和行情事实。
- 始终：每个结果返回完整证据和下一步。
- 先确认：新增信号、修改优先级或改变华亚智能阈值。
- 禁止：访问数据库、调用 Tushare/AI、渲染文字、发送通知或读取系统时间。
- 禁止：修改输入状态或推断成交。
- 禁止：运行时解释含糊的计划原文。

## 验收标准

- 相同输入产生字节稳定的规范化结果和哈希。
- 一个有效低吸事件最多产生一次买入意图。
- 每个动作都能从保存的数值证据解释。
- 行情或参考数据缺失、过期、不完整时按股票失败关闭。
- 风险和 T+1 行为符合交易计划与交易日历。
- 10 只股票状态完全隔离。

## 待确认事项

无阻断事项。阈值均属于计划版本数据，修改时必须生成新版本。
