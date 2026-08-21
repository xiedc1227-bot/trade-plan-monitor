# 规格：market-data（Tushare 行情数据）

> 中文审阅版。英文权威版为 `SPEC-market-data.md`；两份文档必须保持语义一致。

## 目标

通过 Tushare 为最多 10 只活动股票提供规范化、新鲜且完整的 A 股行情与参考数据。本模块负责能力探测、时间与单位转换、交易时段、1 分钟采集、完整 5 分钟聚合、日线核对、实际涨跌停价和版本化技术指标。

Tushare 是首版唯一行情源。内部适配器协议只用于确定性测试和未来替换，不在首版实现第二数据源。

## 技术栈

- Python 3.11+
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
├── aggregation.py     # 1 分钟到完整 5 分钟的幂等聚合
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
- 完整性检查只接受由规范分钟结束时间组成的有界、可重复元组；任意迭代器或集合会在不被消费的情况下拒绝。
- 不完整或过期数据立即阻止该股票产生可操作信号。
- 最新完整分钟收盘价覆盖 `latest_quote`，不建立第二套报价历史。
- 15:00 分钟只形成临时收盘；只有当前交易日的 `daily` 记录才能推进正式收盘风险状态。

## 指标定义

公式版本 `ta-v1`：

- EMA：pandas `ewm(span=n, adjust=False)`；
- MACD `(12,26,9)`，柱值为 `macd - signal`；
- 布林带 `(20,2)`，标准差使用总体标准差；
- RSI14 和 ATR14 使用 Wilder 平滑；
- MA20/MA50/MA200 使用未复权收盘价。

临时当日日线可以用于展示和动能证据，但必须标记为“临时”，且不能覆盖官方日线。

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
