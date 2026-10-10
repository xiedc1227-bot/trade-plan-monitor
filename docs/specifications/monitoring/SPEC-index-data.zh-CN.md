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

完成快照的缓存键为 `(mappingVersion, indexCode, decisionCutoff, requestSetHash, providerContentRevision, minimumFiveMinuteBarCount, minimumOfficialDailyBarCount)`。由于不能在获取前猜测供应商修订号，内部 `(mappingVersion, indexCode, decisionCutoff, requestSetHash, minimumFiveMinuteBarCount, minimumOfficialDailyBarCount, observedNoLaterThan)` 预取键只去重并发获取，并在任务完成时删除。最小数量属于成交额投影使用的已校验采集要求，不会构造虚假的事实请求，也不影响计划 hash。可用的完成快照不可变，并在有界的 512 项缓存中驻留；后续调用会先重新获取，因此不会遮蔽新的供应商修订号。不可用快照不保留。一个指数失败会发布该指数的阻断健康状态，但不会取消或替换其他指数。实时监控可以为没有指数条件的计划提供信息性快照，但其判断不要求该快照；回测也不为该计划强制要求指数历史覆盖。

普通每 cutoff 一次采集批次的一个有界例外，是 `SPEC-monitor-index-trends` 允许的下一分钟发布滞后补取：每 cutoff 最多一次，仅重新获取同 cutoff 最新快照只有 `MISSING_FIVE_MINUTE_BAR` 或 `STALE_DATA` 问题的指数。补取保留每个被选快照的事实请求与成交额最小 K 线数量。其部分批次只持久化重新获取的指数；未变化的健康 head 与独立阻断的 head 保持不动。若获取期间新 cutoff 或不同请求集已取代该指数，丢弃旧补取结果。普通 `prepare` 始终通过按 revision 识别的协调器重新获取，包括新计划需求和下一个交易日。

第二个例外只恢复发生临时 `PROVIDER_UNAVAILABLE` 的指数。指数适配器仅将请求控制器的 `TIMEOUT` 和 `TRANSIENT` 归为可重试；权限、限流、能力认证、处理和未知错误不进入短期重试。同一串行调度器和共享请求控制器最多执行三次额外尝试，分别在前次失败后 30、60、120 秒到期，且不超过首次失败后的五分钟。请求控制器退避和共享冷却仍然生效。恢复状态（`indexCode`、cutoff、首次失败时间、已完成尝试次数、下次到期时间）与快照 head 一同提交；重启后仅在该 head 仍阻断且窗口未过期时恢复。新 cutoff 或成功 head 会取代恢复任务；旧结果或失败结果不能覆盖同 cutoff 已为 `LIVE` 的 head。恢复仅提交指数数据和总览失效事件，不重放已完成的计划评估或通知。总览可展示同一交易日的历史五分钟走势，并明确标出最后有效时间；当前判断事实仍保持阻断。`recoveryAttempts` 和 `nextRetryAt` 表示待执行的短期重试；缺失则使用普通调度。日志只包含指数 identity、固定阶段和封闭错误代码，不包含供应商响应或异常正文。

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

`LiveMarketIndexProvider` 和 `HistoricalMarketIndexProvider` 只公开明确命名的指数操作。Tushare 实时适配器会合并截至前一日期的历史 `idx_mins(freq="5min")` 行与当日 `rt_idx_min_daily(freq="5MIN")` 行，并从 `index_daily` 获取官方日线；股票 `rt_min` 绝不能替代指数接口。并发指数批次只按请求控制器的实际并发容量准入，避免一个批次的三次有序读取让后续指数耗尽控制器入场超时。生产组合保持 `UNVERIFIED`，直到经授权的能力探测证明五个板块参考 identity 加隐藏成交额基准 `399107.SZ`、这些准确 endpoint、时间标签、OHLC/昨收/成交额字段、范围、限额和权限。缺少 `399107.SZ` 的旧 profile 对原有四张总览走势图仍然有效，但成交额基准保持 `UNVERIFIED`。相关能力就绪前，生产适配器返回脱敏 `PROVIDER_UNAVAILABLE`；禁止猜测或复用股票接口。Token、原始响应、权限文本和异常正文不能进入日志、接口、报告或导出。

## 测试策略

- 校验准确十进制、时间戳、身份、OHLC、重复、缺口、未来数据和供应商故障隔离。
- 黄金测试覆盖 SMA、回看 SMA 和两类涨跌幅窗口，包括最小/最大参数和历史不足。
- 证明十只股票共用一个指数和截止时间时只发生一次供应商获取并产生一个快照哈希。
- 证明并发指数批次遵守请求控制器的实际并发容量，不会把后续指数错误阻断。
- 证明需求合并与顺序无关，两份不同计划收到同一不可变快照对象/哈希。
- 证明任一 K 线、公式、请求或修订变化会改变对应哈希；运行元数据不会。
- 证明没有指数条件的计划在快照缺失或阻断时保持原判断。

## 边界与成功标准

- 始终：在供应商边界校验，只使用完整事实，保持快照不可变，并隔离指数故障。
- 先确认：验证/启用供应商、修改公式、健康语义、哈希域或缓存身份。
- 禁止：统一市场结论、隐藏交易门槛、行业指数、合成指数、未完成周期、未来事实或包含 token 的诊断。
- 同一 `(indexCode, cutoff, requestSet)` 产生一份字节稳定快照；监控和回放使用相同模型、公式和哈希。

## ICDR20261009 收市展示修复

已接受的 [index-close-display-repair](SPEC-index-close-display-repair.zh-CN.md) ICDR03–ICDR04/ICDR07–ICDR08 将既有成功保留规则落实到持久化。精确键的 `LIVE` 数据不被后续失败／陈旧／缺口覆盖；后续有效修订按采集时间排序，不按供应商修订号大小。不可变快照与计划输入仍保留实际尝试结果。`market_index_acquisition_state` 单独保存有界脱敏采集诊断及来源证明；迁移 `0025_index_close_display` 增加该表及恢复类型。启动修复只恢复同键已验证记录并保留决策引用。普通临时失败仍为 30/60/120 秒；最终目标在 +5 分钟内共享最多 3 次补充启动，涵盖原因变化及重启。不改变数据源接口、权限、公式或哈希域。
