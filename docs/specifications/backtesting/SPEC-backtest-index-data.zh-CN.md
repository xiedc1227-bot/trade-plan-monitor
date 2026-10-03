# 规格：backtest-index-data

> 中文审阅版。英文权威版为 `SPEC-backtest-index-data.md`；两份文档必须保持语义一致。

## 目标

在股票历史旁冻结准确板块指数历史，计算计划专属预热和覆盖，并在不使用未来数据或供应商访问的情况下回放与监控相同的快照/公式/证据输入。现有数据集和运行保持为不可变兼容 artifact。

## 命令与结构

```powershell
python -m pytest tests/unit/test_backtest_index_data.py -q
python -m pytest tests/integration/test_backtest_index_dataset.py tests/integration/test_backtest_runner.py -q
python -m ruff check src/trade_plan_monitor/backtest src/trade_plan_monitor/market_index
```

```text
src/trade_plan_monitor/backtest/index_data.py      # 需求、覆盖和回放快照
src/trade_plan_monitor/backtest/dataset.py         # 增量 v2 指数 artifact 身份
src/trade_plan_monitor/backtest/market_store.py    # 不可变 INDEX_5M/INDEX_DAILY 修订
src/trade_plan_monitor/backtest/runner.py          # 截止安全快照注入
tests/unit/test_backtest_index_data.py
tests/integration/test_backtest_index_dataset.py
```

## 数据集版本与范围

- 现有 `backtest-dataset-v1` manifest、哈希、股票 artifact 和已完成结果绝不重写。
- 准确匹配上一版六表股票专属结构的市场库会被明确识别，并在单个事务中追加三张空指数表及其索引；现有行和数据集字节经验证保持不变。部分指数扩展、未知结构、sidecar 或任意不匹配仍会在写入前失败关闭。
- 新冻结数据集可以使用 `backtest-dataset-v2`，通过 `board-index-map-v1` 为每个股票代码派生唯一板块指数，并可包含不可变 `INDEX_5M` 和 `INDEX_DAILY` artifact。
- 用户、AI 和 API 客户端绝不选择指数代码。数据集保存按股票代码和指数代码排序的派生 `referenceMarketBindings`。
- 数据集范围仍为 1–10 只股票。派生指数最多五个，不计入额外股票数量。
- 指数供应商获取是独立能力，在另行探测前保持 `UNVERIFIED`。离线夹具和已保存的规范化 artifact 可用于测试；`verify`、冻结、运行、结果查询和导出期间不发生真实请求。

`backtest-dataset-v2` 哈希成员在全部现有股票事实之外，还包含准确映射版本、派生绑定、规范指数 artifact 修订哈希和 `formulaDefinitionHash`。运行任务 id、进度、缓存状态、供应商名称和计划条件不参与。任何相关指数 K 线修订、映射版本或公式定义变化都会产生不同数据集哈希，同时历史 v1/v2 manifest 继续可读。

## 计划专属需求与预热

只有选中计划至少包含一个指数叶子时，指数覆盖才是必需条件。没有指数叶子的计划继续使用现有股票专属覆盖/运行路径，即使信息性指数历史缺失或阻断也一样。

对一份计划，从四个策略树中提取准确事实请求并去重。`eventStart` 之前所需输入取以下最大值：

- `INDEX_CLOSE_GTE_MA`/`INDEX_CLOSE_LTE_MA` 需要 `period` 个正式开市日；
- `INDEX_MA_NON_DECREASING`/`INDEX_MA_NON_INCREASING` 需要 `period + lookback` 个正式开市日；
- `OFFICIAL_OPEN_DAYS` 的 `INDEX_RETURN_*` 需要 `window_size + 1` 个正式开市日；
- `FIVE_MINUTE_BUCKETS` 的 `INDEX_RETURN_*` 需要 `window_size + 1` 个完整五分钟周期。

所需预热由计划决定，绝不使用全局固定数值。日历导航只使用数据集中已经冻结的中国市场正式开市日。缺少前序事实、缺口、重复、未来 K 线、错误指数身份、错误公式哈希，或晚于回放截止的 K 线都属于明确阻断项。

## 存储与回放契约

