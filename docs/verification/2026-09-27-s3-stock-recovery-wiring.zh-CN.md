# S3 股票恢复接线 — F3-C

## SRW-01 — 范围与当前状态

基线 `5e56c41` 包含已独立验收的 F3-B。本片遵循双语[启动分钟修复契约](2026-09-27-s3-startup-minute-repair-contract.zh-CN.md)。startup 无 ticket/outcome/failure-evidence 接口已在实现前独立批准。**最终独立源码/测试评审通过，无剩余 P1/P2；报告 parity 已批准。** 未提交、推送、部署、调用真实服务或使用真实用户数据库。

源码范围为 `runtime/production.py`、`runtime/scheduler.py`、`runtime/service.py` 和 `web/monitor_composition.py`。测试包括独立 wiring 文件、加强后的原 A07，以及明确批准的现有 execution 和 missed-close kill 测试 fixture 时钟对齐。root 持有提交权限。connected identity/authority 报告由各自作者维护；真实最终准入控制见双语 delivery 报告。本批已获最终独立批准；整体集成验收仍另行进行。

## SRW-02 — 首批门槛

- startup 最多发出一次当前日股票获取。空/部分完成后的 completion+30 retry floor 跨有界同步、目标变化及重复 startup 保留；provider retry 必须保留分类与 floor，不虚构 attempts。
- 已预先阻断且覆盖缺失时，保持既有 startup failure；已提交完整覆盖仍为零获取成功。无 ticket 或 `None` 不证明 READY。
- 真实 index-only composition 没有股票语义时仍继续指数工作；股票缓存 getter 为 `None`，误派 STOCK_RECOVERY 不做股票动作。这不授权放松直调股票单元的权限 guard，也不能吞掉已安装权限的撤销。
- STOCK_RECOVERY 属于 maintenance：行情同刻优先，生命周期 cursor/review 两处均保留原行情观测，恰好一个新鲜已过职责可运行，多项已过职责不回放，股票维护不派发 pending 通知。
- 行情成功完成后不能调用 legacy 多标的 `repair_detected_gaps` 旁路；旧 generic 兼容 API 仍供其他调用者使用。
- 原 A07 保留全部 13 项及三个 oracle 对照。progress 现在于每个 wake 及最终完成时断言 generation 不变/无 runner fault；前缀修复后、合法求值前仍零业务状态且 AWAITING_FIRST_EVALUATION；精确断言 10:05 target 于 10:05:12 求值。C2 保留真实获准入场的 10:00:59→10:01:13 startup 调用，且没有立即启动已过职责回放。

最初的指数负控错误地在未安装股票权限时直调股票单元。该拒绝本来正确，不是产品缺陷。记录下述检查点前，已将对照修正为真实 composition 分派。

## SRW-03 — RED 证据

