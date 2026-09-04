# 规格：backtest（历史数据与确定性交易回测）

> 中文审阅版。英文权威版为 `SPEC-backtest.md`；两份文档必须保持语义一致。

## 目标

提供可在非开市时间准备和运行的确定性 A 股回测。经明确授权的 `backtest sync` 操作把 Tushare/QuickSync 历史数据增量下载到隔离的行情 SQLite 数据库；`backtest verify` 冻结精确、按内容寻址的 `dataset_hash`；`backtest run` 只消费该冻结本地数据集、经审核计划和显式成交假设，不访问网络，也不依赖墙上时钟休眠。

回测复用生产计划、行情规范化、指标和纯决策契约，只为研究新增隔离且版本化的模拟成交模型。它绝不发送订单、修改实时监控状态，也不声称历史 `stk_mins` 能证明实时 `rt_min` 或 `rt_min_daily` 契约。

## 已批准的范围变更

用户于 2026-08-25 批准本模块，使历史数据验证和交易计划研究不受开市时间阻断。这是对原“禁止模拟订单”边界的窄例外：

- 实时监控仍然只提醒，绝不推断成交；
- 模拟成交只存在于显式 `BACKTEST` 模式和隔离数据库中；
- 券商连接、基于实时行情的模拟盘、自动下单、杠杆和卖空仍不在范围内；
- 任务 `T058` 仍是独立实时行情契约闸门，任何历史回测结果都不能把它标记完成。

## 模块拆分

`backtest` 继续作为稳定总标识和现有 CLI MVP 的兼容归属。已于 2026-08-26 批准的能力地图把下一版本拆成六个可独立审核的模块，并按依赖顺序实现：

1. [`backtest-data`](SPEC-backtest-data.zh-CN.md) — 经授权的历史获取、不可变修订、覆盖、校验与冻结 `dataset_hash`；
2. [`backtest-engine`](SPEC-backtest-engine.zh-CN.md) — 针对一个经审核计划版本和一只股票的确定性事件时间回放与 `execution-model-v1`；
3. [`backtest-results`](SPEC-backtest-results.zh-CN.md) — 不可变已完成结果发布、有界查询/导出、保留与置顶；
4. [`backtest-jobs`](SPEC-backtest-jobs.zh-CN.md) — 持久化异步提交、进度、取消与崩溃恢复；
5. [`backtest-api`](SPEC-backtest-api.zh-CN.md) — 类型化 REST 资源、幂等、分页与生产组合；
6. [`backtest-web`](SPEC-backtest-web.zh-CN.md) — 面向数据准备、提交、进度和结果审阅的无障碍 Vue 工作流。

能力地图和模块方向已经批准，用户已于 2026-08-26 确认链接的详细规格集合。双语跨模块一致性审计修正了 UUID/CLI 查找 identity、精确金额/时间投影、旧结果复用、增量导出、发布大小及变更幂等条款，且不改变已批准边界。用户已于 2026-08-26 确认这些修正契约，因此聚合详细规格现按修正内容获批。第 15 节与 `BT009`～`BT050` 的授权历史早于现已完成的离线实现。当前 Web/API 表面使用冻结的 42 路径契约，WEBF13 在不改变该契约的前提下完成路由/旅程验收。提交、推送、依赖安装和真实联网访问继续需要分别授权；现有 `BT001`～`BT008` 仍保留为本地 MVP 历史，不作重标。

## 命令

已实现的 CLI 界面明确独立，不与现有 `replay` 命令重叠：

```powershell
python -m trade_plan_monitor backtest sync --symbols 003043.SZ --start 2025-01-02 --end 2025-12-31 --allow-network
python -m trade_plan_monitor backtest verify --symbols 003043.SZ --start 2025-01-02 --end 2025-12-31
python -m trade_plan_monitor backtest run --dataset <dataset_hash> --plan config/plans/003043.SZ.sample.yaml --initial-cash-yuan 100000 --commission-rate 0.0003 --minimum-commission-yuan 5 --stamp-duty-rate 0.0005 --transfer-fee-rate 0.00001 --buy-slippage-bps 2 --sell-slippage-bps 2 --no-event-risk
python -m trade_plan_monitor backtest list --limit 20 --offset 0
python -m trade_plan_monitor backtest prune --batch-size 1000
```

