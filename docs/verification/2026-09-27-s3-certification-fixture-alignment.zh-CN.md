# S3 认证测试 fixture 对齐

## CFA-01 — 范围及已评审诊断

F3-C `a1f217b` 之后、S2 owner 工作期间的纯测试跟进。拥有三个路径：`tests/integration/test_production_certification_gate.py` 及本双语报告。仅修改四个既有用例、一个局部时钟 helper 和一个异常导入。不涉及生产代码、阈值、公开 API、真实服务、用户数据库、推送或部署。

原三用例运行产生 **3 failed, 41 deselected in 10.32s**。两项失败来自固定 sleep 次数假设：新增股票维护在预期实时请求前消耗了可用唤醒，因而第二次请求或首次 429 尚未发生。相邻五分钟退避负控虽然通过，同样没有到达第二个行情职责。Astra 只读分类这些前提，Sol 在编辑前批准限定对齐。

第三项失败发生于已获许可的决策提交、worker 撤销配置权限之后，直接调用的内部 `state.run_deadline`。F3-C 随后的需求同步正确以 `RecoveryAdmissionChangedError` 拒绝已撤销 owner。真实生命周期已仅在需要配置重启时接住故障、标记 `NEEDS_RESTART` 并等待显式停止，否则继续传播。无需新增生产 catch 或放宽权限。独立评审批准此直接调用测试要求精确 typed 退出，不宽泛接受异常，也不宣称本测试执行了完整 runner 路径。

## CFA-02 — 保留的验收门槛

局部时钟 helper 最多放行八次真实调度等待：传输恢复/退避截至 `10:02:12`，429 截至 `10:01:12`。记录每个真实 due，仅推进到该 due，截止后继续等待且不推进。前两个测试要求进入截止点之后的下一次等待，证明目标职责已经返回，而非仅进入 `sleep_calls`。

- 恢复仍须至少两次物理 `rt_min`、同 runtime/controller 且 RUNNING，停止后 controller 正常关闭。
- 五分钟退避负控现证明下一个行情职责完成时物理调用仍恰好一次，不允许下一分钟绕过。
- 429 对照仍须从受控观测时刻起精确 300 秒、持久 repository 绑定、真实干净停止/重开、冷却恢复，以及即使 token 更新也在下限前零供应商调用。
- final-permit 对照仅在该一次内部调用外捕获 `RecoveryAdmissionChangedError`。真实 worker 撤销、恰好一条合法已提交结果、`NEEDS_RESTART` 及关闭的决策准入均保持必需。

未删除、跳过或削弱测试、原业务断言或重试阈值。真实同代次调度撤销路径仍由已提交 authority 测试另行覆盖。

## CFA-03 — 验证

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_certification_gate.py -k 'resumes_after_one_runtime_transport_failure or next_minute_cannot_bypass or 429_cooldown_restores or revocation_after_final_permit' -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_production_certification_gate.py
```

作者结果：**4 passed, 40 deselected in 4.86s**。Ruff 最初要求导入排序，完成仅格式修正后通过。最终测试 SHA256：`D79C4E4C90F241374D3338297A900C91CA7AECA0ECE245043085DC40D267C010`；所观测 S2 候选 `production.py`：`522560DDFB708A0DA31B6C5321611E96E0D700B5DF7AF9AB6B391ACED27658A7`。

独立 Sol 验证使用以下精确命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_certification_gate.py -k "production_composition_resumes_after_one_runtime_transport_failure or next_minute_cannot_bypass_realtime_transport_backoff or production_429_cooldown_restores_before_provider_work_after_restart or revocation_after_final_permit_finishes_one_inflight_decision" -q --tb=short
```

结果：**4 passed, 40 deselected in 4.85s**，无 warning。运行前后六个源码及测试 hash 未变，包括上述两个 hash。Ruff、定向 diff 检查、静态评审和双语一致性均通过，三个路径获批准且无 P1/P2。这些运行有重叠，不能相加。这是冻结源码的 S2 工作候选兼容窗口，不批准 S2，也不等于固定提交汇总验收；C1/C3 和最终全量离线套件保持 OPEN。
