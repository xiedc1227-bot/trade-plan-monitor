# 规格：market-data（Tushare 行情数据）

> 中文审阅版。英文权威版为 `SPEC-market-data.md`；两份文档必须保持语义一致。

## 目标

通过 Tushare 为最多 10 只活动股票提供规范化、新鲜且完整的 A 股行情与参考数据。本模块负责能力探测、时间与单位转换、交易时段、1 分钟采集、完整 5 分钟聚合、日线核对、实际涨跌停价和版本化技术指标。

Tushare 是首版唯一行情源。内部适配器协议只用于确定性测试和未来替换，不在首版实现第二数据源。

## 技术栈

- Python 3.14.x（`>=3.14,<3.15`）
- Tushare Pro Python SDK，并在事件循环之外执行
- pandas：数据规范化和指标序列
- Pydantic 2：校验不可信的第三方返回值
- `zoneinfo.ZoneInfo("Asia/Shanghai")`
- `strategy-state` 提供的 SQLite 仓储

官方接口依据：

- A 股实时分钟：<https://tushare.pro/document/2?doc_id=374>
- 当日分钟回放：<https://tushare.pro/document/2?doc_id=457>
- 交易日历：<https://tushare.pro/document/2?doc_id=26>
- 每日涨跌停价：<https://tushare.pro/document/2?doc_id=183>
- 官方未复权日线：<https://tushare.pro/document/1?doc_id=27>

## 命令

```powershell
python -m pytest tests/unit/test_market_data.py -q
python -m pytest tests/integration/test_tushare_contract.py -q -m "not live"
python -m ruff check src/trade_plan_monitor/market_data tests/unit/test_market_data.py
```

实盘时段契约测试需要真实 `TUSHARE_TOKEN` 和明确的联网授权，默认不执行。

## 项目结构

```text
src/trade_plan_monitor/market_data/
├── models.py          # 规范化 K 线、涨跌停、日历和能力状态
├── provider.py        # MarketDataProvider 协议
├── tushare.py         # Tushare 适配器和错误分类
├── sessions.py        # A 股分钟与交易时段语义
├── aggregation.py     # 完整 5 分钟与临时日线聚合
├── indicators.py      # 版本化 ta-v1 指标
└── reconciliation.py  # 临时收盘与官方收盘核对
tests/unit/
└── test_market_data.py
tests/integration/
└── test_tushare_contract.py
tests/fixtures/market_data/
└── tushare_frames.json
```

## 行情接口契约

```python
class MarketDataProvider(Protocol):
    def probe_capabilities(self) -> ProviderCapabilities: ...
    def realtime_minutes(self, symbols: tuple[str, ...]) -> list[MinuteBar]: ...
    def current_day_minutes(self, symbol: str) -> list[MinuteBar]: ...
    def trading_calendar(self, start: date, end: date) -> list[TradingDay]: ...
    def daily_limits(self, trade_date: date) -> list[DailyLimit]: ...
    def daily_bars(self, symbol: str, start: date, end: date) -> list[DailyBar]: ...
```

Tushare 映射关系：

- `rt_min(freq="1MIN")`：以逗号分隔批量请求最多 10 只股票；官方文档注明单次最多返回 1000 行，成交量单位为股、成交额单位为元。
- `rt_min_daily(freq="1MIN")`：单只股票当日启动恢复和缺口修复；响应中的股票字段只接受文档明确出现的 `ts_code` 和 `code` 两种别名，并且只保留回执日期当天的严格 `1MIN` 行。
- `trade_cal`：交易日、休市日和上一交易日。
- `stk_limit`：当日实际涨停价和跌停价。
- `daily`：官方未复权日线，用于收盘风险状态和日线指标；原始成交量单位为手，乘以 100 转为股，原始成交额单位为千元，乘以 1000 转为元。

能力和限流属于运行时事实，必须独立探测五个接口并展示其状态，不能仅根据配置推断。未提供通过校验的探测股票时，依赖股票的能力保持 `UNVERIFIED`。

供应商失败只公开操作名和一个稳定的 `TushareErrorCode`：`BLOCKED_PERMISSION`、`RATE_LIMITED`、`TRANSIENT`、`INVALID_RESPONSE` 或 `ERROR`。结构化 HTTP 响应状态优先于消息文本；文本回退只识别明确的 HTTP/status/error-code 语境或稳定短语，绝不把股票代码或 Token 中嵌入的数字子串当作状态码。公开错误和能力值绝不包含 SDK 原始消息、授权详情、异常上下文或 Token。

## 数据语义

