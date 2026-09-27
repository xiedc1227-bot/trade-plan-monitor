# S3 当日业务分钟 SDK 边界

## BSB-01 范围与状态

实现及独立代码评审通过，五文件本地提交获批。本片仅实现配对 `2026-09-27-s3-startup-minute-repair-contract` 的 A07-F2-04/05 已批准的具体 provider 前置接口。F2/F3、A07 和 S3-04 保持 OPEN。本片不改变获取 owner、恢复持久化、调度、共享锁、通用协议或生产默认行为。

五文件切片为 `market_data/tushare.py`、`tests/unit/test_current_day_business_sdk_boundary.py`、`tests/unit/test_market_data.py` 中的窄签名断言，以及本配对报告。不包含其他 writer 的 `production.py`、测试和文档。未使用真实行情源、通知或用户数据库，也未推送或部署。

## BSB-02 已实现边界

具体 `TushareMarketDataProvider.current_day_minutes` 接受可选的仅关键字参数 `_physical_start: Callable[[], None] | None = None`，并将其传给既有 `_fetch_frame` 机制。通用 `MarketDataProvider.current_day_minutes(symbol)` 契约不变。普通省略/None 调用保留既有解析、请求参数及异常分类。

启用该接口的调用先经既有 resolver 完成真实认证 wrapper 检查和内部端点查找，再执行本地 hook。hook 紧接已解析 SDK callable 之前运行，位于 provider 异常分类之外。它不作为 SDK 参数发送，不安装到共享 provider/controller 状态，也不供另一调用复用。guard 异常保留原身份，真正 SDK 异常保留既有分类。未来 F2 owner 必须提供其捕获的时钟/来源/取消校验；本接口自身不实现该权限策略，也不阻止迟到响应持久化。

## BSB-03 RED 与 GREEN

- 初始专项运行：**17 failed，0.91s**，因为具体方法不支持该关键字。这是接口 RED 证据，不是 17 个独立生产故障。
- 七行 provider 差异完成后：**17 passed，0.76s**。随后修正一条测试行长问题，没有行为变化。
- 首次相邻运行：**1 failed、309 passed、1 warning，40.15s**。旧具体方法签名相等断言拒绝新增的已批准私有可选关键字。
- 断言现仅在 `current_day_minutes` 明确允许该关键字，检查仅关键字/default/type，并保留全部原参数/类型检查及所有其他方法的精确签名。通用协议未放宽。
- 最终四文件组合运行：**310 passed、1 warning，39.98s**。Ruff 和限定空白检查通过。警告为既有 Starlette/httpx 弃用提示。各运行有重叠，不能相加。
- 独立 Sol 评审无 P1/P2：**17 passed，0.74s**，随后运行组合命令中的三个相邻文件（不含新增专项文件），得到 **293 passed、1 warning，40.67s**。限定 Ruff 和空白检查通过，受审源码/测试哈希不变。独立运行不与作者数量相加。

新增离线测试覆盖真实 wrapper/resolver 在经过 14/15/16 秒时的顺序、调用已撤销时 SDK 零进入、原 guard 异常身份（含取消）、无私有 SDK 参数、no-hook 行/参数兼容、通用协议不变、HTTP 401/403/429/500 分类、并发调用 hook 独立，以及无效 symbol 拒绝。时钟及撤销策略由测试 guard 注入，不代表恢复 owner 已接入。本次共享工作树运行不是第三步最终集成门禁。

## BSB-04 命令

在 `trade-plan-monitor/` 执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_current_day_business_sdk_boundary.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/unit/test_current_day_business_sdk_boundary.py tests/unit/test_sdk_call_boundary.py tests/unit/test_market_data.py tests/integration/test_production_sdk_call_boundary.py -q --tb=short
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/market_data/tushare.py tests/unit/test_current_day_business_sdk_boundary.py tests/unit/test_market_data.py
git diff --check -- src/trade_plan_monitor/market_data/tushare.py tests/unit/test_market_data.py
```

## BSB-05 剩余验收

独立评审及五文件本地提交批准已完成。F2 仍需逐调用恢复接线、不可变捕获、精确缺失行选择、owned 响应事务及跨线程提交围栏；F3 仍需有界自主调度。该可选 provider 接口未关闭原 A07 截止点/进度失败。另一 UPD 提案中的日历和历史指数权限接口未在此实现。
