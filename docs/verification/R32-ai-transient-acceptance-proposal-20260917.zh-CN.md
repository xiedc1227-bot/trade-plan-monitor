# R32 隔离 AI 瞬态分类验收方案

英文原版为 `R32-ai-transient-acceptance-proposal-20260917.md`，本文是等价中文审阅副本。提案 `R32-20260917-V6-LITERAL-TRANSIENT-ACCEPTANCE-1`；候选运行 `r32-20260917-a`。状态 **OFFLINE_PREPARATION_ONLY / LIVE_EXECUTION_NOT_AUTHORIZED / ZERO_EXTERNAL_CALLS**。

## 范围

R32 只准备但不执行一个新的隔离候选，用于验证 R31 的 `transientKind` 契约能否进入既有真实提取链。候选保持 R30 v6 `LITERAL` 请求不变，不增加提取行为，不放宽 schema，也不增加重试、行情调用、账户探测、计划持久化、激活、监控、持仓变更、委托、成交或交易动作。

R30 仅作为历史证据。其已消费 claim 和运行身份绝不得复用。R32 使用全新的提案、运行、operation、幂等键、claim 根目录、运行目录、audit、物理尝试 journal、诊断 sidecar、数据库与复核产物。

## 冻结请求与本地预算

- 目的地：`POST https://api.deepseek.com/chat/completions`；
- 原文 SHA-256：`0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`；
- 提示词 SHA-256：`7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba`，UTF-8 长度 `19,359` 字节；
- 规范请求体 SHA-256：`c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`；
- 模型 `deepseek-v4-pro`、提示词版本 `plan-extract-v6`、`max_tokens=8192`、`temperature=0`、`thinking={"type":"disabled"}`、`response_format={"type":"json_object"}`、`stream=false`，且只有一条 user 消息；
- 连接/写入/连接池 `30s`、读取 `60s`、provider 整体 `65s`、终态观察 `66s`、清理最多 `15s`、总硬边界 `81s`；
- 最多 `1` 次 AI 物理 POST、`0` 次重试/重提、`0` 次行情调用、`0` 次账户调用。任何终态结果（包括 `UNKNOWN`）都会停止候选。

这些值必须从真实本地原文、提示词与请求材料重新计算，不能仅因本文重复记录就视为通过。生产默认值和真实配置保持不变。

## 授权与默认行为

`python -m scripts.r32_ai_transient_acceptance` 是离线干跑，不能创建或消耗 claim。精确审阅包生成也只在本地进行。真实执行要求所有正向门禁通过、显式配置路径、准确的新 R32 授权令牌、准确运行 ID、未消费的 R32 claim，以及绑定所生成包哈希和所述目的地的用户全新明确批准。

R25、R30、历史“默认授权”及“继续”的指令都不构成 R32 真实批准。在取得新批准前，不允许任何 AI、行情、账户、路由、价格、DNS、TCP、TLS、代理、证书或其他网络请求。

## 验收标准

| ID | 标准 |
|---|---|
| R32-A01 | 默认命令和审阅包命令发起零网络调用，且创建或消费零执行 claim。 |
| R32-A02 | 全新 R32 claim 仅允许一次物理 POST，第二次准入在网络 I/O 前被拒绝；绝不复用 R30 身份或 claim。 |
| R32-A03 | 生成的包包含准确完整的本地原文与提示词、固定请求字段、目的地、限制、费用不确定性，以及相对 R30 无发送字段差异的对比；不含凭据。 |
| R32-A04 | 重新计算原文、提示词、提示词字节长度及规范请求体哈希并匹配冻结值；manifest 记录组件及整包哈希，任何篡改都会阻断预检。 |
| R32-A05 | 离线 fake transport 失败经过真实 provider/extraction/sidecar/assessment 路径，输出 sidecar v3，只保留封闭的 `transientKind`，且不保留注入的异常正文、响应正文、Header、凭据、提示词、URL 或 IP 地址。 |
| R32-A06 | 离线 fake 成功经过生产 provider、提取、严格 schema、mapping、字面 oracle 与复核回执检查；失败和 `UNKNOWN` 均终止且不重试或重提。 |
| R32-A07 | 取消遵守总硬截止；清理、audit、物理尝试 journal 与诊断证据一致；独立查询的全部业务表保持为空。 |
| R32-A08 | 聚焦回归与 Ruff 通过。明确列出依赖已安装 Web 资产的已知基线排除项，不禁用或弱化测试。 |
| R32-A09 | 中英文方案、准备报告、精确审阅副本、manifest 元数据与 handoff 的 ID、哈希、限制、边界及验收结果一致。 |
| R32-A10 | 离线准备结束时真实外部调用 `0`、重试 `0`、行情/账户调用 `0`、创建或消费真实 R32 claim `0`；真实执行仍等待明确批准。 |

## 停止条件

任何哈希、审阅包、双语、schema、mapping、oracle、清理、audit、journal、业务表、配置、分支或 claim 不一致都会停止准备。未来真实候选必须在第一个终态结果后停止。`TRANSIENT / UNKNOWN` 是终态，不得因此触发另一次付费请求。
