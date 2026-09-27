# C1 股票分钟权限准备验证

> 规范英文版本为 `2026-09-27-c1-stock-minute-permission-preparation.md`；本文是中文审阅副本。

## SMP-01 范围与状态

- 日期：2026-09-27。
- 契约：[股票分钟权限 owner](2026-09-27-c1-stock-minute-permission-owner-contract.zh-CN.md)，准备设计在 `3c22bff` 获批。
- 状态：**准备已实现；独立实现评审通过，无 P1/P2；已批准本地提交**。
- SDK 边界提交 `4804207fdc78270604b952cc25a372e59d4e32bb` 后已移交 source 写入权。主协调报告该独立切片已获独立批准。SMWO-11 的历史 OPEN 文本不授权分钟执行；本片不修改该契约。
- 范围：`src/trade_plan_monitor/runtime/production.py`、`tests/integration/test_production_stock_minute_permission_preparation.py` 与本双语报告。并行的启动分钟测试及修复草案文档保持未改。

## SMP-02 已实现行为

`_prepare_stock_minute_permission_locked(operation)` 在调用方持有共享维护锁时返回不可变 `PREPARED / UNKNOWN / SKIPPED` 事实。冻结 candidate、原消费者、捕获时刻、语义模式/revision、label、provider/source、factory 及 epoch/Event。不创建预约或调用 SDK。

一份 owned、使用应用 engine 的 SQLite 快照检查最多十个 ACTIVE 版本、有界 payload、两个激活指针、准确 symbol、相等的正 revision、不晚于捕获时刻且相等的 canonical Shanghai 时间戳，以及完整 canonical 计划身份/hash。今日合格 legacy 和 explicit 消费者要求对应服务已组合。缺少业务 READY 输入不排除资格。不执行历史 activation audit 或历史收盘发现。

请求日要求精确持久 SSE 工作日开市事实。窗口为 `[09:31:12, 11:30:00)` 与 `[13:00:00, 15:00:00)`。缺少事实/消费者/授权使用固定 30 秒复查；已知首分钟/午后时刻予以保留。getter 不滑动期限。重新准备重建请求日身份。revoked token 仅在 owned 读取后、捕获的 epoch 与 Event identity 均仍一致时替换；旧 Event 保持 set，绝不 clear。

selector 和廉价 getter 均含八作用域，保留原六项顺序。独立分钟 symbol 游标按升序严格后继选择并回绕，在空集合时保留。既有预约 callback 预计算一次不可变替换，保留 DAILY_BARS O/F 状态。准备与 peek 不调用它。测试直接模拟预约后的通知；不据此证明分钟持久预约/执行行为。

borrowed/pre-used 或错误绑定 session 会抛出配置错误，不关闭或回滚调用方状态。缺少 factory 会延后；分钟独占 peek 不回退业务 UnitOfWork。SQL/编程错误传播。permission-only 读取不启用业务历史恢复。

## SMP-03 RED 与针对性 GREEN

在 `trade-plan-monitor/` 中运行：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_stock_minute_permission_preparation.py -q --tb=short
```

- 初始最小 RED：**4 failed**，分别为两例准备方法缺失、两例分钟 getter 缺失。
- 实现前扩展 RED：**39 failed**。随后首次 GREEN 工作发现两处 fixture 错误：窗口时间早于认证观察时间。fixture 现使用真实的更早认证；未放松产品 gate。
- source 替换回归：**1 failed, 66 passed**；捕获/检查 source identity 后 **67 passed**。
- 固定 due/缺少 factory 回归：**2 failed, 67 deselected**，随后 **2 passed, 67 deselected**。
- 组合复跑前最终针对性运行：**74 passed**，仅有一条既有 Starlette/httpx 弃用警告。

| 契约边界 | 准备证据 |
| --- | --- |
| SMW-01 | 完整 legacy/explicit/混合消费者；排除未来、过期、缺服务、草稿/停用、空集合及仅历史 pending。 |
| SMW-02 | 三表指针/symbol/revision/时间；canonical payload/hash/plan ID/version；坏内容；同 hash 重新激活时原身份冻结；不依赖历史 audit。响应拒绝仍属执行工作。 |
| SMW-03 | 准确首分钟、提前一微秒、午休、午后、收盘；缺失/closed/错误交易所/周末日历；语义模式请求日跨日刷新。 |
| SMW-05 | 八作用域一致、原顺序、raw-due/tie 轮转、较早 scope 延后、独立 symbol 后继、空集合/新增 symbol、稳定 peek 和 O/F 保留。 |
| SMW-08 准备部分 | configuration/generation/stop/label/provider/source/factory/时间变化；语义 revision、无 legacy 兜底、旧认证到期后有效；epoch 加 Event identity 替换。 |
| SMW-11 准备部分 | 一次 explicit BEGIN、并发激活提交时读取一致原身份、borrowed/wrong-bind 处理、SQL 错误。响应快照仍属执行工作。 |
| SMW-15 | 固定期限；准备零预约/SDK/业务写入；不启用历史恢复或 scheduler 入口。 |

fixture 使用应用配置 engine 上的临时 SQLite、真实 legacy repository 激活或既有可信完整 explicit 激活 fixture、可控时钟及离线 SDK。并发写测试有意单独提交 fixture 激活；准备本身仅读取。

## SMP-04 相邻检查

以下运行通过 **501 tests**，仅有相同既有警告。它在最终固定 due/缺少 factory 修正前开始；最终组合复跑覆盖受影响的候选/日线路径及全部准备测试。

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_sdk_call_boundary.py tests/unit/test_sdk_call_boundary.py tests/unit/test_stock_minute_permission_proofs.py -q --tb=short
```

最终组合复跑：**175 passed**，仅有相同既有警告。

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_stock_minute_permission_preparation.py -q --tb=short
```

针对性 Ruff 与空白检查通过：

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/production.py tests/integration/test_production_stock_minute_permission_preparation.py
git diff --check
```

主协调转述独立 Sol 评审通过，无未解决 P1/P2。reviewer 独立复跑了上述准确的最终六文件命令：**175 passed**，包含全部 **74** 个准备用例。额外内联对抗检查确认：仅历史 pending 不产生今日分钟消费者，同时合法 DAILY_BARS 需求仍保留；缺少 factory 的兼容性保留；legacy 认证在等号到期边界失效。这些内联检查是 reviewer 报告的证据，不是新增已入库测试或 writer 运行。reviewer 另报告四个相邻文件 **123 passed**；此处未保留准确命令，因此该数字仅作补充，不作为可复跑主证据。限定 diff 的 Ruff 通过，reviewer 报告 source/test hash 保持不变。

## SMP-05 剩余门槛与边界

独立实现评审已通过，主协调批准仅本片四个文件本地提交。执行入口、持久预约/callback 生命周期、SDK 调用、provider/controller 改动、响应证明验证、自动调度、READY/业务状态及完整 C1 验收仍不属于本片。未运行全仓测试，也未复跑独立启动分钟 RED 测试。未访问真实服务或用户数据库；未推送、部署或发送。