只有 `sync` 允许使用网络和 `TUSHARE_TOKEN`，并且同时需要用户明确授权和字面量 `--allow-network` 参数；`verify`、`run`、`list` 和 `prune` 均仅限本地。`sync` 与 `verify` 默认把 `warmup_start` 设为 `start` 之前 400 个日历日；显式覆盖时，两条命令必须使用相同值。数据集未冻结并验证、六项费用/滑点输入未全部提供，或没有恰好选择 `--no-event-risk` 与 `--manual-event-risk` 之一时，`run` 必须失败。上述数值只是示例假设，不是默认值。当前 `replay` 命令保留既有监控事件语义。

`OfflineBacktestRunner` 会把不可变 `initial_lots` 纳入 `run_id`，但当前 CLI 只暴露 `--initial-cash-yuan`，因此传入空的初始持仓 tuple。经过校验的公共初始持仓输入/导入仍属于未完成验收工作。

## 架构与隔离

```text
Tushare/QuickSync
       │ 明确授权的 backtest sync；网络位于事务外
       ▼
backtest-market.sqlite3
  规范化不可变行修订 + 清单
       │ backtest verify → 冻结 dataset_hash
       ▼
离线事件时间回放 ──→ 现有纯决策引擎
       │               + BACKTEST execution-model-v1
       ▼
backtest-results.sqlite3
  运行摘要 + 判断 + 信号 + 成交 + 每日权益
```

三个存储域彼此隔离：

| 存储 | 负责 | 禁止保存 |
|---|---|---|
| 实时监控 SQLite | 活动计划、人工持仓、实时 K 线、判断、事件、风险、提醒、Outbox、监控事件、审计 | 回测数据集、模拟成交、回测权益 |
| `backtest-market.sqlite3` | 规范历史 artifact、不可变修订、当前 head、数据集 manifest/成员关系、`dataset_hash` | 实时状态、模拟成交、结果详情 |
| `backtest-results.sqlite3` | 不可变运行输入、摘要、判断、信号、成交/未成交原因、每日权益、保留元数据 | 复制的行情 K 线、实时状态、密钥 |

行情库和结果库路径必须解析为不同文件。创建 Schema 前，每个存储都必须拒绝包含实时表或另一回测存储域表前缀的既有 SQLite 数据库。回测数据库不进入实时监控在线备份。Web `BACKTEST_RUN` 提交可以打开一个只读实时存储事务，并且只读取恰好一个不可变计划版本。系统会校验该版本，并在响应前把规范计划快照随已接受请求持久化到 durable 边界；提交对实时存储执行零写入。该 durable 边界提交后，worker 与确定性回放对实时存储执行零读取和零写入。直接 CLI `backtest run` 通过显式 `--plan` 文件接收计划，在本地校验相同快照契约，并且绝不打开实时存储。最终 `BC01` 证据必须比较 Web 提交前后以及 worker/回放前后的精确实时逻辑状态，并断言通知调用次数为零；当前 MVP 尚未完成这些显式零差异验收测试。

## 历史供应商契约

历史获取使用独立接口，不能伪装成实时操作：

```python
class HistoricalMinuteProvider(Protocol):
    def historical_minute_batch(self, symbol: str, trade_date: date) -> HistoricalMinuteBatch: ...
    def historical_minutes(self, symbol: str, trade_date: date) -> tuple[MinuteBar, ...]: ...
    def trading_calendar(self, exchange: str, start: date, end: date) -> tuple[TradingDay, ...]: ...
    def daily_limits(self, trade_date: date) -> tuple[DailyLimit, ...]: ...
    def daily_bars(self, symbol: str, start: date, end: date) -> tuple[DailyBar, ...]: ...
```

Tushare 映射为 `stk_mins`、`trade_cal`、`stk_limit` 和不复权 `daily`。历史能力状态和时间戳标签语义独立于实时能力矩阵。历史能力就绪绝不能把 `rt_min` 或 `rt_min_daily` 改为 `READY`；历史能力被拒绝也绝不能阻断实时监控。

历史同步必须针对范围内存在的交易所分别显式请求 `trade_cal(exchange="SSE", ...)` 和 `trade_cal(exchange="SZSE", ...)`，绝不能依赖省略或空的 exchange 参数。Tushare 官方 `trade_cal` 契约未把 BSE 列为受支持交易所。因此任何 `.BJ` 范围都必须在联网或持久化前以稳定阻断原因 `UNSUPPORTED_HISTORICAL_CALENDAR:BSE` 拒绝。只有另行验证并批准 BSE 日历契约后才能支持北交所历史数据；这不影响实时计划领域继续识别 `.BJ`。

