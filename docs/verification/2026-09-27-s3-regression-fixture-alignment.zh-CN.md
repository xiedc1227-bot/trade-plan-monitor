# S3 回归测试前提对齐

> 规范英文版为 `2026-09-27-s3-regression-fixture-alignment.md`；本文为语义等价的中文审阅版。

## SFA-01 范围与基线

状态：**test-only alignment implemented / targeted verification passed / independent code review passed / six-file local commit authorized**，即仅测试前提对齐已实现、专项验证通过、独立代码评审通过、六文件本地提交已获授权。

源码 `453cc0c` 的整体 offline 检查点由文档提交 `e9c6ac5` 记录于[回归报告](2026-09-27-s3-offline-regression.zh-CN.md)，结果为 **18 failed, 4778 passed, 1 skipped, 4 deselected, 1 warning**。本片将受影响的四个测试文件对齐到既有受支持的生产契约，不改变生产行为，也不豁免该整体失败。

作者在编辑前复现了全部 18 个失败。运行基于 `3c22bff` 的共享工作区，期间存在另一 writer 的 SDK 边界源码改动，因此这些不是隔离、干净、已提交版本的结果。作者仅修改下列四个文件及这份配对报告。本片未编辑 `production.py`、provider、controller、共享 fixture、脚本或另片 startup-minute-coverage 测试。

全部运行仅使用 temporary SQLite、fake SDK/HTTP 和可控时钟。未使用真实服务、真实通知通道、用户数据库、推送或部署。未添加 skip/xfail，未放宽生产安全条件。

## SFA-02 改动与保留的断言

| 文件 | 测试前提对齐 | 保留的行为 |
| --- | --- | --- |
| `tests/integration/test_position_production_composition.py` | 将 composition 的 `SystemClock.now()` 固定为 `_FIXED_NOW`，并提供可取消 sleep。在 schema upgrade 后、任何 active plan 前，调用真实 `RuntimeLivenessRepository.initialize_empty(_FIXED_NOW)`。断言原样例保持 Schema 1、MANUAL、`max_qty=200`。 | 原三个失败测试保留日历权威、幂等新增/关闭重放、最大数量、缺失 active plan、T+1、剩余数量、过期 revision 和恢复 audit 断言。不强改 health 或绕过认证。 |
| `tests/integration/test_r13_channel_acceptance.py` | 注入真实 `CurrentDeliveryAdmission`，使用相同 sessions 和 `pipeline.evaluations._runtime_generation`；共享 pipeline fixture 不变。 | 保留原 DELIVERED、event identity、result hash、quantity 及 console/webhook envelope 断言。再次 dispatch 不产生重复 attempt。不要求所有投递 receipt 都变成 ELIGIBLE：actionable 投递逐次核验。 |
| `tests/unit/test_r14_bounded_acceptance.py` | 在其他字段已获准的 fake AI payload 中补入必需的 `temperature: 0`。 | fake HTTP 503 仍恰好消耗一次物理 attempt，预算耗尽/未获准模型的拒绝仍有效。真实 harness guard 不变。 |
| `tests/unit/test_r17_failure_diagnostics.py` | 为两个 fake Pipeline 补齐非 None 的 `_stock_semantics` 及返回 `()` 的 `recovery_issues()`。 | 保留全部八项请求错误分类/retry/恢复用例和三项不可信异常脱敏用例，包括 SECRET 不泄露断言。 |

与四文件原版本的 AST 比较确认保留全部 **157 条原 assert**：position 52、R13 21、R14 51、R17 33。全部 **29 个原测试函数**均保留，参数化后的基线为 46 项。没有为使 fixture 通过而删除或修改断言。结构检查是实际测试证据的补充，不能替代行为验证。

## SFA-03 负对照

