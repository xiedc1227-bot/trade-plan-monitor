# 回测生产 fake 验收

状态：PASS

- 证据日期：2026-08-31（Asia/Shanghai）
- 证据基线：`main` 的 `f877d8c77b41cec03e58d838e5cb0f01531300d7`；本报告记录从该基线产生的已验收候选，不预先声称其最终提交 ID。
- 边界：仅离线生产组合与确定性 fake contract。没有调用真实 Tushare、券商、通知、凭据、AI 供应商或外部网络。
- 范围说明：BT050 的五项交付物是验收测试、本双语报告对和双语 todo 更新。另经用户授权的生产前置问题已在 BT050 通过前修复；这些修改作为前置项接受审核和验证，不冒充 BT050 精确五文件 harness 范围的新增文件。未放宽任何阈值。

## 参考环境

| 项目 | 固定观测 |
|---|---|
| OS / 主机 | Windows 11 `10.0.26200`、Intel Core Ultra 9 275HX、24 个逻辑处理器、31.43 GiB 可用内存 |
| Python / SQLite | CPython 3.14.7 x64 / SQLite 3.50.4 |
| Node / npm | Node 24.13.1 / npm 11.8.0 |
| 浏览器 | Playwright 1.62.1、隔离 Chromium 151.0.7922.34、仅 Chromium 验收 |
| 存储 / 电源 | NTFS 固定 `D:` 卷、总计 931.5 GiB、平衡电源方案 |
| 运行时 | 单进程、一个活动回放槽、本地 SSD、fake provider、无并发基准负载 |

## 集成功能证据

`BT050-JOURNEY` 在 `tests/integration/test_backtest_acceptance.py::test_fake_production_journey_is_complete_offline_and_live_state_is_unchanged` 中通过：fake 生产路径执行 `sync → verify → submit → poll → result → pin → export`，经过生产 route/composition 边界，且不读写实时供应商状态。

`LIVE-STATE-ZERO-DIFF` 与 `NOTIFICATION-ZERO-CALLS` 是该节点中的精确断言：捕获的实时状态指纹保持不变，供应商、通知和 WebSocket 投递调用数保持为零。所有可见成交与导出均标记为历史模拟/研究输出。

`BT050-TWO-SYMBOL` 在 `tests/integration/test_backtest_acceptance.py::test_each_fixture_symbol_has_stable_buy_and_t1_exit_bytes` 中通过：`003043.SZ` 与 `600000.SH` 的独立多日运行各包含买入和 T+1 减仓/退出，且重复运行/报告/导出字节一致。

两个新增功能节点合并运行结果为 `2 passed`；固定验收文件共收集八个节点。

## 2026-09-02 板块指数扩展证据

已批准的 `market-index-context` 设计现已在监控和回测中完成离线实现。封闭的 `board-index-map-v1` 只映射五个已批准板块，无法分类的股票不会回退而是直接拒绝。共用快照测试证明同一指数/截止时间/请求集合只获取一次并以不可变形式发布；判断测试证明两份计划可以基于同一快照得到不同最终结果，且没有指数叶子的计划在指数数据缺失或阻断时保持原有判断。

Schema v2 增加自动参考市场绑定和六种允许的条件叶子，使用准确范围、三值 `MISSING_INPUT` 行为、确定性路径证据和新哈希域。既有 Schema v1 计划/结果黄金值保持不变。生成式 AI Schema 的变化独立版本化为 `plan-extract-v2`；逐字节相同的 v1 提示词仍可使用，其 SHA-256 为 `420e06c0a8ab136a1b95c8218474fccd7f134d1bc5c9e1365e0c6a4a099e3d8d`，v2 固定为 `6d9ba53055700e508251fc62ce3a10c2c719b68874ac78aee9f27cbd40127daf`。

