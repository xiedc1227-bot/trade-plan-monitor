# 规格：backtest-data

> 中文审阅版。英文权威版为 `SPEC-backtest-data.md`；两份文档必须保持语义一致。

## 目标

增量获取经明确授权的 A 股历史事实，把不可变的内容寻址修订保存到 `backtest-market.sqlite3`，并冻结可复现数据集，使多次离线运行可以复用同一批行情而不复制行情行。

## 关系与范围

`backtest-data` 是稳定 `backtest` 项目下的供应商与数据集边界。它负责历史能力映射、覆盖检查、同步、不可变修订、校验和 `dataset_hash`。它不负责策略回放、模拟成交、结果持久化、任务、HTTP、Vue、实时监控或通知。

一个数据集可以包含 1–10 只股票以复用同步事实，但 `backtest-engine` 每次仍只运行一个经审核的计划版本和一只股票。历史 `stk_mins` 证据继续独立于实时 `rt_min` 和 `rt_min_daily`；本模块不能完成 `T058`。

## 命令

保留现有兼容命令：

```powershell
python -m trade_plan_monitor backtest sync --symbols 003043.SZ --start 2025-01-02 --end 2025-12-31 --allow-network
python -m trade_plan_monitor backtest verify --symbols 003043.SZ --start 2025-01-02 --end 2025-12-31
```

`sync` 是唯一允许联网的操作。`verify`、覆盖检查、数据集列表和冻结读取都只在本地执行。长时间 Web 提交由 `backtest-jobs` 负责，而不是由此命令适配层负责。

## 公共契约

保留与供应商无关的 `HistoricalMinuteProvider`、`DatasetScope`、`DatasetManifest`、`DatasetFreezeResult`、`BacktestSyncResult`、`BacktestSyncService.sync(...)`、`BacktestMarketStore.freeze_dataset(...)`，以及日历、分钟、涨跌停和官方日线的冻结读取契约。

增加供应用/API 组合使用的有界只读契约：

- `inspect_coverage(scope)` 在不访问供应商的情况下返回精确的可用/缺失来源计数；
- `list_datasets(limit, cursor)` 返回不可变 manifest 摘要，`limit` 范围为 `1..100`，使用不透明有界 cursor，并返回精确的 `items`、`limit`、`nextCursor` 和 `hasMore` 页面字段；
- `get_dataset(dataset_hash)` 返回有界 `BacktestDatasetSummary`，包含范围、配置、复权策略、创建时间、artifact/交易日/分钟/参考计数及覆盖/阻断代码，不包含 membership 行；不存在时返回 `NOT_FOUND`；
- `open_frozen_dataset(dataset_hash)` 是引擎/存储内部契约，按股票交易日校验并迭代完整 `DatasetManifest` membership，绝不把它序列化到 HTTP；
- 进度和取消回调属于运维侧通道，不进入 `dataset_hash`、artifact 哈希或供应商事实。

完整 manifest membership 不是公共应用/API 响应。未来诊断如果需要该信息，必须另行批准 cursor 分页投影；首个 Web 版本只暴露摘要与覆盖。

`DatasetScope` 继续包含股票列表、`start`、`end`、`warmup_start`、历史标签配置和复权策略。JSON 适配器使用 camelCase，Python 契约继续使用 snake_case。

## 数据与存储契约

- `backtest-market.sqlite3` 负责规范历史 artifact、不可变修订、当前 head、同步元数据、数据集 manifest/成员关系和 `dataset_hash`。
- 实时数据库和 `backtest-results.sqlite3` 必须解析为不同文件；如果在 DDL 前检测到对方存储域表，则拒绝使用。
- 相同规范内容是无操作。供应商修正只追加修订，绝不覆盖旧数据集引用的内容。
- 数据集引用精确修订，绝不为每次运行复制分钟行。
- 解析或回放前重新计算每个冻结 artifact 的哈希；看似合法的 manifest 文本不能授权被修改的 `content_json`。
- 精确 Decimal 规范化拒绝二进制浮点、统一数值相等的 scale 变体、把定点展开限制为 10,000 个字符，并把转换后的分限制为 `9,223,372,036,854,775,807`。

## 同步、校验与取消

`DatasetScope` 包含 1–10 只不重复股票，`start` 到 `end` 最多五个日历年，`warmup_start` 到 `start` 最多两个日历年。`end >= today`、非法股票/范围、`.BJ` 和未验证配置在访问供应商或持久化前失败。

已批准配置继续是 `TUSHARE_STK_MINS_241_END_V1`：09:30 来源行保留为非策略 `opening_special`，一个完整正常交易日必须暴露精确 240 根可用规范分钟。日历调用必须明确指定 `SSE` 或 `SZSE`。`stk_mins`、`trade_cal`、不复权 `daily` 和 `stk_limit` 响应都属于不可信完整来源；缺失、多余、重复、非法、跨股票、跨交易所或超范围 identity 在持久化前失败。

