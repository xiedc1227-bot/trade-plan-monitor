# S3 进程冷却 fixture 对齐

## 状态与范围

本片以 TEST-ONLY 恢复既有受控进程 429 回归门槛。作者及独立运行均已通过；三个路径获最终独立批准，无 P1/P2。拥有的改动仅限 `tests/integration/test_provider_cooldown_process_restart.py` 的局部时钟 fixture 及本双语报告。本片未修改生产源码、controller、checkpoint 策略、provider 行为或其他测试。未提交、推送、部署，未使用真实服务、外部通知或用户数据库。

## PCF-01 — 诊断与未变的验收要求

原文件的 `change_token=False/True` 两例均失败：第一个 spawn 进程在有界观察结束时仍为 `cooldown_until is None`，以代码 1 退出，尚未进入第二个进程。fixture 只释放一次 scheduler sleep。F3 新增真实股票维护唤醒并先于首个行情 duty 后，该序号不再证明 `rt_min` 已运行。这属于 fixture 前提失配，不是持久化 429 恢复失败或新修复产品缺陷的证据。

编辑前，独立 Sol 审查批准了如下有界、仅 fixture 修正：

- 仅第一个 `induce_limit` child 替换其时钟 sleep 适配器。它释放真实 scheduler 选出的、截至固定 `10:01:12` 的 deadline，最多八次唤醒；后续等待停驻且不推进时间。不直接调用 deadline 或 provider。
- 硬断言要求 `10:01:12` 确已释放、时钟仍精确停在那里、恰好发生一次 `rt_min` 调用，且共享冷却等于该目标加 300 秒（`10:06:12`）。
- 第二个 child 继续保持零 sleep 放行。它在 `10:02:15` 启动，必须为 DEGRADED，精确恢复第一个进程的冷却时间，并且 SDK 调用为零。真实 `spawn`、旧进程成功停止/退出后才新启动、临时 SQLite、相同 token 和手工更换 token 两参数，以及全部原最终断言均保留。同 endpoint 保留其 recovery identity；这不是热重载。

## 执行证据

在 `trade-plan-monitor/` 中运行：

```powershell
# 原 fixture，编辑前
.venv/Scripts/python.exe -m pytest tests/integration/test_provider_cooldown_process_restart.py -q --tb=short
# 修正 fixture 及相邻进程内 429 重启回归
.venv/Scripts/python.exe -m pytest tests/integration/test_provider_cooldown_process_restart.py tests/integration/test_production_certification_gate.py::test_production_429_cooldown_restores_before_provider_work_after_restart -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_provider_cooldown_process_restart.py
git diff --check -- tests/integration/test_provider_cooldown_process_restart.py
```

原结果：**2 failed in 12.09s**。修正后加相邻用例结果：**3 passed in 9.58s**，无 warning。Ruff 与定向 diff 检查通过。两次运行观察到的 HEAD 均为 `8d61a8e35173ca4c8250737d2b6a6eabfdf79810`，叠加 S2 作者未提交的源码 checkpoint。每次均在各自协调的源码稳定窗口内执行。源码在两次运行**之间**变化，因此这不是同源受控 RED/GREEN 对照、不是 clean-HEAD 汇总证据，也不批准 S2。本片没有生产修复。

下列 SHA256 在各自运行紧邻前后相同：

| 文件 | 原窗口 | 修正后 + 相邻窗口 |
|---|---|---|
| runtime/production.py | `522560DDFB708A0DA31B6C5321611E96E0D700B5DF7AF9AB6B391ACED27658A7` | `A7D112694000DDF4DB5BF35170B32BDC4F056D18A991B69BDC272AEAE3CC5938` |
| runtime/service.py | `1FBF2D7C6731F46A4104F0C55C1EC1CB89F3C961482E55D9D87FB7C83FAB84C5` | 相同 |
| runtime/scheduler.py | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` | 相同 |
| web/monitor_composition.py | `3030F227DE0DA8EF02C69BF04996FCE92AF10546C577B10D955CED51AA339C68` | 相同 |
| test_provider_cooldown_process_restart.py | `0A7FC3E231C74B914019D0C71F6ECADCB8CC75EE55D9EE11EC9A49F932768EDD` | `7C9CDE144190D8506D86C060E69E7473A4C26117E938F647487F479F196EF5B1` |
| test_production_certification_gate.py | 本窗口未记录指纹 | `D79C4E4C90F241374D3338297A900C91CA7AECA0ECE245043085DC40D267C010` |

## 独立验证

独立 Sol 重跑上文精确的修正后加相邻命令：**3 passed in 10.34s**，无 warning。协调运行前后六个源码及两个测试 hash 完全一致。Production 和 process-test hash 与修正后的作者窗口相同；相邻 certification 文件现为 `D8C3A617242B46A294CC322649A8BB258243B082D1D0DF30825E5A02087160AE`。上文作者历史 hash 保留，不被覆盖。目标 Ruff、diff 检查、静态评审及双语一致性均通过，三个路径获批准本地提交；不批准 S2，也不替代固定提交全套门禁。

## 局限

本片恢复原有真实进程 shared-429 到期前负控，并增加精确行情时间前提。它**不**证明 UPD-R17 权限预约在精确 300 秒等值处的准入、八 scope 自动维护、UPD-R18 RUNNING/DEGRADED 推进、并发进程 ownership、真实权限或完整 S3/C1 门禁。这些仍归 unified dispatcher 作者及最终固定版本集成审查。历史与相邻用例数量不能相加。