回测数据集 v2 冻结规范化指数 artifact 和准确成员关系，不重写 v1 数据集。运行 v3 复用共用快照/公式计算器，持久化逐决策参考市场证据，并在保持 summary-v2 与 fills-v2 字节兼容的同时发布 summary-v3 导出证据。运行前覆盖端点和已完成运行的指数序列端点均以后端为权威且有界，并纳入冻结的 41 路径 OpenAPI 契约；其 SHA-256 为 `18ce84db8156ad5c4db94a193157e6509b46ab4a03bfdc1ea2b2dceb88fe9d0c`。

验证过程未提供供应商凭据，也没有外部流量：

- 最终缓存身份和正式收盘批处理修复后的快照/运行时受影响聚焦回归：`54 passed`；
- 完整非 live 后端集合：`2,104 passed, 1 skipped`；最终工作树上的八个长时验收节点在 `2,598.17 s` 内全部通过，其余分区为 `2,096 passed, 1 skipped, 4 deselected`；
- AI 提示词兼容/版本回归：`72 passed`；
- 冻结 OpenAPI 快照回归：`13 passed`、共 `41` 条路径，生成 TypeScript 无漂移；
- 前端单元套件：`30` 个文件、`497 passed`；
- 隔离 Chromium：`7 passed`，包括后端解析的运行前覆盖、冻结参考指数页签、准确计划路径和持久化逐决策证据；
- Ruff、`compileall`、OpenAPI/生成 TypeScript 漂移检查、Vue/TypeScript 类型检查、Vite 生产构建和空白检查通过。

真实板块指数供应商能力刻意保持 `UNVERIFIED`。没有调用 Tushare 或其他供应商端点；准确盘中/日线接口、账户对五个指数代码的权限、时间戳/字段语义、限额和最长历史均不在本次授权范围内。离线实现只提供严格供应商协议和确定性 fake，不能解释为真实服务已经就绪。

## 后端资源与性能证据

`BT050-RESOURCE` 使用已批准固定夹具且绝不联网。

### BT-FUNCTIONAL-20D

预热后五次新鲜数据库正式重复全部通过 30 s / 512 MiB / 64 MiB / 32 MiB 闸门：

```text
elapsedSeconds = [5.597796800, 5.520017000, 5.475313000, 5.480158400, 5.444831700]
workingSetDeltaBytes = [13496320, 12861440, 12902400, 12992512, 13561856]
marketDatabaseAndWalBytes = [4235264, 4235264, 4235264, 4235264, 4235264]
resultDatabaseAndWalBytes = [1392640, 1392640, 1392640, 1392640, 1392640]
```

最终 traced-heap 节点相对 256 MiB 上限报告 `12,678,486` bytes。`tests/integration/test_backtest_acceptance.py::test_twenty_day_replay_meets_traced_heap_budget` 通过。

### BT-CAPACITY-1Y

精确夹具包含十个固定股票、252 个交易日、604,800 根可用分钟线、400 个日历日预热；每次重复使用一个冻结数据集并顺序运行十个单股票回放。一次成功完整预热之后进行了以下三次新鲜正式重复：

```text
repetition-1 seconds = [106.295148400, 106.055265700, 104.515315200, 108.556621300, 106.568615600, 106.352307200, 104.775915400, 104.630981600, 103.592741000, 104.496511300]
repetition-2 seconds = [103.749614400, 105.201066500, 104.754093900, 104.687957000, 104.773838400, 104.863972400, 104.684553400, 104.984016300, 104.928564100, 104.851780100]
repetition-3 seconds = [106.300322100, 105.931607800, 106.199623500, 106.405021900, 105.729062700, 105.998598400, 105.680132400, 106.039019600, 106.199076700, 106.013356700]
marketDatabaseAndWalBytes = [519028736, 519028736, 519028736]
resultDatabaseAndWalBytes = [184909824, 184909824, 184909824]
workingSetDeltaBytes = [67825664, 67137536, 64708608]
```

全部 30 个回放值均低于 120 s；每个行情/结果数据库均低于 512/192 MiB，每个 working-set 增量均低于 768 MiB。精确容量 traced-heap 节点相对 384 MiB 上限报告 `123,830,868` bytes，并在 `tests/integration/test_backtest_acceptance.py::test_252_day_replay_from_ten_symbol_dataset_meets_traced_heap_budget` 通过。

