# S3 已调度股票恢复停机证据

## 状态与范围

本片为 S3-07 `STOCK_RECOVERY` 停机边界的 TEST-ONLY 连接验收。作者及独立运行均在协调的源码稳定窗口内通过；三个文件已获独立批准，无 P1/P2。这是一项代表性连接测试，不代表批准 C1 UPD-S2、完整 S3-07 矩阵或整体集成门禁。

拥有文件：`tests/integration/test_s3_scheduled_stock_recovery_shutdown.py` 及本双语报告。本片未修改生产源码或既有测试；未提交、推送、部署，未使用真实服务、真实 provider、真实通知或用户数据库。测试复用已提交 A07 的 `_running`/`_DeadlineClock` composition fixture，以及已提交 identity 测试的完整行快照 helper。SQLite repository、请求控制、恢复、调度、停止/取消/排空及数据库释放均保持真实。只有外部 SDK/通知边界使用离线 fake；fixture 禁止 HTTP。

## SSR-01 — 真实调度 owner、取消与物理排空

测试：`test_scheduled_stock_recovery_stop_revokes_then_drains_before_database_disposal`。

1. 在 10:00:15 启动真实 composition，包含一个活跃 legacy plan，分钟前缀缺少 09:31。启动执行一次股票获取并留下既存 minute/latest_quote 行。释放真实 scheduler 的 sleep，直到下一次股票恢复物理进入 fake SDK worker。在暂停边界断言实际 deadline kind 为 `STOCK_RECOVERY`、其未完成任务属于 `runtime._work_tasks`，并且 `stock-prefix:003043.SZ` 正在执行。恰好存在一个活跃且未撤销的恢复 token，以及一个占用中的 controller 槽位。透明观察器原样转发 deadline；不挑选 deadline、不直接调用 recovery，也不手工注册 owned task。
2. 调用真实 `composition.stop()`。同步观察器在真实 `begin_shutdown()` 返回后立即确认 token 已撤销，而 owned task 和 runner 的取消请求数均为零。保留默认五秒正常排空期，然后等待 lifecycle 实际取消 owned task。物理 SDK 仍暂停时，stop 及其 owner 均未完成，controller 保留恰好一个活跃槽位和零等待者，数据库仍打开且为 READY，实际 engine 尚未释放。没有新 SDK 调用、通知发送或快照覆盖的行情/业务写入。runtime 实例、runner 和 generation 均不变，没有 runner-failure/restart 标记。
3. 释放 SDK。fake provider 的实际响应包含缺失 09:31 对应的源行，因此不能用空响应解释拒绝写入。断言所有 minute/latest_quote 完整行（包括 received_at）及快照中的 evaluation/ledger/head/risk/audit/alert/HOLD/eligibility/attempt/pending-close/explicit-rule 记录完全相同。有用的迟到响应既不能提交新行情，也不能覆盖既存行。没有发送或额外 SDK 调用。
4. 观察真实 SQLAlchemy `engine_disposed`，而非替换 close 回调。顺序为 token-before-cancel、SDK 返回、数据库释放。释放时物理槽位、等待者和 token 数均为零，owned task 已完成。stop 完成后，owned task/token/active deadline 集合为空，没有 recovery scope 仍在执行或安排下一次重试，数据库/lifecycle 为 STOPPED，原 runtime generation 保持不变。没有异常 runner 退出、cleanup failure 或代次替换。

完整行比较有意排除 heartbeat 和请求控制记账；它们合法的排空/清理更新不属于业务写入。Alert/HOLD/attempt 行是不存在的负控，并非预置的历史投递 fixture。45 秒 fixture watchdog、15 秒 worker barrier 和有界观察等待只约束测试，不构成生产时间策略。

## 执行证据

在 `trade-plan-monitor/` 中运行：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_scheduled_stock_recovery_shutdown.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_scheduled_stock_recovery_shutdown.py
git diff --check
```

结果：**1 passed in 7.07s**；Ruff 和 `git diff --check` 通过。执行前观察到的 HEAD 为 `39ab6f4fe9237fb62e3debe8e29e4835feac7676`，执行后撰写报告时观察到 `2518c32152865decafea0a92a197947c5b2e10ea`；共享工作区仍在提交无关改动。本次叠加 S2 作者未提交的最小 wrapper checkpoint。这是源码稳定的候选证据，不声称固定 clean-HEAD，也不代表批准无关的 S2 改动。测试紧邻执行前后的全部七项 SHA256 一致：

| 文件 | SHA256 |
|---|---|
| runtime/production.py | `6BF2CE8DAA3B797896B39EF4A6201DAEDD8DC3E7C33F2A044339527F9C76A7E7` |
| runtime/service.py | `1FBF2D7C6731F46A4104F0C55C1EC1CB89F3C961482E55D9D87FB7C83FAB84C5` |
| runtime/scheduler.py | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| web/monitor_composition.py | `3030F227DE0DA8EF02C69BF04996FCE92AF10546C577B10D955CED51AA339C68` |
| test_s3_scheduled_stock_recovery_shutdown.py | `C60D72167FD81745C354D417AC1816C3138C937E5837E75C5C384596CFBF0542` |
| test_s3_startup_minute_coverage.py | `93E459A2B2D85A975895F4A374CE59F52BA44EF44C0AC4A5CCA16D153B0387EF` |
| test_s3_stock_recovery_identity.py | `9E47CBB6E5F69D5273647F71E1EA90D9096C2230B8B2098DD48CF59C9FA99ED1` |

这是对已实现行为新增的验收覆盖。首次执行即通过；不声称产品 RED，也未人为构造修复前基线。执行前仅修正过一次 Ruff 行长错误。无需生产修复。

## 独立验证

独立 Sol 重跑上文精确单文件 pytest 命令：**1 passed in 7.09s**，无 warning。协调的 S2 检查点窗口内，六个源码及三个测试 hash 在运行前后相同。`production.py` 为 `522560DDFB708A0DA31B6C5321611E96E0D700B5DF7AF9AB6B391ACED27658A7`；作者表中的其余源码及测试项未变。目标 Ruff、静态评审及双语一致性检查通过。评审批准这三个路径本地提交，不意味着 S2 实现批准或固定提交全套结果。作者和独立计数有重叠，不相加。

## 局限

本独立评审通过用例仅补齐真实 scheduler ownership 与既有 recovery-token/lifecycle stop 协议之间缺少的代表性连接。它不重复迟到 provider failure/取消变体、通知发送/receipt 不确定性、进程 kill/restart、storage/cleanup failure、explicit-rule 语义或完整 F1/F2 矩阵；这些保留各自独立证据。后续源码变化需要协调最终复跑；单文件通过不关闭 C1 或整体 S3 门禁。