网络调用位于事务外。一次已校验持久化批次最多 1,000 行。校验持有稳定 WAL 读快照，一次最多扫描一个股票交易日的分钟批次；关闭读快照后，在短 `BEGIN IMMEDIATE` 事务中分批重验所选 head 并发布，每批最多 1,000 个。

取消采用协作方式。同步会在每次供应商调用前、响应后、股票交易日之间以及进入下一来源前检查；已经在途且校验通过的来源可以提交，但观察到取消后不得启动新的供应商请求。冻结会在股票交易日批次之间和发布前检查；取消后只能留下零个 manifest 或一个完整不可变 manifest，绝不留下部分 manifest。重新提交可以复用之前安全提交的缓存行。任务/结果存储之间不存在跨数据库事务。

## 安全与可观测性

信任边界包括 Web/CLI 范围、环境密钥引用、供应商响应和磁盘 SQLite 内容。需要保护的资产是 Tushare 凭据、不可变历史事实、数据集 identity 和本地存储可用性。

- 每次同步提交都要求明确联网授权和环境密钥引用。
- 绝不持久化或记录 Token、Authorization Header、原始供应商响应、被拒绝 payload、来自 Web 请求的数据库路径或堆栈信息。
- 使用参数化 SQL 和稳定、脱敏的错误/阻断代码。
- 为同步开始、有界进度、来源提交、取消、完成和失败发出结构化事件，并携带调用方提供的 `jobId`/请求关联信息；标签集合必须有界。
- 运维日志和回调不能改变内容哈希或数据集 identity。

## 性能预算

- 任何操作都不能把多年分钟数据一次性载入内存。
- 数据集列表/详情响应只包含摘要，且必须低于共享 4 MiB JSON 边界；完整 membership 只在存储/引擎内部增量消费。
- 冻结和回放读取按股票交易日执行，并使用 `(symbol, bar_end)` 或 manifest natural-key 索引。
- 持久化和 head 重验批次最多 1,000 行。
- 重复相同同步执行零次供应商调用且增加零个修订。
- 刷新未变化内容增加零个修订。
- 在保留任何优化前，至少针对两只股票和多个交易日记录数据库/WAL 大小、峰值内存、供应商调用次数和耗时。

## 项目结构

历史供应商接口与 Tushare 映射保留在 `src/trade_plan_monitor/market_data/`。数据集 identity、同步、存储、规范化和存储保护保留在 `src/trade_plan_monitor/backtest/`。CLI 组合保留在 `src/trade_plan_monitor/cli.py`。此逻辑模块拆分不要求仅为了匹配文档名称而移动正常工作的文件。

## 代码风格

在外部/应用边界使用冻结、严格的 Pydantic 值；供应商契约使用 `Protocol`；使用规范 RFC 3339 存储形式精确为 `YYYY-MM-DDTHH:MM:SS.ffffff+08:00` 的带时区 `Asia/Shanghai` 值、整数分或精确 `Decimal`、参数化 SQL、显式稳定阻断和依赖注入。供应商映射可以接受携带 `+08:00` 的 0～6 位小数秒，但必须在哈希/持久化前规范化；拒绝 `Z`、无偏移日期时间文本、超精度和其他偏移。供应商特定映射不得进入数据集逻辑，导入时不得构造网络客户端。

## 测试策略

默认测试使用夹具并执行零次网络调用。单元与集成覆盖必须包含范围边界、241 到 240 标签配置、精确参考 identity、非法/重复事实、周末/午休/交易时段边界、修正、相同同步无操作、取消/重新提交、读快照发布竞态、artifact 篡改、Decimal 上限、数据库路径混淆、重开、不泄露 membership 的有界摘要序列化、完整 manifest 增量迭代和两股票多日覆盖。经授权的真实 Tushare 证据属于独立验证资产，绝不随凭据提交。

## 边界

- 始终：持久化前校验完整供应商来源，并把供应商调用放在事务外。
- 始终：保留不可变修订、精确哈希、明确 SSE/SZSE 日历和隔离存储。
- 先询问：更改供应商/配置、时间戳映射、复权/公司行动策略、BSE 支持、哈希 Schema、范围上限或行情删除/GC。
- 禁止：前向填充、猜测日历/涨跌停、静默丢弃非法行、覆盖被引用修订、暴露密钥、读取实时状态或把历史计作 `T058` 证据。

## 验收标准

- 未变化事实逐字节复现相同的 64 字符 `dataset_hash`；修正产生不同哈希，同时旧数据集继续可复现。
- 完整正常交易日在 `TUSHARE_STK_MINS_241_END_V1` 下暴露精确 240 根可用规范分钟。
- 相同同步在供应商和存储层都保持幂等。
- 取消后重新提交可以完成，且没有重复事实或部分 manifest。
- 每次冻结读取都能检测内容篡改。
- 两只股票跨多个交易日通过精确日历/分钟/涨跌停/日线覆盖，且内存和批次有界。
- 实时与结果存储保持不变，`T058` 继续独立。

## 开放问题

BSE 历史在另行批准日历契约前继续阻断。公司行动复权、用户自定义数据集标签、数据集删除和未引用行情历史 GC 延后到首个 Web 版本之后。