2026-08-25 经授权观察到 `600000.SH` 在 2026-08-24 的 `stk_mins` 返回 241 行，时间覆盖 09:30 至 15:00。供应商构造器继续以 `UNVERIFIED` 失败关闭。CLI 组合显式选择已实现的版本化契约 `TUSHARE_STK_MINS_241_END_V1`：它把 09:30 来源行保留为不参与策略的 `opening_special`，并要求其余结束标签行与现有 240 个规范交易分钟结束时间完全匹配。未知配置不能调用 SDK 或冻结数据集；任何实现都不能静默删除、平移或全部接受这 241 行。

## 增量同步

`backtest sync` 遵守以下不变量：

1. 获取前校验股票、闭区间日期范围、供应商能力、交易所日历和已配置的不复权价格策略。一个 `DatasetScope` 包含 1–10 只不重复股票，`start` 到 `end` 最多跨 5 个日历年，`warmup_start` 到 `start` 最多跨 2 个日历年；更大请求会在联网或持久化前失败。
2. 根据本地当前 head 计算缺失的股票/交易日/接口来源，只请求缺失来源或明确要求刷新的来源。每个已获取参考数据响应必须精确包含请求 identity：`trade_cal` 覆盖其显式交易所的每个日历日，`daily` 覆盖请求区间内每个预期开市日的 `(symbol, trade_date)`，`stk_limit` 覆盖每个请求开市日的 `(symbol, trade_date)`。identity 缺失、多余或重复时会在持久化前分别以 `INVALID_RESPONSE:trade_cal`、`INVALID_RESPONSE:daily` 或 `INVALID_RESPONSE:stk_limit` 失败；`--refresh` 绝不能用不完整响应替换完整 head。
3. 所有网络调用都位于 SQLite 事务之外。先校验有界供应商响应，再用短事务插入；单个持久化批次最多 1,000 行。
4. 使用稳定内容哈希。相同规范事实只保存一次；上游修订生成新的不可变修订，不能覆盖旧数据集使用的行。
5. 每个通过校验的供应商结果都在请求下一个来源前持久化，因此后续重试会跳过已有已提交 head。重复相同同步不会创建重复 artifact 或 head 修订。
6. 只保存脱敏的操作/错误元数据。Token 和原始授权/供应商响应体绝不持久化或打印。

真实 Tushare 历史参考适配器比实时部分健康路径更严格。任意无法解析行或重复 identity（即使内容相同）都会把整个原始来源作为脱敏 `INVALID_RESPONSE` 失败。各来源 identity 规则必须明确：`trade_cal` 拒绝其他交易所或超出请求范围的日期；`daily` 拒绝其他股票或超出请求范围的日期；市场全量 `stk_limit(trade_date)` 拒绝其他日期，但合法允许该日期的其他有效股票。同步层随后从市场全量涨跌停响应中选择本次请求的 `missing_symbols`，并独立要求该选集及每个日历/日线请求集合精确完整。历史持久化前不能静默丢弃任何非法原始行。

历史行情作为共享去重缓存长期保留。数据集引用精确不可变修订，绝不为每次运行复制同一批分钟行。结果自动清理不能删除被数据集或保留运行引用的行情修订。删除无引用历史行情必须通过显式离线维护操作。

## 数据集校验与标识

`backtest verify` 完全离线并且失败关闭，校验：

- 根据 `trade_cal` 检查精确股票/日期覆盖，包括周末、节假日、午休和规范 09:30/15:00 边界；
- 版本化历史标签映射，以及每个完整普通交易日恰好 240 条可用一分钟 K 线，除非显式表示交易所时段例外；
- 严格有序且唯一的 `(symbol, bar_end)` identity，并拒绝内容冲突的重复 payload；
- 带 `Asia/Shanghai` 时区的时间戳、合法整数分 OHLC、非负整数股数、精确 Decimal 元成交额和允许的 provenance；
- 实际 `stk_limit`、官方不复权 `daily`，以及从显式 `warmup_start` 到请求结束时间的完整参考数据覆盖。

跨模块时间契约只有一套：每个活动回测时间戳，包括行情事实、回放事件、任务生命周期、审计/幂等记录、结果发布、持久化、API 值和 Web 展示，都使用带时区的 `Asia/Shanghai`。输入只接受 `+08:00` 和 0～6 位小数秒，并在 identity 处理前规范化；规范持久化、哈希、Cursor 编码、输出和导出文本精确使用 `YYYY-MM-DDTHH:MM:SS.ffffff+08:00`。`Z`、无时区值、超过 6 位小数秒和其他偏移均校验失败。仅日期字段按中国市场日历解释，任何层都不得通过主机或浏览器时区转换已接纳值。

