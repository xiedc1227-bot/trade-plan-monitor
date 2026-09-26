# S3 协调基线回归

## 范围与状态

2026-09-27，协调会话在 DAILY_BARS 准备层提交 `233f969abf14435048fee8b9830361b888b34506` 后，复跑了既有 S3-04–S3-08 测试组。共享工作区中另一路股票分钟实现仍在进行。这些仅为基线结果，不是最终集成版本证据，也不代表缺失场景已验收。

仅运行使用临时状态和假边界的离线测试。未使用真实行情供应商、通知服务或用户数据库，未推送或部署。本报告不改变契约或任务勾选状态。

## 实际执行结果

| 分组 | 结果 | 耗时 | 含义 |
| --- | --- | --- | --- |
| S3-04 既有时段/恢复用例 | 147 passed | 21.12s | 既有测试通过；不证明强制结束后的恢复义务重建。 |
| S3-05/S3-06 既有隔离与身份用例 | 81 passed, 1 warning | 52.01s | 仅为既有隔离与激活围栏基线。 |
| S3-07/S3-08 既有生命周期、发送与本地读取用例 | 140 passed, 1 warning | 10.50s | 仅为既有排空/发送/读取基线；不是完整 C3 验收。 |

三次不重叠执行合计 **368 项测试通过**。两条警告均为既有 Starlette/httpx 弃用警告。未通过跳过或弱化测试获得这些结果。

从 `trade-plan-monitor/` 实际执行的命令：

```powershell
.venv/Scripts/python -m pytest tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_runtime_recovery_coverage.py tests/integration/test_missed_close_execution.py -m 'not live' -q --tb=short
.venv/Scripts/python -m pytest tests/integration/test_production_a06_matrix.py tests/integration/test_production_a06_process_scheduler.py tests/integration/test_market_index_runtime.py tests/integration/test_recovery_activation_fences.py tests/integration/test_production_certification_gate.py -m 'not live' -q --tb=short
.venv/Scripts/python -m pytest tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py tests/integration/test_notification_delivery.py tests/integration/test_delivery_admission.py tests/integration/test_persistent_monitor_read_service.py -m 'not live' -q --tb=short
```

## 剩余门槛

C1 仍待 DAILY_BARS 物理请求接线、股票分钟证明与集成、统一维护调度及完整跨进程验收。S3-04–S3-09 仍未完成。尤其是物理请求跨行情截止时间后进程被强制结束，仍需明确的重启义务恢复证据；存活心跳或 31.25 秒准入保护本身不足以证明安全。该缺失场景正在独立检查，并未宣称通过。在宣称 C1/C3 或第三步完成前，必须针对最终集成版本重跑规定门槛。
