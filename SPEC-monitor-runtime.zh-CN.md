# 规格：monitor-runtime（监控运行时）

> 中文审阅版。英文权威版为 `SPEC-monitor-runtime.md`；两份文档必须保持语义一致。

## 目标

运行一个本地常驻监控进程，为最多 10 只活跃股票调度 Tushare 数据采集、修复缺口、对每个新完成的 5 分钟周期严格评估一次、校准官方收盘数据、以事务方式持久化状态与提醒、如实暴露健康状态，并能干净关闭。

浏览器关闭后，运行时仍须正常工作。AI 提取运行在独立且有界的执行路径中，绝不能延误行情采集期限或规则评估。

## 技术栈

- Python 3.11+
- 使用 `asyncio` 管理应用生命周期
- 为同步 Tushare SDK 调用配置独立的 `ThreadPoolExecutor(max_workers=2)`
- 为 AI HTTP 调用配置独立的有界异步信号量
- 集成 FastAPI lifespan
- 通过 `strategy-state` 使用 SQLite 持久化调度和状态
- 使用带脱敏的标准库结构化日志

无需 Celery、Redis、APScheduler、分布式队列、工作进程集群或高可用协调器。

## 命令

```powershell
python -m pytest tests/unit/test_monitor_runtime.py -q
python -m pytest tests/integration/test_ten_symbol_runtime.py -q
python -m ruff check src/trade_plan_monitor/runtime tests/unit/test_monitor_runtime.py tests/integration/test_ten_symbol_runtime.py
python -m trade_plan_monitor monitor --once --config config/app.yaml
```

## 项目结构

```text
src/trade_plan_monitor/runtime/
├── clock.py           # 可注入的真实或模拟时钟
├── scheduler.py       # 感知交易时段的分钟和收盘调度
├── request_control.py # 限速、有界并发、重试与冷却
├── recovery.py        # 启动时及当日缺口修复
├── symbol_service.py  # 单只股票的评估编排
├── health.py          # 数据供应商、系统及股票健康状态
├── service.py         # 运行时生命周期与协调
└── cli.py             # validate、once、run、replay、backup 命令
tests/unit/
└── test_monitor_runtime.py
tests/integration/
└── test_ten_symbol_runtime.py
```

## 启动顺序

1. 加载并验证应用配置和密钥引用。
2. 打开 SQLite，执行已批准迁移并检查基本完整性。
3. 加载已启用的计划版本；活跃股票超过 10 只时拒绝启动监控。
4. 分别探测 Tushare 实时分钟、当日分钟、交易日历、每日涨跌停价和日线能力。
5. 刷新并缓存当前及下一段交易日历，以及当日实际涨跌停价。
6. 若当前为开市交易日，通过 `rt_min_daily` 按股票串行、幂等地修复当日分钟数据。
7. 根据规范化交易时段时钟计算下一个市场分钟截止点。
8. 即使供应商能力受阻也启动 Web 应用，但必须显示降级或只读健康状态，并禁止可执行监控信号。

## 实时调度

- 每个连续交易分钟完成后，加上可配置的 12 秒宽限期，调用一次 `rt_min(freq="1MIN")`；单个批次包含全部已启用股票，最多 10 只。
- Tushare 源时间戳由 `market-data` 规范化；调度器使用交易所标准时间区间，而不是原始标签。
- 不另行轮询实时报价；最新已完成分钟线的收盘价即为展示价格。
- 按股票验证返回数据；单只股票缺失或格式错误只阻断该股票。
- 每个完整 5 分钟周期只评估一次；周期不完整时立即禁止可执行评估。
- 连续两个所需周期不完整时，将股票标为 `DEGRADED`；首次周期不完整就必须阻断买入提醒。
- 动态启用或停用计划后，下一个批次立即生效，无需重启进程。

## 缺口修复与收盘校准

- 启动修复对每只活跃股票调用一次 `rt_min_daily`，同时最多执行一个修复调用。
- 后续修复仅处理检测到的缺口，并为下一次计划内实时批次让路。
- 通过幂等写入处理重复或乱序的修复数据。
- 最后一分钟仅生成临时收盘快照。
- 官方 `daily` 校准时间可配置，默认约为 15:20、16:00 和 17:00。
- 只有返回的官方数据行与当前交易日匹配时，才推进收盘风险状态。
- 若官方数据不可用，持久化 `CLOSE_PENDING`；下次启动时先重试，再评估下一交易日的收盘状态转换。

