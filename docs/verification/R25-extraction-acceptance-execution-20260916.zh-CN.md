# R25 提取专用验收执行记录

英文原版为 `R25-extraction-acceptance-execution-20260916.md`，本文是等价中文审阅副本。提案 `R25-20260916-AM-EXTRACT-3`；运行 `r25-20260916-a`。状态 **EXTRACTION_ACCEPTANCE_FAILED / ALLOWANCE_CONSUMED / CLOSED / FULL_WORKFLOW_NOT_PROVEN**。

## 结果

Asia/Shanghai 09:30 核对时，DeepSeek 当前官方页面仍将 `deepseek-v4-pro` 标记为 `DeepSeek-V4-Pro-0813`，记录了 `POST /chat/completions`，并保持每百万 Token 峰值价格：缓存命中输入 0.044 美元、缓存未命中输入 1.32 美元、输出 3.96 美元。来源：https://api-docs.deepseek.com/quick_start/pricing/ 和 https://api-docs.deepseek.com/api/create-chat-completion/。

用户对不可变本地审阅包给出精确批准后，最终离线预检于 `2026-09-16T09:41:23.794194+08:00` 在干净 HEAD `a67b76ca34c9dc1801c790ce45b23986eef12550` 上通过。会话于 `09:41:54.211503+08:00` 至 `09:42:24.947266+08:00` 运行，共 30.735763 秒。唯一一次 `trade_cal` 物理启动成功，当前日期参考校验通过，并持久化 399 条日历记录。

`LITERAL` 用例进行了一次 AI POST 物理启动，并得到无内容诊断：`status=PROVIDER_ERROR`、`stage=provider`、`providerErrorCode=TIMEOUT`、`path=unknown`、结束原因未知、无用量值、无返回模型匹配结果。其操作 ID 为 `8c00d923-dc5d-484e-9175-7e53d0d552b0`。由于保留元数据无法确认接收/完成及计费情况，候选将该用例分类为 `EXTRACTION_OR_DIAGNOSTIC_REJECTED`，立即停止且没有重提。`SEM-AMB-01` 与 `SEM-UNS-01` 均未发送。

AI 启动为 1/3：`LITERAL=1`、`SEM-AMB-01=0`、`SEM-UNS-01=0`。行情启动为 1/1，且仅 `trade_cal=1`；其他行情端点全部保持为零。重试和联网前拒绝均为零。AI 请求已物理启动但未返回用量，因此费用无法确定；行情数据费用及税费同样未知。

正常审计存在，`physical-attempts.json` 中最终 AI/行情预算快照与 `audit.json` 一致，清理状态为 `COMPLETE`，18770 端口无监听。全新运行目录作为已消耗的一次性占位保留，不得复用。`validated-review-results.json` 仅包含被拒绝用例的复核记录，没有保存已验证提取结果。`plan_version`、`plan_activation_state`、`active_plan` 和 `plan_extraction_review` 均为零。

SQLite 只读检查使用 `mode=ro` 与 `PRAGMA query_only=ON`。`trading_calendar` 有 399 行；`alembic_version` 与 `monitor_sequence` 各有一行。包括原文、版本、复核、激活、持仓、行情 K 线/报价、求值、提醒及投递表在内的其他全部业务表均为零行。

## 证据完整性

- `audit.json`：`32a1da86d7f537a7144b255d5fadac153767339a0d157206ae05a951c9f7be6a`。
- `physical-attempts.json`：`662746e3ed56e0e18bad82c5229dfec216d4815f90ed4d1bc0b5027cb0040dc2`。
- `monitor.ai-extraction-diagnostics.jsonl`：`8bc1613700b7d5e352df4f1efb357f977f21f682e4cee697e3894d912aa3c869`。
- `validated-review-results.json`：`0415f10dfa5ff0dc7b003b28a1cf4d31245dc62628a45edcaad86ca916729e21`。
- `monitor.sqlite3`：`2dc2c988d34a1b1eed196bbc58bcdef8ab01e879aa83c4d92ccca772327612ec`。
- 真实 `config/app.yaml`：`89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`，与此前预检记录一致。

游标密钥因文件系统权限禁止普通检查，故有意排除在哈希/输出之外。本文不保留凭据、直连地址、授权请求头、原文、提示词、供应商原始内容或异常正文。

## 结论边界

R25 证明固定候选只准入一次成功的日历前置调用，仅尝试首个已批准 AI 用例，在首次供应商超时后停止，保留无内容诊断，并完成隔离清理且没有激活或保存计划。它不证明 `plan-extract-v5` / 8192 提取成功、字面忠实度、任一语义阻断、供应商模型匹配或人工复核。

证据无法区分连接、TLS、写入、读取、远端处理或本地超时原因，也无法证明供应商是否收到或计费该超时请求。已消耗的占位、运行 ID、窗口和额度不得复用。不得激活计划、自动开启 R26，也不得在没有全新有界候选及授权时再次发起真实请求。
