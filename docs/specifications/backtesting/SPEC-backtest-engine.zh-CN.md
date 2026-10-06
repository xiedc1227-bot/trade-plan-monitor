# 规格：backtest-engine

> 中文审阅版。英文权威版为 `SPEC-backtest-engine.md`；两份文档必须保持语义一致。

## 目标

使用事件时间和 `execution-model-v1`，在冻结数据集上回放一个股票的一个不可变、经审核计划版本；生成确定性完成报告，且不访问网络、墙上时钟、实时状态、通知、WebSocket 或券商。

## 关系与范围

`backtest-engine` 消费 `backtest-data`，并复用已批准的 `plan-domain`、`market-data`、`strategy-state` 和纯 `decision-engine` 契约。它负责运行输入 identity、事件时间回放、模拟成交、指标和规范报告。它不负责供应商调用、可变任务、HTTP、Vue、结果保留或实时监控。

一次运行表示一个不可变且已校验的计划快照及其一只股票。Web 提交必须把该快照绑定到一个 RFC 4122 `planVersionId`。所选计划不要求已在实时链路激活，因为回测支持激活前审阅；但必须通过与 `canActivate=true` 相同的确定性校验。多股票共享资金、组合成交、参数寻优和批量比较不在首版范围。

## 操作入口

Web/API 通过 `backtest-jobs` 提交 `BACKTEST_RUN`，显式提供成交费用、滑点和研究假设。后台工作者执行冻结输入；回放不在 HTTP 请求处理器内运行。不保留回测 CLI 或计划文件兼容适配器。

## 公共契约

新增不可变 `BacktestRunInput` 和 `BacktestInitialLotInput` 值。`BacktestRunInput` 包含 `runFormulaVersion`、规范计划快照与重新计算的 `plan_sha256`、可选的 `plan_version_id: UUID | None` 查找 identity、`dataset_hash`、初始现金、规范化初始持仓、`ExecutionConfig`、明确事件风险假设、上下文边界和 Schema/公式版本。Web 提交要求 UUID；仅领域输入和既有历史结果继续允许 `None`。`planVersionId` 只作为审计/查找元数据，不进入运行哈希 preimage；快照只通过精确 `plan_sha256` 和 `plan.version` 参与 identity。

`BacktestInitialLotInput` 与实时 `PositionLot` 分离，包含 `lotKey`、`bucket`、`acquiredTradeDate`、`quantity` 和 `costBasisFen`。`lotKey` 是调用方稳定的 1–64 字符标识，必须匹配 `[A-Za-z0-9][A-Za-z0-9._-]*`，并且在命令内唯一。不同 `lotKey` 的多个持仓可以共享 `(bucket, acquiredTradeDate)`。输入按 `(bucket, acquiredTradeDate, lotKey)` 规范化；数量必须是正数 100 股整手，`costBasisFen` 表示整批持仓的正数剩余总成本，并不是每股价格。v2 运行哈希生成后，才使用 `lotKey` 作为稳定 source key 派生运行限定的 `PositionLot` ID。这样既保留同日多批次 identity/tie-break，也消除使用一个已经需要 `run_id` 的 `PositionLot` 来计算同一个 `run_id` 所形成的循环。

每个初始持仓都使用所选计划的股票，满足 `acquiredTradeDate <= dataset.start`，并以 original quantity 等于 remaining quantity 的完全开放状态开始。每个 bucket 和全部初始数量汇总都必须在哈希或回放前满足经审核计划的 bucket/最大仓位上限。

保留 `backtest_run_id(...)`、`OfflineBacktestRunner.run(...)`、`BacktestRunReport`、`BacktestBlockedError`、`ExecutionConfig` 及信号/订单/成交/outcome/权益契约。增加类型化内部取消结果，只携带阶段和最后安全事件 identity；取消绝不产生部分 `BacktestRunReport`。

进度与取消属于运维侧通道，不进入 `run_id`、`report_hash`、决策输入、有序输出或报告字节。

## 运行 Identity 与确定性