## 请求控制

默认配置：

```yaml
requestControl:
  tushareExecutorWorkers: 2
  tushareMaxConcurrency: 2
  minIntervalMs: 1000
  jitterMs: 250
  timeoutSeconds: 15
  inCycleRetries: 2
  symbolBackoffSeconds: [30, 60, 120, 300]
  sharedRateLimitCooldownSeconds: 300
aiControl:
  maxConcurrentExtractions: 1
  queueLimit: 5
```

- 权限或访问被拒绝时转为 `BLOCKED_PERMISSION`，不得盲目重试。
- 遇到供应商配额或限流响应时启动全局冷却，禁止立即形成重试风暴。
- 普通临时故障使用有界重试，并在后续周期退避。
- Tushare 网络调用在线程池中运行；数据库操作仍在应用执行路径内完成，不进入供应商线程。
- AI 使用独立的队列和信号量，运行优先级低于监控任务。

## 健康状态契约

供应商能力状态：`UNVERIFIED`、`READY`、`BLOCKED_PERMISSION`、`RATE_LIMITED`、`ERROR`。

单只股票健康状态：`STARTING`、`LIVE`、`STALE`、`GAPPED`、`DEGRADED`、`BLOCKED`、`CLOSE_PENDING`。

健康信息必须暴露时间戳与数据年龄、最后完成分钟、最近评估、缺口、下次轮询、下次重试、冷却、延迟、错误码、线程池利用率、数据库和 WAL 状态，以及提醒投递状态。不得暴露密钥或供应商原始响应体。

## 运行时事务流程

```text
在事务外获取数据
→ 验证并规范化
→ 短事务：写入或更新 K 线及参考数据
→ 构建不可变上下文
→ 在事务外执行纯函数评估
→ 短事务：认领评估 + 应用状态意图 + 提醒入队 + 写入审计
→ 发布已提交事件
```

## 代码风格

```python
async def run_minute_cycle(self, deadline: datetime) -> None:
    symbols = await self.active_symbols(limit=10)
    bars = await self.provider_executor.realtime_minutes(symbols)
    await self.persist_and_evaluate(bars)
```

`MarketDataProvider` 返回已经过校验和规范化的值；运行时不得再次转换供应商原始行。时钟、供应商、仓储和发布器均通过依赖注入。避免使用全局客户端，也不得创建没有明确取消归属的后台任务。

## 测试策略

- 使用模拟时钟覆盖交易时段、午休、周末、节假日、宽限期和最后一分钟。
- 覆盖 10 只股票完整或部分返回，以及单只股票故障隔离的批次测试。
- 证明缺口修复和 AI 任务不能延误实时轮询的截止时间测试。
- 权限、限流、超时、重试、冷却和有界工作线程测试。
- 启动修复及动态计划变更测试。
- 覆盖重复数据、重启和延迟修复的严格一次评估测试。
- 临时与官方收盘校准测试。
- 优雅关闭测试：停止调度、完成或中止有界任务、提交已完成事务并执行 WAL 检查点。
- 使用 10 只合成股票模拟完整交易日的稳定性测试，验证内存和数据库增长有界。

## 边界

- 始终：当所需能力或数据未就绪时，对可执行决策采取封闭失败。
- 始终：尽可能按股票隔离健康状态和故障。
- 始终：计划内实时任务优先于缺口修复和 AI 任务。
- 需先确认：活跃股票超过 10 只、增加进程或队列，或改变默认行情采集频率。
- 禁止：提交券商订单，或把提醒当作成交。
- 禁止：让 AI 请求进入行情线程池或监控事务。
- 禁止：正常启动命令监听 `0.0.0.0`。

## 验收标准

- 浏览器未连接时，一个进程仍能监控 10 只已启用股票。
- 同一批次中一只股票失败或缺失，不会取消其他健康股票。
- 每个完成的 5 分钟周期针对同一计划和公式版本最多评估一次。
- 数据超过配置的陈旧阈值时，立即阻断可执行信号。
- AI 供应商故障或提取缓慢不会对轮询截止时间产生可测影响。
- 重启修复不会重复生成 K 线、状态转换或提醒。
- 关闭后数据库保持一致，且不存在失去归属的后台任务。

## 待确认问题

- Tushare 账户的具体容量仍以实时契约测试为准。若单次 10 只股票批量请求被拒绝，运行时可在相同全局限速下按确定顺序分块，同时继续支持 10 只股票。
