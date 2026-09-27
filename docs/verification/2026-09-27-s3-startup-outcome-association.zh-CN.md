# S3 启动结果关联

## F1-STATUS — 范围与状态

F1 独立源码与测试提交完整性评审通过，允许六文件本地提交。A07 与 S3-04 保持 OPEN。本片在 `runtime/service.py` 和 `runtime/explicit_service.py` 实现已批准 F1 契约，新增 `tests/integration/test_s3_startup_outcome_association.py`，并更新 `test_explicit_runtime_production.py` 中五项协调器预期。本片没有修改生产获取、恢复、调度、composition、数据库结构、UI 或 API 源码。共享工作区含其他 owner 的改动；这些观测不代表隔离提交版本认证。本片未推送、部署、访问真实供应商或真实用户数据库。

## F1-DESIGN — 已实现边界

`PlanCycleIdentity` 与 `PlanCycleOutcome` 是内部不可变值。协调器在指数/股票获取前捕获有序候选身份，选择 due 子集时不重新捕获 activation，并在按原顺序提取真实结果前验证完整预期身份集合。遗漏、重复、多余以及错误 consumer/plan/activation/target 身份均拒绝。交叉校验 legacy facts/result 和 explicit result 实际表达的身份。合法 legacy `INCOMPLETE` 保持 `facts=None`，没有 evaluation、claim 或 event。

已知 activation、inventory 与 manual-risk guard 的失败直接产生封闭的内部 `STALE` 值。没有围绕求值、存储、提交或发布进行宽泛异常捕获。公开 legacy batch 方法保留结果元组及预期 stale 过滤。独立 explicit 调用保留可选 `expected_activation_revision=None` 默认值和带类型 stale 异常。生产路径把原始正整数 revision 传入严格捕获和最终提交。explicit 结果 activation 身份在持久化前及 DUPLICATE 路径也接受检查。

逐计划记账不等于批次原子性。健康兄弟可独立提交，包括在之后出现协议/关联错误之前。取消和非预期错误继续传播。求值回调、持久化、提交、提交后回调或发布抛出的同类型异常不属于正常 stale outcome。

## F1-RED — 复现证据

实施前的独立运行分别建立以下证据：

- 首批六项：**3 failed、3 passed，10.01s**。最终事务前 activation 失效逸出协调器；内部一致但 activation 错误的结果在新建与重复路径均被接纳。发布异常和独立默认调用对照通过。
- 四项真实 composition 竞争：**4 failed，4.56s**。真实 SDK 等待期间，同计划 deactivate/reactivate 使旧 10:05 调用写入 revision 3 ledger。最终 activation、inventory 及 manual-risk 变化使 runner 故障。
- 十二项关联接口用例：**12 failed，1.35s**，因为拟议的内部身份/记账 API 尚不存在。这是接口 RED 证据，不是额外十二项已观测生产故障。

构建测试时，依据真实结构修正了 SQL 字段假设错误（ledger 应使用 `target_value` 而非 `target_bucket_end`，以及不存在直接 `alert_event.symbol`）。最终 alert 快照通过 `payload_json` 选择 symbol，没有移除任何业务表安全断言。这些测试构建错误不归类为产品回归。

## F1-VERIFY — 最终候选证据

最终定向文件包含 **44 项**：最初 22 项、四项错误来源对照、三项 legacy 发布/取消对照、四项 explicit payload 对照、一项混合消费者排序对照、一项 legacy stale/兄弟对照，以及九项 legacy payload 对照。最终完整文件运行：**44 passed，17.48s**。

强化后的四项 composition 竞争使用真实 composition/controller/provider/scheduler、假 SDK、受控行情时钟和临时 SQLite。测试准备阶段建立真实的更早 10:00 explicit ledger；被测 10:05 和 10:10 求值仅由真实 scheduler deadline 驱动。断言原 revision 1 的带类型 stale 记账、被拒 scope 在任一激活 revision 下业务零变更、既存行精确保留、健康兄弟独立提交、runtime generation 不变、无 `RUNTIME_RUNNER_FAILED`，且下一合法 10:10 求值成功、不回放 10:05。快照覆盖两类 ledger、explicit rule occurrence state、alert outbox、legacy result/head/risk 和 pending close state。HTTP 入口全部禁止。

相邻运行：**133 passed，74.12s**，包含当时的 35 项定向测试，以及 `test_ten_symbol_runtime.py`、`test_market_index_runtime.py` 和 `test_explicit_runtime_production.py`。随后九项 legacy payload 在最终整文件运行前独立得到 **9 passed，2.34s**。重叠运行独立记账，不相加作为最终套件数量。Ruff 与空白检查通过；既有 Starlette/httpx 弃用警告仍存在。

