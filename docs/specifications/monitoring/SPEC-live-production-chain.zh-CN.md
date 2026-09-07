# 规格：live-production-chain

> 中文审阅版。英文权威版为 `SPEC-live-production-chain.md`；两份文档必须保持语义一致。

## 目标

让安装式本地 Web 应用如实接通生产监控 runtime：类型化正常投影未就绪、可跨重启的持久投影、经认证的股票与板块指数获取、每个 deadline 单批次判断，以及绝不根据传输失败推断领域 readiness 的浏览器状态机。

本规格实施 `CAPABILITY-MAP-live-production-chain.md` 中登记的 P0 模块，并保留此次修复以外全部既有实时、AI、板块指数和回测行为。

## 命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration tests/replay -q -m "not live"
.\.venv\Scripts\python.exe -m pytest tests/contract/test_tushare_live.py -q -m "not live"
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check
npm --prefix web run type-check
npm --prefix web run test -- --run
npm --prefix web run test:e2e
npm --prefix web run build
git diff --check
```

真实 selector 独立且串行。它只能在注入一次性密钥并处于适合对应操作的市场窗口时运行。

## 投影可用性契约

`GET /api/v1/dashboard`、`GET /api/v1/symbols` 和 `GET /api/v1/symbols/{symbol}` 对正常投影生命周期状态返回 HTTP `200`。既有成功 `SymbolPage` 和 `SymbolDetailResponse` 结构保持不变；`DashboardResponse` 新增可空 UUIDv4 `runtimeGeneration`，用于把传输存活状态绑定到生成该快照的 runtime 实例。每个端点另外允许同一严格 `ProjectionUnavailableResponse`：

```json
{
  "availability": "UNAVAILABLE",
  "reason": "AWAITING_FIRST_EVALUATION",
  "observedAt": "2026-09-05T10:00:00.000000+08:00",
  "sequence": 42,
  "symbol": "003043.SZ"
}
```

Dashboard/集合范围不得出现 `symbol`，股票详情范围必须包含 `symbol`。合法原因为 `EMPTY_DATABASE`、`NO_ACTIVE_PLANS`、`NO_ACTIVE_PLAN` 和 `AWAITING_FIRST_EVALUATION`；范围与原因必须一致。响应不包含伪造统计、行、判断、K 线、板块指数快照或健康事实。格式合法但未知的股票仍返回 `404 NOT_FOUND`。存储/迁移/损坏/组合故障继续返回固定 `503 SERVICE_UNAVAILABLE` envelope。

后端在一个一致读取边界内决定原因。历史仅 hash evaluation 不是完整结果，因此不能使投影可用。

## 迁移 0009 与持久读取模型

迁移 `0009_live_monitor_projection` 在不重写既有行的前提下增加：

- `evaluation_result`：精确既有 evaluation identity、不可变 `result_hash`、规范完整结果 JSON、判断/来源时间与 schema version；
- `symbol_decision_head`：每个股票一个 head，指向完整 evaluation result 及其已提交事件 sequence；
- `symbol_health_projection`：每个股票一份完整当前健康投影，带单调 revision；
- `pending_official_close`：每个股票/日期/计划/公式一份可恢复未解决官方收盘 identity；
- `market_index_snapshot`：不可变规范快照 JSON 与全部既有内容 hash/revision identity；
- `market_index_snapshot_head`：每个 mapping/index/cutoff request domain 一个当前 head。

外键和检查约束必须阻止 head 指向缺失或跨 identity payload。既有 `evaluation_ledger` 行、event/alert ID、全局 sequence、计划字节、result hash、回测存储和 Schema v1 数据均保持不变。任一新表存在用户数据时，downgrade 必须在破坏性 DDL 前拒绝；恢复使用已验证数据库备份，而不是合成逆向数据。

`PersistentMonitorReadService` 在一个 Unit of Work 内从持久 head 组装 Dashboard/股票响应，并读取同一 `monitor_sequence` 高水位。空数据库、无活动计划、请求股票无活动计划，以及活动计划尚无完整结果时返回类型化 unavailable。它绝不伪造零值 Dashboard，也不根据 ledger hash 重新计算判断。

## 原子判断契约

每个盘中或官方收盘 identity：

```text
在事务外获取供应商数据
→ 校验/规范化，并在短事务中持久化行情事实
→ 构建不可变上下文，并在事务外执行判断
→ 一个短事务：
   claim + evaluation_result + decision head + episode/risk intent
   + pending-close transition + alert/outbox + audit + committed event
