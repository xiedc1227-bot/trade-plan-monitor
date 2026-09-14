# 指数收盘恢复验证

## 范围与原因

2026-09-14 15:20:16 +08:00，`000001.SH` 持久化了带有 `PROVIDER_UNAVAILABLE` 的 `BLOCKED` 快照。现有日志未能还原原始异常，后续独立采集已成功。SQLite 中没有待执行的指数恢复任务。

没有符合条件的计划评估时，`_refresh_dashboard_indexes` 原来仅在 `close_attempt == 1` 时采集指数，因此 16:00、17:00 的收盘任务无法替换 15:20 的失败快照。确定性回归测试复现了这两个错失的恢复机会。

## 修改与边界

- 没有选中符合条件的计划评估时，每次计划内的 `OFFICIAL_CLOSE` 任务都会刷新首页指数。空的 `plans=()` 保持仅展示行为，不评估计划或发送提醒。
- 常规指数采集、发布延迟恢复和临时故障恢复均保留至少 2 根正式日线，避免新发布的当日收盘数据挤掉首页所需的前一交易日数据。
- 首页的 `priorClosePoints` 和 `sessionChangeRatio` 使用日期严格早于截止日期的最后一根正式日线。缺少前一交易日数据时，显示带有 `MISSING_OFFICIAL_DAILY_BAR` 的 `BLOCKED`，并将摘要行情字段标为不可用。
- 不修改不可变的已存快照及其哈希；昨收修正位于读取投影层。现有临时故障重试限制、数据源请求间隔和计划评估规则保持不变。

## 验证

16:00、17:00 的恢复测试在调度修改前失败，修改后通过。两个昨收回归用例在投影修改前失败，修改后通过。已有的模拟收盘测试现在会先推进时钟，再执行未来时点的任务。

在 `test_live_pipeline_acceptance.py`、`test_market_index_runtime.py`、`test_market_index_snapshots.py`、`test_market_index_web.py`、`test_tushare_market_index.py`、`test_monitor_runtime.py` 和 `test_persistent_monitor_read_service.py` 中，186 项选定测试通过。主检查通过 183 项，另一次检查通过其余 3 项不受影响的启动变体。Ruff 和 `git diff --check` 通过。未运行整个仓库的完整测试集。

另外两项选定测试失败；加载原始 `HEAD` 版本的 `runtime/production.py` 后，也复现了相同失败：

- `test_market_index_persistence_reuses_an_older_canonical_content_revision`：头记录时间保持为 10:36，而非预期的 10:38。
- `test_startup_batches_persisted_pending_closes_by_date_and_shared_index[index_error]`：参考快照为 `LIVE`，而非预期的 `BLOCKED`。

未禁用或修改这两项原有失败测试，保留为独立排查事项。

## 本地恢复结果

对 `000001.SH` 的一次性补采复用了原失败快照的截止时点和事实请求，要求 48 根五分钟线及 2 根正式日线，且只在获得验证通过的 `LIVE` 快照后发布。通过已有持久化事务追加了一个 `market.index.updated` 事件，序号为 633。未执行计划评估或通知。

已重启 PyCharm 中原有的 `dev` 后端；`/api/v1/health` 返回 `RUNNING`，`startedAt` 为 2026-09-14T17:03:05.929554+08:00。`/api/v1/dashboard` 和浏览器均确认：

- `000001.SH`：`LIVE`，当前点位 3885.333，昨收 3888.1106，涨跌幅显示 -0.07%。
- 完整数据截止 2026-09-14T15:00:00+08:00。
- 沪深成交额显示为 1.61 万亿元人民币。

下次轮询为 2026-09-15T09:31:12+08:00。后续收盘恢复仍依赖计划采集时数据源成功返回；本次修改没有增加无限制的盘后重试。