以下五项已有协调器用例改为断言 `results == ()`，而不是逸出的 `StaleExplicitDecisionError`：

- `test_real_sell_scheduler_rejects_concurrent_inventory_revision_change`。
- `test_actual_deadline_revision_guards_reject_stale_explicit_buy[deactivation]`。
- `test_actual_deadline_revision_guards_reject_stale_explicit_buy[rotation]`。
- `test_actual_deadline_revision_guards_reject_stale_explicit_buy[inventory]`。
- `test_actual_deadline_revision_guards_reject_stale_explicit_buy[manual-risk]`。

其既有零 alert、零 rule occurrence、inventory 和 publication 断言保留。这是在实现已批准的协调器正常 stale 语义，不是移除安全检查。新的 composition 用例补足兄弟、generation 和下一 deadline 保证。独立调用的 typed-raise 对照继续启用。

## F1-TRANSITION — 原 A07 矩阵

原 13 项文件未修改，结果为 **3 failed、10 passed，11.94s**。两项不完整前缀引发 runner 故障的回归现已通过。两项 progress 现失败：F1 移除偶然的 supervisor 重启恢复后，到 10:10:12 仍未补回缺失启动前缀。冻结截止点用例仍失败，在捕获 10:00 后持久化 10:01。安全、完整前缀重启、未来行/新获取及三个 oracle 对照仍通过。没有新增 skip、xfail、放宽时间边界、强制重启或伪造 INCOMPLETE。宣称 A07 完成之前仍需 F2/F3。

## F1-REVIEW — 独立评审与测试自包含修正

独立 Sol 评审未发现源码 P1/P2。分开运行通过 **44 项，17.46s** 和 **98 项相邻测试，58.21s**。原 A07 矩阵再次得到 **3 failed、10 passed，11.86s**，仍是两项进度失败及冻结截止点失败。四项额外内存检查确认 explicit evaluator/commit-admission 与 legacy public/strict evaluator 抛出的同类 stale 异常继续传播且业务零写入。这些运行期间源码和依赖哈希稳定。上述是分开的重叠证据，不是汇总通过。

一项 P2 涉及提交完整性：新测试从未跟踪的 A07 测试文件导入 `_DeadlineClock`，而该文件不属于本次六文件切片。协调会话通过 `builtins.__import__` 拒绝该模块，复现了**一项收集错误**，没有移动或修改 A07 文件。先前的 `sys.meta_path` 尝试未排除 pytest 的重写 hook，不属于 RED 证据。修正将同一小型时钟工具保留在本地，继承已跟踪的 `ControlledClock`；deadline 等待、64 次唤醒上限和真实 scheduler 推进均未改变。独立工具检查确认等价，且不再导入未跟踪的测试文件。

继续禁止该模块导入时，最终专项加相邻运行通过 **142 项、1 项警告，74.90s**。两份受审运行时源码未改；共享 `production.py` 依赖由另一 writer 工作中，因此不属于干净版本集成门禁。定向 Ruff 和空白检查通过。最终配对报告评审已关闭 P2，无剩余 P1/P2；只允许提交六个 F1 文件，不包含仍为 RED 的 A07 矩阵。

隔离命令如下。修正前收集失败的复现使用的 pytest 参数列表仅包含专项路径、`--collect-only` 和 `-q`。

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest
original_import = builtins.__import__
def isolated_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'test_s3_startup_minute_coverage':
        raise ModuleNotFoundError('Uncommitted A07 test is unavailable in the F1 commit')
    return original_import(name, globals, locals, fromlist, level)
builtins.__import__ = isolated_import
raise SystemExit(pytest.main(['tests/integration/test_s3_startup_outcome_association.py', 'tests/integration/test_ten_symbol_runtime.py', 'tests/integration/test_market_index_runtime.py', 'tests/integration/test_explicit_runtime_production.py', '-q', '--tb=short']))"
```

## F1-COMMANDS — 复现

在 `trade-plan-monitor/` 执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_outcome_association.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_outcome_association.py tests/integration/test_ten_symbol_runtime.py tests/integration/test_market_index_runtime.py tests/integration/test_explicit_runtime_production.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/service.py src/trade_plan_monitor/runtime/explicit_service.py tests/integration/test_s3_startup_outcome_association.py tests/integration/test_explicit_runtime_production.py
git diff --check
```