→ commit
→ 发布精确已提交失效事件
```

重复 identity 不发布。回滚不改变 head、risk/episode 状态、outbox、event sequence 或 pending-close 状态，也不发布。发布失败不撤销已提交状态；回放继续以数据库为来源。

## 生产供应商与 Runtime 契约

- `TushareClient` 与股票 provider 只使用经认证的股票 profile。`rt_min(freq="1MIN")` 每个 deadline 只接收一次逗号分隔请求，其中包含全部活动股票且最多十只。判断使用该批次返回/持久化的数据，不能执行第二次报价请求。
- deadline coordinator 一次性捕获不可变的计划、股票和激活 revision 集合。`SymbolService` 必须使用该精确股票 tuple，不得独立重新读取 active set；之后发生的激活顺延到下一个 deadline，停用/轮换则由最终 revision fence 拒绝。
- `RequestController` 强制全局物理启动节奏、有界准入、完整 15 秒准入超时及其后独立的完整 15 秒供应商超时、分类冷却/退避和 deadline 优先级。关闭 controller 会唤醒每个排队等待者，使其在 callable 启动前返回 `CLOSED`。数据库工作绝不进入 provider worker，provider/网络工作绝不进入数据库事务。
- 存在持久 `pending_official_close` 的股票不能停用，也不能轮换到另一计划。计划写锁和 pending 检查位于同一事务，因此启动恢复始终为该 pending identity 保留一份活动不可变 owner。
- 启动时独立校验能力、刷新日历/涨跌停/参考历史、重试持久 pending close、串行恢复当日分钟，再启动 deadline supervisor。失败阶段保持可见且可恢复；不得遗留无所有者任务。
- `RuntimeEvaluationService` 对到期股票和指数需求分组，构造不可变输入，对每个完整 5 分钟 identity 判断一次，并通过上述原子边界提交。
- deadline coordinator 让下一个行情 deadline 优先于 recovery/background。runtime 一旦进入 `STOPPING` 就立即停止 controller 准入，给予自有工作有界完成/取消窗口，之后才汇合线程池。可恢复 supervisor 报告故障并采用有界重启策略，不能在健康仍显示 `LIVE` 时静默退出。
- 只有 runtime 健康状态为 `RUNNING` 时观测到的启动后运行循环意外返回或异常才允许重启。每次尝试都创建全新的 runtime；每个 Web composition 生命周期最多重启三次，精确延迟为 `1`、`2`、`4` 秒。进程重启会重置预算。
- 重启退避期间及预算耗尽后，健康状态为 `DEGRADED`、`read_only=true`、`nextPollAt=null`。stop/取消、启动/配置/迁移失败或清理失败属于终止性错误，绝不重试。每个延迟/runtime 任务均由 composition 持有、可取消并汇合；只有失败 runtime 清理成功后才改变服务绑定。
- 板块指数 provider 与股票 provider 相互独立，拥有自己的已认证 endpoint/profile 和 `SourceTimeLabel`。一个指数失败只为明确依赖该指数的计划路径生成阻断证据；其他指数与无指数条件的计划继续运行。

生产股票路径在新鲜股票能力记录为 `READY` 并选定已验证 `SourceTimeLabel` 前保持依赖阻断。历史 T058 可见阻断结果不是该记录。此闸门通过前，生产 composition 使用真实请求控制限制，但必须保持 `DEGRADED`、不读取 Token、不调用 provider，也不得构造可执行 deadline coordinator。

## 真实 Harness 与证据契约

普通测试执行零外部请求。真实 harness 在选定进程中直接运行，并从被忽略的本地 `config/app.yaml`
读取 `tushare.token`；`ai.api_key` 采用相同的直接配置约定。迁移期间仍可读取原有 `token_ref` 与
`api_key_ref`，且直接值优先。

真实调用串行、单并发、起点至少相隔 `1.25` 秒、每次 `15` 秒超时且不自动重试。遇到第一个 `429` 后停止所有后续调用。股票和指数观测使用独立报告、授权 context、能力集合和时间戳标签。只有在 `trade_cal` 证明观测日期开市且当前窗口可暴露完整分钟后，才能认证实时分钟标签语义。窗口不合适时结果为 `NOT_RUN_MARKET_WINDOW`，不能猜测映射。禁止调用 DeepSeek 和全部其他 provider。

## Vue 组件与状态地图

| 组件/组合函数 | 职责 | 契约 |
|---|---|---|
| `useMonitorStream` | 持有快照获取、重试、Socket 和存活周期 | 不使用 Health fallback；只有有效快照才能开 Socket |
| `AppShell` | 渲染非纯颜色连接状态 | 只读语义状态 |
| `DashboardRouteView` | 组合快照或类型化 unavailable 展示 | 不推断空状态 |
| `SymbolRouteView` | 组合详情或类型化 unavailable 展示 | 不重建判断 |
| `PriceChart` | 惰性 ECharts 渲染和可访问表格 | chart chunk 只在图表路由异步加载 |

浏览器状态机区分 `SNAPSHOT`、`UNAVAILABLE`、`STALE` 和 `DISCONNECTED`。`SNAPSHOT` 表示已存在经过校验的权威响应；存活状态可以细化可见连接标签，但不能伪造数据。`UNAVAILABLE` 只能来自类型化 HTTP `200` 变体，且绝不打开 WebSocket。`STALE` 必须已有此前通过校验的缓存快照。`DISCONNECTED` 只用于没有可用缓存时的传输/超时/非法响应失败。公开 REST 与 WebSocket sequence 以 JavaScript 安全整数上限为界。只有 heartbeat 的精确 sequence 和 `runtimeGeneration` 都与已应用的权威快照一致时，才能建立存活状态；因此 supervisor 替换或进程重启即使时钟回退，也必须强制执行 REST 恢复。

Playwright 使用已安装 Google Chrome channel（`channel: "chrome"`）、单 worker、零 retry；除另行组合的本地生产旅程外，使用确定性同源 fake。安装式旅程分配测试自有回环端口，只有自有 launcher 识别出其 Uvicorn 进程后才接受 readiness，在确认退出前保留两个进程 identity，并为每个优雅/强制清理工具设置上界。每个验收用例要求控制台 error 为零、warning 为零且 `requestfailed` 为零。Firefox 不是门禁。非图表路由不得请求 chart chunk。

## 测试策略

- 先写 RED 单元/集成测试，覆盖类型化可用性、空库/无计划/首次判断、503 故障区分、迁移保留、回滚、重启重建、单批次 deadline、无第二次获取、指数故障隔离和 supervisor 恢复。
- 迁移测试从每个受支持的旧 revision 开始，保留精确受保护行/hash，并拒绝不安全 downgrade。
- OpenAPI 快照和生成 TypeScript 必须同步改变并保持逐字节 current。
- Vue/Vitest 覆盖每种状态转换，并证明已删除 Health fallback。Chrome 覆盖 console/request 清洁、unavailable 不开 WebSocket、路由行为和 chunk 隔离。
- 配置测试覆盖直接 Tushare/AI 凭证以及旧引用格式兼容性。

## 边界

- 始终：可用性、完整结果、健康以及计划/指数依赖以后端为权威来源。
- 始终：供应商 I/O 位于数据库事务外，且只在 commit 后发布。
- 始终：保留历史 identity、hash、Schema v1、回测、DeepSeek 和既有 Web 工作。
- 先确认：增加其他 provider、修改公式/映射版本、下单、暴露非回环监听或重新解释历史 ledger 行。
- 禁止：伪造空快照、让 Vue 根据 Health 推断 readiness、共用股票/指数时间戳证据、自动重试真实认证，或从 Tushare 认证 runner 调用 DeepSeek。

## 验收标准

- 空库/无计划/首次判断状态返回类型化 `200`；真正存储/组合故障返回 `503`。
- 一次完整已提交判断可跨重启，并生成相同权威 Dashboard/股票投影与高水位 sequence。
- 每个 deadline 最多启动一次十股票实时批次，任何判断均不执行第二次获取。
- 一个板块指数故障只影响显式依赖它的计划路径。
- 类型化 unavailable 状态下 Vue 不打开 Socket，且 Chrome 验收保持干净。
- 非图表路由请求中不存在 ECharts 代码。
- 全部必需离线闸门通过；只有密钥与市场窗口前置条件满足时才记录真实证据。

## 审核状态

用户通过明确请求批准实施。2026-09-07，用户针对这款个人工具取消 OS 凭据存储与仅子进程注入
边界，允许把凭证直接保存到被忽略的本地应用配置中；市场窗口闸门继续保留。实时分钟语义仍未
认证，直至 `config/app.yaml` 包含 Tushare Token，且之后获授权的开市窗口运行提供新鲜证据。