命令从 `trade-plan-monitor` 执行，使用离线 SDK 与临时数据库：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_wiring.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
```

新增接线：**10 failed，2 passed，1 warning，4.73s**。失败定位到 startup 获取 10 次而非 1 次、空/部分/provider retry 缺失启动 schedule 记账、composition getter/scheduler callback/deadline kind 尚缺，以及真实 legacy gap-repair 调用。两个通过对照区分预先阻断且缺失与已提交完整覆盖。cursor/dispatch 断言仍待缺失接线建立，尚不能独立证明具体行为失败。

加强后原 A07：**2 failed，11 passed，11.51s**。仅 empty/partial 自主前缀恢复仍 RED；C2 及全部三个 oracle 通过。未 skip、xfail 或削弱测试。这些是作者运行，不是独立评审结果。

## SRW-04 — 实现与修正历史

Startup 与维护现共用私有 ticket/accounting 内核。Startup 不施加维护 reserve；维护保留 31.25 秒。有界失败缓存只保存类别、有效 floor、原始 requirement，不保存异常/cause/traceback。本 scope 合法 empty/partial 成功可清 retryable 证据，但保留 completion+30 及更晚 schedule floor；无 ticket、兄弟成功、target/activation 变化不清先前失败。完整已提交事实允许 startup 成功，但不清 controller/缓存 BLOCKED。只有同 binding 权威 blocked→clear 观测释放 BLOCKED 证据。本次 guard 失效仍为 startup 失败，不作为 provider 错误证据。

Production 正常返回同步有界需求。STOCK_RECOVERY 使用纯缓存 getter、两个 lifecycle 维护 cursor/review 点及 composition pending-dispatch 排除。真实 scheduled SDK 从 10:01:12.000001 跨至 10:02:13，证明只对原 10:02 target review 一次；fake-work 控制另保留多 elapsed 不回放。Index-only composition 对股票工作零动作，不削弱直接 unit authority 检查。原 production 多 symbol gap-fetch 只同步需求；通用 RecoveryService 兼容接口保留。

Root 发现共用内核日期回归：official-close await 可以跨 D→D+1。聚焦 `-k startup_date_rollover` 先为 **1 failed, 20 deselected, 1.59s**，恢复物理获取前请求日期过滤后为 **1 passed, 20 deselected, 1.45s**。未知/无 capture/非请求日期保留旧 skip 语义。

独立评审发现 fatal 被掩盖的 P2：真实独立线程/UOW 在 controller 返回 ERROR/QUEUE_FULL/CLOSED/INVALID_RESPONSE 前补齐全部事实。`-k fatal_provider` 先为 **4 failed, 4 passed, 18 deselected, 1 warning, 2.96s**；在记账后、startup 汇总前检查本次 fatal outcome 后为 **8 passed, 18 deselected, 1 warning, 2.61s**。维护原异常 identity 行为不变。

两个 execution 停机测试原来假定 empty startup 后立即请求（此前相邻 317 passed/2 failed）。获准 fixture 现在推进到实际 completion floor，运行真实 reserve 延后，再推进至返回 wake；原 token/drain/database 断言全部保留。这是 fixture 对齐，不是产品修复。

Official-close kill/read/outcome 批次初始为 **2 failed, 47 passed, 1 warning, 93.89s**。两个 missed-close fixture 只释放一次固定 sleep，现在被 15:00 合法股票观测先消耗，原 15:00:12 realtime 请求未释放。真实 composition 诊断确认 RUNNING/READY 及精确 wake。独立批准的 fixture-only 修改按实际 deadline 释放至 15:00:12，并设八次 wake guard、断言两个时点均经过；SDK 入口、强杀、无 pending、同/次日恢复及唯一性/幂等断言全部保留。Completed/restart 阶段政策不变。

## SRW-05 — 最新作者证据与评审边界

从 `trade-plan-monitor` 执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_identity.py tests/integration/test_s3_stock_recovery_authority.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_execution.py tests/integration/test_s3_stock_recovery_owner.py tests/integration/test_s3_frozen_startup_recovery.py tests/unit/test_monitor_runtime.py tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_runtime_liveness.py tests/integration/test_runtime_plan_expiry.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
```

日期/fatal 修复后、随后一处仅换行修改前：**43 passed, 1 warning, 26.18s**（26 wiring + 13 A07 + 2 delivery + 1 identity + 1 authority）；直接相邻 **319 passed, 1 warning, 55.37s**；针对性 120h/liveness/plan-expiry 准入 **29 passed, 1 warning, 13.30s**。最终修正后的四个 kill 命令在末版源码上为 **4 passed, 26.07s**。此前 27/35 目标、319 相邻及独立 15 connected-case 窗口均早于日期/fatal 修正，仅为历史证据。重叠计数不相加。

末版源码/测试独立评审后继续冻结。Production SHA256 为 `38608F351317BBA04E35D169FC471B0F9707884E83C61E816544073143E968F7`；与 43/319 测试窗口唯一区别为表达式换行。作者全量 `.venv/Scripts/python.exe -m ruff check src tests scripts` 通过。未 skip/xfail，未削弱业务断言。本源码/测试验收不关闭整体 C1 或 C3。历史决策回放、新 freshness 阈值及新恢复 loop 仍不在范围。

## 最终独立验证

独立 Sol 在 `trade-plan-monitor` 目录针对末版冻结源码/测试运行以下精确命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_stock_recovery_identity.py tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
.venv/Scripts/python.exe -m ruff check .
git diff --check
```

**159 passed, 1 warning, 52.75s**。11 个 SHA256（四个源码、七个测试文件）运行前后均与最终冻结值完全一致。Ruff 与 diff 检查通过。最终 F3-C/A07 源码/测试无剩余 P1/P2；startup fatal 掩盖 P2 已关闭。此前独立 155/28.47s 窗口跨 AD22→38608 仅换行修改，不作为最终 fixed-revision 验收；由本次 159 用例覆盖，而非相加。作者与独立窗口保持分列。五组双语报告 parity 已独立核对通过；不宣称整体 C1/C3 已关闭。本次文档更新不修改源码/测试，也不提交。
