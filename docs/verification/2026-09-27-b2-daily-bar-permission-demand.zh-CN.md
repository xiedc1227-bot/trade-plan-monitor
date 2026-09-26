# B2 DAILY_BARS 权限需求

## 范围

在 `LegacyHistoricalCloseReader` 上新增独立只读方法；不接入生产、不改变共享 B1 候选、不扩展 scheduler、不迁移、不调用 SDK、不写行情/评估/通知，也不授予历史执行权限。现有 `missing_targets_in_session` 保持不变。调用方提供新的 explicit-BEGIN SQLite 快照；helper 使用 `no_autoflush`，不拥有事务。

## 契约

- DBPD-01：`inspect_permission_demand_in_session(session, symbol, now, cursor=None)` 返回不可变 `DemandCheck`，包括 `NEEDED`、`NONE` 或 `UNKNOWN`、完整当前身份、可选凭据、原因及下一游标。身份包括 symbol、plan_version_id、plan_hash、formula_version、activation_revision 和实际 activated_at。激活证据损坏时返回 `UNKNOWN`，不能分页绕过；激活与孤立发布读取保留现有 1000+1 上限。
- DBPD-02：今日符合策略的 ACTIVE legacy 计划立即得到 `TODAY_REFERENCE`，不读取历史日期、checkpoint 或 pending，也没有 D_need；仍验证完整当前身份。未来策略没有历史需求。已过期策略使用 `HISTORICAL_CLOSE`。
- DBPD-03：每次历史调用最多检查连续 32 个自然日、32 次日期完成证据和 1 个最新已验证收盘 checkpoint。起点为 max(实际激活/策略起点, checkpoint+1)；终点受策略、观察时间及收盘到期限制。没有 366 天或五天截断。复用 `_scope`、`_latest_completed_close`、`_CompletionReader` 和 `discover_missed_closes`；不能调用无界 missing-target 扫描。
- DBPD-04：适用开市日的完成状态为 `ABSENT` 时，可在当前快照产生见证 `(S,D_need)`，即使此前日期未知。这只证明权限需求，绝不授权跨 `UNKNOWN` 的业务重放。pending 日期本身不构成证据。pending 的存在不能否决经独立验证的激活、日历及完成缺失证据，也不能使其凭据失效。本 helper 不读取 pending，也不将其作为捷径。仅有 pending 且历史证据不足时仍为 `UNKNOWN`。
- DBPD-05：游标保存完整身份、next_date、checkpoint 身份/哈希、observed_at 和 reader 实例 token，不携带 ORM 值或事务权限。未知页仍前进，尾页回绕至权威起点。无关全局事件、时间前进和日历刷新本身不重置进度。身份变化从起点重建；checkpoint 前进则跳过覆盖前缀。checkpoint 回退/替换/损坏、时钟回退或其他 reader 会使游标失效并返回 `UNKNOWN`；不带该游标重试可重新开始。
- DBPD-06：`NONE` 必须由覆盖终点的 checkpoint、权威适用区间为空，或当前快照内已完整检查且全部完成的剩余适用区间证明。短尾页不充分。不能拼接不同快照的分页来证明完成。
- DBPD-07：`validate_permission_demand_in_session(session, receipt, now)` 返回 bool。凭据绑定身份、类型、可选 D_need、checkpoint、captured_at 和 reader token。TODAY 重新验证完整身份和今日资格；HISTORICAL 对同一日期点查策略、日历、缺失状态及最新 checkpoint。完成、checkpoint 覆盖/回退/损坏、身份 ABA、时钟回退、跨日复用或其他 reader 都使凭据失效。有效凭据仍不携带执行权限。

## 验证

以真实临时 SQLite 夹具为主要证据；mock 仅观察预算或禁止不应调用的路径。先 RED 后实现。专项覆盖今日短路、第 33 天、超过 366 天的历史、未知页前进/回绕、不能仅由尾页推导 NONE、读取预算、无关事件/日历刷新、身份 ABA、checkpoint 前进/回退、裸 ledger/孤立发布/损坏证据、凭据失效、pending 歧义及零写入/SDK 调用。必须运行历史恢复、权限候选相邻回归及 Ruff、diff 检查。独立复核前不提交。

结果（2026-09-27）：

- RED：新测试在临时数据库完整初始化后，因尚未实现 `inspect_permission_demand_in_session` API 而出现 `AttributeError`；发生在实现之前。
- 复审修正：此前 38 项需求测试及 279 项不同测试通过，仍漏掉了一个 P1。按 symbol 对 pending 的全局否决违背独立历史证据；此前通过结果不能作为该行为正确的证据。
- P1 RED：在临时 SQLite 中通过正常 `RuntimeEvaluationService._mark_close_pending` 写入，复现两处失败：独立需求由 `NEEDED` 变为 `UNKNOWN`，已有合法凭据变为 false。另三项仅有 pending 且缺少日历、激活或完成证据的测试保持 `UNKNOWN`（2 failed、3 passed、37 deselected）。
- P1 GREEN：5 passed、37 deselected。最终合并运行：283 项通过（42 项需求测试及 241 项相邻测试），耗时 52.56s，存在 1 条既有 FastAPI/Starlette `httpx` 弃用警告。Ruff 与 `git diff --check` 通过。修复仅删除本次新增的全局否决、私有辅助方法及其导入，不增加 pending 捷径。
- 独立 Sol/xhigh 复审：42 项需求测试、Ruff 和 diff 检查通过；正常 pending 反例已消除，本 helper 范围内未发现剩余 P1/P2。
- 预算观测覆盖恰好 32 次日期读取加 1 次 checkpoint 读取。分页可以到达第 33 天和第 371 天，400 天前的缺口仍可见。实际激活时间与策略起点均受到约束。
- 原恢复方法未改变。变更限定为 4 个文件，未访问真实数据库/服务/供应商、未接入生产。

命令（从 `trade-plan-monitor/` 运行）：

```powershell
.venv/Scripts/python -m pytest tests/integration/test_daily_bar_permission_demand.py -x -q
.venv/Scripts/python -m pytest tests/integration/test_daily_bar_permission_demand.py -k 'normal_pending or pending_alone' -q --tb=short
.venv/Scripts/python -m pytest tests/integration/test_daily_bar_permission_demand.py tests/integration/test_historical_close_evidence.py tests/integration/test_close_recovery_evidence.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/unit/test_missed_close_recovery.py tests/unit/test_production_historical_recovery.py tests/integration/test_missed_close_execution.py tests/integration/test_close_recovery_session_ownership.py -q --tb=short
.venv/Scripts/python -m ruff check src/trade_plan_monitor/runtime/historical_close_evidence.py tests/integration/test_daily_bar_permission_demand.py
git diff --check
```
