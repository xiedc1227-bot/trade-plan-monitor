# B2 DAILY_BARS 内部权限复核

## 契约

- DBPW01：将准备提取为同步 `_prepare_daily_bar_permission_locked`，保留异步取锁 wrapper。`_maybe_recheck_daily_bars_permission` 持有同一锁并重新准备恰好一次，不能使用旧准备或二次分页。SKIPPED 映射为 SKIPPED；UNKNOWN 映射为 DEFERRED，并保留原 30 秒延后。
- DBPW02：冻结原 candidate、receipt、准备 captured_at、语义模式/revision、日历 epoch/event、reader 和 session factory。要求 DAILY_BARS、candidate/receipt 的 symbol 相同且池为 O/F。历史 d_need 可以不同于 SDK anchor。
- DBPW03：排队前冻结 latest_start=captured_at+15 秒及 31.25 秒 market guard。预约前、queue admission、worker 入口、紧邻 SDK 入口四处检查配置/语义/generation/stop/日历身份、同日且时间>=captured_at、取消 Event 及冻结 market window。worker 检查零数据库读取。缺 authority/demand/anchor/window 固定延后 30 秒；具体 market blocker 沿用现有让行期限规则。
- DBPW04：从原 candidate 创建 on_reserved。仅成功持久化 300 秒预约后，推进 scope、原 O/F 游标及交替状态恰好一次。abort/invalid/timeout 保留预约；实际启动延长 floor 不再次调用 callback。
- DBPW05：为 `probe_daily_bars_permission` 及私有 daily 路径增加 keyword-only `_physical_start=None`。在参数校验及构造后、紧邻 `_fetch_frame('daily')` 前、broad catch 外调用。同一 sentinel 原样传播。普通 daily/history 路径与 strict parsing 保持不变；证明精确 symbol/date 的恰好一条官方记录。
- DBPW06：响应在 owner 上使用捕获 factory 的新 owned explicit-BEGIN 快照，验证原 reader/receipt 及精确原 anchor（SSE、工作日、早于响应日期、开市）。不能调用另开 UnitOfWork 的 anchor helper、重新分页/选候选或替换新 receipt。快照前后检查冻结 authority/source identity/epoch/time。完成/checkpoint 覆盖、回退/损坏及身份 ABA 使原 receipt 失效；O/F 成员变化及正常 pending 不使其失效。响应时不复核未来 31.25 秒启动窗口。
- DBPW07：仅 controller validate_after=true 清除 DAILY_BARS，成功时仅移除自身 local defer。不写业务数据或接入 scheduler。RequestNotStarted 映射为 DEFERRED；已知 permission/429/transient/timeout/invalid-response 映射为 FAILED。ERROR/CLOSED/QUEUE_FULL、SQL/save/callback 异常及取消继续传播。未知 worker 异常仍由 controller 包装为 ERROR，不承诺保留原类型。
- DBPW08：捕获调用方 owner_task 及每次调用独立的 threading.Event。CancelledError 时先设置 Event 再抛出，finally 永久设置它。所有启动及响应守卫检查 Event。owner 响应还须在读取前及返回 true 前确认捕获 owner_task.cancelling()==0；worker 不访问 Task。即使外层 catch 未执行，已请求取消也不能清权限。不保证 Event 设置前 SDK 绝无启动。物理工作由 controller 单 worker/retained slot 排空；不为排空继续持有维护锁，不修改 controller。快照验证与随后 controller 清权限不是原子操作，也不授予业务执行权限。

## RED 矩阵

| ID | 必需证据 |
| --- | --- |
| R01 | TODAY/HISTORY × O/F、d_need!=anchor、精确调用、仅自身 scope 清除、零业务 SQL 写 |
| R02 | 共享锁无死锁，重新准备一次 |
| R03 | 到期/429/其他 scope 门槛；缺失固定 30 秒不滑动、不分页 |
| R04 | 四处撤销边界；预约前零游标推进，预约后保留预约，拒绝时零 SDK 调用 |
| R05 | 原 receipt 失效不能借用有效替代凭据 |
| R06 | 历史完成/checkpoint 覆盖、回退及损坏 |
| R07 | 原 anchor 无效但另一日期有效；伪造周末开市行 |
| R08 | O/F 移动仍可清权限，原池 callback 一次 |
| R09 | 并发写入、响应单快照、worker 零 SQL |
| R10 | 时钟退到 receipt 后但准备前、跨日拒绝、临近市场期限的合法迟到响应 |
| R11 | save/callback/queue/invalid/429/timeout 结果及重开临时库恢复状态 |
| R12 | 真实 provider seam 传播同一 sentinel，普通 daily 不变 |
| R13 | SDK 前取消、启动后取消且迟到成功与排空顺序、已请求但尚未 catch 的取消阻止清权限 |

