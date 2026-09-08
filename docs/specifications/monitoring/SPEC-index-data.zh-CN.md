# 规格：index-data

> 中文审阅版。英文权威版为 `SPEC-index-data.md`；两份文档必须保持语义一致。

## 目标

获取或回放经过校验的板块指数 K 线，计算可复用且带版本的数值事实，并为同一截止时间判断的全部计划按 `(indexCode, decisionCutoff)` 发布一份不可变共用快照。本模块只提供数据事实，绝不生成市场强弱标签或交易影响。

## 技术栈与命令

- Python 3.14、冻结且严格的 Pydantic 值、精确 `Decimal`、SHA-256 和 `Asia/Shanghai` 时间戳。
- 供应商协议和确定性离线假实现；供应商响应属于不可信输入。

```powershell
python -m pytest tests/unit/test_market_index_data.py -q
python -m pytest tests/integration/test_market_index_snapshots.py -q
python -m ruff check src/trade_plan_monitor/market_index tests/unit/test_market_index_data.py tests/integration/test_market_index_snapshots.py
```

这些命令不包含真实 Tushare 或其他供应商调用；真实调用需要单独授权。

## 项目结构

```text
src/trade_plan_monitor/market_index/
├── models.py       # K线、健康状态、事实请求、事实和快照
├── formulas.py     # market-index-facts-v1 纯计算
├── provider.py     # 实时/历史供应商协议和安全错误
├── snapshots.py    # 校验、需求合并和共用截止时间缓存
└── canonical.py    # 十进制、K线集合、请求集合和快照哈希
tests/unit/test_market_index_data.py
tests/integration/test_market_index_snapshots.py
```

## 数据契约

`MarketIndexBar` 是指数专属类型，不能接受股票代码。字段包括 `index_code`、`interval=FIVE_MINUTE|OFFICIAL_DAILY`、`bar_at`、精确正数 `open_points`、`high_points`、`low_points`、`close_points`、可空的精确非负 `volume`/`amount`、`observed_at`、`source_kind=PROVISIONAL|OFFICIAL` 和有界供应商修订号。日线 `bar_at` 固定为规范 15:00 `+08:00`；五分钟 `bar_at` 必须是已完成的交易时段周期。OHLC 顺序、身份、重复、未来截止、缺口、时间戳、十进制和来源语义必须在使用前通过校验。

`MarketIndexHealth` 为 `LIVE|STALE|GAPPED|BLOCKED`。有序且唯一的问题代码封闭为：

- `MISSING_FIVE_MINUTE_BAR`、`MISSING_OFFICIAL_DAILY_BAR`、`INSUFFICIENT_HISTORY`；
- `STALE_DATA`、`DUPLICATE_IDENTITY`、`GAPPED_SERIES`；
- `INDEX_IDENTITY_MISMATCH`、`FUTURE_DATA`、`INVALID_TIMESTAMP`；
- `NONCANONICAL_DECIMAL`、`INVALID_OHLC`、`FORMULA_MISMATCH`、`PROVIDER_UNAVAILABLE`。

只有 `LIVE` 可以作为条件证据。其他健康状态仍可展示，但会让每个受影响的指数叶子返回 `MISSING_INPUT`；它们不能在计划树之外产生全局阻断。

`MarketIndexSnapshot` 包含身份、最新完整五分钟 K 线、合并请求所需的正式日线历史、上一正式收盘、排序后的指标事实、健康状态/问题、`completed_bucket_at`、`observed_at`、`mapping_version`、正数 `revision`、`bar_set_hash`、`request_set_hash`、`formula_definition_hash` 和 `snapshot_hash`。它是冻结值，不能包含计划 id、条件结果、信号、`entryAllowed`、`decisionEffect` 或市场分类。

## 可复用事实与准确公式

公式版本为 `market-index-facts-v1`。事实单位为 `POINTS` 或 `RATIO`，并保留参数、结果、输入截止、来源哈希、健康状态和公式哈希。

- `SMA(period)`：以判断截止时间可用的最新正式开市日为终点，准确取最后 `period` 个正式开市日收盘点位的算术平均值。`period` 范围 `2..250`。
- `SMA_LOOKBACK(period, lookback)`：包含当前 `SMA(period)` 以及终点准确向前 `lookback` 个正式开市日的 `SMA(period)`。需要 `period + lookback` 个收盘值；`lookback` 范围 `1..60`。
- `RETURN(window, window_size)`：`(current_close / base_close) - 1`，其中基准是当前观测之前准确 `window_size` 个完整观测。`window` 为 `FIVE_MINUTE_BUCKETS|OFFICIAL_OPEN_DAYS`，`window_size` 范围 `1..250`，输入需要 `window_size + 1` 个收盘值。

