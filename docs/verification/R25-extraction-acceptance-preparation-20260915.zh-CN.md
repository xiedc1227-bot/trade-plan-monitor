# R25 提取专用验收准备记录

英文原版为 `R25-extraction-acceptance-preparation-20260915.md`，本文是等价中文审阅副本。提案 `R25-20260916-AM-EXTRACT-3`；运行 `r25-20260916-a`。状态 **OFFLINE_PASS / SPECIFIC_EGRESS_APPROVAL_PENDING / LIVE_NOT_RUN / ZERO_EXTERNAL_CALLS**。

## 原文与隐私清单

三份拟议输入全部是版本库内的合成测试夹具。`LITERAL` 来自 `tests/fixtures/ai/explicit-plan-literal-source-v3.json#sourceText`；`SEM-AMB-01` 和 `SEM-UNS-01` 来自 `tests/fixtures/ai/explicit-plan-semantic-acceptance-v2.json` 中的同名 ID。冻结原文 SHA-256 依次为 `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`、`26760155a5c87044b514ab2cff3a162dcef45d739dc863961ee629573e9e991e` 和 `23401380e6f188abe6da02c2e77db8e4f67bb8e7133efa191329cf505baa11b0`。

夹具含有合成的交易规则与持仓表述。离线模式清单未发现邮箱地址、疑似手机号、12 位以上疑似账号、凭据词或券商名称。它们不读取真实账户、生产持仓或生产计划。该分类不替代具体内容外发批准；精确原文和完整提示词已在本地展示供审阅。

## 已实现候选

- `scripts/r25_extraction_acceptance.py` 默认仅干跑且不创建占位。`--execute` 必须同时满足精确授权串、精确运行 ID、拟议日期/时段门禁及通过的离线预检。
- 它预留端口 `18770`，原子占用全新隔离目录，启动生产参考生命周期，并在 AI 之前仅允许一次 `trade_cal` 物理启动。其他行情上限全部为零。
- 所有新调用共享 900 秒截止边界，随后协作清理不超过 20 秒。
- 随后使用生产配置的 AI 组合，并在隔离会话中显式覆盖 v5/8192；每份冻结原文只允许一次物理启动，固定顺序为 `LITERAL`、`SEM-AMB-01`、`SEM-UNS-01`。被忽略的真实 `config/app.yaml` 仍保持原显式值不变。
- 每个终态结果都必须存在已记录的无内容诊断，且 `modelMatchesConfigured=true`。进入下一用例前先运行冻结的字面及语义 oracle。任何失败、模型不匹配、缺失诊断、回执/查询不确定或超时，都会停止且不重提。
- 已验证结果视图写入 `validated-review-results.json`；永不保留供应商原始内容。审计保持脱敏。清理阶段验证 `plan_version`、`plan_activation_state` 和 `active_plan` 为空，因此提取不能变成激活。

## 离线验证

在 `2026-09-15T15:00:34+08:00`，干跑预检只读取本地配置及证书元数据，未打印凭据或直连地址。结果显示 AI 别名/密钥与行情 Token/连接地址均存在、股票证书就绪、18770 端口可用；`ready=false` 的唯一原因是拟议的 2026-09-16 门禁当前尚未到达。该过程未请求 AI 或行情，也未探测余额或模型列表端点。

R25 聚焦测试：**7 项通过**，另有一个既存 Starlette/httpx 弃用警告。覆盖候选身份/上限、精确请求材料、中英文审阅包生成、按序提前停止、冻结字面/语义 oracle、查询不确定且不重提，以及精确执行门禁。R25/R23/R24 加 v4/语义提取回归组 **46/46** 通过。候选与聚焦测试的 Ruff 检查通过。

另一个历史 R14/R17/R18/R20 接线组为 **39/40** 通过。唯一失败的是既存 `test_ai_guard_allows_only_one_approved_prompt_and_counts_failed_attempt`：该测试载荷漏掉了未改动 R14 传输守卫早已要求的 `temperature=0` 字段。R25 未修改该守卫或测试，其精确请求材料测试已证明包含 `temperature=0`。因此将其如实记录为既存历史测试漂移，不在 R25 范围外顺手修改。

生成的本地审阅包为 `data/r25-extraction-review/egress-review.md`，并有等价的 `egress-review.zh-CN.md`。它包含每份完整原文和逐字完整的唯一 user 提示词，而不只是哈希；明确写明接收方 DeepSeek、目的地址 `POST https://api.deepseek.com/chat/completions` 及三项用途。Authorization 值被有意排除。审阅包 SHA-256 分别为英文 `6b0d300b0404a24b690281f9336a013f430b72ec9371be069b82c66aab92833d`、中文 `4d689c24721901e3de8ee38d1accdfdc6f3f54433c36c446a5dff11ce04a32d0`。

## 当前官方路由与价格快照

2026-09-15 读取的 DeepSeek 价格页把别名 `deepseek-v4-pro` 标记为模型版本 `DeepSeek-V4-Pro-0813`，并说明 2026 年 9 月 14 日后继续提供 V4 Pro API 服务。其工作日峰值价按每百万 Token 计为：缓存命中输入 0.044 美元、缓存未命中输入 1.32 美元、输出 3.96 美元；非峰值减半。拟议的 Asia/Shanghai 09:30～09:45 在周三对应 UTC 01:30～01:45，因此属于文档所列工作日 UTC 01:00～04:00 峰值时段。来源：https://api-docs.deepseek.com/quick_start/pricing/ 和 https://api-docs.deepseek.com/api/create-chat-completion/。

用传输层 19,000 UTF-8 字节提示词上限作为保守的 19,000 输入 Token 算术边界，采用峰值缓存未命中输入价、每次用满 8,192 输出 Token 且共三次，请求费用为税前及账户特定调整前 `0.17256096` 美元。这只是估算，不是保证收费或账户余额。真实分词、缓存状态、输出长度、价格变化、税费、行情费用和余额仍未知。未授权也未执行充值或外部账户探测。

## 结论与剩余门槛

R25 离线准备证明候选的本地边界和失败行为；不证明真实供应商结果。本轮没有 AI POST、`trade_cal`、其他行情请求、Webhook、券商动作、持仓变化、计划激活或已消耗的 R25 占位。

父任务尝试发起真实执行时，被系统自动审批拒绝，原因是准确的潜在敏感载荷及外部目的地尚未得到具体批准。因此，剩余批准范围很窄：用户必须先检查生成的精确审阅包，再明确批准把其中展示的三份原文/提示词载荷发送至所列 DeepSeek 端点，用于所列三项提取测试。本任务不会重新索取通用继续权限。