本地尚未提交的 MVP 当前包含部分 UTC 规范化行情元数据及结果/导出投影。排除在 `dataset_hash` 外的元数据只有在建立验证备份并证明数据集 identity 不变后才能迁移。参与 identity 的 UTC v1 结果/导出字节保持为不可变兼容 artifact；活动路径使用版本化 v2 中国时间结果/内容/导出投影，并且在另行批准采纳前，绝不通过新 API 暴露或复用 v1。

事实缺失、非法、冲突或语义未验证时产生稳定阻断项。内容损坏使用 `INVALID_<KIND>:<identity>:<date>`；交易所前序日历事实断裂使用 `INVALID_CALENDAR_CHAIN:<exchange>:<date>`；OHLC 超出当日实际涨跌停使用 `PRICE_OUTSIDE_DAILY_LIMIT:<symbol>:<date>`。校验器绝不前向填充分钟、猜测交易日、用写死的 10% 涨跌幅替代实际限制，或把临时 K 线当作官方收盘。

由于 `verify` 不接收计划，计划特定的指标充分性在后续 `run` 中校验；runner 会对计划使用的每项指标检查日线历史，包括适用时的 MA200，不足则阻断。`run` 还要求显式人工事件风险输入或明确记录的无事件假设；缺失绝不能静默解释为安全。

`dataset_hash` 是以下内容的规范哈希：数据集 Schema 版本、历史标签配置、股票/日期范围、复权策略、有序不可变行修订哈希、日历/涨跌停/日线事实和预热边界。供应商回执时间和本地数据库行 ID 不参与哈希，除非它们选择了不同内容修订。事实不变时再次校验必须逐字节返回相同哈希。供应商修订会生成新哈希，同时旧数据集仍可复现。

所有回测内容哈希和 identity 哈希都使用同一套精确 Decimal 规范化。`0.0003` 与 `0.00030` 这类数值相等但 scale 不同的有限值会序列化为相同的非指数定点文本，因此产生相同哈希；零统一表示为 `0`，拒绝二进制浮点，并且任何结果都不依赖进程全局 Decimal context。精确定点展开超过 10,000 个字符的值会在哈希前失败关闭，不能耗尽内存或形成依赖 context 的 identity。CLI 元转分同样不依赖全局 context：最多接受两位小数及其后任意额外尾零，在展开前拒绝超大指数，并要求转换结果不超过 signed 64-bit 分上限 `9,223,372,036,854,775,807`。

内容寻址必须在每次读取冻结 artifact 时重新验证，不能只在插入时验证。解析或回放被引用 artifact 前，存储必须重新计算其规范内容哈希并与冻结的 `artifact_hash` 比较；任何不一致都产生稳定的篡改/损坏阻断。即使 manifest 或哈希字符串语法合法，也绝不能授权已被修改的 `content_json`。

冻结校验持有稳定 WAL 读取快照，按日期顺序逐个校验每日分钟批次，不能把多年分钟语料一次性载入内存，也不能在扫描期间占用写入者。读取快照关闭后，只有发布阶段获取短 `BEGIN IMMEDIATE` 事务，并分有界批次重新校验每个已选 `natural_key -> artifact_hash` head；校验到发布之间只要任一 head 发生修订，就必须中止冻结，不能发布混合版本。通过校验的 manifest 还会构建有界缓存的 `natural_key` 字典，因此后续单键成员查询在重新读取并重算被引用 artifact 前是 O(1)。

## 事件时间回放与禁止未来数据

回放只按冻结事实中保存的时间戳推进，判断期间既不休眠也不读取墙上时钟。它绝不调用 `MarketSessionScheduler`、`SymbolService`、`RecoveryService`、`RuntimeLifecycleService`、实时提醒、Webhook、WebSocket 或通知 Outbox。

它必须复用已批准的生产契约，不能重复实现策略规则：

- `TradePlan`、计划校验、不可变版本和 `plan_sha256`；
- `MinuteBar`、`TradingDay`、`DailyLimit` 和 `DailyBar`；
- `expected_minute_ends`、`normalize_source_minute`、`aggregate_five_minute_bar` 和 `aggregate_provisional_daily_bar`；
- `calculate_ta_v1`、`reconcile_daily_close`、`EvaluationContext` 和 `evaluate(EvaluationContext)`；
- `EvaluationResult`、`result_hash`、事件/风险意图和 `SignalIntent`。

