# 当前计划回放使用指南

## R01. 本地合成示例

在 `trade-plan-monitor/` 使用既有开发环境执行。此命令创建新的临时目录、合成原始日线/分钟数据、冻结数据集、完整 Schema 5 分钟/日线计划、明确研究声明及独立 JSON/CSV 结果。不会连接供应商，也不会读取本地应用配置。

```powershell
$replayDemo = Join-Path $env:TEMP ("unified-replay-" + [guid]::NewGuid().ToString("N"))
.venv/Scripts/python.exe scripts/create_unified_replay_fixture.py --output $replayDemo --run
```

省略 `--run` 可只生成文件。输出目录必须为空。生成的 `dataset.json` 包含 `datasetHash`；`minute-plan.json` / `minute-research.json` 和 `daily-plan.json` / `daily-research.json` 是可独立使用的两对输入。所有价格和条件均为合成值。日线示例明确声明合成常数复权因子；绝不能把它复制为真实原始数据的证明。两份脚本初始均无操作，因此会产生信号，但库存和现金不变。分钟信号在 09:35 确认，窗口为 `CURRENT_SESSION`；日线信号在 2026-08-24 确认，窗口为 2026-08-25 的 `NEXT_EXCHANGE_SESSION_ONLY`。两者都不代表已经成交。

## R02. 既有 CLI 与 Web 入口

`backtest run` 对完整当前计划接受 `--research-input <local-json-path>`。既有现金、执行成本、`--market-db`、`--results-db` 和 `--report-dir` 选项继续适用。初始批次通过 API/Web 的 `initialLots` 提供；当前 CLI 以无批次开始。生成器的 `--run` 使用这条真实 CLI 链路。API 接受已解析 JSON 作为 `researchInput`，不接受文件路径。旧计划禁止该字段，当前计划必须提供。

Web 使用时，在 `/backtests/new` 选择完全对应的已保存、已审核当前版本，并把匹配研究 JSON 粘贴到“统一计划研究输入 JSON”。计划不必真实激活。服务器独立检查已保存的不可变审核；JSON 中的 `review.confirmed: true` 不能批准未审核计划。嵌套研究字段保持 snake_case，包括 `started_at`、`inventory_known`、`review.content_hash`、`adjustment_proofs` 和 `operations`。外层 HTTP 字段仍用 camelCase。缺失或不匹配研究权限返回冲突；格式错误或不支持的假设返回校验错误。

结果页面区分评估时信号与脚本操作后状态。逐信号展示数量、执行窗口和阻断，以及数据阻断、提醒证据和风险状态。可选 JSON 是详细证据，不是阻断信号的唯一解释。

不启动生产服务器即可复现隔离的真实 API/任务/读取/导出链及浏览器夹具：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_unified_replay_entries.py -q -m 'not live'
Push-Location web
npm run test:e2e -- tests/e2e/backtests.spec.ts -g "current research input"
Pop-Location
```

API 测试自行创建已审核未激活的合成计划和临时数据库。浏览器使用既有本地 fake API 及真实强类型决策字节，操作当前表单/详情页面，并检查可访问性及外部请求/控制台错误。两者都不是实际 AI 或供应商认证。

## R03. 明确操作与资金

空 `operations` 数组不授权库存变化。`SIMULATE` 指定规则及准确 occurrence 或风险种类、完整正整手数量、明确时间和顺序。当前权限、T+1、CORE、容量、报价和风险校验仍然适用。部分数量请求被阻断；已消费 occurrence 不能再次授权同一交易。限定范围的肯定/否定事实、独立事件证据、停用、已审核替换终止及明确风险重评都属于冻结输入。替换不执行第二个计划。另存草稿不终止原权限。

监控回执价格与研究滑点、费用分开。研究现金不足会阻断资金估值，保留完整监控回执；之后收益持续为 null。未知库存保持未知。`DECISION` 和 `EXECUTION_OUTCOME` 详情采用当前强类型证据。摘要 JSON 使用 `backtest-report-summary-v4`；既有成交导出路由对当前运行输出 `explicit-simulation-valuation-v1` CSV，区分 `monitor_status` 与 `valuation_status` 两列。旧导出保持原字节。

## R04. 限制

依赖日线的规则需要冻结复权证明及核验交易日覆盖。未来复权锚点被拒绝。`FULL_SESSION_SUSPENSION` 明确以 `RESEARCH_FULL_SESSION_SUSPENSION_UNSUPPORTED` 阻断，不能覆盖已经交易的冻结分钟。当前回放不支持 `MANUAL_EVENT_RISK`。历史分钟 profile 保留确定的 12 秒接收宽限及 ready 数据集覆盖要求。本功能不认证实际历史采集时刻、真实持仓、券商订单、通知或实时供应商。

日内启动可按当前监控语义使用当日已完成桶，但 `started_at` 之前不产生事件、操作或估值。日历上下文最多 512 行，前向只到下一开市日；历史覆盖缺失保持可见。超过 70,000 个决策事件或安全整数资金边界之前，报告以稳定错误失败。既有 API 单项/响应/分页限制继续执行。
