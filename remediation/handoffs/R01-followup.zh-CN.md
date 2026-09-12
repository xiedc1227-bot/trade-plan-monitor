# R01 补充交接：提醒活动计划返回契约

日期：2026-09-12（Asia/Shanghai）。`R01-followup.md` 是英文正式版；本文为语义等价的中文审阅副本。任务：`01a09521-cfc7-7921-922c-c5d848d5ba29`；协调任务：`01a093fc-f8d3-73d1-b759-ad76c7451697`。

## 完成情况与提交

已在提醒活动计划查询返回契约范围内完成获授权的 R01 回归补修。这是既有有效期约束的必要纠正，不是新产品能力，也不是 R09 工作。

- 基线：`main/b16523723c6cd4e1acc90c13f61fce1094706289`。
- 实现及回归提交：`2f0b1b407faac80574e0752b311b07e06984e78f`，`fix: 修复提醒活动计划返回契约`。
- 本双语交接另作后续纯文档提交。其身份就是包含本文件对的提交，可用 `git log -1 --format=%H -- remediation/handoffs/R01-followup.md` 查询；不嵌入循环自引用哈希。

实现提交精确修改：

1. `src/trade_plan_monitor/notifications/outbox.py`
2. `tests/integration/test_notification_delivery.py`
3. `tests/integration/test_alert_production_composition.py`

本交接提交仅新增本文及 `remediation/handoffs/R01-followup.md`。本次不修改规格，因为补修恢复的是已记录的 R01 契约，而不是变更契约。

## 根因与纠正后的行为

`AlertOutbox._active_plan_for_event` 声明返回 `TradePlan | None`，但 R01 提交 `099e41e119d9bca05b7cbf6834a696e0b1a9b6ed` 在“没有活动计划行”和“活动 identity 与保留提醒不匹配”两个分支引入了 `False` 返回。两个公开调用方只检查 `None`，所以 `False` 越过保护后，在真实 `GET /api/v1/alerts` 组合及投递策略检查中访问 `.activation` 并抛出 `AttributeError`。

两个正常缺失分支现在返回 `None`，与声明边界一致。因此：

- 没有活动计划的提醒会保留，但既不是当前可操作，也不允许投递；
- 不可变计划 identity 已被替换的提醒会作为历史记录保留，`currentActionable=false`，并且既不可操作也不可投递；
- 当前活动且目标日期有效的计划仍可操作并允许投递，包括既有日期区间策略的两个包含边界；
- 已到期的普通排队提醒仍会保留，但不能发送；
- 受限历史例外保持不变：跨日创建的 `RISK_BREACH` 只有在原目标交易日有效时才允许投递；
- 活动计划 JSON 损坏或 payload/hash 不一致时仍抛出 `OutboxStorageError`；没有吞掉异常，也没有增加宽松降级。

提醒查询及已读确认不会修改持仓。既有原子确认/持仓隔离回归继续通过。

## RED 与 GREEN 证据

所有命令均使用 `.venv/Scripts/python.exe -B`、隔离临时 SQLite/配置、假供应商或本地 TestClient，并加 `-p no:cacheprovider`。

- 既有生产组合 RED：聚焦的 `GET /api/v1/alerts` 回归因 `AttributeError: 'bool' object has no attribute 'activation'` 失败：`1 failed, 1 warning in 1.79s`。
- 新增回归 RED：覆盖缺失/替换计划的两个公开策略方法及缺失/替换提醒查询路径：`6 failed, 1 warning in 2.40s`。
- 最小修复后上述六项 GREEN：`6 passed, 1 warning in 1.72s`。
- 最终通知投递与生产提醒组合文件：`40 passed, 1 warning in 4.42s`。其中包含有效/到期/当前投递边界、历史官方收盘风险例外、损坏计划存储、确认隔离及真实提醒查询组合。
- R01 生产有效期集成文件（`test_live_pipeline_acceptance.py`、`test_ten_symbol_runtime.py`）：`67 passed in 21.41s`。
- 计划域有效期策略：`148 passed in 0.20s`。
- 三个实现文件的 Ruff lint 通过，`git diff --check` 通过。仅格式检查在 `outbox.py` 与 `test_alert_production_composition.py` 的新增 hunk 之外报告既有基线排版差异，未改写它们；本次扩展的 `test_notification_delivery.py` 通过格式检查。

RED 记录位于 `C:/Users/xiedc/.codex/visualizations/2026/09/12/01a09521-cfc7-7921-922c-c5d848d5ba29/R01-followup-red.md`。

## 完整离线后端结果与无关失败

检查测试边界后，完整命令 `.venv/Scripts/python.exe -B -m pytest -m "not live" -q -p no:cacheprovider` 运行 39 分 17 秒后完成，结果为：

- `2390 passed`
- `1 skipped`（Windows 上的平台特定 POSIX owner 用例）
- `4 deselected`（须明确授权的真实 Tushare/AI 契约测试）
- `2 failed`

两个失败均为与本补修无关的 R07 OpenAPI 门禁遗漏，单独复现为 `2 failed in 1.99s`：

1. `test_openapi_change_requires_bilingual_spec_approval`：生成摘要 `fe3305aaf31db3eb8314675ab74790b40fc6e3ea08f44f69679127434bb001e3` 未写入本地 Web 双语规格。
2. `test_openapi_contains_only_approved_paths_and_public_error_schemas`：R07 路径 `/api/v1/manual-event-risk` 和 `/api/v1/manual-event-risk-confirmations` 未加入 `APPROVED_PATHS`。

两个路径及其 OpenAPI 输出均来自 R07 提交 `beff0410150813e64a242a3821a299090d963e9b`；本补修没有修改路由、生成契约、OpenAPI 快照或本地 Web 规格。R07 的更广泛 `pytest -x` 当时先被本次修复的 R01 提醒异常阻断，因此该交接未暴露后续门禁失败。问题留给协调任务安排；本次严格限界任务没有扩展成无关 OpenAPI 修复。因此 R01 补修的聚焦检查为绿色，但不声称整个后端全绿。

两个最慢的离线容量节点也已成功完成。十标的/252 日节点约 23 分钟，历史记录约 25.2 分钟；traced-heap 节点约 10 分钟，历史记录约 12.0 分钟。没有使用真实 AI、行情额度、外部通知、券商/交易调用、生产数据库、真实计划/持仓、配置或凭据。

## 工作区保护与审阅

12 项用户自有修改保持起始时的精确字节；最终复核的有序路径/SHA-256 清单摘要为 `00ac48879c89c722f538e88e84e1d6dccb82b2860fd08252199164a6a934eee7`。4 个 R00 未跟踪文档也保持精确字节并继续未跟踪；其清单摘要为 `f52aeaf1269d09a3f9807de2c5ae18faff06b3f5577a5f2aee1ee1f0cf88e408`。未执行 stash、reset、checkout、push、发布、真实数据写入或无关暂存。

五维审阅未发现本补修的正确性、安全性、架构、性能或可读性阻断。它未增加依赖或查询，保留损坏存储的明确错误，并将行为限定在声明的可空返回边界。较大的测试差异是有意的行为覆盖，不是生产复杂度。

## 下一步

按显式完成回调协议，协调任务负责创建后继。协调任务核验本交接及实现提交后，可使用 `gpt-5.6-sol` / `high` 启动已授权的 R09；本执行任务不创建后继。R09 实施前必须重读实际 HEAD/工作区、R08 的有限显式计划设计及本文件对。无关的 R07 OpenAPI 门禁遗漏继续保持可见，不能误当作 R09 语义变化。R14 真实调用仍须另行获得有边界授权。
