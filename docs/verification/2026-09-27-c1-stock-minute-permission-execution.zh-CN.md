# C1 股票分钟权限执行验证

> 本文是中文复核副本，规范性英文版本为 `2026-09-27-c1-stock-minute-permission-execution.md`。

## SME-01 范围与状态

- 日期：2026-09-27。
- 状态：**实现完成；修后 writer 验证与独立最终复审通过；P2 关闭且无剩余 P1/P2；已获本地提交授权**。
- 设计依据：[SMWO owner 契约](2026-09-27-c1-stock-minute-permission-owner-contract.zh-CN.md)。协调者在准备片 `47a803ba68d72e3b80f495f4f08aac5f16ba4ff8` 获独立验收、独立 SDK 边界 `4804207fdc78270604b952cc25a372e59d4e32bb` 完成评审后，释放了执行实现权限。
- 本片仅拥有 `src/trade_plan_monitor/runtime/production.py`、`tests/integration/test_production_stock_minute_permission_execution.py` 和本双语报告。本 writer 不修改 provider、controller、dispatcher、recovery service、业务 reader 或数据库 schema。
- 自动 dispatch、业务启动恢复、READY 和完整 C1 验收仍 OPEN。设计批准和 provider 测试不等于 owner 实现验收。

## SME-02 已实现的 owner 行为

两个内部分钟入口在首次 await 前捕获外层 Task 并创建本次调用 Event。共享 owner 获取维护锁并且只准备一次。闭包保留原始 consumer/candidate、权限模式/revision、label、provider、wrapper 及底层 SDK client、session factory、calendar epoch/Event。

在预留前、排队准入、worker 入口和最终 SDK 边界，请求检查冻结请求日期、最晚开始时刻（`captured_at + 15s`）、合法请求窗口、31.25 秒市场 guard、configuration/certification/semantics、generation/stop 和身份栅栏。最后一次权限 I/O 在唯一 S 采样前完成；S 后只进行原始模式时间规则及内存检查，然后调用已解析的 SDK callable。Legacy 认证保留真实加载器包含等号的 `valid_until` 边界，晚一微秒拒绝。STOCK semantic 模式不继承旧认证到期限制。

每次调用独占 evidence slot 和实际 S 记录。owner 要求精确 `MinutePermissionEvidence`、匹配的 endpoint/symbol/date/label 及实际 S、`0 <= R-S <= 15s`、正数 A、有界严格类型计数及排序去重 source dates。C 最多两个且日期集合必须包含请求日；START 没有 B，END 每 source date 最多一个 B，A+C 每 source date 最多 240 个普通分钟身份。响应验证时不重新分类。

捕获的 factory 打开一个新的、自有的、应用 engine 显式 BEGIN 响应快照。它重新验证原始三表 consumer，不能替换为另一个合法 symbol；并查询 `source_dates ∪ {request_date}` 中每个精确 SSE 工作日开市事实。并集最多 1,001 个日期；每组 250 个精确 `IN` 查询共享同一快照。不使用历史日期范围 helper、额外业务 UnitOfWork、历史 audit 扫描或 calendar SDK 请求。所有权预检位于 context manager 外，配置错误不破坏调用方事务。

读取响应快照前和返回 true 前均检查外层 Task 的取消状态。调用取消标记永久保留，包括 `finally`；worker 不访问 Task 或应用数据库。已开始的物理工作由 controller drain，不为此保留维护锁。废弃结果 slot 不能填充下一次调用的 slot。

既有 controller 在调用一次性 cursor callback 前持久化 300 秒预留。物理开始 floor 延长和成功清锁不重复 callback。成功只清除自身权限块与 local defer。已知 permission/429/transient/timeout/invalid 返回 `FAILED`；原始 `RequestNotStartedError` 返回 `DEFERRED`，采用市场 blocker 加一微秒或固定 30 秒复查。`ERROR/CLOSED/QUEUE_FULL`、checkpoint、callback 和 SQL 错误向上传播。只写 controller recovery checkpoints。

## SME-03 RED-to-GREEN 证据

