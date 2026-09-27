# C1 UPD-S1 日历/历史指数权限 SDK 边界验证

> 本文是中文复核副本，规范性英文版本为 `2026-09-27-c1-calendar-history-permission-sdk-boundary.md`。

## CHB-01 范围与状态

- 日期：2026-09-27。
- 依据：提交 `26b15e2` 中已批准的 [UPD-05、UPD-S1 及 UPD-R06 的 provider 部分](2026-09-27-c1-unified-permission-dispatch-contract.zh-CN.md)。
- 状态：**实现完成；writer 验证及独立 Sol 评审通过；无 P1/P2；五文件本地提交获批**。
- 拥有路径：`src/trade_plan_monitor/market_data/tushare.py`、`src/trade_plan_monitor/market_index/tushare.py`、`tests/unit/test_calendar_history_permission_sdk_boundary.py` 及本双语报告。
- 保留独立提交 `e7c6d8f` 的业务 `current_day_minutes` hook。本片不修改 generic protocol、SDK resolver/helper 实现、production owner、controller、scheduler、service 或数据库 schema。并行分钟 owner 评审工作独立，不包含在本片中。

## CHB-02 最小实现

`probe_trading_calendar_permission(exchange, anchor, *, _physical_start=None)` 经 `_trading_calendar` 将可选逐调用 callback 传给既有 `_fetch_frame` helper。`probe_historical_minutes_permission(index_code, anchor, *, _physical_start=None)` 将其传给既有 `_call_index_sdk` helper。

进入 helper 前已构造全部普通参数。有 hook 时，既有 nominal resolver 完成真实 `_CertifiedTushareClient` 检查并解析内部 callable，然后紧邻该 callable 调用前执行 guard。hook 既不是 SDK kwarg，也不存入 provider state；每次调用重新解析 endpoint。guard/resolver 异常（包括同一个 `RequestNotStartedError`）留在 provider 分类之外。实际 SDK 失败保留既有分类与脱敏。

省略 hook 或传入 `None` 保留普通路径、参数值、响应解析、错误行为和缓存。calendar proof 仍接受精确的休市日行。历史指数 proof 仍沿用完整 48/49 行已结束会话 parser，不填充、替换或清除缓存。provider 不增加 owner deadline、anchor 政策、股票分钟分类、认证到期阈值、权限 I/O 或自动 dispatch。测试中的时间/撤权 guard 是 callback 夹具，不是新增 provider 政策；真实 production owner guard 属于 UPD-S2。

## CHB-03 RED-to-GREEN 与目标检查

从 `trade-plan-monitor/` 运行：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_calendar_history_permission_sdk_boundary.py -q --tb=short
```

- 初始 RED：**44 failed, 10 passed**。两个权限方法都缺少 `_physical_start`，新 opt-in 调用因此失败；既有无 hook 分类/parser 路径继续通过。
- 最小透传后：**6 failed, 48 passed**。这六项失败是历史指数 `fields` 顺序的测试期望笔误。保持 provider 原顺序并修正夹具期望，不计作产品修复。
- 扩展目标：**62 passed**。

落盘用例通过真实认证 wrapper 和动态内部 resolver 覆盖两 endpoint：认证/解析耗时 2 秒、恰好 15 秒及 15 秒加一微秒；两个阶段内撤权；真实 wrapper 拒绝；guard 的 sentinel/RuntimeError/ValueError/CancelledError 原对象保留；resolver 异常身份；无私有 SDK kwargs；guard 前完成请求构造；休市 calendar 成功；完整历史 proof；省略/`None` hook 兼容；既有 cache 对象保留；generic protocol 不变；malformed 响应与真实 HTTP 403/429/500 分类；并发/连续调用隔离。并发 worker 测试禁止 SQL 或 Task 访问；一条调用拒绝时另一条可恰好进入一次内部 SDK。

## CHB-04 Provider/proof 回归与 lint

完整所选既有 provider/proof/boundary 矩阵 **904 passed**，含全部 **62** 例新增测试，有一个既有 Starlette/httpx 弃用警告。测试纯折行后的最终重跑同样 **904 passed**。最终运行前后两个 provider source hash 及最终 test hash 保持不变：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_calendar_history_permission_sdk_boundary.py tests/unit/test_market_data.py tests/unit/test_tushare_client.py tests/unit/test_tushare_historical.py tests/unit/test_tushare_live_probe.py tests/unit/test_tushare_market_index.py tests/unit/test_tushare_permission_probe.py tests/unit/test_index_http_classification.py tests/unit/test_minute_permission_transport.py tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_sdk_call_boundary.py tests/unit/test_current_day_business_sdk_boundary.py tests/integration/test_tushare_contract.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_sdk_call_boundary.py -q --tb=short
```

定向 Ruff 与源码空白检查：

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/market_data/tushare.py src/trade_plan_monitor/market_index/tushare.py tests/unit/test_calendar_history_permission_sdk_boundary.py --output-format concise
git diff --check -- src/trade_plan_monitor/market_data/tushare.py src/trade_plan_monitor/market_index/tushare.py
```

评审快照 SHA256：

- `market_data/tushare.py`：`5FD5ACF4ECA7177E1B95CAE5C6ADDE022A1DBB2454BBE15DEA371FDD0FA4FDE0`。
- `market_index/tushare.py`：`84AD6415E2C331B06238A8E9692F6C5A26F12A3C6CE6B68542F8BF005B3908CF`。
- `test_calendar_history_permission_sdk_boundary.py`：`12735A260C1BD09FE1FDFE633EDF3532E5B562122BB067ACAB2B9B95816E9CEC`。

独立 Sol 使用 CHB-03 目标命令验证 **62 passed，0.79 秒**，并使用下方命令验证 **237 项相邻测试通过，1 个既有 warning，48.03 秒**。受审 source/test hash 保持不变。这些独立运行与 writer 矩阵重叠，不能相加。独立 Ruff 及限定路径空白检查通过，无剩余 P1/P2。

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_tushare_permission_probe.py tests/unit/test_sdk_call_boundary.py tests/unit/test_tushare_historical.py tests/unit/test_tushare_market_index.py tests/unit/test_index_http_classification.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_sdk_call_boundary.py -q --tb=short
```

## CHB-05 剩余门槛

独立实现评审通过，五文件本地提交获批。这仅是 UPD-R06 的 provider seam 部分。真实 calendar/historical owner guard、snapshot/anchor 规则、取消/准入、统一 dispatch 和 RUNNING/DEGRADED 进展属于 UPD-S2–S5，这些 callback 测试不能证明上述能力。C1 保持 OPEN。

测试使用 fake SDK callable、受控时钟和真实 wrapper/parser；相邻集成夹具使用临时数据库。没有真实服务调用、用户数据库访问、通知、依赖变更、push 或部署。不声称完整仓库测试或 live release 验收。
