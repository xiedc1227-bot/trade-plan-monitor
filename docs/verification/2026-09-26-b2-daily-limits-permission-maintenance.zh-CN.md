# B2 DAILY_LIMITS 权限维护：离线内部薄步

## 范围

新的 `_maybe_recheck_daily_limits_permission` 方法仅处理已阻断的 `DAILY_LIMITS`。它与 `INDEX_DAILY` 共用权限维护锁，在锁内重新选择全局首个按原始预约到期的候选，并仅通过控制器持久预约的 `on_reserved` 回调推进内存权限游标。未接入 RUNNING/DEGRADED 调度器，也未新增其他作用域的物理权限探针。

所有者线程在预约前及 provider 响应后，分别通过单次有界 SQLite 快照同时读取 `legacy_symbols` 与准确的、已结束且已持久化的 SSE 工作日开市锚点。当日无 eligible ACTIVE legacy 需求、无锚点或 stock 授权暂不可用时，仅在前次检查到期后固定延后 `now + 30s`。重复调用及纯到期 getter 不滑动该时间，也不预约工作。显式 STOCK 语义要求 `stk_limit` scope 与相同 semantic revision；受支持的 legacy 模式在无 semantic bindings 时使用 stock certification。配置、认证、代次、停止状态及日历 epoch 在排队和 worker 准入期间复核。SDK worker 不读取数据库。

provider 私有 `_physical_start` 回调在 `_fetch_frame` 前立即执行，位于其宽泛异常脱敏处理之外。冻结的 31.25 秒市场保护适用于排队前、排队准入、worker 入口及 SDK transport 前最后一刻。响应验证拒绝时钟回拨到捕获时间以前或日期变化，但不重新套用未来的市场启动保护。`stk_limit(D)` 是整市场的日期权限证明：请求期间新激活的 legacy 股票可满足终态需求，而终态无 legacy 需求或只剩 explicit 计划均不能清锁。若周六仍有 eligible MANUAL legacy 计划，可用可信、已结束的周五锚点证明；错误的周末开市记录不能成为锚点。证明不写入业务日涨跌停行或日历缓存。

## 验证

RED 首先因缺少内部方法而失败。另一项 RED 证明，拒绝 `semantic_bindings=None` 会使受支持的 legacy stock-certification 模式无法复核。模拟 SDK 与临时 SQLite 测试覆盖合法单次请求及仅清本作用域、无需求/无锚/无授权固定延后、共享 429 与全局到期排序、真实 legacy 构造与无效显式 STOCK binding、周末锚点选择、持久预约及回调故障、排队中止/停止/无效响应/超时、物理启动撤销后零 SDK 调用、恢复后的配置及语义撤销、同值日历 epoch 改变、响应后重读精确锚点、与 `INDEX_DAILY` 串行交错、午夜及时钟回拨拒绝、接近下一市场截止点的合法响应，以及 SDK 请求期间的终态需求变化。专项与相邻命令 **138 项通过**；全量 Ruff 与 `git diff --check` 通过。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/unit/test_daily_permission_proofs.py tests/unit/test_permission_reservation_ack.py tests/integration/test_production_semantic_gate.py -q
.\.venv\Scripts\python.exe -m ruff check .
git diff --check
```

后续调度接入仍须证明权限工作不消耗市场截止点游标。其他权限作用域、RUNNING/DEGRADED 派发及端到端 C1 验收保持 OPEN。未请求真实 Tushare 行情、发送通知、修改用户数据库、推送或部署。
