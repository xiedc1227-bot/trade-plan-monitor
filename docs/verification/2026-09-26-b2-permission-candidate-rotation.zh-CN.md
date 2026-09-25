# B2 权限候选轮转：离线第二薄步

## 范围

`ProductionMonitorPipeline` 用一个不可变内存状态保存六个权限作用域的游标，并分别保存 `DAILY_BARS` 官方（`O`）与回退（`F`）池的 `(symbol,date)` 游标。重复窥视候选保持只读。仅在控制器的持久 `on_reserved` 确认成功后，才整体替换该状态；下一状态在预约前计算，回调只做一次有界内存赋值。即使后续排队中止、物理 SDK 未启动，已提交预约仍计入轮转。持久化失败和候选扫描均不推进游标。

首次日线选择在 `O` 存在时优先使用 `O`。两池均存在时，预约在 `O` 与 `F` 之间交替，每池分别按有界的日期倒序、股票升序推进。上一对消失或移到另一池时，按保留的排序键选择严格后继，仅越过末尾才回绕。池为空时保留游标，供以后恢复。作用域并列时依据上次成功预约的作用域；探针尝试或失败本身不触发轮转。游标仅存在于进程内，重启时重置。

## 验证

RED 测试首先因缺少回调工厂、池身份、不可变状态及严格后继辅助函数而失败。GREEN 阶段用模拟 SDK 与临时 SQLite，覆盖六作用域同到期、重复窥视、持久预约后排队中止但只确认一次、O/F 交替、同日跨股票及跨日后继、删除和跨池移动的候选、空池恢复，以及 checkpoint 保存失败时游标不变。新增轮转文件 **4 项通过**。相邻命令 **89 项通过**；全量 Ruff 与 `git diff --check` 通过。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_candidate_selection.py tests/integration/test_production_certification_gate.py tests/unit/test_permission_reservation_ack.py tests/unit/test_request_recovery_admission.py -q
.\.venv\Scripts\ruff.exe check .
git diff --check
```

尚未接入生产调度，也未新增物理权限探针。本切片未实现 30 秒本地检查或跨重启游标持久化。后续生产调用方必须在串行预约流程中立即构造并传入预计算确认；多个回调若基于同一旧状态并发预计算，则不属于本切片。C1 保持 OPEN。未请求真实 Tushare 行情、发送通知、修改用户数据库、推送或部署。