前置 RED 为 `959,445,307` traced bytes。已接受修复在顶层流式计算规范报告哈希，每次只编码一条已验证 decision。Runner 金样保持一致（`19 passed`），最终峰值有界，且未改变 hash domain 或公共报告字段。

### BT-QUERY-LARGE 与 BT-EXPORT-100K

夹具包含 10,000 个 jobs、1,000 个 completed runs、目标运行 100,000 条 fills、每种公共 detail 30,000 行及 2,000 个权益点。五次预热加 30 次正式调用全部通过：

| 操作 | p50 ms | p95 ms | 最大 ms |
|---|---:|---:|---:|
| jobs | 2.529 | 2.895 | 3.059 |
| runs | 49.707 | 50.927 | 52.629 |
| fills | 5.458 | 5.759 | 5.781 |
| decisions | 9.238 | 9.625 | 9.882 |
| signals | 9.264 | 9.604 | 9.633 |
| outcomes | 9.625 | 9.921 | 10.067 |
| equity | 87.444 | 91.851 | 138.556 |

查询内存增量为 `1,589,248` bytes，DB+WAL 为 `298,213,376` bytes。页面始终不超过 100 items，每项不超过 32 KiB，JSON 小于 4 MiB，权益恰好 2,000 点。

```text
exportFirstByteMs = [2.7377, 2.7569, 2.7174, 2.6593, 2.7122, 2.8713, 2.8024, 3.0776, 3.0798, 2.7860, 2.8057, 2.7528, 2.8589, 2.7283, 2.8529, 2.7950, 3.0727, 3.1176, 2.9188, 2.7701, 2.7511, 3.0803, 2.6918, 2.8374, 3.0930, 2.6989, 3.2186, 3.1143, 2.8103, 2.6789]
exportThroughputMiBPerSecond = [6.2086, 6.1234, 6.2454, 6.1157, 6.2000, 6.1693, 6.1502, 6.0388, 6.1672, 6.0885, 6.1561, 6.1213, 6.1920, 6.0896, 6.1698, 6.1085, 6.1147, 6.0674, 6.1391, 6.1535, 6.0889, 6.1712, 6.0916, 6.1745, 6.0963, 6.0955, 6.0668, 6.1321, 6.0974, 6.1282]
```

首字节 p95 约为 3.115 ms，最小吞吐为 6.039 MiB/s，导出内存增量为 `2,945,024` bytes，最大 chunk 保持低于 64 KiB。CSV header 在 active-v2 元数据验证后发出；完整 100,000 行发布集合在第一条 fill 行前完成 content-hash、JSON identity 与 set-hash 验证。Payload/SQL-identity 篡改回归通过（export 文件 `5 passed`），断连行为由下文证据引用。

## 浏览器、bundle 与无障碍

`BROWSER-CHROMIUM-ONLY` 在隔离 Chromium 生产 build 中使用 1440×900、4× CPU slowdown、20 ms loopback latency，每路由五次预热加 20 次测量。它不声称 Gecko/Firefox 兼容性。

| 路由 | LCP p75 / 最大 ms | INP p75 / 最大 ms | CLS p75 / 最大 |
|---|---:|---:|---:|
| `/backtests` | 172 / 192 | 0 / 0 | 0.04019 / 0.04019 |
| `/backtests/new` | 172 / 188 | 16 / 24 | 0.04019 / 0.04019 |
| `/backtests/data` | 172 / 216 | 16 / 24 | 0.04019 / 0.04019 |
| `/backtests/{runId}` | 204 / 208 | 0 / 0 | 0.02107 / 0.02107 |

INP 为零表示观察事件低于 Chromium PerformanceEventTiming 报告下限。代表性交互 p95 分别为：筛选 21 ms、分页 30 ms、结果 tab 21 ms、校验摘要聚焦 30 ms、取消对话框打开 29 ms、关闭 28 ms。排序控件按设计禁用，固定值为 `completedAt_desc`；未伪造排序交互。全部浏览器样本的 console、API、failed-request、unexpected-request 和外部网络 finding 均为零。

