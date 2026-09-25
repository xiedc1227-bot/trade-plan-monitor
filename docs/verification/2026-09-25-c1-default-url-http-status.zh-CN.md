# C1 默认 URL HTTP 状态保留（离线）

## RED 与原因

已安装的 Tushare 1.4.29 `DataApi.query` 用 `requests.Response` 的真假值判断结果。非 2xx HTTP 响应会直接变成空 DataFrame，供应商适配器无法再读取状态。使用假 `requests.post` 的离线测试发现：默认 URL 路径把 401 和 403 归为 `INVALID_RESPONSE`，未锁存权限阻断；把 429 也归为 `INVALID_RESPONSE`，未记录共享冷却。同一测试中的假 `connect_ip` 路径则保留 `BLOCKED_PERMISSION` 与 `RATE_LIMITED`。未调用真实服务。

## 有界修改

`create_tushare_client` 现仅在无 `connect_ip` 且使用官方默认 `DataApi` factory 时安装实例自有的 query 适配器。它仍使用一次 `requests.post`，保留既有 URL、JSON 载荷、超时及由环境管理的代理/CA 行为。整数型非 2xx 状态产生清洗后的 `HTTPError`，只附带含状态码的合成 response；不附原始 response、request、body 或异常上下文。适配器保留 2xx DataFrame 与供应商 code 的处理，并清洗畸形响应及传输异常，关闭每个已取得的 response。关闭失败不会覆盖已分类结果。注入的 `data_api_factory` query 实现、直连 IP 路径及进程全局 SDK/requests 行为均未改变。

## 验证与边界

默认 URL 的 401/403/429 用例已从 RED 转为 GREEN：控制器现保留权限阻断或共享 429 冷却。离线测试还覆盖 408/500 瞬态退避、带毒的非 2xx 响应体、有效及空的 2xx 表、畸形 2xx 数据、供应商 code/message 分类、两个客户端配置、响应关闭、超时清洗、不泄漏秘密及每次调用仅一次物理请求。`tests/unit/test_tushare_client.py` **58 项通过**。与 `tests/unit/test_monitor_runtime.py`、`tests/integration/test_production_certification_gate.py` 的相邻组 **190 项通过**。全仓 Ruff 与 diff 检查通过。独立 Sol/`xhigh` 评审未发现本有界修改的 P1/P2 问题。

`tests/unit/test_market_data.py` 尚有独立的基线冲突：其注入的 `requests.Timeout` 用例期待 `TRANSIENT`，但未改动的 HEAD 供应商适配器代码将其映射为 `TIMEOUT`。该参数单独运行仍失败；本切片不修改这一分类或断言。C1 保持 **OPEN**，包括 `2026-09-25-c1-provider-recovery-evidence.zh-CN.md` 所列的五个生产权限复核作用域。本次离线结果不认证真实 Tushare 权限或服务行为。未请求真实行情源、发送外部通知、迁移用户数据库、部署或推送。