- 系统内部使用带 `Asia/Shanghai` 时区的规范化 K 线结束时间。
- 源分钟时间戳必须精确落在整分钟，包括 pandas 纳秒余量也必须为零；任何分钟内偏移都失败关闭。
- Tushare 时间标签可能表示分钟开始或结束，必须通过实盘契约测试确定映射；调度器和缺口检测不得直接假设原始标签语义。
- 监控时段覆盖 09:30～11:30 和 13:00～15:00。首版规则流不使用开盘集合竞价数据；14:57～15:00 的收盘集合竞价仍属于下午监控窗口。
- 数据只有在分钟结束、经过默认 12 秒宽限，并通过代码、OHLC、非负成交量/额和交易时段校验后才可用。
- 1 分钟数据幂等键为 `(symbol, bar_end)`。
- 每个必需供应商字段必须恰好出现一次。列重排或额外列无害；缺失或歧义必需列以及无 Schema 空帧属于 `INVALID_RESPONSE`，带完整类型列的空帧则是有效的无数据。
- 逐行先解析 identity。任一非法或冲突 payload 都会永久使该响应中的 identity 失效，且不受行顺序影响；无法识别、未请求或缺失的行绝不使健康 identity 失效。
- 十进制十次幂通过精确移位完成，不读取外部 decimal 精度。价格必须精确成为正整数分，股数必须精确成为非负整数；整数结果超过 640 个十进制位时，在分配前拒绝。
- 只有一个交易时段内的全部预期分钟都存在时，才能生成完整 5 分钟 K 线；禁止跨午休聚合。
- `aggregate_five_minute_bar` 只接受同一股票恰好五个规范化 `MinuteBar` 值组成的精确、可重复 tuple。分钟缺失、重复、股票混合、跨时段、休市日或未知交易日输入都不能生成 K 线；完整输入乱序后仍产生相同的不可变 `(symbol, bar_end, formula_version)` 值。
- 5 分钟 `amount_yuan` 必须根据 decimal tuple 精确求和，且不读取外部 decimal context。零值不扩大指数跨度；非零对齐系数或最终求和超过 640 位安全跨度时，必须在大内存分配前失败关闭。
- 完整性检查只接受由规范分钟结束时间组成的有界、可重复元组；任意迭代器或集合会在不被消费的情况下拒绝。
- 不完整或过期数据立即阻止该股票产生可操作信号。
- 最新完整分钟收盘价覆盖 `latest_quote`，不建立第二套报价历史。
- `current_day_minutes` 判断上下文切片是不可变精确 tuple，包含当前日期首个规范分钟结束时间到 5 分钟判断截止时间（含两端）的全部规范完整分钟，最多 240 行，并保留规范午休边界。分钟缺失、重复、乱序、股票/日期混合、超出交易时段、晚于截止时间或任意迭代器输入均失败关闭。该切片复用持久化分钟历史，不建立第二套报价历史。
- 行情持久化只接受有界的规范化值 list/tuple 批次，每次最多 1,000 行。分钟、日线和涨跌停修正只有在 `received_at` 更新时才能推进；同一回执时间出现冲突事实时失败关闭，较旧回放无害。
- 行情历史读取必须提供明确的闭区间开始/结束边界，超过 10,000 行时失败关闭。日历读取同样要求范围；由于该表没有回执版本列，后续权威日历抓取可以修正相同 `(exchange, cal_date)`。
- 持久化 5 分钟 K 线必须结束于交易时段内有效的 5 分钟边界。其 `(symbol, bar_end, formula_version)` identity 是确定性的，不能被冲突事实覆盖。
- `aggregate_provisional_daily_bar(current_day_minutes=..., source_as_of=...)` 是 T032 为盘中指标生成当前日期临时 `DailyBar` 的纯边界。它根据精确切片确定性生成：首个开盘价、最高价最大值、最低价最小值、最后收盘价、股数成交量之和、精确元成交额之和、`is_official=False`，以及最新来源回执。其 `source_as_of` 是切片截止时间。截至 15:00 的聚合是临时收盘，绝不能改标或覆盖独立的官方行。只有当前交易日的官方 `daily` 行才能推进官方收盘风险状态。

`reconcile_daily_close(symbol=..., current_trade_date=..., daily_bars=...)` 是纯边界，接收不可变 tuple；其中最多包含同一股票、精确日期下分别持久化的临时与官方 `DailyBar` 行。可变集合、超过两行、重复 provenance、股票混合和非当前日期都会失败关闭；输入顺序不可观察。

不可变 `CloseReconciliationIntent` 分别保留 `provisional_bar` 与 `official_bar`，并暴露 `status`、`close_delta_fen` 和 `advance_close_risk`。没有当前日期官方行时，状态为 `CLOSE_PENDING`，官方行与差值均为 `None`，且不能推进收盘风险。存在所请求日期的真实 `DailyBar(is_official=True)` 时，状态为 `OFFICIAL_READY`；若两类行都存在，`close_delta_fen` 等于官方收盘减临时收盘，且只有保持原样的官方行获准进入下游风险判断。重复持久化记录和重启重建产生相同意图；该函数不执行持久化、调度、健康状态修改或风险判断。

## 指标定义

公式版本 `ta-v1`：