生产 build gzip 大小为：entry 26.54 KiB、共享 Vue helper 23.17 KiB、四个非图表回测路由 5.98/6.61/8.25/11.28 KiB、共享 backtest API chunk 10.68 KiB、lazy ECharts chunk 168.36 KiB。三个非图表路由加载零 ECharts bytes；详情路由仅在选择权益 tab 后加载。

允许的 Chromium E2E 文件以 `6 passed` 通过：`web/tests/e2e/backtests.spec.ts` 与 `web/tests/e2e/accessibility.spec.ts`。它们覆盖 320/768/1024/1440 layout、200% text、键盘/reduced motion、request/timer/DOM 上限、lazy loading 和零 serious/critical axe finding。受保护的 `web/tests/e2e/security.spec.ts` 未读取也未运行。Windows `NVDA` 四路由清单沿用 BT049/BC18（`cb81cf4`）的 PASS；未跟踪 screenshot、trace、profile 或 download。

## 迁移、回滚、竞态、保留与隔离证据

以下精确节点合并重跑并以 `12 passed` 通过：

- `MIGRATION-ROLLBACK` — `tests/integration/test_backtest_migrations.py::test_migration_decision_is_bound_to_source_and_verified_backup_facts`
- `MIGRATION-IDENTITY` — `tests/integration/test_backtest_migrations.py::test_market_metadata_migration_preserves_all_identity_bearing_rows`
- `BACKUP-RESTORE` — `tests/integration/test_sqlite_backup.py::test_verified_backup_restores_to_a_readable_database`
- `CANCEL-FIRST-RACE` — `tests/integration/test_backtest_job_coordinator.py::test_atomic_completion_gives_cancellation_first_one_terminal_and_no_partial_result`
- `PUBLICATION-FIRST-RACE` — `tests/integration/test_backtest_job_coordinator.py::test_atomic_completion_gives_publication_first_one_terminal_and_visible_result`
- `RECOVERY-FENCING` — `tests/integration/test_backtest_job_leases.py::test_recovery_has_exactly_three_claim_generations_and_fences_stale_tokens`
- `REPLAY-RESTART` — `tests/integration/test_backtest_runner.py::test_midrun_cancellation_and_restart_replay_from_the_frozen_beginning`
- `RETENTION-BOUND` — `tests/integration/test_backtest_retention.py::test_result_cleanup_consumes_only_caller_budget_and_never_vacuums`
- `WAL-SNAPSHOT` — `tests/integration/test_backtest_result_queries.py::test_detail_page_uses_one_wal_snapshot_during_partial_cleanup`
- `EXPORT-BOUNDS` — `tests/integration/test_backtest_export_api.py::test_disconnect_stops_before_pulling_the_next_chunk_and_closes_iterator`
- `EVENT-LOOP-ISOLATION` — `tests/integration/test_backtest_job_coordinator.py::test_blocking_job_keeps_event_loop_responsive_and_heartbeats_on_one_owned_thread`
- `PRODUCTION-PLAN-ISOLATION` — `tests/integration/test_backtest_production_composition.py::test_production_factory_is_lazy_and_run_replay_reuses_one_plan_snapshot`

迁移授权把重新计算的源 fingerprint 与已验证备份事实绑定；确定性测试 backup SHA-256 事实为 `dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd`，源 fingerprint 不匹配会被拒绝。恢复检查 `PRAGMA integrity_check = ok` 和 WAL sentinel。因此回滚是经过验证的文件恢复，而不是反向或猜测 SQL。既有 v1 bytes 与承载 identity 的 rows 保持不变。

板块指数启动兼容性新增两个聚焦节点：

- `MARKET-INDEX-SCHEMA-EXPANSION` — `tests/integration/test_backtest_migrations.py::test_exact_pre_index_market_schema_expands_without_rewriting_v1_data`
- `MARKET-INDEX-PARTIAL-FAIL-CLOSED` — `tests/integration/test_backtest_migrations.py::test_partial_market_index_extension_still_fails_without_mutation`

