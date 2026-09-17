# R30 AI 超时预算准备记录

英文原版为 `R30-ai-timeout-budget-preparation-20260917.md`，本文是等价中文审阅副本。状态 **OFFLINE_COMPLETE / AUTHORIZATION_SCOPE_CORRECTED / CLAIM_UNCONSUMED / ZERO_EXTERNAL_CALLS_TO_DATE**。

批准后更新：全部本地门禁均通过，但直接打开的官方价格页面显示了高于冻结审阅包快照的价格。首次派发尝试在创建 claim 或网络执行前停止。该零调用事实仍然有效；把 USD `0.01582704` 解释为用户设定的金额硬上限是错误的。批准问题明确将约 USD `0.01583` 表述为估算而非账单保证，用户批准了一次请求及其可能费用。详见 `R30-ai-timeout-budget-execution-20260917.zh-CN.md`。

## 已完成的离线工作

- 从 R29 提交 `d7279155b8965423d55fc71adfe6d50b4079fa06` 创建隔离工作树 `D:\Workspace\Projects\ai-quant-pilot\trade-plan-monitor-r30` 和分支 `codex/r30-ai-timeout-budget`。
- 保留原 main 工作树的 8 个无关未提交文件，未暂存、修改、清理、stash 或提交它们。
- 为 `AIProviderConfig` 增加可选的 `transport_timeout_seconds` 与 `read_timeout_seconds`。默认均为 `None`，因此既有生产行为仍将 `timeout_seconds` 同时用于连接/读取/写入/连接池和外层截止。
- 准备一个 R30 候选：连接/写入/连接池 `30` 秒、读取 `60` 秒、provider 整体 `65` 秒、终态观察 `66` 秒、清理最多 `15` 秒、总硬边界 `81` 秒。
- 模型、原文、提示词、`max_tokens=8192`、temperature、思考模式、JSON 响应格式、streaming 标志、端点与单消息请求体均与 R29 不变。直接比较本地真实 R29/R30 材料文件得到 `sourceBytesEqual=true`、`promptBytesEqual=true`、`bodyEqual=true`，且规范请求体 SHA-256 均为 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`。
- 在 `data/r30-ai-timeout-budget-review/` 下生成被忽略的精确审阅包；包 SHA-256 为 `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`。
- 在未上传计划数据的前提下重新核对 DeepSeek 官方路由/模型/价格页面及 HTTPX/Python 超时语义。冻结审阅快照按固定请求边界得到一次请求 USD `0.01582704` 的保守估算。随后直接打开官方页面时，`POST https://api.deepseek.com/chat/completions` 保持不变，但页面显示了更高的峰值/非峰值价格，对应估算为 USD `0.05884032` 与 USD `0.02942016`；真实账单仍未知。

## 离线证据

RED 阶段因 provider 模型尚不接受独立传输/读取预算而失败。完成最小实现后：

- R30、R29 聚焦验收与 R30 超时单元测试：**27/27 通过**。
- 更广的 provider/提取/配置生命周期/R26/R27/R28/R29/R30 回归组：**188/189 通过**。唯一失败是 `test_production_app_defaults_to_direct_ai_configuration`；隔离工作树有意不含已构建的前端资产，因此在 `ProductionAssetError: Installed Web assets are unavailable` 停止，未进入 AI 超时或候选链路。
- 同一更广回归组明确排除该已知资产依赖用例后：**188 通过，1 deselected**。
- 候选提交前，全部改动 Python 文件的 Ruff 与 `git diff --check` 通过。
- 缩放延迟响应测试用 `40 ms` 模拟晚于原 `30 ms` 边界、早于新 `65 ms` 整体边界的响应。它走过生产 provider、提取、严格 schema、映射校验和字面 oracle。结果被接受，AI 物理启动计数为 1、行情启动为 0、隔离业务表全为 0、清理完成，audit/journal/仅供复核产物一致。
- 独立的缩放硬截止测试证明了取消传播、`OVERALL_DEADLINE`、单次启动与安全错误元数据。其余聚焦测试保留 CONNECT/READ/WRITE/POOL 可观测分类，在联网前拒绝第二次请求，回执未知时零重提停止，并从证据中排除秘密。

时间缩放与 fake transport 只证明本地控制流，不证明真实 DeepSeek 性能。HTTPX `MockTransport` 不模拟网络时序。任何 mock 结果均不作为真实成功报告。

## 外部调用与状态记账

R30 准备期间：

- DeepSeek POST：`0`；
- 行情调用（包括 `trade_cal`）：`0`；
- 余额/模型列表/账户探测：`0`；
- 消耗真实 claim：`0`；
- 创建真实隔离运行数据库：`0`；
- 计划保存/激活、持仓、委托、成交、Webhook：`0`。

被忽略的审阅包是唯一 R30 本地数据产物。真实配置、凭据、供应商响应或账户数据均未复制到工作树。

## 精确批准事项

真实运行前，审阅者必须检查：

- `data/r30-ai-timeout-budget-review/egress-review.zh-CN.md`；
- `data/r30-ai-timeout-budget-review/egress-material.json`；
- `data/r30-ai-timeout-budget-review/manifest.json`。

批准的准确含义是：按包 SHA-256 `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`，向 `https://api.deepseek.com/chat/completions` 发送恰好一次非流式 `LITERAL` POST，零重试、零行情，并接受其可能费用。USD `0.01582704` 是冻结快照披露的保守估算，已明确不是账单保证，也不是用户设定的金额硬上限；真实分词、缓存分配、输出长度、计费、税费及账户调整均声明为未知。后来披露的较高估算没有改变已批准的路由、内容或物理调用上限。它不授权第二次 POST、账户探测、行情调用、计划保存/激活或交易动作。

执行时预检必须使用显式只读原配置路径，校验配置 SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`，确认分支干净已提交且 claim 未使用，并重新核对官方路由与价格。当前本地日期门禁为 Asia/Shanghai `2026-09-17`；错过后必须披露并更新本地门禁、重新干跑，不能静默发送。
