# S3 股票恢复调度身份验证证据

## 状态与范围

这是 S3-06/A09 的 TEST-ONLY 连接验收。加强后的最终测试已在协调的源码稳定窗口以及下述最终独立组合运行中通过。本报告不批准整个 F3-C，也不关闭 S3-06、C1 或总体集成门禁。

独占文件：`tests/integration/test_s3_stock_recovery_identity.py` 及本双语报告。本片未修改生产源码或既有测试。未提交、推送、部署，也未使用真实服务、真实行情源、真实通知或用户数据库。

本测试明确依赖尚未提交的 A07 `test_s3_startup_minute_coverage.py` 中 `_Run`、`_CoverageSDK` 及由真实调度器控制的时钟。A07 与 C 必须同批验收，本文件不能独立提交。同时复用已提交的 live-pipeline fixture helper。SQL repository、请求控制、恢复、生命周期调度、评估和发送准入均为真实实现。仅远端 SDK 与通知 transport 使用离线 fake；fixture 禁止 HTTP。

## SRI-01 — 过期物理响应、健康兄弟与新恢复

测试：`test_scheduled_stock_recovery_reactivation_rejects_old_facts_and_resumes`。

1. 10:00:15，两个活跃 legacy 计划使用同一个真实 composition。首个计划缺少 09:31；启动恰好进行一次股票获取。兄弟计划可在自己的真实调度轮次获得完整事实。
2. 释放实际调度 sleep，直到首个计划进入一次受调度的 `rt_min_daily` 物理调用。fake SDK worker 固定完整响应并等待。在该暂停边界，硬断言 lifecycle 实际 deadline kind 为 `STOCK_RECOVERY`、当前 task 尚未完成且属于 `runtime._work_tasks`、`stock-prefix:003043.SZ` 的 `snapshot.in_progress=True`。透明 observer 原样转发原 deadline 和结果，不替换 scheduler、不选择 deadline，也不直接调用业务工作。这样可避免带有围栏的旧 gap-repair 旁路误满足本测试。另一个真实 SQLite connection 在**当前时钟**停用并重新激活同一计划，保持 plan version/hash，activation revision 从 1 变成 3。不得将时钟倒退到先前激活时点。
3. 释放过期 SDK 响应。硬断言首个计划完整 minute 与 latest_quote 行（含 received_at）以及全部已快照业务表完全不变。缺失的 09:31 不得接纳。不得伪造或重标旧 evaluation、risk update/audit、decision head、alert/HOLD 或 delivery attempt。
4. 保持该首分钟不可用，继续释放真实 wake。健康兄弟在 10:05:12 产生真实的 10:05 结果，activation revision 为 1；首个计划仍没有决策或通知意图。
5. 在离线 SDK 边界恢复历史供应。后续真实维护获取修复前缀，不重写先前已提交 minute 行，也不执行评估。仅下一合法市场 duty 在 10:10:12 为首个计划产生唯一结果，target 为 10:10，通过 decision head 关联 activation revision 3。验证 result/ledger/head hash、formula、source time、实际 evaluation time、完整前缀和 0..90 秒年龄。兄弟先前结果保持不变；不得为首个计划回放 10:05。

每次已释放 wake 和每个物理等待边界均硬断言原 runtime_generation、RUNNING 状态及无 RUNTIME_RUNNER_FAILED。未替换 evaluator/recovery，也未直接执行 deadline。45 秒 watchdog、8 秒 worker barrier 和 64 次 wake 上限只约束测试，不是生产时间策略。

## 执行证据