| ID | 观察到的保护 |
| --- | --- |
| SFA-N01 | 省略 liveness 初始化：health 保持 `BLOCKED` 和 `LEGACY_PLANS_REQUIRE_REVIEW`，GET health 返回 200，持仓 POST 返回 409，liveness 仍缺失，完整 position/idempotency/audit 行快照均不变。 |
| SFA-N02 | 投递前，每个 BUY/SELL/RISK_ALERT fixture 都恰有一条持久 event 和一条 explicit evaluation ledger，receipt 为 `HOLD / RECOVERY_REQUIRED`。旧的无 admission dispatcher 零 attempt；真实 admission 随后仅投递一次，再次 dispatch 为空且持久 attempt 数仍为一。 |
| SFA-N03 | 生成同样三类 alert 后、dispatch 前删除持久 `PositionInventoryConfirmation`。真实 admission 保持 receipt 为 HOLD 且零 attempt；原 event 和 evaluation ledger 均各保留一条。 |
| SFA-N04 | 缺失和非零 temperature 均在内层 MockTransport 前被拒绝；已发送请求数和 `totalAttempts` 均为零。 |
| SFA-N05 | `_stock_semantics=None` 时，参考数据刷新不进入 fake Pipeline，不产生 stage error、retry deadline 或 failure callback。 |

最终测试新增七个参数化用例：一个缺 liveness、三个库存确认撤销、两个 temperature、一个缺 STOCK binding。无 admission 和重复投递检查强化原有 R13 用例。这些负对照基于既有安全行为通过，不声称它们是新的生产 RED→GREEN 修复。

## SFA-04 已执行验证

作者在 fixture 修改前后运行了同一个四文件命令：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/integration/test_position_production_composition.py tests/integration/test_r13_channel_acceptance.py tests/unit/test_r14_bounded_acceptance.py tests/unit/test_r17_failure_diagnostics.py --tb=short
```

| 阶段 | 实际结果 |
| --- | --- |
| 初始复现 | **18 failed, 28 passed, 1 warning**，14.51 秒，退出码 1。失败分布：position 3、R13 3、R14 1、R17 11。 |
| 初次前提对齐及首批负控 | **49 passed, 1 warning**，14.38 秒，退出码 0。 |
| 包含全部负控的最终四文件运行 | **53 passed, 1 warning**，22.47 秒，退出码 0。 |

相邻验证命令：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/integration/test_runtime_liveness.py tests/integration/test_runtime_plan_expiry.py tests/integration/test_position_lot_recovery_audit.py tests/integration/test_delivery_admission.py tests/integration/test_recovery_alert_eligibility.py tests/integration/test_notification_delivery.py tests/integration/test_explicit_runtime_production.py tests/integration/test_r14_offline_wiring.py tests/unit/test_r17_bounded_acceptance.py --tb=short
```

相邻结果：**172 passed, 1 warning**，89.71 秒，退出码 0。

```powershell
.venv/Scripts/python.exe -m ruff check tests/integration/test_position_production_composition.py tests/integration/test_r13_channel_acceptance.py tests/unit/test_r14_bounded_acceptance.py tests/unit/test_r17_failure_diagnostics.py
git diff --check
```

修正已编辑 R13 文件的一处 import 顺序问题后，Ruff 和 diff 空白检查通过。pytest warning 是已有的 Starlette/httpx TestClient 弃用提示。不同阶段或重叠运行的数量不能相加。

主协调另行报告 Astra 只读进程内可行性验证中，46 个原用例通过，并报告额外负控观察。这些支持诊断，但不是上表作者的实际执行结果，也不能替代对本次落盘改动的正式评审。

主协调随后转述独立 Sol/xhigh 最终批准：四个测试文件及配对报告无 P1/P2。reviewer 独立运行四文件测试：**53 passed, 1 warning**，22.42 秒。另一项同进程 clock fixture 方法 identity 恢复检查为 **1 项通过**。reviewer 的 Ruff 和 diff 检查通过，四个受评文件的 hash 在评审期间保持稳定。reviewer 确认原有 **157 条 assert / 29 个测试函数**全部保留，最终文件包含 **193 条 assert / 33 个测试函数 / 53 个用例**。这些独立观察与作者运行分开记录，不能相加。评审使用 HEAD `3c22bff`，存在另一 writer 的未提交源码改动，不能称为干净版本的完整测试通过。

## SFA-05 剩余门槛

独立代码评审已通过，主协调已授权仅将四个测试文件与两份报告合计六文件本地提交。最终集成版本仍须重新运行整体 offline 检查；此前失败的整体检查点不能因这些专项结果而改记通过。

另片 startup-minute-coverage RED 用例、SDK 边界修复、minute-owner 实现、统一 scheduler 及更广的 S3-09/C1/C3/业务第三步验收均不在本次测试前提对齐范围内，不声称这些门槛已完成。