每个截止点只能向引擎提供该事件时间或之前可获得的事实。五分钟判断只能看到已完成的组成分钟；临时日线只包含当时已经出现的分钟；当日官方 `daily` 只能在官方收盘阶段可见。预热事实只初始化指标，不能产生收益或成交。修改某截止点之后的任何事实，都不能改变此前的判断、`result_hash`、信号或成交。

MVP 使用一个显式有界滚动上下文：最新 512 根完整五分钟 K 线、当前日前 499 根官方日线，以及 512 个日历日事实。报告限制 `BOUNDED_ROLLING_CONTEXT_512_5M_499_DAILY_512_CALENDAR` 会公开该研究边界。它限制每次判断上下文，但不能作为更广 `BC01` 内存/数据库资源上限已经通过的证据。

每个可操作信号只有一个精确事件时间 identity：`signalAt == EvaluationResult.snapshot.evaluatedAt`。盘中判断时，该值等于最新输入分钟的 `receivedAt`；官方收盘判断时，该值等于官方日线事实的 `receivedAt`。runner 绝不能改用来源分钟的 `barEnd`、五分钟桶结束、硬编码 15:00 或本地墙上时钟。订单只能从后续满足 `openAt >= signalAt` 的规范候选 K 线开始考虑。离散回放顺序允许产生事件先在某个边界完成，再处理 `openAt` 为同一边界的下一分钟 K 线事件，因此允许相等并不代表能在产生信号的 K 线或桶内成交。生产历史分钟事实通常设置 `receivedAt == barEnd + 12s`；常规分钟信号仍只会从之后的分钟开始考虑，不会获得前视。成交必须记录该成交分钟的 `filledAt == openAt`。

## 模拟成交模型

公式版本 `execution-model-v1` 是确定性的，并且只属于 `BACKTEST`：

- 信号不能在产生它的分钟或五分钟桶内成交；最早候选是离散回放顺序中后续第一根 `openAt` 不早于该信号基于 `receivedAt` 的事件时间的可交易一分钟 K 线，只有产生事件已经完成时才允许同一边界相等；
- MVP 把零成交量候选分钟作为不可交易代理，并让订单继续等待；引擎按每个连续规范候选推进到之后第一根正成交量分钟，遗漏必需候选时以 `MISSING_NEXT_MINUTE` 失败，只有有限回放结束且此前遇到零成交量分钟、但始终没有后续可交易 K 线时才产生 `SUSPENDED`；
- 默认成交价由该成交 K 线开盘价加上按方向配置的基点滑点得到，并且 `filledAt` 必须精确等于该 K 线的 `openAt`，绝不能使用其 `barEnd`；
- 买入数量遵守 100 股整手；持仓不能为负，不允许杠杆或裸卖空；
- 按交易日执行 A 股 T+1，现金、计划最大仓位、目标仓位和可卖数量共同限制每笔成交；
- 使用实际每日 `stk_limit` 判断涨跌停不可成交；停牌、缺少下一分钟、区间结束、资金不足、整手非法和 T+1 均产生明确未成交原因；
- 佣金率、最低佣金、印花税率、过户费率和滑点均为必需的版本化配置。金额、费用、现金和盈亏使用整数分或精确 `Decimal`，禁止二进制浮点。费率和滑点转换为精确整数分子/分母：费率向上取整到分，买入滑点向上取整，卖出滑点向下取整，部分持仓成本分摊取最接近的分且正数中点向上。任何计算都不读取环境 Decimal precision 或 rounding mode；
- `RISK_BREACH` 只是风险事件，绝不自行代表成交。

报告会逐字公开三项成交简化：`ZERO_VOLUME_MINUTE_USED_AS_NON_TRADABLE_PROXY` 表示 MVP 用零成交量作为停牌/不可交易代理；`FILL_QUANTITY_NOT_CAPPED_BY_MINUTE_VOLUME` 表示模拟器不建模参与率或市场冲击；`CONSERVATIVE_LIMIT_LOCK_FROM_OPEN_OR_SLIPPAGE` 表示原始开盘价或滑点后价格任一触及实际每日涨跌停都会阻断成交。它们属于研究限制，不是隐藏的券商行为。