禁止前向填充、插值、成分股合成、未完成报价、用日线替代五分钟请求或用股票 K 线替代指数 K 线。等号和条件阈值由 `plan-index-conditions` 处理，不属于本模块。

## 共用快照协调

每次获取截止时间前，协调器按派生 `indexCode` 对活动 Schema v2 计划分组，只提取计划中的指数事实需求并进行合并去重。随后每个指数供应商表面在该截止时间最多调用一次，并为该分组发布一份快照。计划读取同一对象/哈希，但分别判断。

完成快照的缓存键为 `(mappingVersion, indexCode, decisionCutoff, requestSetHash, providerContentRevision)`。由于不能在获取前猜测供应商修订号，内部 `(mappingVersion, indexCode, decisionCutoff, requestSetHash, observedNoLaterThan)` 预取键只去重并发获取，并在任务完成时删除。可用的完成快照不可变，并在有界的 512 项缓存中驻留；后续调用会先重新获取，因此不会遮蔽新的供应商修订号。不可用快照不保留。一个指数失败会发布该指数的阻断健康状态，但不会取消或替换其他指数。实时监控可以为没有指数条件的计划提供信息性快照，但其判断不要求该快照；回测也不为该计划强制要求指数历史覆盖。

## 规范化与哈希规则

- 十进制使用有限、非指数形式的规范文本：正负零统一为 `0`，去除多余前导/尾随零，并拒绝二进制浮点数。准确定点展开超过 10,000 个字符时，在格式化前失败关闭。
- 时间戳使用六位小数和显式 `+08:00`；拒绝 `Z`、无时区、其他偏移和非整分钟 K 线身份。
- K 线按 `(interval, barAt)` 排序；请求按完整类型键排序；事实使用同一键排序。排序后的数组顺序参与哈希。
- `barSetHash = SHA256("market-index-bars-v1\0" + UTF8(canonicalJson(bars)))`。
- `requestSetHash = SHA256("market-index-requests-v1\0" + UTF8(canonicalJson(requests)))`。
- `formulaDefinitionHash = SHA256("market-index-facts-v1\0" + UTF8(canonicalJson(exact formula definitions)))`。
- `snapshotHash = SHA256("market-index-snapshot-v1\0" + UTF8(canonicalJson(all snapshot fields except snapshotHash)))`。

供应商名称、原始响应顺序、缓存命中、计划 id、运行耗时和条件结果绝不进入内容哈希。供应商修订号和规范化内容需要参与。

## 供应商边界

`LiveMarketIndexProvider` 和 `HistoricalMarketIndexProvider` 只公开明确命名的指数操作。Tushare 实时适配器会合并截至前一日期的历史 `idx_mins(freq="5min")` 行与当日 `rt_idx_min_daily(freq="5MIN")` 行，并从 `index_daily` 获取官方日线；股票 `rt_min` 绝不能替代指数接口。生产组合保持 `UNVERIFIED`，直到经授权的能力探测证明五个代码、这些准确 endpoint、时间标签、OHLC/昨收字段、范围、限额和权限。在此之前，生产适配器返回脱敏 `PROVIDER_UNAVAILABLE`；禁止猜测或复用股票接口。Token、原始响应、权限文本和异常正文不能进入日志、接口、报告或导出。

## 测试策略

- 校验准确十进制、时间戳、身份、OHLC、重复、缺口、未来数据和供应商故障隔离。
- 黄金测试覆盖 SMA、回看 SMA 和两类涨跌幅窗口，包括最小/最大参数和历史不足。
- 证明十只股票共用一个指数和截止时间时只发生一次供应商获取并产生一个快照哈希。
- 证明需求合并与顺序无关，两份不同计划收到同一不可变快照对象/哈希。
- 证明任一 K 线、公式、请求或修订变化会改变对应哈希；运行元数据不会。
- 证明没有指数条件的计划在快照缺失或阻断时保持原判断。

## 边界与成功标准

- 始终：在供应商边界校验，只使用完整事实，保持快照不可变，并隔离指数故障。
- 先确认：验证/启用供应商、修改公式、健康语义、哈希域或缓存身份。
- 禁止：统一市场结论、隐藏交易门槛、行业指数、合成指数、未完成周期、未来事实或包含 token 的诊断。
- 同一 `(indexCode, cutoff, requestSet)` 产生一份字节稳定快照；监控和回放使用相同模型、公式和哈希。

## 审核状态

当前用户于 `2026-09-02` 的请求已授权实施和离线验证。真实供应商能力仍明确未验证，不在本次授权范围内。