从 `trade-plan-monitor/` 运行：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_stock_minute_permission_execution.py -q --tb=short
```

- 初始 owner 入口 RED：**2 failed**；扩展后的实现前矩阵为 **30 failed**，均缺少分钟执行入口。首轮实现后 **30 passed**。
- 最后权限 I/O 反例：替换 wrapper 底层 SDK client 被错误接受。48 例运行包含这 **1 个实现 RED** 及 7 个 fixture/setup 失败。捕获并检查底层 client 身份修复了真实缺口；夹具修正后 48 例通过。
- 下述分类计数 RED 命令：**6 failed, 97 deselected**。伪造 C>2、START B、过多 END B、过多普通分钟身份、缺请求日却含 C 的结果，曾在违反 provider 契约时被接受。owner 现在全部拒绝，未改变既有 provider 语义。
- 评审前目标运行：**103 passed**，有一个既有 Starlette/httpx 弃用警告。
- 独立评审发现一项 P2：owner 将真实加载器包含等号的 legacy 到期边界改为了不包含等号，原测试也错误地期待拒绝。修订后的真实 loader 正反控在到期等号/晚一微秒处得到 **1 failed, 1 passed, 102 deselected**。仅将 owner 的 `<` 改为 `<=` 恢复兼容后，完整执行目标 **104 passed**，保留同一既有警告。这是当前目标证据；独立修前结果不是修后批准。
- 无效认证 hash 构造、日历夹具重复插入、slots 对象 monkeypatch、错误 controller 构造参数、错误 checkpoint scope 名、测试追加位置错误，以及事务观察器误统计夹具 writer，均为测试构造问题，不计入产品修复或独立 RED 证据；修正时没有 skip 测试或删除断言。

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_stock_minute_permission_execution.py -q --tb=short -k category_count_bounds
.venv/Scripts/python.exe -m pytest tests/integration/test_production_stock_minute_permission_execution.py -q --tb=short -k original_legacy_expiry
```

全部运行使用应用配置的临时 SQLite、完整真实 activation 夹具、受控时钟、假 SDK callable 和真实 provider/parser/controller。快速超时隔离用 0.05 秒测试 controller；owner evidence 区间仍为 15 秒。不访问真实服务或用户数据库，不发送外部通知，不 push 或部署。

## SME-04 契约覆盖

| 契约边界 | 已落盘 owner 证据 |
| --- | --- |
| SMW-01–03 | Legacy、explicit、mixed owner 成功；原始身份替换、同 hash revision、ABA、替换 symbol 拒绝。已验收的 74 例准备文件提供完整 consumer、三表、请求窗口和跨日准备覆盖，并与本片一起重跑。 |
| SMW-04 | 精确调用一次 `rt_min_daily` 或 `rt_min`，带 symbol、`1MIN` 和 fields；仅清自身 block/defer；SQL 观察器拒绝业务写入。 |
| SMW-05–06 | 重跑既有八 scope 准备测试；真实持久化 callback 恰一次、独立 symbol cursor/global position、DAILY_BARS O/F 保留、保存失败、预留后 veto/无效响应、物理 floor 延长、coalesced waiter。 |
| SMW-07 | 四个 owner 准入关口、排队等待后撤权、固定 +15 秒等号/晚一微秒、31.25 秒等号 blocker。 |
| SMW-08 | 最后 I/O 中更换 provider/底层 client/factory/generation/stop/epoch/Event/time；semantic binding 缺失、mode/revision 变化；legacy 到期包含等号及晚一微秒负控；响应阶段 Event 身份替换不能恢复旧权限。准备 token 重建由准备片独立覆盖。 |
| SMW-09 | 真实 A 与 B/C 混合、typed empty、只有 incomplete、malformed frame；原始 not-started sentinel 穿过 provider/controller；已知失败分类及意外错误。 |
| SMW-10 | 未知 B-only 日期、700 天前稀疏日期、关闭/未知/周末事实、1,000 个稀疏 source dates 加请求日、五个精确 chunk 且无第二 UnitOfWork。 |
| SMW-11 | 准备和响应使用不同 session、真实 SQLite 事务状态、并发夹具 writer 时身份/日历一致快照、borrowed/split-bound 响应 session 保留、SQL 错误传播；worker 不访问 SQL/Task。 |
| SMW-12 | 精确 invocation S、S 到实际 SDK 入口之间没有权限 I/O 或重采样、伪造时间戳拒绝、冻结 proof 验证、合法请求响应跨午休/收盘及新逼近市场 deadline、rollback 和迟到 R 拒绝。 |
| SMW-13 | 排队及 SDK 内取消、外层 catch 前已请求取消、响应快照中取消、超时后迟到正证明、第二调用独立 slot、slot drain 前无第二物理开始、维护锁释放。 |
| SMW-14 | 真实共享 429、重新打开临时 SQLite 验证 durable 300 秒、虚拟 1.25 秒共享 pacing、save/callback/SQL 错误传播。 |
| SMW-15 | 多次 getter 不移动固定 local defer；成功保留其它 local defer；SQL 观察器仅允许读取和 recovery checkpoints。未接入自动调度入口。 |