每个 `ExecutionOutcome` 都把不可变 `resolvedAt` 和 `sourceBarId` 证据纳入 identity、报告 payload 及保留详情哈希；持久化 outcome 详情的 `eventAt` 等于 `resolvedAt`，不是原始信号时间。成交或按 K 线拒绝的 outcome 在该 K 线 `openAt` 解决，并记录其 `sourceBarId`；忽略不可执行信号时在 `signalAt` 解决且没有来源 K 线。如果第一根必需规范交易时段分钟缺失，并由之后 K 线暴露缺口，则订单以 `MISSING_NEXT_MINUTE` 失败关闭，在该后续已观察 K 线的 `openAt` 解决并记录其 `sourceBarId`，不能跳过缺口继续成交。`NO_NEXT_MINUTE` 仅用于回放结束时始终没有观察到候选，因此没有来源 K 线；`SUSPENDED` 保留已观察零成交量来源证据，并在回放边界解决。午休和下一有效交易时段开盘属于规范边界，不是伪造分钟缺口。

每笔成交必须追溯到 `run_id`、`plan_sha256`、`dataset_hash`、`result_hash`、信号 identity、来源 K 线 identity、成交模型版本和费用模型输入。

## 运行标识、幂等与恢复

精确版本化 `run_id` preimage 由 [`backtest-engine`](SPEC-backtest-engine.zh-CN.md) 负责；本总规格既不重新定义，也不静默扩展它。空的规范化初始持仓列表保留现有逐字节相同的 `backtest-run-v1` preimage，并继续可读、可复用。非空公共初始持仓列表选择 `backtest-run-v2`，并用包含稳定 `lotKey` 的规范化 `BacktestInitialLotInput` 表示每个持仓。`planVersionId` 只是查找/审计引用：Web 提交使用它获取恰好一个不可变计划快照，但它不参与任一 identity preimage。修改任一精确 preimage 都必须新增公式版本和迁移决策。

相同输入和代码兼容公式版本必须产生相同的有序判断、哈希、成交、每日权益、报告字节和 `run_id`。重复运行已完成任务是无操作/读取现有结果。当前 MVP 没有策略事件游标：判断/成交回放会从冻结数据集起点在内存中重新运行。若结果持久化期间中断，重试会确定性重放冻结输入，并在唯一 identity 下幂等补齐 staged 行，不重复产生判断、信号、成交或权益行。已有 identity 下出现冲突内容时失败关闭。策略回放期间按事件游标恢复仍属于开放的 `BC01` 验收工作。

结果发布采用 staged/materialized 恢复协议。系统先 staged 规范摘要，再以幂等方式写入成交和有界详情批次。只有摘要中的完整 `reportHash`、预期成交/详情数量，以及成交集和详情集各自精确的规范 `(identity, contentHash)` 集合哈希都与已存行一致时，单个验证事务才能设置内部 `materialized` 可见性标记。首次成功发布会把这些成交/详情数量和 identity-content 集合哈希持久化为 materialization 元数据；已发布运行的每次重试都必须与该元数据精确匹配。在该事务提交前，普通摘要/列表/成交/详情读取和统计都看不到 staged 摘要、成交或详情；只有显式恢复与维护路径可以检查它们。普通摘要/成交/详情读取在返回每行前，必须把 SQL identity 与其已哈希规范 payload 交叉校验；请求的 detail-kind 过滤只能在校验后执行，不能借过滤隐藏损坏行。`materialized` 是唯一发布闸门，并不是公开运行状态。现有结果 status enum 为兼容读取继续保留 `COMPLETED`、`FAILED` 和 `CANCELLED`，但新的任务化发布路径只写入 materialized 的 `COMPLETED` 结果，并把尝试失败/取消保存在 `backtest-jobs`。随后把摘要 JSON 和成交 CSV 作为 materialized 长期摘要/成交账本的可重建投影原子写入。重复 `run` 或恢复请求遇到摘要/账本文件缺失或损坏时，不访问供应商、不重放策略、也不重复成交即可重建。staged identity、内容集合哈希、行数不完整或已发布元数据不匹配时失败关闭。

`reportHash` 标识运行首次 materialized 时的原始完整规范 `BacktestRunReport`，其中包含当时存在的判断/信号/结果/权益详情。详情经过保留策略清理后，该哈希继续作为长期审计 identity，但它不是任一输出文件的字节哈希，也不承诺能重建已过期详情。重建资产只包含 `backtest-report-summary-v1` 和长期成交账本；被保留策略删除的详情继续保持删除。

## 结果与报告

兼容结果 Schema 可以读取有界的 `COMPLETED`、`FAILED` 和 `CANCELLED` 摘要。新的任务化路径只 materialize 完整 `COMPLETED` 研究结果，其中包含输入 identity、覆盖范围、数据质量阻断项、假设、事件起止时间和公式版本；失败/取消尝试诊断保留为有界任务记录，使同一确定性 `run_id` 以后仍可完成。当前 CLI 会 materialize 已完成运行，迁移到原子结果/任务发布仍属于开放工作。成功内存报告及保留期内详情行包括：

