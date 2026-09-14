# R00 整改基线与验收预期索引

日期：2026-09-12（Asia/Shanghai）。本文为中文审阅副本；`baseline.md` 是英文正式基线，两者语义等价。

## 范围与来源

- 仓库：`D:/Workspace/Projects/ai-quant-pilot/trade-plan-monitor`。
- 已重新核对分支与 HEAD：`main` / `bcea43f9cdd28a7fee45cdb4db10cf63e6bbac34`。
- 本 R00 仅新增文档。不改变业务逻辑、计划、持仓、数据库、凭据、供应商、通知或交易行为。
- 输入是不可变验收材料目录 `C:/Users/xiedc/.codex/visualizations/2026/09/12/01a093fc-f8d3-73d1-b759-ad76c7451697/business-acceptance/` 中的 `acceptance-report.md`、`scope.json`、`verification-record.json`、`remediation/tasks/{plan,todo}.md` 及其中文对照。
- 历史验收证据是预期与缺陷刻画，不是这次重新核对工作区版本的通过结论。

## 原有工作区

R00 开始前已有下列十二项用户改动，且仍归用户所有：`config/app.example.yaml`；`docs/specifications/monitoring/SPEC-ai-plan-drafting.md`；`docs/specifications/monitoring/SPEC-ai-plan-drafting.zh-CN.md`；`src/trade_plan_monitor/config.py`；`tests/unit/test_config.py`；`web/src/components/market-index/MarketIndexSparkline.vue`；`web/src/components/market-index/marketIndexChartOptions.ts`；`web/src/layouts/AppShell.vue`；`web/tests/e2e/accessibility.spec.ts`；`web/tests/e2e/dashboard.spec.ts`；`web/tests/unit/AppShell.spec.ts`；`web/tests/unit/marketIndexChartOptions.spec.ts`。

R00 已重新计算 `scope.json` 中十五个关键文件的全部 SHA-256，均一致。没有覆盖、reset、暂存或纳入任何原有改动。

## 离线复现边界

执行前已审阅 `ai-review-probes.py` 和 `market-review-probes.py`，随后以 `PYTHONDONTWRITEBYTECODE=1`、`.venv\\Scripts\\python.exe -B` 重跑。它们使用 `TemporaryDirectory`、假 AI/SDK、虚拟时钟与合成/样例数据；不会读取生产配置，也不会调用 AI、行情、Webhook 或交易服务。临时 SQLite 会在退出时删除。B1/B2 Playwright 缺陷复现已审阅但未重跑，因为两条 Python 复现已经完成 R00 的针对性确认；其历史结果仍只作为缺陷证据。

## 问题—证据映射

| 问题 | 验收预期 / 复现 | R00 结果与后继重点 |
|---|---|---|
| F01 P0 过期计划仍执行 | `market-review-probes.py` 的 M2：2026-09-01 结束日期在 2026-09-08 仍产生 `BUY_CORE_READY` 数量100和持久化 `RISK_BREACH` | 已离线确认；R01 必须在选择、上下文和提交统一执行有效期。 |
| F02 提醒恢复漏展示 | B1/B2 Chromium 反例：`snapshot -> alert` 与 `snapshot.required` 到达 LIVE 却未刷新提醒 | 保留历史隔离浏览器证据；R02 负责转为回归。 |
| F03 审核可绕过 | A1：缺少语义依据的假提取结果省略问题后可保存并激活 | 已离线确认；R04 负责服务端来源与审核绑定。 |
| F04 编辑后沿用审核 | A2：低价从6300改6200仍保留 resolved 审核与可激活性 | 已离线确认；R05 负责按内容哈希失效。 |
| F05 人工风险不可完成 | M1：`False` 允许 `BUY_CORE_READY`；`None` 在重启前后均为 `BLOCKED_DATA` | 已离线确认；R07 负责持久化且有范围的人工输入。 |
| F06 计划表达缺口 | S01/S04 要求五根完成K线的算术均量、五分钟风险、明确动作/数量/重复；当前契约无法无损表达 | 未修复、未重新解释；R08 定义契约，R09/R10 实现。 |
| F07 ANY 被隐式阻断 | M3：价格分支满足、量分支不满足仍为 `BLOCKED_RISK` / `BEARISH_VOLUME_EXPANSION` | 已离线确认；R06 只允许显式强制阻断。 |
| F08 普通修正需 JSON | 静态证据：九个 JSON textarea 且执行预览不完整 | 未改 UX；R12 负责普通表单与完整预览。 |
| F09 提示词契约漂移 | A3/当前单测预期：v2 SHA-256 为 `795a3d...1fe9`；进程内仅移除 `399107.SZ` 即恢复 `6d9ba...27daf` | 已离线确认；R03 负责明确提示词/Schema 版本。 |

## 场景预期映射

| 场景 | 不可变业务预期 | 基线状态 |
|---|---|---|
| S01 | 完成五分钟收盘在 [9.80,10.00] 且本根量 >= 前五根完成K线算术均量 x 1.5 -> 买100 | 无法忠实执行（F06）；不能以中位数替代。 |
| S02 | 两个价格端点包含；恰好1.5倍允许 | 现有组件仅确认包含区间和相等比较；不代表支持均量。 |
| S03 | 未完成五分钟K线不能产生按完成K线确认的提醒 | 有历史离线组件/集成证据；保留为回归预期。 |
| S04 | [10.80,11.00] -> 卖100；完成五分钟收盘 < 9.50 -> 风险 | 无法忠实执行（F06）；不能以 TACTICAL 或日收盘替代。 |
| S05 | 模糊描述不得虚构参数 | F03 A1 未能做到闭环；真实模型语义准确性仍未验证。 |
| S06 | AI 失败、格式错误或重大遗漏不得激活或伤害活动计划 | 历史离线覆盖不完整；F03 仍有审核旁路。 |
| S07 | 陈旧、乱序、重复、断线或部分数据不得虚构信号 | 历史离线覆盖不完整；F02 仍有浏览器恢复缺口。 |
| S08 | 重试/重启去重；确认不得改变实际持仓 | 有历史离线/浏览器证据；外部送达是至少一次而非收件人恰好一次。 |
| S09 | 更新、停用或过期停止新的可操作提醒 | F01 已重新确认失败；旧排队提醒的当前展示尚未确认。 |

## R00 验收状态

R00-A 已完成：已在不改变交易行为的前提下索引实际基线、用户原有改动、问题证据、场景预期与离线边界。外部验收材料中的原任务清单按要求保持不变；本地记录是串行执行链的完成证据。未宣称 F01–F09 任一整改已完成。
