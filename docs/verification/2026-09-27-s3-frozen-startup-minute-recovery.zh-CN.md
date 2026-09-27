# S3 冻结启动分钟恢复 — F2 实现

## F2-IMPL-01 — 状态与边界

2026-09-27。已批准设计：双语 `2026-09-27-s3-startup-minute-repair-contract` 的 A07-F2 / VERIFY-02 / VERIFY-05，以及独立批准的 token-before-cancel 窄接口。独立实现评审已通过，无 P1/P2；下文分开记录作者与独立证据。最终追加候选基线：`4b1c823a40a7b4fd8e0b85eca78920dfa08f5710`，加本片未提交改动。

范围：`runtime/production.py`、`runtime/recovery.py`、`runtime/recovery_targets.py`、`runtime/service.py`、`web/monitor_composition.py`、新增 `tests/integration/test_s3_frozen_startup_recovery.py` 及本报告对。复用已提交的业务 SDK hook `e7c6d8f`；未改 provider、controller、scheduler 或 UoW。无推送、部署、真实服务、真实用户数据库、schema 改动、权限重置或新增业务恢复循环。

F3 尚未实现：过渡启动仍允许最多 10 个 symbol，每个最多 240 个 required minute ends。启动 retarget/yield 仍沿用现有过渡错误政策，作为启动失败处理；这不是 F3 正常 maintenance outcome 处理。未向启动施加 maintenance reserve。既有官方收盘顺序和政策不变。explicit 当前日预取不构成对 explicit 评估新增的 legacy-prefix 就绪要求。

## F2-IMPL-02 — 已实现契约

- 不可变 `RecoveryCapture` 保留原始 target/cutoff、精确前缀、规范 payload/hash/version/activation identity、配置与语义 revision、source 对象身份、runtime generation、epoch 和 revoked Event 身份。
- `recover_scope` 接受每次调用独立的持久化、业务取数、准入回调以及线程安全 attempt token。通用兼容路径仍调用 `current_day_minutes(symbol)`。production 在真实 wrapper 准备完成后绑定具体 provider 的 `_physical_start`；不替换共享回调、worker 不查 SQL、不检查 Task。
- capture 与响应持久化使用独立的短 owned transaction。最终持久化重读精确身份、日历和已提交 required ends，仅插入仍属于 `missing_now` 的响应行。即使旧请求获得更晚的规范化时间戳，也保留并发合法分钟及其 latest_quote 贡献。
- 外部校验和 repository staging/flush 在 baseline `RLock` 外完成。锁内仅有最新 memory/clock predicate 和同步 commit。围栏失败会一起回滚 minute 与 latest_quote。真实双连接旧读快照产生 `SQLITE_BUSY_SNAPSHOT`；不重试旧 capture。
- 两次 coverage 读取与持久化中的 guard 变化均转换为 typed retarget。已识别存储错误通过不进入 repr 的结果字段保留原异常，启动传播该异常。编程错误与取消传播；取消先发布 attempt token，再 drain 已拥有的物理调用。

## F2-IMPL-03 — Authority 与来源证据

两个真实 composition worker setter `_revoke_configuration` / `_revoke_semantics` 均在共享 baseline `RLock` 下发布 Event 并增加 epoch，释放后才通知 owner loop。真实 `_open_database_sync` 仅将 READY / WAL READY 两项赋值放入该锁；迁移和 dispose 保持锁外。最终准入保留旧 lifecycle 的 `_stopping`、`_cleanup_complete`、`_cleanup_failed`、`_liveness_failed` 及 generation/database-readiness 检查；没有增加 `_accepting_work`。其余已审计 authority 变化仍由 owner loop 发布。将 scoped persistence 移至 worker 会使此证明失效。

