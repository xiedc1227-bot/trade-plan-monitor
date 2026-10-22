# 计划运行状态读取时区修复 — 2026-10-22

## PR-TZ-001 — 故障与根因

打开已保存草稿时，页面同时请求 `GET /api/v1/simulation-position-inventory`
和 `GET /api/v1/plan-runtime/{symbol}`。模拟库存请求在构造
`DailyInventoryResource` 时失败：生产生命周期时钟返回带时区的 UTC 时间，
但 `evaluated_at` 要求 `ShanghaiDatetime`。浏览器因此显示
`本地监控服务发生内部错误`。已有评估头的 UTC `updated_at` 也会在
`DailyStateView` 中触发相同问题。

问题出在响应序列化，并非交易政策无效，也不构成关闭时区校验的理由。
既有历史模拟数据仍受 `DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED` 保护。

## PR-TZ-002 — 修复与边界

`web/daily_service.py::read_daily` 现在复用现有 `_shanghai_datetime`，
转换正常库存响应、不支持库存响应以及已存评估头的时间戳。
转换保留同一真实时刻，并拒绝无时区时间。生产时钟和已存时间戳保持不变。

没有修改响应模型、来源审核、领域校验、历史数据识别、交易规则、启用操作
或库存写入逻辑。本次没有吞掉异常、推测时区、伪造零库存、自动迁移历史持仓，
也没有新增外部 AI 或行情请求。

## PR-TZ-003 — 回归验证

新增文件为 `tests/integration/test_plan_read_timezone.py`。
所有测试数据库均与 `data/monitor.sqlite3` 隔离。

| 检查 | 实际结果 |
| --- | --- |
| 修复前的新增回归测试 | 7 failed、4 passed；失败稳定复现严格时区不匹配 |
| 修复后的新增回归测试 | 11 passed |
| 相关回归选择，包含新增11例 | 117 passed |
| 修改的 Python 源码及新增测试文件 Ruff 检查 | 通过 |

覆盖正常和不支持的库存响应、未改变的默认 UTC 时钟、UTC 评估头时间、
转换跨越北京时间日期边界、拒绝无时区时钟、响应模型继续拒绝未经转换的
UTC/无时区值、HTTP 读取，以及库存与激活记录保持不变。

实际执行的测试选择：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_plan_read_timezone.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_plan_read_timezone.py tests/integration/test_daily_simulation.py tests/integration/test_daily_plan_boundaries.py tests/integration/test_daily_plan_chain.py tests/integration/test_daily_simulation_review_regressions.py tests/integration/test_plan_production_composition.py tests/unit/test_daily_safety_boundaries.py tests/unit/test_current_review_contract.py -q --tb=short
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/web/daily_service.py tests/integration/test_plan_read_timezone.py
```

Windows TestClient 使用本地事件循环支持及工作区内的独立临时目录运行，
未调用外部提供商。117例结果仅代表所选回归范围，不代表整个仓库测试套件。

## PR-TZ-004 — 实际草稿页面与保护状态

核实本地服务身份后，使用原配置重启服务，并重新加载和检查以下已保存草稿：

`/plans/f053d41c-2eca-4c3b-980b-ac6c370c2881`

页面不再显示内部错误，两个读取请求均返回 HTTP 200。
实际保留状态为 `UNSUPPORTED`，原因为
`DAILY_SIMULATION_LEGACY_DATA_UNSUPPORTED`；页面显示
`计划当前状态：历史数据不支持模拟`。这是保留的保护状态，不表示已完成
模拟库存初始化。库存快照继续为 null。

| 验收项 | 实际值 |
| --- | --- |
| 计划标识 | `SNGC-OBS-20261022`，版本 `1`，`605296.SH` |
| 持久化状态 | `DRAFT` |
| 技术提醒 | 1条；`close`、偏移 `0`、`LT`、固定 `2659` `FEN`、`OFFICIAL_DAILY_CLOSE` |
| 买入／卖出／风险清仓规则 | 0／0／0 |
| 审核绑定 | `review_id=null`、`review_revision=0`、`confirmed_at=null` |
| 启用按钮 | 禁用 |
| 计划哈希 | `18825a7f0dfd462f10b2392d74eaa826b6e6c11e128a54484937252320e2cea5` |
| 修复前后实际／模拟库存及激活状态 | 完全一致 |

保护状态比对覆盖实际持仓表、激活表、风险表，以及除提取／审核记录外的
每日记录。另行核对草稿哈希和审核绑定不变。没有确认审核、启用计划、
初始化库存或执行模拟交易。

## PR-TZ-005 — 证据

脱敏证据位于 `evidence/2026-10-22-plan-runtime-read-timezone/`：

- `acceptance.json`：已存草稿、类型化响应、浏览器观察及最终检查。
- `protected-before.json`／`protected-after.json`：保护记录数量及哈希。
- `test-results.json`：实际修复前后及相关回归测试结果。
- `http-status.txt`：本地读取请求成功状态行。
- `draft-restored.jpg`：修复后实际浏览器页面。

原人工研究附件及 AI 提取验证归档仍保存在
`data/research/SNGC-OBS-20261022/validation-20261022-115118/`，内容未修改。
工作区内原有的其他改动保持不变。
