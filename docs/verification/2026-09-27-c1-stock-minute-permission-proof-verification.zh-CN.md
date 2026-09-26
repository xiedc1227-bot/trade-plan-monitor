# C1 股票分钟权限证明离线验证

> 规范英文报告为 `2026-09-27-c1-stock-minute-permission-proof-verification.md`；本文件为对应审阅副本。

## SMPV-01 范围与状态

日期：2026-09-27。契约、独立代码复审及最终文档评审已通过；离线实现已完成，其八个文件的本地提交已获授权。本报告对应配对的 `2026-09-27-c1-stock-minute-permission-proof-contract` 文档。C1 与生产恢复验收仍开放。

改动仅限 `src/trade_plan_monitor/market_data/tushare.py`、`src/trade_plan_monitor/market_data/tushare_client.py`、两份新增单元测试及配对契约／报告。未修改 production、controller、scheduler 或普通分钟过滤代码。`_fetch_frame` 现在保留本地请求未开始哨兵；两个客户端路径同样保留，并在泛化连接处理前保留抛出的结构化 HTTP 状态。

## SMPV-02 实现证据

- 两个单股票方法采用严格整批解析，固定 12 秒宽限和最长 15 秒证据区间。更长的传输 timeout 配置不能让迟到结果有效，这些方法也不强行缩短传输 timeout。
- Frozen slots 的 `MinutePermissionEvidence` 包含排序去重的 A/B/C 来源日期及分类计数，不是持久日历或运行时授权批准。
- 构造结果前验证必需列、精确标量类型、规范源时间戳、重复、有限正 OHLC、整数股数、非负金额及 640 资源上限。B 不能位于未来；C 的 END 标签只有在区间已开始时才允许晚于 R。
- 私有无正向证明异常为类型化 `INVALID_RESPONSE`，在解析 catch 外抛出。Provider 异常按固定元数据重建，原始 cause/context/属性/notes 不会保留。可信原始 `RequestNotStartedError` 对象在假 SDK、`_fetch_frame` 和安装客户端 default/direct 包装中原样传播。
- 测试日历回调一旦被调用就立即失败。传输均为内存假服务；安装客户端测试替换两条网络路径并使用假 token。未调用真实服务、用户数据库、历史写入、评估或通知。
- 首轮通过后，独立代码评审发现两个缺陷：`DataFrame.to_dict` 在验证前调用数值子类钩子，回调／SDK 修改可让请求中途的源标签变化。精确反例已先失败再修复。现在有界 tuple 迭代保留 object 单元格类型，已验证局部标签在回调前冻结并沿用到结果构造；普通数值 DataFrame 列仍被接受。独立修复复审已通过，证据如下。

## SMPV-03 已执行 RED 与 GREEN

命令均从 `trade-plan-monitor/` 使用其 `.venv` 执行。

| 阶段 | 命令 | 实际结果 |
| --- | --- | --- |
| 首轮解析器 RED | `.venv/Scripts/python.exe -m pytest -q tests/unit/test_stock_minute_permission_proofs.py --tb=no` | 129 failed；新方法尚不存在。 |
| 独立传输 RED | `.venv/Scripts/python.exe -m pytest -q tests/unit/test_minute_permission_transport.py --tb=short` | 116 failed、2 passed；同时复现既有 wrapper/fetch 路径吞掉请求未开始异常。 |
| 首轮合并 GREEN | `.venv/Scripts/python.exe -m pytest -q tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py --tb=short` | 247 passed，0.94s。 |
| 扩展相邻回归 | 下方命令 | 518 passed，32.47s，包含额外 11 项时钟／零值边界。 |
| 补充传输边界 | `.venv/Scripts/python.exe -m pytest -q tests/unit/test_minute_permission_transport.py --tb=short` | 136 passed，0.79s；包含新增 18 项类型化异常脱敏及 30/120 秒传输配置用例。 |
| 代码评审反例 RED | 下方精确反例命令 | 14 failed、1 passed、140 deselected，0.74s：六项子类钩子失败、八项冻结标签失败；普通数值列基线通过。 |
| 代码评审反例 GREEN | 相同精确反例命令 | 修复后 15 passed、140 deselected，0.57s。 |
| 最终分钟合并 GREEN | `.venv/Scripts/python.exe -m pytest -q tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py --tb=short` | 修复后 291 passed，0.93s。 |
| 最终相邻回归 | 下方最终回归命令 | 修复后 773 passed，37.59s。 |

