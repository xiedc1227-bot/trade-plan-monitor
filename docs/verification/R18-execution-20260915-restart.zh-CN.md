# R18 同日上午重启执行记录——业务失败

英文原版为 `R18-execution-20260915-restart.md`，本文是等价中文审阅副本。方案 ID `R18-20260915-RESTART-105`；运行 ID `r18-20260915-b`。最终状态 **AI_INVALID_OUTPUT / BUSINESS_FAILED / SESSION_CONSUMED**。

## 执行与有界调用

已授权的替代候选于 `2026-09-15T09:40:26.803818+08:00` 启动，处于 09:40–09:45 准入门禁内。浏览器显示隔离服务正在运行且可监控，`trading_calendar` 及其他已认证行情能力均为就绪。固定 `LITERAL` 原文经正常浏览器页面向已配置的 `deepseek-v4-pro` 提交一次。

终态为 `INVALID_OUTPUT`。有界诊断记录阶段 `response`、原因 `FINISH_REASON`、`finishReason=length`、`modelMatchesConfigured=true`，尝试次数为一。报告用量为提示 5,077 token、完成 4,096 token，共 9,173 token。输出达到固定完成上限，未通过封闭契约；没有返回或保存草稿。

依照已批准的失败停止规则，没有重新提交字面原文，也没有发送 `SEM-AMB-01` / `SEM-UNS-01`。随后立即停止服务。审计因此把受控取消记录为 `FAILED` / `CancelledError`；隔离计划清理结果为 `INACTIVE`。

物理启动保持在硬上限内：

- DeepSeek：**1 / 3**，仅 `LITERAL`。
- 行情：**1 / 105**，仅 `trade_cal`。
- 联网前拒绝：两侧闸门均为 **0**。

## 业务证据

隔离数据库包含 399 条交易日历记录；计划版本、活动计划、激活状态、提取审核、持仓、分钟 K 线、五分钟 K 线、求值、提醒及投递尝试均为零。没有审核或激活计划，没有执行行情规则求值，也没有产生站内提醒。上述两次物理启动可能产生 AI 与行情费用；本文不声称具体金额。

R18 重启未通过业务验收。本候选及其授权均已消耗，不得重试。更早的候选 `r18-20260915-a` 仍单独记录为 `NOT_RUN_TIME_GATE / ZERO_EXTERNAL_CALLS`。