运行 identity 必须显式版本化。现有空初始持仓工作继续使用 preimage 完全不变的 `backtest-run-v1`：`plan_sha256`、`plan.version`、`dataset_hash` 与范围、正数初始现金、空 `initial_lots` 列表、指标公式、精确 512/499/512 上下文、成交配置/哈希，以及显式事件风险布尔值。现有 v1 结果继续逐字节可读、可复用。

公共非空初始持仓支持使用 `backtest-run-v2`。其规范 preimage 包含相同 v1 语义值，但以包含 `lotKey` 的规范化 `BacktestInitialLotInput` 列表替代绑定运行的 `PositionLot`，并把 `backtest-run-v2` 作为公式/Domain 版本。`planVersionId`、数据库行 ID、重新计算计划哈希/版本之外的完整快照字节、`job_id`、`attempt`、进度、时间戳和取消都不进入 identity。公式选择是确定性的：空输入列表使用 v1，非空列表使用 v2。修改任一 preimage 都必须新增公式版本和迁移决策。

固定上下文继续为 512 根完整五分钟 K 线、499 根此前官方日线和 512 个日历日事实。精确 Decimal 规范化、费率转有理数、整数分金额、各方向取整、precision-28 half-even 指标和全部既有限制 Token 保持不变。

`run_id` 标识确定性研究结果，`job_id` 标识一次持久化提交/操作。一个任务可以有多个由 `attempt` 记录的 worker claim generation；终态后重试会创建新的 `job_id`。失败或取消的任务不能占用已完成结果 identity，因此新任务可以用同一 `run_id` 重新回放直至完成。

## 事件时间与禁止未来数据契约

回放只沿冻结事实时间戳推进。每次判断只能看到该事件时间或之前可用的事实。五分钟桶只包含已完成分钟，临时日线只包含已观察分钟，官方日线只在官方收盘时可见，预热事实绝不贡献收益或成交。

每个可操作信号都满足 `signalAt == EvaluationResult.snapshot.evaluatedAt`，事件归属于来源事实的 `receivedAt`。候选成交分钟在离散回放顺序中必须晚于产生事件，并满足 `openAt >= signalAt`；成交记录 `filledAt == openAt`。引擎绝不替换成 `barEnd`、桶结束、固定 15:00 或墙上时钟。

修改判断之后的事实不能改变更早的判断、`result_hash`、信号、outcome 或成交。缺少必要规范候选时必须失败关闭，不能跳过。

## 模拟成交契约

`execution-model-v1` 保留实际每日涨跌停、按交易日 T+1、100 股整手、现金/仓位上限、目标上限、禁止杠杆、禁止做空、显式费用、方向性滑点和精确未成交原因。零成交量分钟继续作为不可交易代理；候选持续到之后第一根正成交量分钟或有限回放结束。

`RISK_BREACH` 是风险事件，绝不暗示成交。报告必须原样保留限制 Token，包括 `ZERO_VOLUME_MINUTE_USED_AS_NON_TRADABLE_PROXY`、`FILL_QUANTITY_NOT_CAPPED_BY_MINUTE_VOLUME`、`CONSERVATIVE_LIMIT_LOCK_FROM_OPEN_OR_SLIPPAGE`、`DAILY_EQUITY_DRAWDOWN_SAMPLING`、`WIN_RATE_PER_SELL_FILL_NOT_ROUND_TRIP`、`METRIC_DECIMAL_PRECISION_28_HALF_EVEN` 和 `BOUNDED_ROLLING_CONTEXT_512_5M_499_DAILY_512_CALENDAR`。

## 取消与恢复

引擎在每个来源分钟步骤、判断、交易日切换、最终化和交付发布前检查取消。它在一个逻辑分钟迭代内观察取消，在确定性安全边界停止，并且不返回完成报告。

重启恢复从冻结起点确定性重放，并依赖幂等 staged 结果写入。策略事件游标恢复明确延后，不能标记为完成。取消、重试、attempt、lease 和进度由 `backtest-jobs` 负责。

## 安全与可观测性

引擎只接受已校验内存契约和冻结数据集读取器。它不得构造供应商、打开实时数据库、读取来自 HTTP 的任意路径、调用调度器/恢复服务、发出实时事件、入队通知或连接券商。