- 数据覆盖与缺口摘要；
- 有序判断及 `result_hash`；
- 信号和明确的已成交/未成交结果；
- 现金、持仓、已实现/未实现盈亏和每日权益；
- 总收益率、最大回撤、交易次数、胜率、换手和总成本；
- `BLOCKED`/`SKIPPED` 数量以及所有模型限制。

每个持久化详情 identity 都必须同时由 `run_id` 和其判断/信号/结果/权益 identity 限定范围。两个运行可以合法共享生产 `result_hash`，同时具有不同成交假设；它们必须保存独立详情行，不能碰撞或抑制其中一个。

指标语义也以限制形式显式公开：`DAILY_EQUITY_DRAWDOWN_SAMPLING` 表示最大回撤只使用每日权益点，不能声称捕获盘中低谷；`WIN_RATE_PER_SELL_FILL_NOT_ROUND_TRIP` 表示胜率按卖出成交分类，而不是重建完整往返交易；`METRIC_DECIMAL_PRECISION_28_HALF_EVEN` 表示收益率、回撤及胜率除法使用 precision 28 和 `ROUND_HALF_EVEN` 的隔离 Decimal context。这三个 Token 都保留在报告假设/限制中，环境进程 precision 不能改变指标字节或 identity。

MVP 通过 CLI 输出稳定的 `backtest-report-summary-v1` JSON 和模拟成交 CSV。两者缺失时都能根据长期摘要/成交行确定性重建。判断、信号、未成交结果和每日权益属于独立有界详情行，受相同的 100 次/90 天或 14 天保留规则约束；它们绝不嵌入永久规范 blob，清理后即不可用。系统保存每日而非每分钟账户权益。原始供应商响应和重复历史 K 线不是结果资产。已批准的 FastAPI/Vue 方向现通过冻结的 42 路径 OpenAPI/生成 TypeScript 契约和真实生产路由实现。WEBF13 记录最终路由接线和新建回测旅程，不改变该契约；只有 Router 占位仍不能算完成。

## 保留与性能

保留策略明确作用于已发布详情和已废弃未发布 stage：

| 记录类别 | 默认保留期 |
|---|---|
| 运行摘要、哈希、假设、最终指标和成交账本 | 长期保留 |
| 成功运行的判断/信号/每日权益详情 | 最新 100 次且不超过 90 天；先达到的限制生效 |
| 失败/取消任务诊断及任何兼容诊断详情 | 14 天 |
| 明确启用时的分钟级调试轨迹 | 14 天 |
| 已废弃且未 materialized、未置顶的 staged 摘要/成交/详情 | 14 天；三类记录在同一个有界清理预算下进入候选 |
| 已置顶运行及其详情 | 手动取消置顶或删除前豁免 |
| 被数据集/运行引用的去重行情修订 | 保留 |

清理使用带索引的 `run_id`、状态、完成/创建时间、materialization 和置顶状态，以最多 1,000 行的有界批次删除，并且绝不在实时监控或回测运行期间执行大型 `VACUUM`。`prune` 在同一总批次预算内先移除符合条件的废弃 staged 详情/成交/摘要行，再移除已发布过期详情；近期或置顶 stage 仍可用于恢复。WAL 检查点只在安全阶段/停止边界执行；`VACUUM` 是显式离线维护操作。

结果存储已经实现置顶状态和清理豁免。当前 MVP CLI 提供 `list` 与 `prune`，但尚未提供置顶/取消置顶命令；公共置顶和初始持仓管理仍属于未完成的运维验收工作。

在获批的最多 10 只股票规模下，一个普通年度约有 600,000 条分钟行，5 年约 3,000,000 条。查询必须使用 `(symbol, bar_end)` 或数据集/运行/日期索引，按交易日有界分块回放，不能把多年数据一次性载入内存。最终 `BC01` 性能测试必须定义明确的数据库、WAL、内存、任务和线程上限，并证明重复运行不会增长行情表或结果表；当前 MVP 尚未验证这些资源上限。

## 安全与运维边界

