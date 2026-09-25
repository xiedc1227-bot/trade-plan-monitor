# B2 控制器预约确认：离线第一薄步

## 范围

`TushareRequestController.recheck_permission` 仅在绑定恢复仓储后接受可选的内部同步 `on_reserved` 回调。新逻辑权限复核的 300 秒预约提交后、探针任务或 SDK 调用开始前，恰好调用一次。同作用域共享探针的后续调用方不调用其回调。工作线程后来延长预约时间不会再次调用回调。不传 `on_reserved` 的既有行为保持不变。

回调必须返回 `None`。回调抛错、返回其他值或返回 awaitable 时，在保留持久化阻断和重试时间后抛出固定脱敏的本地 `PermissionReservationCallbackError`。此时不启动 SDK，不标记 provider 或 checkpoint 故障，也不在控制器内关闭。非法或异步回调入参，以及未绑定仓储的用法，在新预约写入前被拒。checkpoint 写入失败时既不调用回调也不启动 SDK。

## 验证

RED 阶段因缺少回调故障类型而在测试收集时失败。GREEN 阶段使用模拟 SDK 与临时 SQLite，验证回调内独立数据库会话可在 SDK 启动前看见已提交预约、第二共享等待者回调不运行、发起预约的调用方取消后共享探针继续、排队中止与停止保留一次确认且不启动 SDK、回调故障只暴露脱敏本地异常、未绑定/非法入参与持久化失败均无回调副作用，以及工作线程后来延长重试不会二次确认。新增文件 **9 项通过**。相邻命令 **84 项通过**；全量 Ruff 与 `git diff --check` 通过。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_permission_reservation_ack.py tests/unit/test_request_recovery_admission.py tests/unit/test_tushare_permission_probe.py tests/integration/test_production_certification_gate.py -q
.\.venv\Scripts\ruff.exe check .
git diff --check
```

B2 第一薄步尚未接入 `ProductionMonitorPipeline`、RUNNING/DEGRADED 调度、任何新物理探针、30 秒本地检查或游标推进。C1 保持 OPEN。未请求真实 Tushare 行情、发送通知、修改用户数据库、推送或部署。
