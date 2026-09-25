# C1 指数 SDK HTTP 分类：离线修正

## 范围与结果

独立 Sol/`xhigh` 复审批准该有界修正，本切片无剩余 P1/P2 问题。私有指数 SDK 调用边界现对普通 `idx_mins`、`rt_idx_min_daily`、`index_daily` 请求及既有历史/实时指数权限探针的原始 HTTP 故障做安全分类。此前新增的纯 `INDEX_DAILY` 探针也复用该边界。控制器、请求参数、缓存策略与物理请求顺序均未改变。

## 故障行为

模拟仅带状态码的 HTTP 401/403 错误现以 `BLOCKED_PERMISSION` 进入控制器，只锁存受影响的指数 operation。各 operation 保留自身权限阻断和 300 秒预约，不锁存无关作用域。HTTP 429 触发共享限流冷却。每次尝试只发出一条 SDK 请求。`RequestNotStartedError` 原样透传，不变成 provider 故障。安全化的 provider 异常在原始异常处理段之外抛出，因此暴露的异常不会保留原始 token、响应正文、cause 或 context。

## 验证与剩余门禁

`tests/unit/test_index_http_classification.py` 初始在五个受影响边界产生 **16 项 RED 失败、1 项通过**。修正后，**17 项专项测试全部通过**。相邻指数 provider、日级探针、实时解析、请求控制器及生产指数权限探针测试组合 **198 项通过**。修改的 provider 与新增测试文件的 Ruff 检查和 `git diff --check` 均通过。所有调用仅使用模拟 SDK 响应及临时离线测试状态。

未请求真实 Tushare 行情、发送外部通知、迁移用户数据库、推送或部署。剩余五个业务权限作用域仍未接入生产维护调度；持久化锚点与复核编排属于后续工作。本修正不能关闭 A05、C1 或发布验收。C1 保持 **OPEN**。
