# 业务第三步：最终离线生命周期门禁

## 状态与固定范围

**全量回归 PASSED；独立源码/矩阵评审已批准业务第三步及 C1/C3 限定范围完成。最终四份文档一致性核验 PASSED。** 被测源码/测试 HEAD：`e35f3442b874d0766229b5a511fba38e89b02fed`。协调者在收集前冻结源码和测试；这四份文档在运行期间并行起草。HEAD 保持不变，运行后源码/测试差异为空。

目标验收仅为业务第三步离线生命周期集成及 C1/C3。专项整体保持 **IN PROGRESS**；第一步保留限定历史恢复验收。C2、旧 RR004/RR006/RR014 勾选项、第四步 UI/协议及 C4、第五步完整发布验收及 C5 不随本门禁自动关闭。保留 S3-09 的重型回测排除；这不是提案第 7 节全部发布门禁。

仅使用临时 SQLite、假 SDK/transport/channel 边界和受控时钟。不包含真实行情源、真实外部通知、真实用户数据库、推送或部署。配置变更须安全停止 → 人工编辑 → 启动新进程，不做 hot reload。120 小时规则使用合法所有者持久 `last_alive_at`，不使用行情年龄。串行重启证据不证明 OS 级多实例锁；不确定发送不证明外部恰好一次投递。

## S3 证据与故障矩阵

链接报告保留原候选身份、结果和限制。本表将其证据映射到最终组合门禁；历史限定范围通过不单独等于最终门禁通过。

| 门禁 | 已覆盖边界与保留要求 | 证据 |
| --- | --- | --- |
| S3-01 / A04 | 连续四次瞬态失败保留 owner/generation、本地读取及 30/60/120/300 秒下限；恢复不耗尽崩溃监督预算。 | [已安装重试时序](2026-09-24-a04-installed-retry-timeline.zh-CN.md)、[降级读取](2026-09-27-s3-degraded-read-health.zh-CN.md) |
| S3-02 / A05 | 保守继承旧 `INDEX_MINUTES`，分别阻断 `idx_mins` 和 `rt_idx_min_daily`；每项 proof 仅清除自身 scope。持久 300 秒预约、共享 429 及 1.25 秒节流跨顺序进程保留，R17 包含精确到期相等。 | [Scope 迁移](2026-09-24-a05-index-permission-scope-migration.zh-CN.md)、[行情源证据](2026-09-25-c1-provider-recovery-evidence.zh-CN.md)、[R17](2026-09-27-s3-permission-reservation-process.zh-CN.md) |
| S3-03 / C1 | 共用有界权限选择覆盖八个 scope、RUNNING 调度及 DEGRADED 维护。Startup 和 permission 时钟独立；权限 proof 不能开放业务准入。 | [共用 dispatcher](2026-09-27-c1-unified-permission-dispatch.zh-CN.md)、[RUNNING](2026-09-27-c1-permission-running.zh-CN.md)、[DEGRADED](2026-09-27-c1-permission-degraded.zh-CN.md) |
| S3-04 / A03/A07/A10 | 空/部分分钟不证明就绪；同代次修复有界。会话/跨 deadline 行为和四项漏收盘 kill/restart 用例在其被测范围内保留义务。完整无限制历史恢复另行验收。 | [启动覆盖](2026-09-27-s3-startup-minute-coverage.zh-CN.md)、[有界恢复](2026-09-27-s3-stock-recovery-wiring.zh-CN.md)、[漏收盘](2026-09-27-s3-missed-close-kill-restart.zh-CN.md)、[调度夹具](2026-09-27-s3-scheduler-fixtures.zh-CN.md) |
| S3-05 / A06 | 畸形股票/指数依赖仅隔离受影响计划；健康计划族继续推进。实际顺序进程指数恢复保留下限，纯指数 unit 内不执行股票工作或业务发送。 | [指数进程](2026-09-27-s3-index-retry-process.zh-CN.md)、[A06 夹具证据](2026-09-27-s3-regression-fixtures.zh-CN.md)、[调度夹具](2026-09-27-s3-scheduler-fixtures.zh-CN.md) |
| S3-06 / A09 | F1 精确身份、F2 冻结 capture-to-commit 围栏及 F3 同代次有界修复拒绝旧 authority。配置漂移要求显式停止和新进程；仅元数据刷新无害。 | [身份](2026-09-27-s3-stock-recovery-identity.zh-CN.md)、[冻结启动](2026-09-27-s3-frozen-startup-minute-recovery.zh-CN.md)、[恢复接线](2026-09-27-s3-stock-recovery-wiring.zh-CN.md)、[DEGRADED 漂移](2026-09-27-c1-permission-degraded.zh-CN.md) |
| S3-07 / A08/D5 | 四个通知提交/发送 kill 窗口各使用四个顺序进程。实际股票维护及 RUNNING/DEGRADED 权限工作在 SDK 挂起时停止；取消后不能接受迟到 proof，物理工作在数据库释放前排空。外部回执丢失可能重复效果。 | [通知 kill](2026-09-27-s3-notification-kill-restart.zh-CN.md)、[股票停止](2026-09-27-s3-scheduled-stock-recovery-shutdown.zh-CN.md)、[权限停止](2026-09-27-s3-scheduled-permission-shutdown.zh-CN.md) |
| S3-08 / A11 | 已安装午休待机不同于进展逾期。持久心跳不能让停滞业务变健康；权限/事实修复本身不能让决策可操作。这是后端证据，不是完整页面/协议验收。 | [已安装存活](2026-09-27-s3-installed-runtime-read-liveness.zh-CN.md)、[降级读取](2026-09-27-s3-degraded-read-health.zh-CN.md)、[股票投递/读取边界](2026-09-27-s3-stock-recovery-delivery.zh-CN.md)、[DEGRADED](2026-09-27-c1-permission-degraded.zh-CN.md) |
| S3-09 / C3 | 汇总生命周期、迁移/回滚、stop/drain 及提交/崩溃/发送证据，须通过固定 HEAD 回归及最终独立集成评审。 | 下方结果与评审；[任务顺序](../../tasks/runtime-recovery-todo.zh-CN.md) |

