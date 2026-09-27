# S3 调度股票恢复的权限围栏

## SRA-01 — 范围与状态

一项接通的 S3-06 测试使用真实应用组合层、调度器、认证 provider wrapper、请求控制器及临时 SQLite。所有 SDK/渠道边界均为离线替身；A07 fixture 禁止 HTTP 客户端请求。本测试片不修改源码、schema、用户数据库或真实通知，不推送、不部署。

基线 HEAD 为 `8d83f79`；四个 F3-C 源文件及加强后的 A07 fixture 是工作候选，不是已提交发布版本。本测试导入 A07，须与该 fixture 一起验收/提交，不能单独宣称为自包含的已提交测试。F3-C 实现及最终集成门禁仍另行处理。独立验证已批准本权限测试/报告片纳入该共同批次。

## SRA-02 — 接通场景及硬断言

部分数据启动后，只释放实际调度器等待。暂停观测到的 `STOCK_RECOVERY` duty 所属物理 `rt_min_daily` SDK 请求。在此前合法行情工作结束后，保存全部已存在分钟/最新报价字段及业务行。SDK worker 仍被阻塞时，仅修改临时 token，并由第二个 worker 执行真实 `configuration_is_current` 文件比较及权限撤销发布。不模拟准入结果或撤销 Event。

释放 SDK，返回包含原先缺失 `09:31` 分钟的有效响应。要求分钟/最新报价零晚到变更，包括 `received_at`；evaluation、ledger、head、risk、pending-close、alert 和 delivery 行均不改变。保留原生命周期、runner 和 owner generation；runner 以 `NEEDS_RESTART` 等待显式停止，无后续 poll/retry，也无新增 SDK/渠道入口。恢复旧配置并将观察时间推进五分钟，仍不能解锁已撤销的 baseline。

这证明请求已进入 SDK 后在提交边界被拒绝，不声称阻止了已开始的请求。第二个 worker 的真实校验调用是受控故障交错，不是新增自动监视器。

## SRA-03 — 观察层校正，不是产品修复

- 首次运行处于尚未接完的 C 窗口，在 SDK 入场前失败（`1 failed, 2.10s`）；不是稳定基线 RED。
- 首个完整候选运行已到达写入/owner 保护，但健康副本的 generation 断言失败（`1 failed, 2.17s`）。`RuntimeHealthSnapshot.runtime_generation` 有意排除序列化，而校验式 `model_copy(update=...)` 会重新生成被排除字段的默认值。因此断言真实生命周期及其直接 health generation，不把复制后的隐藏字段当公开代次契约。未修改 health 实现或第 4 步协议。
- 额外公开状态断言最初错误地预期已有内容的总览（`1 failed, 2.14s`）。首次求值前，既有 union 应为 `UNAVAILABLE / AWAITING_FIRST_EVALUATION`。修正后的断言要求这一准确响应、无当前 symbol health，以及实际 heartbeat frame 的 `runtimeLive=false`、`runtimeGeneration=null`，并非接受任意不可用原因。

## SRA-04 — 作者验证

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_authority.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_stock_recovery_authority.py
```

修正后的专项 **1 项通过，2.03s**。专项及全部 13 项 A07 对照 **14 项通过，13.93s**。Ruff 通过。这些是独立且有重叠的运行，不能相加。组合运行前后下列 hash 未改变：

| 路径 | SHA256 |
| --- | --- |
| `src/trade_plan_monitor/runtime/production.py` | `7A5DE1FE6ADF80587505A3E3156B6CDD6A3C25A93192B2A83046EA2C1806A275` |
| `src/trade_plan_monitor/runtime/scheduler.py` | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| `src/trade_plan_monitor/runtime/service.py` | `1FBF2D7C6731F46A4104F0C55C1EC1CB89F3C961482E55D9D87FB7C83FAB84C5` |
| `src/trade_plan_monitor/web/monitor_composition.py` | `3030F227DE0DA8EF02C69BF04996FCE92AF10546C577B10D955CED51AA339C68` |
| `tests/integration/test_s3_startup_minute_coverage.py` | `93E459A2B2D85A975895F4A374CE59F52BA44EF44C0AC4A5CCA16D153B0387EF` |
| `tests/integration/test_s3_stock_recovery_authority.py` | `73A68A95AB130BDA25D40BA1FDAD6FBF53979C4798BCEF0323A85AB8E9D9D67B` |

## SRA-05 — 独立验证及剩余门禁

Sol 独立验证以下命令 **15 项通过，17.46s**：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_identity.py tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
```

SRA-04 的六个 hash 及 identity 测试的 `961410F55D498DB70CB8BD4CAE4DF2BA2B9D0235DC477355F65BF6802FBA2767` 在运行前后保持不变。两个新测试的 Ruff 通过；双语评审未发现语义差异。评审批准 authority 的 oracle 校正及三个文件随 C/A07 纳入，而非独立提交。本组合运行早于另行要求的 identity 测试补强：不关闭该测试缺少明确维护 owner 断言的问题，也不批准全部 C 源码。

最终冻结的 F3-C 候选已与加强后的 identity 和 delivery 对照一起独立重跑：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_stock_recovery_identity.py tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
```

结果：**159 passed, 1 warning, 52.75s**。四个源码及七个新增/修改测试的 hash 在运行前后均匹配最终冻结值。最终 `production.py` SHA256 为 `38608F351317BBA04E35D169FC471B0F9707884E83C61E816544073143E968F7`；本 authority 测试及另三个源码的 hash 仍与 SRA-04 一致。加强后的 identity 测试为 `9E47CBB6E5F69D5273647F71E1EA90D9096C2230B8B2098DD48CF59C9FA99ED1`。全项目 `ruff check .` 和 `git diff --check` 通过，源码/测试未报告剩余 P1/P2 问题。这些重叠运行不能相加。

这关闭了本接通对照所要求的最终候选重跑，不关闭 C1 统一权限派发、C3 整体或固定已提交版本的全套验收。最终双语报告评审已通过，批准 21 个受审路径共同本地提交。
