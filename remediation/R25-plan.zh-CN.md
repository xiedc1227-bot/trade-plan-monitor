# R25 计划：提取专用真实验收候选

英文原版为 `R25-plan.md`，本文是等价中文审阅副本。状态 **OFFLINE_IMPLEMENTED / SPECIFIC_EGRESS_APPROVAL_PENDING / LIVE_NOT_RUN**。

## 目标与边界

- 为尚未证明的 `plan-extract-v5` / `max_tokens=8192` 真实供应商链路准备一个全新提取专用候选。
- 离线证明候选只按固定顺序 `LITERAL`、`SEM-AMB-01`、`SEM-UNS-01` 发送三份冻结合成夹具，首次失败或不确定后停止，且绝不激活计划。
- 保持生产提取合同：配置别名 `deepseek-v4-pro`、一条 user 消息、`temperature=0`、`thinking={"type":"disabled"}`、`response_format={"type":"json_object"}`、`stream=false`、供应商零重试及显式 `max_tokens=8192`。
- 准备阶段不调用 AI 或行情；不改变 `config/app.yaml`、凭据、持仓、生产数据库、历史证据、已消耗占位、Webhook 配置或券商状态。

## 候选合同

| 稳定 ID | 合同 |
|---|---|
| R25-B01 | 提案 `R25-20260916-AM-EXTRACT-3`；运行 `r25-20260916-a`；拟议启动门禁为 **2026-09-16 09:30:00～09:45:00 Asia/Shanghai（含端点）**。该门禁仅为提议，尚未批准或消耗。 |
| R25-B02 | 全新根目录 `data/r25-extraction-acceptance/r25-20260916-a/`、全新 SQLite 数据库及预留回环端口 `18770`；不复用任何 R14/R17/R18/R20/R22/R23/R24 占位或证据。 |
| R25-B03 | 一个共享的 900 秒新调用边界，加最多 20 秒协作清理。不后台等待、不创建自动化、不跨日续跑。 |
| R25-B04 | 行情上限严格为一次 `trade_cal` 物理启动；其他行情端点上限全部为零。参考调用必须是第一个外部调用；失败或不确定将阻止全部 AI 调用。 |
| R25-B05 | AI 上限为三次物理 POST 启动，三份冻结输入各一次，零重试，严格按 `LITERAL`、`SEM-AMB-01`、`SEM-UNS-01` 排序。任何输入都不重提。 |
| R25-B06 | 字面 oracle 失败、回执/查询不确定、供应商结果非法/截断、诊断失败、返回模型不匹配或语义 oracle 失败，都会停止全部后续用例。 |
| R25-B07 | 成功的已验证结果只保留在隔离审阅产物及提取复核表中。`plan_version`、`plan_activation_state` 和 `active_plan` 必须为空。人工复核始终必需，绝不从通用执行授权推断。 |

## 业务 oracle

1. `LITERAL` 必须保留全部 15 条精确原文条款、每个冻结的原文路径/条款绑定与单位，以及全部冻结的复核前数值。仅来自历史人工测试补充的策略在人工复核前继续保持未解决。
2. `SEM-AMB-01` 必须匹配其冻结含糊性 oracle，保留 `UNRESOLVED_SEMANTICS`，且不可激活。
3. `SEM-UNS-01` 必须匹配其冻结不支持语义 oracle，保留 `UNSUPPORTED_SEMANTICS`，且不可激活。
4. 已验证审阅产物仅供后续人工检查；自动 oracle 通过不等同于人工复核、保存或激活决定。

## 批准与完成条件

精确本地审阅包生成于 `data/r25-extraction-review/egress-review.md`，并有等价的 `egress-review.zh-CN.md`。其中包含每次请求的完整原文、完整唯一 user 提示词、来源、原文/提示词 SHA-256、目的地址及固定请求体字段；凭据被排除。只有用户针对该文件展示的准确内容，明确批准为所列三项用途外发至 `https://api.deepseek.com/chat/completions` 后，才允许真实执行。

只有候选、聚焦测试、中英文计划/报告/交接、本地审阅包和干净本地提交均存在时，R25 离线准备才完成。真实业务验收仍未证明；必须另行启动候选并由人工明确复核本次最新已验证结果后，才可能继续。
