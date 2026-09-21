# 恢复评估事务验证 — 2026-09-21

> 英文文件为规范输入；本文为成对中文审阅副本。续接 `6dff7ae`；不是 RR012/RR013 完整验收或部署验收。

## 范围与边界

此前两个提交 `964fde2` 和 `6dff7ae` 已推送到 `origin/codex/consolidate-r19-r32`；本增量开始前远端读取确认 head 为 `6dff7ae591c2dae33683cb3c447fd6bc2125f4f9`。本增量仅通过严格、显式启用的构造参数 `recovery_delivery`，将既有初始 HOLD 入队辅助方法接入两类评估服务。生产工厂/装配和通知发送保持不变。该选项不是发送保护：现有发送器不检查新元数据。

事务边界包含判断认领/结果、规则或风险/episode 转换、投影、规范提醒、交付元数据和审计。失败时不得发布已回滚的判断/提醒事件。旧版行情获取和官方收盘待处理准备在该事务之前已提交，继续保持持久化。重复判断或去重跳过不改写分类，不虚构来源；无意图评估不创建交付元数据。缺失历史记录仍需独立有界重建。

设计审查发现既有辅助方法存在时钟不匹配：工作单元默认使用 UTC，普通入队会规范化任何带时区的时钟，但该辅助方法将原始时钟传给只接受上海时区的仓储。现改为传入既有规范化 `_now` 方法；规范来源时间戳和评估器时间校验不变。未使用真实数据库/配置、行情源或通知渠道；未引入依赖、迁移、生成 Schema 或 UI 变更。

## 测试先行与审查证据

- 时钟兼容：UTC/UTC-4 两个示例在一行辅助方法修复前因 `ValueError` 失败，修复后与存储/入队回归一起通过。这解决集成前置条件，不放宽时间戳校验。
- 评估器 RED：构造参数尚不存在时，24 失败 / 3 通过。核心实现后 36 项通过；修正 fixture 并增加无意图、规范等价、重复不回填及双意图原子性用例后，最终覆盖 48 项。注入元数据/审计 SQL 失败，证明回滚后可成功重试；第二次写入失败时两条显式意图全部回滚。最终独立代码审查在此仅存储增量范围内未发现剩余实质问题。
- 实现子任务使用 `gpt-6-astra` / `high`；独立审查使用 `gpt-6-astra` / `xhigh`。这些设置不证明主任务模型/强度。按用户此前选择，继续跳过额外跨模型审查。

## 实际验证

| 命令 | 实际结果 |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_delivery_eligibility_storage.py -k normalizes_the_outbox -q --tb=short` | 修复前：2 失败、40 排除、1 项既有警告；失败于上海时区时钟校验 |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_delivery_eligibility_storage.py tests/unit/test_notification_outbox.py -q --tb=short` | 修复后：88 通过、1 项既有警告、6.09 秒 |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_recovery_alert_eligibility.py -q --tb=short` | 实现 agent 源码冻结后：48 通过，8.22 秒 |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | 通过 |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI 快照与前端类型均为最新 |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | 源码冻结后最终功能回归：3241 通过、4 项既有失败、1 项既有跳过、4 项 live 排除、1 项既有警告；489.73 秒 |

全部 50 个新增用例（48 个事务用例及 2 个时钟用例）均包含在本次最终功能运行中。4 项失败与此前报告完全一致：规范指数 head 更新时间、pending-close 指数错误参考健康状态、行情源 TIMEOUT 与 TRANSIENT 分类，以及 R14 模拟载荷被 temperature 门禁拒绝。未观察到新增功能失败；完整验收门禁仍未全绿。本轮未重跑未改动的重型回测验收文件，其此前全量运行证据仍见 `2026-09-21-runtime-recovery-increments.md`。既有跳过项为 Windows/POSIX 所有权边界。未删除、跳过或放宽失败断言。

显式评估器测试使用 UTC 工作单元时钟。探索性的旧版 UTC fixture 在提醒入队前复现了另一项既有默认路径错误：`_persist_projection_dependencies` → `HealthRepository.upsert_symbol` → `MonitorEventDraft.occurred_at` 拒绝 UTC 值。不传 `recovery_delivery` 时同样失败，因此未扩展本切片去修复。旧版集成 fixture 保留既有上海时区时钟契约。入队规范化修复不表示全部旧版仓储接受 UTC 时钟；生产装配变更前必须保留对此集成限制的说明。

空白检查通过。三个变更文档对的标题数量一致，规范化配对路径后技术字面量一致。高置信度秘密模式扫描覆盖全部 11 个变更文件，未发现匹配；这是限定范围的卫生检查，不是凭据审计。UTC 辅助方法修复及评估器实现已在此前要求的推送之后保存为本地提交 `60b0690` 和 `5970eba`；本轮继续工作未推送这些提交。

## 剩余工作

这是 RR012 的可选事务切片，不是已完成的恢复交付系统。持久化当前风险/持仓/日历/屏障重建、遗漏官方收盘发现、旧版抑制持久化和逐渠道最终发送准入仍未完成。生产生命周期/状态接线、协议/UI 实现及进程重启验收也未完成。`2026-09-21-recovery-delivery-metadata.md` 记录的 4 项既有功能失败不予豁免。不表示默认切换、合并或部署。