- EMA：pandas `ewm(span=n, adjust=False)`；
- MACD `(12,26,9)`，柱值为 `macd - signal`；
- 布林带 `(20,2)`，标准差使用总体标准差；
- RSI14 和 ATR14 使用 Wilder 平滑；
- MA20/MA50/MA200 使用未复权收盘价。

`calculate_ta_v1` 接受只含一只股票和一种 K 线类型（`DailyBar` 或完整 `FiveMinuteBar`）的不可变 tuple，日期/时间 identity 必须严格递增，且最多包含 10,000 个值。同一日同时出现临时/官方行等重复日线日期时，必须先由核对流程解决，不能在计算时静默去重。

整数分 OHLC 输入在 pandas 计算前只转换一次为有限浮点元。价格型输出为 `ema10_yuan`、`ema12_yuan`、`ema26_yuan`、`macd_yuan`、`macd_signal_yuan`、`macd_histogram_yuan`、`boll_middle_yuan`、`boll_upper_yuan`、`boll_lower_yuan`、`atr14_yuan` 以及 `ma20_yuan`/`ma50_yuan`/`ma200_yuan`；`rsi14` 是 0～100 的无量纲值。超出有限浮点计算范围的值失败关闭。

RSI14 使用前 14 个收盘差值的平均上涨/下跌作为种子，首个值位于索引 14。ATR14 使用前 14 个真实波幅的简单平均作为种子，首个值位于索引 13。后续 RSI/ATR 使用 Wilder 递推 `(previous * 13 + current) / 14` 平滑。其他不足窗口明确返回 `None`；决策引擎把所需指标缺失视为阻断项。

`IndicatorSeries` 和每个 `IndicatorPoint` 都是封闭且不可变的，公开复制更新会重新执行校验。固定 OHLCV 黄金测试锁定 pandas 3.0.5 下的 `ta-v1` 结果；任何有意的公式或兼容性变化都必须创建新公式版本并更新黄金值。

当前日期日线指标计算必须只选择一个当前日期来源。临时聚合生成 `PROVISIONAL` provenance 及其精确切片截止 `source_as_of`；核对后的官方行生成 `OFFICIAL` provenance 和规范 15:00 `source_as_of`，并且只有在 `advance_close_risk=True` 时才有资格进入官方收盘判断。在 `calculate_ta_v1` 前，同时或隐式选择来源、缺失截止 provenance 以及混合来源都必须失败关闭；调用方将 `IndicatorSeries` 与所选来源事实配对。当前日期临时日线可用于展示和动能证据，但绝不能覆盖官方日线或推进官方收盘状态。

## 代码风格

```python
class MinuteBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    bar_end: datetime
    open_fen: int
    high_fen: int
    low_fen: int
    close_fen: int
    volume_shares: int
    amount_yuan: Decimal
    received_at: datetime
```

适配器只负责规范化和错误分类，不能包含交易规则。

## 测试策略

- 使用模拟 DataFrame 覆盖五个接口、列名变化、乱序、重复、空值、非法数值、部分股票缺失、单位和 Token 脱敏。
- 覆盖开盘集合竞价、午休、最后一分钟、周末、节假日和未知交易日。
- 覆盖分钟缺失、重复到达、恢复补充和完整 5 分钟只生成一次。
- 使用固定 OHLCV 文件验证指标黄金值。
- 覆盖临时/官方收盘一致、差异、延迟到达和下次启动恢复。
- 覆盖精确/有缺口的判断当日切片、240 行上限、临时来源截止时间，以及拒绝同时或隐式选择当前日期指标来源。
- 实盘测试确认 10 只股票批量结果、时间标签、成交量/额单位、延迟、能力状态和最后一分钟行为。

## 边界

- 始终：所有第三方响应必须校验后才能持久化。
- 始终：脱敏 `TUSHARE_TOKEN` 和权限相关错误内容。
- 始终：交易日未知、实际涨跌停缺失、分钟过期或日线不足时失败关闭。
- 先确认：修改公式版本、复权策略、默认宽限时间或增加第二数据源。
- 禁止：用写死的 10% 涨跌幅替代实际涨跌停价作出买入判断。
- 禁止：把缓存价格当作官方收盘价。
- 禁止：在 Tushare 执行线程中进行数据库操作。

## 验收标准

- Tushare 接受时，最多 10 只活动股票能够使用一个规范化批量请求。
- 单只股票缺失只阻断自身，不影响同批次健康股票。
- 实时分钟成交量保持股、成交额保持元且不缩放；官方日线的原始手数和千元值只在适配器边界转换一次，成为股和元。
- 不完整 5 分钟 K 线绝不进入可操作规则判断。
- 能力、日历或涨跌停数据未知时产生明确健康阻断。
- 指标黄金值跨运行保持稳定。
- 官方收盘核对可审计且幂等。

## 待确认事项

账号实际权限和限流必须由启动探测及实盘契约测试确认，规格不写死账号级阈值。