在 `trade-plan-monitor/` 中运行：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_identity.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_stock_recovery_identity.py
```

初版结果：**1 passed in 4.54s**，基于 HEAD `8d83f7913fb9bb295313322580205f5a0d9739d6` 加 C 作者未提交源码。以下四个源码 SHA256 在本轮执行前后完全一致：

| 源码 | SHA256 |
|---|---|
| runtime/production.py | `2EEDEBFFD778BBF6B7CA9FBC0CE346489316A9B26D42A39AC352FAC4A7516076` |
| runtime/service.py | `1FBF2D7C6731F46A4104F0C55C1EC1CB89F3C961482E55D9D87FB7C83FAB84C5` |
| runtime/scheduler.py | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| web/monitor_composition.py | `3030F227DE0DA8EF02C69BF04996FCE92AF10546C577B10D955CED51AA339C68` |

独立审查前加强的测试已在源码作者协调的窗口通过：**1 passed in 4.57s**；Ruff 通过。HEAD 仍为 `8d83f7913fb9bb295313322580205f5a0d9739d6`。此时 `runtime/production.py` 为 `7A5DE1FE6ADF80587505A3E3156B6CDD6A3C25A93192B2A83046EA2C1806A275`；另外三个源码 hash 与上表一致。该轮运行前后，四个源码 hash 以及以下两个测试 hash 均完全一致：

- 身份测试：`961410F55D498DB70CB8BD4CAE4DF2BA2B9D0235DC477355F65BF6802FBA2767`。
- A07 fixture 依赖：`93E459A2B2D85A975895F4A374CE59F52BA44EF44C0AC4A5CCA16D153B0387EF`。

根据独立审查意见，增加了上述明确的 deadline/task/scope 所有权断言。C 作者修正 date-skip 后，最终测试在另一个协调窗口通过：**1 passed in 4.88s**；Ruff 通过。HEAD 未改变。此时 `runtime/production.py` 为 `9A8095BF2C0D1C59BCC1FF1903B3554A35EC15552764AA3383B3E303429894A8`；另外三个源码 hash 及 A07 hash 与上文一致。最终身份测试 hash 为 `9E47CBB6E5F69D5273647F71E1EA90D9096C2230B8B2098DD48CF59C9FA99ED1`。该作者运行前后六个 hash 均完全一致。

以上是分别执行、相互重叠的开发运行，不是独立用例。本新增连接测试没有独立执行的 baseline RED：首次运行之前 C 接线已经落地。未通过动态替换 HEAD 模块制造 RED。C 另行记录的真实 wiring/A07 RED 不属于本测试的 RED。

### SRI-02 — 最终独立组合验证

独立 Sol 审查者在 `trade-plan-monitor/` 中，针对最终冻结候选执行了以下准确命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_stock_recovery_identity.py tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
.venv/Scripts/python.exe -m ruff check .
git diff --check
```

结果：**159 passed, 1 warning in 52.75s**。两项质量检查均通过。该组合运行包含未再改变的最终身份测试及其 SDK 暂停处三重所有权断言：实际 `STOCK_RECOVERY` deadline、尚未完成且属于 lifecycle 的 task、该 symbol 正在执行的 stable scope。

HEAD 仍为 `8d83f7913fb9bb295313322580205f5a0d9739d6` 加冻结候选。审查者确认四个源码文件及被监测测试文件的 before/after hash 一致。`runtime/production.py` 为 `38608F351317BBA04E35D169FC471B0F9707884E83C61E816544073143E968F7`；scheduler、service 和 composition 与上表一致。身份测试仍为 `9E47CBB6E5F69D5273647F71E1EA90D9096C2230B8B2098DD48CF59C9FA99ED1`，A07 仍为 `93E459A2B2D85A975895F4A374CE59F52BA44EF44C0AC4A5CCA16D153B0387EF`。

这 159 个用例与先前作者/审查者运行存在重叠，不得相加计数。这是最终候选证据，不是 clean-HEAD 或全套测试证据，也不关闭 C1 或总体集成门禁。

## 局限

本单一场景覆盖 legacy prefix 语义、同计划激活替换、一个健康兄弟及进程内调度恢复。不重复整个 F1/F2 故障矩阵、explicit-rule 语义、worker 来源撤销、进程 kill/restart 或正向通知发送。本例中的 alert/HOLD/attempt 是不存在的负控，不是预存历史通知 fixture。候选结果不是 clean-HEAD 集成证据；后续源码改变后仍需最终协调复跑。