- 始终：`backtest sync` 必须使用环境密钥引用并获得明确联网授权。
- 始终：下载事实必须先校验再持久化，并保留稳定、脱敏的供应商错误。
- 始终：网络调用位于数据库事务外，三个存储域保持隔离。
- 始终：已接受的 Web 运行只能在只读实时存储事务中解析恰好一个不可变计划版本，在响应前持久化其已校验快照，并且提交期间对实时存储执行零写入。
- 始终：直接 CLI 运行使用显式 CLI `--plan` 文件；durable 提交边界之后，worker 和回放对实时存储执行零读取和零写入。
- 始终：历史日历显式请求 `SSE`/`SZSE` 交易所 identity；在另行验证 BSE 日历契约前阻断 `.BJ`。
- 始终：每次读取冻结 artifact 都重新计算哈希，报告文件只能根据已验证的 staged 规范内容恢复。
- 始终：配置和报告显著说明不复权价格/公司行动限制。MVP 不会静默应用 `qfq` 或 `hfq`，也不模拟分红、拆股、配股或其他公司行动。
- 先确认：修改时间戳映射、复权策略、公式/成交版本、保留默认值、已批准 API 路径/传输方式或 Web 信任边界。
- 禁止：把回测计作 T058 证据、发布回测信号、修改实时状态或连接券商。

## 测试策略

最终 RED 到 GREEN 验收必须至少覆盖两只股票和多个交易日，并验证：

- 周末、午休、09:30/15:00 边界和对已观察 241 行响应的显式处理；
- 缺失、重复、冲突、乱序、空值和非法分钟事实；
- 一个有效买入和一个减仓/退出信号、下一分钟而非同桶成交、最后一分钟不成交、实际涨跌停锁定、T+1、整手、资金不足、费用和滑点；
- 数据缺口以 `MISSING_NEXT_MINUTE` 失败关闭并带精确 `resolvedAt`/`sourceBarId`，且预热/参考数据不足时失败关闭；
- 通过修改后续事实并比较所有此前 identity/哈希证明无未来数据；
- 重复报告逐字节稳定、staged 结果中断/重试恢复、没有重复成交，以及仍开放的策略事件游标恢复边界；
- 精确验证 `signalAt == snapshot.evaluatedAt == receivedAt` 来源、下一可交易分钟 `filledAt == openAt`，并拒绝同分钟成交或用 `barEnd` 替代；
- 显式 SSE/SZSE `trade_cal` 调用、严格拒绝原始参考行、联网前拒绝 `.BJ`、读取快照/短发布冻结竞争、O(1) manifest key 查询、冻结 artifact 篡改检测和 materialized 摘要 JSON/成交 CSV 重建；
- `BC01` 精确验证 Web 提交前后和 worker/回放前后的实时逻辑状态相等、提交期间实时存储零写入、durable 边界之后实时存储零读写、回放期间通知/网络调用为零，以及数据库路径隔离；
- 内存、SQLite/WAL、任务和线程增长有界，以及保留/置顶行为。

默认测试只使用夹具，不使用凭据或网络。真实历史获取探测属于另行授权的验证资产，不能替代提交的确定性测试。

## 验收标准

- 历史数据只增量同步一次，按内容去重、校验后可由多次离线运行复用。
- 冻结数据集和相同配置能复现相同 `run_id`、判断、成交、权益和报告字节。
- 数据缺失或语义未验证时以明确原因阻断执行；未来事实不能影响较早结果。
- 模拟成交遵守下一分钟、实际涨跌停、T+1、整手、现金、仓位、费用和滑点契约。
- Web 提交在一次只读不可变计划查找后保持实时数据库状态不变，worker/回放不读取该数据库，并保持实时数据库状态和通知计数不变。
- 长期摘要/成交保持可查询，同时有界详情保留和索引避免性能无界下降。
- 活动持久化及公开的回测时间在端到端保持规范 `Asia/Shanghai`/`+08:00`，不经过主机/浏览器时区转换；隔离 UTC v1 兼容字节绝不被静默重新解释。
- T058 在其实时联网、权限、时间戳和行情窗口证据通过前继续独立阻断。

## 审核状态

用户于 2026-08-25 批准了接口同步到本地、冻结后离线回测的混合方向、隔离存储和有界保留策略，又于 2026-08-26 批准了六模块能力地图和方向。用户还于 2026-08-26 确认六份详细模块规格并批准 `local-web` Backtest Extension Boundary。用户随后明确确认每个回测时间都使用 `Asia/Shanghai`/`+08:00`，不再保留独立活动 UTC 契约，并确认其余修正后的跨模块条款。因此聚合详细规格现按修正内容获批。当前实现公开冻结的 42 路径 OpenAPI 契约和 10 条真实生产路由。WEBF13 不增加 API、Schema、哈希或供应商变更；其独立配对路由/旅程报告已于 2026-09-04 通过。更广的真实供应商历史同步继续单独受闸门约束。
