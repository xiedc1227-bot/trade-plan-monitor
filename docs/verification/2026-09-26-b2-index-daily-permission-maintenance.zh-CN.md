# B2 INDEX_DAILY 权限维护：离线第三薄步

## 范围

内部 `_maybe_recheck_index_daily_permission` 路径仅处理 `INDEX_DAILY`。它进入共享维护锁，检查该作用域的原始/本地/共享到期时间，读取 B1 有界候选与缺锚证据，且仅当全局到期选择器的第一个合格候选为 `INDEX_DAILY` 时继续。它在控制器持久预约前立即创建 B2 轮转回调。尚未接入 RUNNING/DEGRADED 或六作用域调度。

缺少已持久化、已结束的 SSE 开市日时，仅在此前本地检查到期后设置一次 `now + 30s` 延后。重复调用与纯到期 getter 不滑动此时间，也不预约 provider 工作。预约前要求已认证 READY 的指数及准确的持久化工作日开市锚点；错误的周末开市记录从候选选择和精确锚点验证中排除。所有者线程在 provider 响应前后检查锚点；SDK worker 不做数据库操作。冻结的 31.25 秒市场保护在排队前、排队准入、worker 入口，以及紧贴 SDK transport 的 provider 私有 physical-start 检查点执行。响应验证检查当前授权、已持久化日历/epoch，以及时钟未回拨到捕获的启动时间之前；不再次套用未来的市场启动空档。

权限证明只进行一次只读 `probe_official_daily_permission(I,D)` 请求。不更新指数缓存、业务历史、评估、通知或市场截止点游标。持久预约成功时只推进内存权限游标，即使随后排队中止；持久化失败则不推进。控制器回调故障作为脱敏本地故障向上传播，不关闭控制器。

## 验证

RED 首先因缺少内部执行器而失败。模拟 SDK 与临时 SQLite 测试覆盖合法单作用域清锁与一次 SDK 调用、未到期/共享 429/无授权/无锚/其他作用域先行门禁、固定 30 秒本地延后、持久化及回调故障、排队撤销/停止/无效响应/超时、配置和语义变更后恢复、同值日历提交改变 epoch、worker 物理启动复核、所有者线程数据库访问、响应后重读持久锚点、两个作用域串行交错，以及第二运行实例在内存游标重置后恢复 300 秒预约。新增 RED 用例证实较新的错误周末开市记录挤掉周五锚点，以及同日响应时钟回拨导致错误清锁；现已拒绝这两种情况并保留持久化的 300 秒预约。请求在 31.25 秒保护窗之外启动，响应到达实际下一市场截止点前 17 秒时仍可合法清锁。专项与相邻命令 **167 项通过**；全量 Ruff 和 `git diff --check` 通过。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/unit/test_daily_permission_proofs.py tests/unit/test_permission_reservation_ack.py -q
.\.venv\Scripts\ruff.exe check .
git diff --check
```

后续调度接入必须证明权限结果不消耗市场截止点游标；本切片仅提供内部调用，尚无调度派发或游标可供验证。既有 `historical_anchor`、`_historical_index_permission_anchor` 和实时 `current_open` 仍接受错误的周末开市记录；统一六路接入前须另做有界修复。其他权限作用域、生产调度及端到端 C1 验收保持 OPEN。未请求真实 Tushare 行情、发送通知、修改用户数据库、推送或部署。
