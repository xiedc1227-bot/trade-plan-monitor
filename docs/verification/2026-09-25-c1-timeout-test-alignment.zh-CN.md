# C1 行情数据超时测试预期校正

## 发现与校正

修改前完整运行 `test_tushare_provider_errors_use_stable_codes_and_drop_raw_context` 参数组：**1 项失败、13 项通过**。只有注入的 `requests.Timeout` 用例期待 `TRANSIENT`，而 provider 返回 `TIMEOUT`。`git show HEAD:src/trade_plan_monitor/market_data/tushare.py` 确认既有 `_safe_provider_error` 分支明确将 `requests.Timeout` 映射为 `TushareErrorCode.TIMEOUT`；该行为不是近期日级或指数探针变更引入。仅把这一条过时的测试预期改为 `TIMEOUT`。产品错误分类未改变。

## 验证与边界

断言校正后，参数组 **14/14 项通过**，完整的 `tests/unit/test_market_data.py` **171/171 项通过**，该文件的 Ruff 检查通过。此前有日期的证据正确记录了当时观察到的失败；本文更新其当前测试状态。未请求真实 Tushare 行情、发送外部通知、迁移用户数据库、推送或部署。五个业务权限作用域仍未接入生产维护调度，因此 C1 保持 **OPEN**。