已完成汇总中的迁移/备份覆盖可追溯到 [scope 迁移测试](../../tests/integration/test_index_permission_scope_migration.py)（子进程中断回滚拆分；保留新 scope 状态时拒绝降级）、[恢复存储测试](../../tests/integration/test_runtime_recovery_storage.py)（待完成状态拒绝降级及空状态降级路径），以及 [SQLite 备份测试](../../tests/integration/test_sqlite_backup.py)（在线备份包含未 checkpoint 的 WAL 写入，并恢复成可读取的临时数据库）。相关 120 小时/liveness/expiry 证据：[runtime liveness 测试](../../tests/integration/test_runtime_liveness.py)和[计划过期测试](../../tests/integration/test_runtime_plan_expiry.py)。这是既有离线测试清单，不是新备份操作。

## 已完成切片与历史失败

`53b731271b4b3a10a8558da993ecd000f03c1d58` 完成 UPD-S5：固定 30/60/120/300 秒 startup 时序、独立八 scope 维护、仅相关 startup operation/共享冷却可延后下限、保留 pipeline/owner，以及 source drift 后等待显式 stop。最终作者专项：**82 passed, 1 warning in 16.64s**；独立专项：**82 passed, 1 warning in 16.52s**（29 DEGRADED + 51 lifecycle + 2 scheduled permission-stop 用例）。独立的相邻窗口记录在 [DEGRADED 报告](2026-09-27-c1-permission-degraded.zh-CN.md)，不与此计数相加。

早期 `453cc0c` 汇总保留为 **18 failed, 4778 passed, 1 skipped, 4 deselected, 1 warning in 670.06s**，见[历史回归报告](2026-09-27-s3-offline-regression.zh-CN.md)。之后在 `53b731271b4b3a10a8558da993ecd000f03c1d58` 使用下方全量命令的结果保留为 **16 failed, 5695 passed, 1 skipped, 4 deselected, 1 warning in 1087.48s**。两次结果均不改写为通过。

这 16 项失败来自已批准的有界 startup、共用权限排序及新增 maintenance wake 后过时的测试前提。两组经独立评审的仅测试校正保留生产源码，实际运行原后段业务断言，未删除测试、新增 skip/xfail 或降低业务检查：

- `2dc2919a1fe8b2f38b1dce9843ad16b70e80eab2`：三个调度夹具文件；作者 **24 passed, 1 warning in 30.91s**，独立 **24 passed, 1 warning in 31.21s**。[证据](2026-09-27-s3-scheduler-fixtures.zh-CN.md)。
- `e35f3442b874d0766229b5a511fba38e89b02fed`：五个回归夹具文件；作者 **41 passed, 1 warning in 95.00s**，独立 **41 passed, 1 warning in 94.92s**。[证据](2026-09-27-s3-regression-fixtures.zh-CN.md)。

两组覆盖 65 个不同用例；重复的作者/评审窗口和全量计数不相加。

## 固定 HEAD 门禁结果

```text
.venv/Scripts/python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short
.venv/Scripts/python.exe -m ruff check src tests scripts
git diff --check
```

| 门禁 | 实际观察 |
| --- | --- |
| `e35f3442b874d0766229b5a511fba38e89b02fed` 收集 | 5712/5716 tests collected, 4 deselected, 2.12s |
| 完整 S3-09 回归 | **5711 passed, 1 skipped, 4 deselected, 1 warning in 1074.18s (17:54)**；exit code 0 |
| Ruff `src tests scripts` | 全量运行前后均通过 |
| Diff 空白检查 | 全量运行前后均通过；最终文档检查已通过 |
| 源码/测试稳定性 | 运行后 `git diff --name-only -- src tests` 无路径；HEAD 不变；工作区变更仅限四份文档路径 |
| 最终独立集成评审及双语一致性 | Astra 已批准源码/矩阵及第三步/C1/C3 限定关闭，无 P1/P2；最终四份文档一致性 **PASSED** |

四项 deselection 为 live 测试。单项 Windows/POSIX 语义 skip 是 `test_backtest_production_composition::test_cursor_key_rejects_foreign_posix_owner_before_use`。重型 `tests/integration/test_backtest_acceptance.py` 排除来自 S3-09。warning 为既有 Starlette/httpx 弃用警告；本门禁不修改依赖。

## 评审与完成边界

有界实现使用 `gpt-6-sol` / `high`；迁移计划条件评审使用 `gpt-6-sol` / `xhigh`。最终集成评审使用 `gpt-6-astra` / `xhigh`；既定文档使用 `gpt-6-sol` / `medium`。Astra 评估固定 HEAD 全量通过、前后检查、经独立评审的 65 用例夹具校正及证据矩阵后，已批准源码/矩阵关闭：已批准第三步内无 P1/P2 或额外未达门槛。此前已通过稿一致性评审已通过；最终四份文档一致性为 **PASSED**。仅协调者在评审后记录最终本地文档提交，其身份须与上方被测源码/测试 HEAD 区分。

业务第三步及 C1/C3 仅在本次批准的离线生命周期范围内完成。本报告不认证真实服务权限、OS 级多实例锁、全部历史故障场景、第四步或第五步。专项保持 IN PROGRESS。