本地版本：Python `3.14.7`、SQLite `3.50.4`、SQLAlchemy `2.0.52`；未升级依赖。现有 engine 使用 `isolation_level=None` 和发出 `BEGIN` 的 begin listener，本片因此没有增加第二个 BEGIN。这与官方 [SQLAlchemy SQLite 事务方案](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#enabling-non-legacy-sqlite-transactional-modes-with-the-sqlite3-or-aiosqlite-driver) 一致；网站当前描述 `2.0.54`，并非本地安装补丁版。

本地 `sqlalchemy/orm/session.py` 的 `_prepare_impl` / `commit` 会 dispatch before/after-commit 事件并 flush pending work。本应用未注册应用 commit/flush 回调（`rg` 仅发现 engine connect/begin listeners）；repository 的 minute/latest_quote staging 在进入锁前已 flush。不能泛化为“SQLAlchemy 不会调用回调”。参见 [Session flushing](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#flushing)。集成测试断言 commit 前 session clean、SQL 仅在 owner 且 authority lock 外发生，并验证 pre-read/final-write/post-read 的三个独立显式事务。

真实旧快照及锁顺序测试依据 [SQLite snapshot isolation](https://www.sqlite.org/isolation.html) 和 [Python 3.14 RLock 语义](https://docs.python.org/3.14/library/threading.html#rlock-objects)。覆盖 revoke-first 回滚、commit-first 完成后再撤权、真实 worker 锁外通知以及同步校验触发撤权而不死锁。没有在锁内 join 需要同锁的 worker。

## F2-IMPL-04 — RED 与 token 追加前作者验证

所有命令从 `trade-plan-monitor` 运行，使用临时离线数据库。

本节 108 / 247 / 350 计数属于 **token 追加前窗口**，基于 `9548f7a65f26172c486e315b2a81f98353e17982` 加先前候选观察得到。不将其复用为最终追加证据；见 F2-IMPL-05。

最初原始 A07 对照：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q --tb=short -k 'real_provider_filters or frozen_acquisition_cutoff or new_real_acquisition'
```

F2 前结果：**1 failed, 2 passed, 10 deselected, 3.58s**。C2 在真实 `10:00:59` → `10:01:13` SDK 调用后多写了 `10:01` 行。C1 future filtering 和 C3 新的较晚 capture 是正控。新增 seam 测试先观察到三个真实 RED（缺少 per-call persistence 及两个被吞掉的编程错误），随后依次观察到缺少 business-fetch callback 的 RED、三个缺少 capture/persistence API 的 RED，以及 capture authority 被静默跳过的 RED，再对应修复。

最终验证前已修正测试打包：原始 A07 测试未被跟踪，不能成为本片依赖。通过 `builtins.__import__` 禁止该模块时，最初产生 **no tests collected, 1 import error**。新增 composition fixture 现位于本文件，仅引用已经提交的 helpers。未改动的 A07 测试/报告对不属于本片。仅 fixture 修正（日历必填字段、composition state 访问及合法替换 SDK 对象）不计为产品缺陷修复。

追加前目标与直接相邻检查，显式禁止 A07 导入：

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest; original = builtins.__import__; builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError('A07 is not a committed dependency')) if name == 'test_s3_startup_minute_coverage' else original(name, *args, **kwargs); raise SystemExit(pytest.main(['tests/integration/test_s3_frozen_startup_recovery.py', 'tests/integration/test_runtime_recovery_coverage.py', 'tests/unit/test_recovery_targets.py', '-q', '--tb=short']))"
```

**108 passed, 1 warning, 33.01s**，包含 **52 个新增 F2 case**。覆盖不可变精确身份/前缀、并发回调隔离/默认兼容、两个 typed coverage-read guard、原始存储 cause、真实 wrapper 延迟/撤权/source 替换、SDK 前后取消与 drain、最终围栏变化、实际 composition authority writer、四项 lifecycle admission flag、不增加 accepting-work 依赖、真实双连接重激活回滚及真实 provider 等待中的并发 minute/latest_quote winner。

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_stock_minute_permission_execution.py tests/integration/test_production_stock_minute_permission_preparation.py tests/unit/test_current_day_business_sdk_boundary.py tests/unit/test_stock_minute_permission_proofs.py -q --tb=short
```

**350 passed, 1 warning, 29.74s**。

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_recovery_storage.py tests/integration/test_runtime_lifecycle.py tests/integration/test_recovery_activation_fences.py tests/integration/test_live_pipeline_acceptance.py tests/integration/test_explicit_runtime_production.py tests/integration/test_production_semantic_gate.py tests/unit/test_recovery_coordinator.py tests/unit/test_monitor_runtime.py tests/unit/test_request_recovery_admission.py tests/unit/test_production_historical_recovery.py tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
```

追加前重跑：**247 passed, 1 warning, 113.26s**，包含四个真实官方收盘 kill/restart 窗口及 lifecycle/manual-stop/liveness 覆盖。前一轮完全相同的 11 文件命令也通过 247 例，用时 112.53s。

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
```

**2 failed, 11 passed, 12.62s**。只有未改动的 F3 autonomous-progress 两例（`A-empty`、`B-missing-0931`）仍为 RED。C2 和全部三个 oracle 对照通过；没有引入 skip/xfail、削弱断言或抑制启动调用。这不是完整 A07 验收，也不依靠 supervisor replacement 实现恢复。

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/recovery.py src/trade_plan_monitor/runtime/recovery_targets.py src/trade_plan_monitor/runtime/production.py src/trade_plan_monitor/web/monitor_composition.py tests/integration/test_s3_frozen_startup_recovery.py
git diff --check
```

两者均通过。测试 warning 是既有 Starlette/httpx 弃用提示。

## F2-IMPL-05 — Token-before-cancel 追加

pipeline 的 owner-loop registry 从首次 await 前到物理 drain 完成期间持有每次 attempt Event。`revoke_active_recovery_attempts` 只设置这些 Event，不 cancel、clear、join、查询 SQL、获取 authority lock 或修改共享 baseline revocation flag。迟建 attempt 在首次 await 前注册并重新检查当前 admission/generation，失效时先设置 token，再以 `RecoveryAdmissionChangedError` 退出。既有取消 fallback 保留。

composition 转发同步回调，尚未存在 pipeline 时为 no-op。`RuntimeLifecycleService` 校验 optional callable，并保留合法 falsey callable。`begin_shutdown` 发布 `_stopping` / `_accepting_work` 后，在 dispatcher/controller shutdown 或任何 task cancellation 前执行撤销。回调失败被锁存并进入既有 stop cleanup，而不从同步入口逃出。重复成功不能抹掉尚未呈报的错误。只有 `stop` / `_observe_stop_result` 呈报后，后续成功回调才允许既有 cleanup retry 消费该错误。drain 失败保留原始主异常及 `__cause__`，通过 `recovery_revocation_error` 单独保留 revoker 异常。数据库 dispose 仍等待 drain。

新增 RED 证据：两个真实 SDK 前后 `begin_shutdown` 测试和重复 stop 失败锁存测试最初 **3 failed, 52 deselected, 3.31s**，随后 **3 passed, 52 deselected, 2.78s**。合法 falsey callable 单独失败后，在 **1.18s** 通过。对照在 `begin_shutdown` 返回后立即同步断言，不 await/sleep：token 已设置、task 未取消、worker 未 drain、数据库仍 READY。其他对照覆盖 heartbeat/dispatcher/provider drain cause、late attempt、未发布且无 pipeline 的 candidate、重复 stop、新 generation token 隔离和非 callable 构造拒绝。最终 F2 文件包含 **65 cases**。

最终追加运行使用 F2-IMPL-04 的四条原命令，在 falsey 修正后冻结全部五个源码文件及测试：

- 禁 A07 导入的目标/直接相邻三文件：**121 passed, 1 warning, 37.29s**（65 个 F2 case）。
- Permission/SDK 四文件：**350 passed, 1 warning, 29.84s**。
- Lifecycle/recovery 十一文件：**247 passed, 1 warning, 113.70s**。
- 完整原 A07：**11 passed, 2 failed, 12.84s**，仅两个 F3 autonomous-progress case；C2 和全部 oracle 对照保持 GREEN。

中间 falsey 前窗口（120 passed，36.85s；350 passed，29.22s；247 passed，113.24s；A07 11 passed / 2 failed，12.38s）属于历史，不复用为最终证据。F2-IMPL-04 更早的 108 / 247 / 350 窗口位于整个 token 追加之前。

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/recovery.py src/trade_plan_monitor/runtime/recovery_targets.py src/trade_plan_monitor/runtime/production.py src/trade_plan_monitor/web/monitor_composition.py src/trade_plan_monitor/runtime/service.py tests/integration/test_s3_frozen_startup_recovery.py
git diff --check
```

最终两项检查均通过。最终验证窗口中全部六个源码/测试 hash 保持稳定。

## F2-IMPL-06 — 交接

独立 Sol 评审通过，无剩余 P1/P2，token 顺序项已闭合。其最终精确命令为：

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest; original = builtins.__import__; builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError('A07 is not a committed dependency')) if name == 'test_s3_startup_minute_coverage' else original(name, *args, **kwargs); raise SystemExit(pytest.main(['tests/integration/test_s3_frozen_startup_recovery.py', 'tests/integration/test_runtime_lifecycle.py', 'tests/integration/test_monitor_production_composition.py', '-q', '--tb=short']))"
```

独立结果：**138 passed, 1 warning, 36.57s**。独立完整原 A07 使用 F2-IMPL-04 命令：**11 passed, 2 failed, 12.00s**，同样仅 F3 progress。独立 Ruff 限定五个改动源码文件及新增测试（并非全仓 lint）；Ruff 与 `git diff --check` 通过。评审者确认全部六个源码/测试 hash 稳定。

打包依赖与字面 token 顺序缺口现为已闭合历史项。停在未提交状态，等待 root 协调报告双语 parity 确认及精确八文件本地提交；不推送。F3 自主恢复及后续 C1 calendar/history owner 接线仍是独立已批准薄片，因此这不是完整 A07 验收。