`INDEX_5M` 自然身份为 `(indexCode, barAt)`，`INDEX_DAILY` 为 `(indexCode, officialTradeDate)`。每个不可变 artifact 使用与监控相同的规范 `MarketIndexBar` 和内容哈希。修订只追加；引用内容绝不覆盖。冻结读取在解析前重新计算哈希，并按指数-日期有界迭代。

`MarketIndexReplaySeries` 只提供 `barAt <= decisionCutoff` 的 K 线。每份计划/截止时间调用监控使用的同一 `market-index-facts-v1` 计算器和快照构造器。同一回放进程中，相同 `(indexCode, cutoff, requestSetHash, datasetRevision)` 的快照在不同股票运行/reader 间驻留共用；计划证据继续独立。

`datasetRevision` 只作为进程内回放驻留栅栏。回放快照的内容 `revision` 来自准确选中 K 线的供应商修订号，因此本地 SQLite 行 ID 绝不进入 `snapshotHash`；相同的监控/回放 K 线、请求和截止时间会保持逐字节一致。

盘中股票判断只使用完整指数五分钟周期以及在该截止时间已经可用的正式日线事实。正式收盘股票判断只在观察/确认时间不晚于判断输入时使用当天规范正式指数收盘。预热 K 线参与 `marketIndexDataHash`，但不能产生成交或可见事件期收益。

## 身份

- `marketIndexDataHash = SHA256("backtest-index-data-v1\0" + UTF8(canonicalJson(sorted exact index artifact memberships)))`。
- `indexRequirementHash = SHA256("backtest-index-requirements-v1\0" + UTF8(canonicalJson(sorted plan fact requests and exact paths)))`。
- 包含指数叶子的 Schema v2 计划使用 `backtest-run-v3`；预映像包含现有规范运行输入以及绑定、`marketIndexDataHash`、`indexRequirementHash` 和 `formulaDefinitionHash`。
- 所有现有股票专属输入的 `backtest-run-v1` 和 `backtest-run-v2` 预映像保持字节一致。

修改任一会影响判断的指数 K 线、路径、条件、阈值、截止、映射或公式都会改变对应数据集/运行/报告哈希。修改显示范围、任务元数据或分页不会。

## 覆盖投影

`BacktestReferenceMarketCoverage` 包含绑定、条件路径、准确所需/可用五分钟和正式日线数量、预热起止、有序阻断项、`marketIndexDataHash` 和 `formulaDefinitionHash`。覆盖由服务端计算。只有计划使用指数叶子时才阻止提交/回放；否则 `required=false`、路径为空，缺失指数 artifact 只提供信息。

覆盖校验使用所选股票已经冻结且经过认证的开市日历。它要求准确存在计划专属的末尾预热日期/周期，以及事件区间内每一个正式日线和五分钟指数观测。缺失观测使用稳定的 `GAPPED_INDEX_OFFICIAL_WARMUP`、`GAPPED_INDEX_FIVE_MINUTE_WARMUP`、`GAPPED_INDEX_OFFICIAL_EVENT` 或 `GAPPED_INDEX_FIVE_MINUTE_EVENT` 阻断项；原始行数不能掩盖缺失的前序事实或事件周期。

## 测试策略

- 证明每种条件及组合最大值的准确动态预热。
- 证明 v1 数据集/运行/结果黄金值不变，v2 指数修订只追加。
- 证明五分钟和正式收盘截止没有未来数据，包括同时间戳观察顺序。
- 证明相同 K 线、请求和截止下，监控与回放创建字节一致的快照/证据。
- 证明两份计划共用一份回放快照但产生独立/不同结果。
- 证明指数覆盖只阻断包含指数叶子的计划，离线回放供应商/网络调用严格为零。
- 证明任一 artifact 篡改、身份混用、缺口、重复、未来 K 线或公式不一致都会失败关闭。

## 边界与成功标准

- 始终：保持旧 artifact 不可变，根据股票代码派生指数，让预热参与身份，并复用实时公式/计算器。
- 先确认：启用真实供应商、修改数据集/运行哈希域、历史时间戳语义、映射或公式。
- 禁止：改写历史、使用未来/未完成数据、合成指数、混入行业数据或在回放中调用供应商。
- 相同实时/回放输入产生相同快照和条件证据字节；无条件计划保持原有行为。
