# B2 DAILY_BARS 权限准备

## 范围

仅实现 production 内部准备：不预约、不调用 SDK、不写业务数据、不接自动调度或物理权限探测。变更限定为 `production.py`、新增集成测试及本配对报告。这不代表 C1 完成，也不证明跨 scope 无饥饿。

## 契约

- DBPP-01：可选 `permission_session_factory` 提供安全权限读取会话及稳定、独立的 `LegacyHistoricalCloseReader`。默认回退至已传入的 `recovery_session_factory`，绝不反向填充业务恢复选项，也不启用 `_historical_reader`。没有安全来源时返回 `UNKNOWN`，本地固定延后 30 秒。不能从 UnitOfWork 私有字段推断 factory。
- DBPP-02：`_prepare_daily_bar_permission` 持有共享权限维护锁。先检查 DAILY_BARS 阻断及有效到期时间=max(raw, local, 429)。其他候选仅在 effective-due<=now 时参与竞争，保留 raw-due 及现 scope 游标排序。无需宽候选选择器已经包含 DAILY_BARS：无需求/anchor/authority 仍固定设置 now+30。未到期调用不能滑动该期限或检查分页；其他 scope 优先时不检查需求页。
- DBPP-03：owner 线程的一份 explicit-BEGIN SQLite 快照包含 ACTIVE 枚举、需求检查、凭据复核、日历与官方日线读取及候选构建。共享现有证据逻辑并保持 pure peek 行为；不能拼接 UnitOfWork 读取与另一份需求快照。数据库读取错误向上传播。
- DBPP-04：cursor/receipt 缓存最多保留 10 个当前 ACTIVE legacy symbol，裁剪已消失 symbol。今日符合策略的计划使用 helper 的 TODAY 短路。每次调用最多检查一个已过期历史 symbol 及一页 <=32 个自然日，通过独立 symbol 轮转在完整当前历史清单中选择严格后继。UNKNOWN、NONE 及新 symbol 后续仍可检查。成功后可以再次检查；32 天预算按每次调用计算，不是生命周期总预算。
- DBPP-05：跨日使 receipt 失效，但保留有效分页 cursor。无关事件及同值日历刷新不重置进度。遇到 `invalid_cursor` 或 checkpoint 回退才丢弃 cursor；普通证据暂缺时保留。身份变化交由 helper 重建。pending 不能否决独立验证的需求。
- DBPP-06：在同一快照内逐个验证最多 10 个缓存 receipt，各自遵守 helper 的点验/checkpoint 预算，与单页 32 天预算分别声明。仅当前有效 receipt 对应 symbol 进入 O/F；保留现有池排序、严格后继选择及交替语义。返回不可变结果，包含 candidate、原 receipt、captured_at、语义绑定事实及日历 epoch。它不构成执行授权，也不允许长期复用缓存许可。
- DBPP-07：准备不能推进 controller 预约或 scope/O/F 游标。无有效需求/anchor/authority 时返回 `UNKNOWN`，本地固定延后 30 秒。继续执行配置、语义、generation 和 admission 撤销边界。本步仅证明历史 symbol 调查公平；跨 scope 调度是后续接入门槛。

## 验证

使用真实临时 SQLite 与 fake SDK。覆盖生产 composition、仅权限 factory 构造、到期/429/其他 scope 门槛及 pure peek、raw 更早但 effective 在未来、无 anchor 固定延后、10 symbol 轮转、new/NONE/UNKNOWN 再次检查、第 33/371 天及跨日进度、receipt 失效/身份 ABA/时钟回退/reader 更换、正常 pending、单快照以及零预约/SDK/业务写。运行 helper、候选、轮转、INDEX_DAILY、DAILY_LIMITS 相邻回归及 Ruff/diff 检查。独立复核前不提交。

结果（2026-09-27）：

- RED：真实生产 composition 成功启动后，新测试因缺少独立 `_permission_demand_reader` 而出现 `AttributeError`。配对契约及测试均先于实现。
- GREEN：28 项准备层测试通过。覆盖十 symbol 的 UNKNOWN/NONE 再次检查、跨日到达第 33/371 天、正常 pending 写入、原 receipt 保留、严格凭据过滤、共享锁串行化及并发激活写入下的证据一致性。一次准备恰好执行一次 `BEGIN`，在该同一 session 中验证 10 个 receipt，且只发出 `BEGIN`/`SELECT`；预约期限、scope/O/F 状态和 fake SDK 调用数保持不变。
- 相邻合并运行：137 项通过，耗时 46.82s（28 项准备测试加 109 项 helper/候选/轮转/INDEX_DAILY/DAILY_LIMITS 测试）。存在 1 条既有 FastAPI/Starlette `httpx` 弃用警告。Ruff 与 `git diff --check` 通过。
- O/F 的 366 天 anchor 窗口与无年龄截断的历史需求分页保持分离。普通激活证据暂缺时保留 cursor；reader 更换会使缓存 receipt 及本次检查的旧 cursor 失效。每次成功后重复准备仍限制为一次历史检查和最多 10 次 receipt 复核。
- 独立 Sol/xhigh 复审通过，无新增 P1/P2。复审者独立确认 28 项准备测试、137 项合并测试、Ruff/diff 检查及双语一致性均通过。变更限定为 4 个文件。未调用真实服务、用户数据库，未推送、部署、接入 scheduler 或物理 DAILY_BARS probe。

命令（从 `trade-plan-monitor/` 运行）：

```powershell
.venv/Scripts/python -m pytest tests/integration/test_production_daily_bar_permission_preparation.py -x -q --tb=short
.venv/Scripts/python -m pytest tests/integration/test_production_daily_bar_permission_preparation.py -q --tb=short
.venv/Scripts/python -m pytest tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_daily_bar_permission_demand.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py -q --tb=short
.venv/Scripts/python -m ruff check src/trade_plan_monitor/runtime/production.py tests/integration/test_production_daily_bar_permission_preparation.py
git diff --check
```
