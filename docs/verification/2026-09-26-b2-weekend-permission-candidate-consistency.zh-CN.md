# B2 周末权限候选一致性：离线验证

## 范围

本次有界修复让三处既有读取遵守同一已结束工作日开市规则。B1 `historical_anchor` 仅选择 `weekday() < 5` 且 `is_open=True` 的已结束、已持久化 SSE 记录。B1 实时 `current_open` 要求今天是工作日，且今天唯一的已持久化 SSE 记录为开市。既有 `_historical_index_permission_anchor` 七日辅助方法采用相同工作日开市规则。`calendar_anchor` 仍接受已结束的周末记录，无论开市或闭市，以便 `trade_cal` 证明日历访问。未增加调度器、预约或物理探针路径。

## 验证

两个新增 RED 用例表明，较新的错误周日开市记录会挤掉周五历史指数锚点，错误周六开市记录会生成实时指数候选。修复后，历史候选与既有辅助方法均选择周五；周六实时作用域没有候选或物理 SDK 调用。保护用例确认已持久化的周日闭市记录仍可作为 `TRADING_CALENDAR` 锚点。相邻历史、实时、B1 和 INDEX_DAILY 回归测试覆盖合法工作日行为。专项与相邻命令 **104 项通过**；全量 Ruff 通过。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_permission_candidate_selection.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_index_daily_permission_maintenance.py -q
.\.venv\Scripts\python.exe -m ruff check .
git diff --check
```

本次仅涉及候选选择及既有历史锚点读取。统一六作用域调度接入及其市场截止点游标证明仍为 OPEN。未请求真实 Tushare 行情、发送通知、修改用户数据库、推送或部署。