结构化运行事件使用稳定名称和有界字段，例如 `jobId`、`runId`、阶段、股票、数据集哈希前缀、判断/成交数量、耗时和脱敏阻断代码。不得记录计划原文、完整计划 JSON、初始持仓 payload、数据库路径、密钥或原始异常文本。遥测不能影响确定性输出。

## 性能预算

- 每次判断上下文受声明的 512/499/512 上下文约束，每次行情读取限制为一个股票交易日输入批次。
- Runner 绝不把五年多股票数据集一次性实体化到内存。
- 当前兼容 Runner 会在内存中保留完整有序 `BacktestRunReport`，因此本规格不能从滚动上下文边界推导端到端堆上限。流式/staged 输出或经实测接受的整次运行内存上限继续作为开放 `BC01` 工作。
- 进度回调由 `backtest-jobs` 合并；引擎不按每分钟写数据库进度。
- 优化前要在同一固定夹具上记录墙钟耗时、峰值内存、判断数、成交数和数据库增长；测量噪声内的变化不得作为优化保留。

## 项目结构

回放、成交模型、规范运行/报告 identity 和与应用无关的值对象保留在 `src/trade_plan_monitor/backtest/`。生产决策契约继续保留在现有 domain/decision/market-data 包。HTTP 适配器可以组合引擎，但绝不拥有或复制成交规则。

## 代码风格

使用冻结严格值、公式纯函数、显式版本常量、精确 Decimal/整数运算、具有规范 `YYYY-MM-DDTHH:MM:SS.ffffff+08:00` 表示的带时区 `Asia/Shanghai` 事件值、穷尽式枚举处理、确定性排序和判断器/数据集读取器依赖注入。拒绝 `Z`、无偏移值、超精度和其他偏移。环境 Decimal context、进程时钟或主机时区不能影响输出。

## 测试策略

保留一股票一日精确 49 次判断和一个每日权益点的回归，并为现有空持仓夹具保留逐字节相同的 `backtest-run-v1` ID。把确定性夹具扩展为至少两只股票各自跨多个交易日的单股票运行，并至少包含一次有效买入和一次减仓/退出成交。覆盖 v2 同日多持仓 key/tie-break、正数总成本、实际涨跌停、T+1、整手、现金/仓位上限、费用/滑点、缺失分钟、零成交量、最后一分钟不成交、禁止未来数据修改、取消、重启重放、稳定字节及零供应商/实时/通知调用。

## 边界

- 始终：使用一个已校验不可变计划版本、一只股票、冻结数据集、明确初始状态，以及明确成交/事件风险假设。
- 始终：保留事件时间来源、确定性 identity、精确运算和所有已声明研究限制。
- 先询问：更改公式/Schema 版本、滚动边界、取整、指标语义、事件风险形状、公司行动、参与率/冲击或组合/共享资金成交。
- 禁止：使用未来事实或墙上时钟、在产生信号的 K 线/桶内成交、访问实时状态/网络/通知、把风险事件当成券商成交，或发布取消后的部分报告。

## 验收标准

- 相同输入复现相同 `run_id`、有序判断、成交、权益、`report_hash`、JSON 字节和 CSV 字节。
- 后续事实修改不会改变更早的 identity 或输出。
- 每个语义事件时间都是 `Asia/Shanghai`/`+08:00`；只改变操作性任务/审计时间绝不能改变 `run_id`。
- 初始持仓按规范影响 identity、权益、成本基础、可卖数量和 T+1。
- 取消不产生完成结果，同一输入可以在之后的 `job_id` 下完成。
- 两只股票跨多个交易日覆盖可操作买入和减仓/退出路径。
- 回放期间网络、实时数据库读写和通知调用次数全部精确为零。
- 判断上下文和行情读取保持在已声明滚动及股票交易日边界内；整次运行堆/资源验收在完成测量或重新设计前，继续明确开放于 `BC01`。

## 开放问题

结构化事件风险记录、公司行动、成交量参与率、市场冲击、组合/共享资金成交、参数寻优/批量比较和策略事件游标继续延后。当前显式事件风险布尔值和从起点确定性重放恢复仍是首版契约。