## 验证状态

已在实现前记录契约及 RED 矩阵。分钟片在 `95feccb` 释放 provider 文件；本次只在 `tushare.py` 增加 DAILY_BARS seam，不修改 `tushare_client.py` 或分钟行为。内部入口及真实 provider seam 已实现、完成离线验证，并获独立复核批准本地提交这五个文件。不访问真实服务或用户数据库，不推送、部署，不修改 controller 或 scheduler。

### RED 与 GREEN 证据

- 补齐真实 provider seam 及排队市场延后规则前，`real_provider or market_blocked` 选择集结果为 **9 failed, 1 passed, 42 deselected**：缺少 `_physical_start` 支持，且具体 market blocker 错用固定延后。实现后，当时全部 **52** 项用例通过。
- 补充入口门控、请求期间正常 pending 及激活身份 ABA 检查后，全部 **57** 项用例通过。
- 新增预约前最后一道市场校验测试，先复现固定延后 30 秒而非冻结 blocker 期限加一微秒的失败。预约前与排队中止现复用同一冻结窗口延后 helper，最终全部 **58** 项专项用例通过。
- 最终合并运行 DAILY_BARS 准备/需求/维护、候选选择/轮转/周末一致性、INDEX_DAILY/DAILY_LIMITS 维护及 daily 证明回归：**248 passed**（包含上述 58 项专项）。
- 分钟证明/传输回归：**291 passed**。两个改动源文件及新增测试文件的 Ruff 通过，`git diff --check` 通过。
- 集成运行出现一条既有 Starlette/httpx 弃用警告；没有调用外部 provider。

### 独立复核

主协调于 2026-09-27 转达终版独立复核通过：**11 个测试文件共 281 passed**，包含全部 **58** 项专项；Ruff 与差异检查通过，测试后 source/test hash 未变。无剩余 P1/P2。首次发现的预约前最后一道 market-blocker 期限 P2 已关闭，双语报告已确认一致。放行仅覆盖本内部权限复核片，不包含 scheduler 接入或 A07 生产修复。本地提交后，释放 `production.py` 和 `tushare.py`，供分钟 owner 接手下一片设计/实现。

### 复现

在 `trade-plan-monitor/` 下使用现有虚拟环境执行：

```powershell
.venv/Scripts/python -m pytest tests/integration/test_production_daily_bar_permission_maintenance.py -q --tb=short
.venv/Scripts/python -m pytest tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_daily_bar_permission_demand.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/unit/test_daily_permission_proofs.py -q --tb=short
.venv/Scripts/python -m pytest tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py -q --tb=short
.venv/Scripts/python -m ruff check src/trade_plan_monitor/runtime/production.py src/trade_plan_monitor/market_data/tushare.py tests/integration/test_production_daily_bar_permission_maintenance.py
git diff --check
```

### 证据边界

测试使用真实临时 SQLite、真实 request controller 与持久化恢复 repository、受控时钟/Event 及离线 SDK 响应。通过重开临时数据库核对恢复期限下限。拒绝 worker SQL；只读复核仅允许恢复 checkpoint 写入。并发写入测试证明 receipt 与 anchor 在同一响应快照内验证，包括快照开始后提交的 anchor 变更。

快照验证与 controller 清权限仍是两个操作，稍后的提交可能改变业务事实。取消检查保证外层 catch 尚未执行时，已请求的取消也不能清权限，但不承诺取消 Event 设置前 worker 绝不进入 SDK。维护锁释放后，物理工作由既有 controller slot 排空。这些测试证明权限复核行为，不证明在线 provider 可用性，也不授予业务执行权限。