## SME-05 相邻验证

最终六个分类计数反例之前，首轮综合运行 **672 passed**，其中执行片为 97 例，包含全部 74 例准备测试。该精确命令评审前重跑 **678 passed**，包含当时全部 **103** 例执行测试及 **74** 例准备测试，有一个既有 Starlette/httpx 警告。该次运行前后 source/test hash 不变。这些计数早于 P2 到期边界修正：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_sdk_call_boundary.py tests/unit/test_sdk_call_boundary.py tests/unit/test_stock_minute_permission_proofs.py tests/integration/test_production_stock_minute_permission_preparation.py tests/integration/test_production_stock_minute_permission_execution.py -q --tb=short
```

Controller/storage/session 相邻验证：**84 passed**。运行早于最终仅分类计数修正；该修正不改变这些组件。

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_request_recovery_admission.py tests/integration/test_runtime_recovery_storage.py tests/integration/test_close_recovery_session_ownership.py -q --tb=short
```

P2 修复后的最终目标/相邻组合 **335 passed**，保留同一既有警告，包含全部 **104** 例执行及 **74** 例准备测试、候选及 DAILY_BARS 路径、真实 production certification/semantic 门禁：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_stock_minute_permission_preparation.py tests/integration/test_production_stock_minute_permission_execution.py tests/integration/test_production_certification_gate.py tests/integration/test_production_semantic_gate.py -q --tb=short
```

独立 Sol 修后最终重跑，精确命令经协调者确认：**104 passed, 1 warning in 16.42s**。到期 P2 已关闭，无剩余 P1/P2。该独立结果与 writer 的 104/335 结果分别归属：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_stock_minute_permission_execution.py -q --tb=short
```

最终 source/test 修改后的定向 Ruff 已通过：

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/production.py tests/integration/test_production_stock_minute_permission_execution.py --output-format concise
git diff --check -- src/trade_plan_monitor/runtime/production.py
```

评审快照 SHA256：

- `production.py`：`021993781B39E3F1E88EB63402D30CCE1EBB65B2D6B0DD4746F646A0FE252581`。
- `test_production_stock_minute_permission_execution.py`：`459CCAB58ACE2A39BDC63E4C42B2A249A8E38A7ACD406ED362DC71B381263C4D`。

## SME-06 剩余门槛与限制

首轮独立 owner 评审发现上述到期 P2。协调者确认独立 Sol 修后最终复审通过：P2 关闭、无剩余 P1/P2，授权本地提交这四个文件。并行 A07 工作及另行授权的 UPD-S1 provider 工作不计入本报告实现；较广命令验证的是共享 checkout，而非 release artifact。本 writer 未运行完整仓库测试或 A07 startup RED 文件。

此证明只说明 endpoint 可读，不授予业务 READY 或交易权限。快照验证和 controller reset 不属于一个原子数据库事务。S 位于调用已解析 SDK callable 前，不等于网络发送时间，也不保证零线程调度延迟。取消不会强制中断活动 SDK 调用。已观察权限撤销是单调的，但不声称可检测绕过受支持 epoch 路径且未被观察的外部 ABA。真实 `rt_min` 正证明行可用性、自动调度、启动业务接入和完整 C1 验收仍需独立过关。
