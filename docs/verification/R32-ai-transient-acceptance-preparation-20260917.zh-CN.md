# R32 AI 瞬态分类验收准备记录

英文原版为 `R32-ai-transient-acceptance-preparation-20260917.md`，本文是等价中文审阅副本。状态 **OFFLINE_COMPLETE / EXACT_REVIEW_PACKAGE_READY / LIVE_EXECUTION_NOT_AUTHORIZED / ZERO_EXTERNAL_CALLS / ZERO_REAL_CLAIMS**。

## 已完成范围

R32 在隔离工作树 `D:\Workspace\Projects\ai-quant-pilot\trade-plan-monitor-r32` 的 `codex/r32-ai-transient-acceptance` 分支准备，基于 R31 提交 `ca7e878fea27f1a9a602915a9a48cbfd80a83cf6`。主工作树继续保持在 `e947397d373aa6ed79c5e88f16145eedf14053f0`，其 8 项无关改动均被保留。

离线候选使用提案 `R32-20260917-V6-LITERAL-TRANSIENT-ACCEPTANCE-1` 与运行 `r32-20260917-a`。它具有全新的 R32 claim 根目录、运行目录、operation 与幂等身份、audit、物理尝试 journal、sidecar、隔离数据库和复核产物，不复用已消费的 R30 claim 或 `r30-20260917-a` 身份。

默认命令为 `DRY_RUN_NO_NETWORK`。精确审阅包生成也只在本地进行。真实执行还要求 `--execute`、显式配置路径、准确授权令牌 `R32_20260917_LITERAL_ONE_AI_ZERO_MARKET_TRANSIENT_ACCEPTANCE`、准确运行 ID、全部正向门禁、未消费的 R32 claim，以及用户全新的明确批准。当前没有提供或推断出该批准。

## 重新计算的冻结请求

在不显示原文或提示词文本的情况下，已解析并比较 `D:\Workspace\Projects\ai-quant-pilot\trade-plan-monitor-r30\data\r30-ai-timeout-budget-review\` 下真实 R30 `egress-material.json` 与生成的 R32 材料。结果为：

- `sourceBytesEqual=true`，原文 SHA-256 为 `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`；
- `promptBytesEqual=true`，提示词 SHA-256 为 `7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba`，UTF-8 长度 `19,359` 字节；
- `bodyEqual=true`，规范请求体 SHA-256 为 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`；
- 历史 R30 包 SHA-256 为 `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`。

候选仍是一次非流式 `POST https://api.deepseek.com/chat/completions` 请求，模型 `deepseek-v4-pro`、提示词版本 `plan-extract-v6`、`max_tokens=8192`、`temperature=0`、`thinking={"type":"disabled"}`、`response_format={"type":"json_object"}`，且只有一条 user 消息。相对 R30 没有发送字段差异。

## 精确本地审阅包

完整原文与提示词只出现在 `data/r32-ai-transient-review/` 下受控本地审阅文件中；本报告不重复其内容。包中不含凭据、授权值、供应商响应、异常正文、Header 或直连 IP 地址。

| 文件 | SHA-256 | 字节数 |
|---|---|---:|
| `egress-material.json` | `0d21ba5216c8ff5b70aea3bc50fdbb4f0a9ca43e55bf8890065f873c7bd0941f` | `25,613` |
| `egress-review.md` | `401cc23111147d3389b474e5e2211fd2cac9110ebee852d5ff7563602930f2c0` | `22,184` |
| `egress-review.zh-CN.md` | `3d196b44697168688510c1e5a851282e932e66431126c4a40e78e76838f7739d` | `22,080` |
| `manifest.json` | `5a60e76e4499a921d09351adb2d0e7b38e66a3525526354d176436ca8d0e3b13` | `570` |

按 `egress-material.json`、`egress-review.md`、`egress-review.zh-CN.md` 顺序计算的整包 SHA-256 为 `7832b7e80f791c6a9f58fb30e1bd1f18f1958c60e6d845557d9b4f5e0916bfda`。manifest 记录相同顺序、组件哈希、整包哈希及提案 ID。离线测试证明修改任一组件都会使包校验失败。

审阅包披露 R30 价格观察时间 `2026-09-17T10:22:27.399234+08:00` 及其历史峰值/非峰值估算，但明确标注它们只是历史快照，不是当前报价、账单保证或金额硬门槛。真实分词、缓存拆分、输出长度、计费、税费及账户调整仍未知。即使未来执行，供应商是否接收、处理和计费也可能仍无法确认。

## 候选限制与终态行为

- AI 物理 POST 上限 `1`；重试/重提 `0`；行情调用 `0`；账户调用 `0`；
- 连接/写入/连接池 `30s`；读取 `60s`；provider 整体 `65s`；终态观察 `66s`；清理最多 `15s`；总硬边界 `81s`；
- 任何终态结果都会停止，包括 `TRANSIENT / UNKNOWN`；
- 有效响应继续经过既有 provider、提取、严格 schema、mapping、字面 oracle 与复核回执校验；
- 瞬态响应使用 sidecar v3 与 R31 封闭 `transientKind` 契约，且不保留异常/响应内容；
- 生产默认值、真实配置、TLS 校验、代理行为、持仓、计划状态与提取 schema 均未改变。

R32 准备不需要真实配置，因此没有打开真实配置。既有只读执行门禁仍要求未来真实候选开始前匹配 SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`。

## 离线验证

- R32 聚焦集：**11/11 通过**，带一条既有 Starlette/httpx 弃用警告。
- R31 诊断面加 R27、R29、R30 与 R32 兼容组：**132/132 通过**，带同一条既有警告。
- R15 非资产用例：**2/2 通过**；两个参数化 `test_simulated_production_composition_selects_the_database_sidecar` 用例因隔离工作树不含已安装 Web 资产而明确排除。该已知基线已具名说明，未弱化。
- `scripts/r32_ai_transient_acceptance.py` 与 `tests/integration/test_r32_ai_transient_acceptance.py` 通过 Ruff。
- `git diff --check` 通过。

离线 fake 已验证：默认零执行、一次准入及第二次网络 I/O 前拒绝、确定性包与防篡改、真实 provider/extraction/sidecar/assessment 路径、v3 `CONNECT` 与 `UNKNOWN` 分类、内容脱敏、有效响应的 schema/mapping/oracle 成功、不确定回执停止、整体截止取消、清理完成、audit/journal 一致、零行情启动，以及 38 张业务表全部零行。这些 fake 不是 DeepSeek 可用性、处理或计费证据。

## 外部调用与 claim 记账

- 真实 AI 请求：`0`；
- 真实重试/重提：`0`；
- 真实行情与账户请求：`0`；
- 路由、价格、DNS、TCP、TLS、代理、证书或其他网络探测：`0`；
- 创建或消费真实 R32 执行 claim：`0`；
- R30 重放：`0`；
- 真实验收：**未运行**。

## 剩余授权门禁

R32 目前只准备好供人工审阅精确本地包。R25/R30 批准、历史“默认授权”及“继续”指令均不授权本次新 POST。若用户批准该精确包，后续轮次仍须在创建 claim 或开始网络 I/O 前执行本地不可变门禁及任何必要的当前官方路由/价格复核。本轮不包含任何 R33 动作。