```text
.venv/Scripts/python.exe -m pytest -q tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py tests/unit/test_tushare_client.py tests/unit/test_daily_permission_proofs.py tests/unit/test_tushare_permission_probe.py tests/unit/test_tushare_market_index.py tests/unit/test_tushare_historical.py tests/unit/test_live_certification_profiles.py tests/unit/test_live_certification_runner.py tests/integration/test_tushare_contract.py tests/integration/test_production_semantic_gate.py tests/integration/test_production_certification_gate.py --tb=short
```

后续 18 项传输用例在 518 项运行之后增加；上述数量如实对应各次执行，不把所有用例假称为同一次运行。

精确反例命令（两个问题修复前后均执行）：

```text
.venv/Scripts/python.exe -m pytest -q tests/unit/test_stock_minute_permission_proofs.py -k "numeric_subclass_hooks or source_label_is_frozen or builtin_numeric_dataframe" --tb=short
```

最终回归命令，包含普通 market-data 和请求准入／预约检查：

```text
.venv/Scripts/python.exe -m pytest -q tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py tests/unit/test_tushare_client.py tests/unit/test_daily_permission_proofs.py tests/unit/test_tushare_permission_probe.py tests/unit/test_tushare_market_index.py tests/unit/test_tushare_historical.py tests/unit/test_live_certification_profiles.py tests/unit/test_live_certification_runner.py tests/unit/test_market_data.py tests/unit/test_request_recovery_admission.py tests/unit/test_permission_reservation_ack.py tests/unit/test_realtime_index_permission_parser.py tests/integration/test_tushare_contract.py tests/integration/test_production_semantic_gate.py tests/integration/test_production_certification_gate.py --tb=short
```

早期通过数量属于历史证据，不代表两个缺陷行为通过验收。上述最终运行已包含对应回归保护。

协调任务报告了独立评审者实际修复后结果：**291 项分钟测试通过、297 项相邻测试通过、32 项扩展断言通过**，且**无剩余 P1/P2**。扩展覆盖两个 operation、A/B/C int/float 子类零钩子调用、callback/SDK 改为 END/UNVERIFIED 仍保持冻结 START、仅 C 无证明拒绝，以及普通 numeric dtype 兼容。这些属于评审者独立运行，不叠加到作者的 773 数量；交接未提供评审者精确命令，本文不编造。

## SMPV-04 矩阵覆盖与剩余验证

`test_stock_minute_permission_proofs.py` 覆盖 SMP-RED-01–05、07、09–12 及 worker 侧 SMP-RED-08：A/B/C 混合、无证明、不可变结果、冻结时钟、开盘／未来／时段边界、原始行数上限、跨日日期、行转换前的别名／schema、精确标量类型、任意转换陷阱、包含 zero/amount 的 640 raw/coefficient/展开边界，以及不访问日历。既有普通分钟契约测试提供行为回归覆盖。

`test_minute_permission_transport.py` 覆盖 SMP-RED-06 和 07/10 的传输方面：fake/default/direct 路径单次尝试；原始未开始对象；返回／抛出的 HTTP 401/403/429（含 connection-first 多重继承）；timeout/TLS/connection/decode/schema/provider 失败；安全 cause/context/属性；配置 30/120 秒 timeout 时准确 15 秒通过、超出一微秒拒绝。

SMP-RED-08 的 owner 开市日、epoch、停止、代次及授权检查仍为后续接线工作。本轮测试不声称清除生产 latch 或执行调度。

独立评审报告两个缺陷后，完整非 live 命令 `.venv/Scripts/python.exe -m pytest -q -m "not live" --tb=short` 在完成前被中止（中止后进程退出码为 1）。这不是完整测试结果，修复后未重新运行；最终验证为上述 291 项分钟专项和 773 项相邻回归。不声称全仓库测试通过。

## SMPV-05 静态检查与实际边界

最终 Ruff 与差异空白检查通过。也已核对配对文档结构、签名、命令、数值阈值／结果及工作区归属。其他任务的 production／wiring／kill-restart 文件不属于本次改动。仅本薄步八个文件获准本地提交；不包含推送、部署或真实服务认证。静态命令：

```text
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/market_data/tushare.py src/trade_plan_monitor/market_data/tushare_client.py tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py
git diff --check
```

独立代码复审已通过，但生产环境清除对应 operation 前，仍须对全部返回来源日期验证当前持久开市证据。真实 `rt_min` 可能不返回 A 行；离线夹具不能证明真实恢复可行性。严格证明专用列／标量规则不改变普通业务分钟读取。八个文件本地提交获准前，最终文档口径核对已通过。
