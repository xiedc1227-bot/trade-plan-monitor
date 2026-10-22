# AI源证据审核契约验证 — 2026-10-22

## AI-RC-01 范围与不变量

最初完整的 `deepseek-flash` 响应正确表达了所需提醒，但源证据审核失败。38条绑定路径全部误带 `draft.` 外层前缀；身份/展示元数据和未登记空值被绑定，`PRODUCT_CONTRACT` 还附带了来源分句ID。语法正确的草稿不等于提取通过。

本次只更新 `src/trade_plan_monitor/ai/plan_extraction.py` 中 `build_current_plan_prompt` 组装的可信指令。Schema 5、`plan-extract-v9`、原文分句、JSON解析、`semantic_values`、源证据审核器、启用和模拟权限均未改变。没有输出归一化、前缀剥离、元数据过滤、参数推断或响应后修补。

精确中文输入保存在 [source.txt](../../tests/fixtures/ai/current-review-contract/source.txt)。它与用户最终精简正文逐字节一致，SHA256为 `d672ee69ade8c1cbcee496bf5c88976d305227f9d985be151391c25a16aaab65`。人工研究附件未提交。原报告未确认的时间仍为空；既有软件契约MACD预热值仍为26。没有改变交易原则或阈值。

## AI-RC-02 可信契约修正

提示词现在于JSON Schema之后、不可信原文之前提供结构化源证据审核契约：

- `bindings.path` 和 `clauses.paths` 使用计划根路径，不带 `draft.`。
- `plan_id`、`version`、`name` 和整个 `metadata` 子树保留为草稿的身份/展示信息，不建立策略绑定。`symbol` 和 `market` 仍是必须绑定来源的运行时资产范围，混合身份分句也不例外。
- 不绑定未登记空值或容器。既有显式空值例外 `levels.low_buy`、`levels.pressure`，以及空数组、非空叶子、`ALL`/`ANY` 类型字符串结构仍须审核。缺少必要交易参数时仍留空并阻断审核。
- `PRODUCT_CONTRACT` 的 `clause_ids` 必须为空、`supplement_id` 必须为null。来源型绑定仍使用精确原文分句引用；AI不得创建人工权限。
- 绑定值与候选JSON序列化后的类型精确一致。Decimal参考值保持字符串；整数分转换仍接受原有精确价格检查。
- 非规则标题和展示说明可采用具有明确语义角色和理由的 `CONTEXT`。真实指令、期限、缺失交易参数和技术要求不得隐藏为背景说明。`BACKGROUND` 保留精确登记排除的边界。

元数据、混合空值、身份范围和软件常量示例消除了外层Schema的歧义。服务端继续拒绝不兼容输出，不替模型适配输出。

## AI-RC-03 回归与运行时证据

新增[回归模块](../../tests/unit/test_current_review_contract.py)包含12个用例：将提示词与既有语义路径及产品绑定契约核对，原样回放最初失败响应，并将未经修改的成功响应交给真实解析器和审核器。负向变异覆盖绑定/分句路径前缀、元数据、未登记空值、产品来源附带分句ID、Decimal类型不一致及分句遗漏。必要持仓上限缺失时仍保持空值并阻断审核。

| 检查 | 结果 |
| --- | --- |
| 针对性提取/安全/源证据/集成回归 | 94项通过；1条既有Starlette/httpx弃用警告 |
| 全部单元测试及离线契约测试 | 3,433项通过；4项 `live` 测试未选择；1条既有警告；58.45秒 |
| `python -m ruff check --no-cache src tests` | 通过 |
| 修改的Python文件格式检查 | 通过 |
| 在内存中删除必要资产范围声明的变异检查 | 测试按预期失败并捕获变异；契约已恢复；源码无变异 |
| 完整后端测试库 | 未完成，不计为通过 |

Windows asyncio需要本地回环socket，因此离线测试在受限socket沙箱外运行。新的工作区 `--basetemp` 避开了既有系统临时目录权限问题。普通全库命令存在integration/unit两个 `test_backtest_service_contract.py` 模块同名冲突；importlib模式还需要将旧测试目录加入 `PYTHONPATH`。兼容调用收集到7,607项离线测试，但集成测试长时间无进展后已中断。没有削弱任何测试断言或运行时校验器。前端代码未改变。

### 真实AI提取

在用户明确授权后，通过 `ConfiguredAICommandService.extract -> extract_plan` 将同一正文发送至项目配置的 `https://api.deepseek.com/chat/completions`，使用 `deepseek-flash`，与Web共用当前提取器。保持项目默认值：输入上限50,000字符、输出上限4,096 token、等待30秒、重试上限2次。成功请求的完整提示为48,400字符，仅1次提供商尝试，返回 `finish_reason=stop`，输入14,196 token、输出3,469 token。

最终未经修改的响应通过精确源证据审核，覆盖全部15个分句、32条字段绑定：

| 验收项 | 实际结果 |
| --- | --- |
| 提取状态 | `SUCCEEDED` |
| 草稿存在且结构有效 | 是 |
| 校验问题 / 假设 / 警告 | 0 / 0 / 0 |
| 普通BUY / SELL规则 | 0 / 0 |
| 清仓分支 | 0 |
| 技术提醒 | 1条：`RISK-ALERT-01`、`RISK_ALERT` |
| 提醒条件 | 最新正式完整日K的 `close`，`offset=0`，严格 `LT` 固定 `2659 FEN` |
| 确认方式 | `OFFICIAL_DAILY_CLOSE` |
| 新增量能、指标、人工事实或指数条件 | 无 |

修复后的第1次真实请求仍误绑定元数据/空值，被拒绝；第2次返回可审核草稿但遗漏 `symbol`/`market` 证据，产生2项阻断问题。两次均未计为成功，也未修补。继续澄清契约后，第3次请求满足全部验收条件。最终输入和响应逐字节原样复制为测试样例；响应SHA256为 `f75114a2e9f943e4c7a10e887adf0a36a2e67750d1f81d9290434b5b0497d9c4`。

参见[机器可读真实验证证据](evidence/2026-10-22-ai-source-review-contract/live-verification.json)、[最初被拒绝响应](../../tests/fixtures/ai/current-review-contract/deepseek-before.json)和[通过审核响应](../../tests/fixtures/ai/current-review-contract/deepseek-after.json)。真实调用的提示哈希与最终实现一致。

## AI-RC-04 权限与限制

真实提取使用不持久化的CLI服务。该调用流程没有打开计划/账户数据库，没有批准或启用计划，没有初始化或修改模拟库存。`config/app.yaml` 逐字节未变。测试使用固定提供商和临时存储；另行授权的真实调用是显式执行的。

本结果验证的是这一精确输入/响应及未放宽的严格审核，不保证任意未来模型输出。新的不兼容响应仍须按严格规则拒绝。本次未引入指数联动、动态数量、基本面监测、自动交易或自定义提醒正文功能。人工审核及显式启用仍是独立要求。