板块指数结构扩展完成后，全部 `37` 个迁移测试以及排除独立重型验收文件的完整非 live 后端套件分别以 `37 passed` 和 `2098 passed, 1 skipped, 4 deselected` 通过。现有六表 `data/backtest-market.sqlite3` 的副本也成功完成启动扩展，`PRAGMA integrity_check = ok`，三张新增指数表均为空；该检查没有修改原数据库。

## P19～P27 证据映射与检查点决定

| 能力 | 证据 |
|---|---|
| P19 兼容/迁移 | MIGRATION-ROLLBACK、MIGRATION-IDENTITY、BACKUP-RESTORE、MARKET-INDEX-SCHEMA-EXPANSION、MARKET-INDEX-PARTIAL-FAIL-CLOSED |
| P20 上海时间 identity/input | 既有 run-input/time 金样与完整后端闸门 |
| P21 回放/发布 | BT050-TWO-SYMBOL、REPLAY-RESTART、容量/功能测量 |
| P22 查询/导出/保留 | BT-QUERY-LARGE、BT-EXPORT-100K、RETENTION-BOUND、WAL-SNAPSHOT、EXPORT-BOUNDS |
| P23 jobs/恢复 | CANCEL-FIRST-RACE、PUBLICATION-FIRST-RACE、RECOVERY-FENCING、EVENT-LOOP-ISOLATION |
| P24 后端 API/组合 | BT050-JOURNEY 与 PRODUCTION-PLAN-ISOLATION |
| P25 生成前端契约 | production build、type-check 与前端单元闸门 |
| P26 浏览器/无障碍 | BROWSER-CHROMIUM-ONLY、axe、键盘/响应式 E2E、NVDA |
| P27 最终集成 | 本报告与 `tests/integration/test_backtest_acceptance.py` |

明确将 `BC01` 重评为 PASS：四项已记录检查现已全部满足。双股票/多日可操作 fills、持久 lease/恢复、从起点重放、LIVE-STATE-ZERO-DIFF、NOTIFICATION-ZERO-CALLS、资源上限、置顶/取消置顶及 initial-lot/公共结果路径均有覆盖。历史获取继续与真实 Tushare 验收分离，任何模拟记录均不呈现为券商成交或实时提醒。策略事件 cursor resume 保持既有延期，不作静默声称。

在 BT050 的决定时点，`T058` 保持 Open 且受外部闸门阻断，因为未授权或运行真实 Tushare contract。在同一时点，`T059` 与 `C24` 保持 Open，因为可选真实 AI、真实 contract 和最终用户发布验收不属于 BT050。T059 与 C24 随后于 2026-09-01 通过验收；其历史发布决定不认证当前仓库级门禁。这些有时间边界的状态不作为 BT050 失败。

`BC19 / I4` 对这份历史验收证据已完成。在其决定时点，最终离线闸门中，排除受保护文件的后端套件以 `1,941 passed, 1 skipped` 通过，前端单元套件以 `484 passed` 通过，允许的 Chromium E2E 套件以 `6 passed` 通过；Ruff check/format、`compileall`、`pip check`、OpenAPI/TypeScript generator `--check`、type-check、生产构建与空白检查也全部通过。最终新鲜上下文对抗审核覆盖正确性、安全、架构、性能、兼容性、测试充分性与双语证据，未发现未解决 P0～P2 问题。两项仅可维护性的 P3 观察已修正，随后受影响后端闸门以 `302 tests` 通过。当前仓库级门禁和 LPC012 状态由实时生产链路验收单独记录。

## 已知警告与制品策略

唯一重复测试警告是既有 Starlette `TestClient`/httpx2 弃用警告。原始临时 SQLite 数据库、浏览器 profile、screenshot、trace、下载导出与 profiler 数据保持在 Git 外。五个受保护验证专用文件继续保持未跟踪、未触碰，并从正式文件清单排除。
