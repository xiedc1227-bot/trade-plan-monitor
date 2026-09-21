# 恢复交付元数据验证 — 2026-09-21

> 英文文件为规范输入；本文为成对中文审阅副本。续接 `5f91b51`。这是隔离实现证据，不是任意时段重启完整验收或部署批准。

## 范围与边界

- RR011 存储切片：迁移 `0019_alert_delivery_eligibility`、对应 ORM 模型及绑定 session 的仓储。缺失元数据初始化为 HOLD，每批最多 100 条。规范提醒/结果的载荷及哈希不变。可操作提醒按原始来源截止时间 +90 秒失效，不使用恢复创建时间；状态风险提醒不只按年龄过期。
- 仓储持久化显式风险分类、捕获的屏障/结果身份、revision 校验及原子审计。对照新读取的规范提醒校验来源/类别/截止时间及分类证据。损坏元数据和数据库失败明确暴露，不授予许可。抑制为终态；HOLD 可重新评估。提交/回滚由调用方拥有。
- `AlertOutbox.enqueue_recoverable` 为显式启用接口：规范入队和初始 HOLD 共享调用方事务。去重不重置元数据，不虚构当前激活来源。既有评估器调用方及发送器默认行为不变。
- RR012–RR013 策略切片：独立旧版纯分类器覆盖已批准的最新风险/当前持仓适用性，以及重复退出只取最新一条。在终态抑制前通过原始计划/结果重建已证明来源。必须具备一致的当前观察、官方历史/阶段、T+1 及当前目标持仓。仅在重新认证当前观察后，休市日目标才可沿用前一交易时段。此策略不读取持久化当前历史，不持久化旧版抑制，也不发送消息。
- 非空表降级拒绝丢弃交付元数据，包括终态审计记录。仅升级/降级临时数据库；未触碰生产数据库、凭据/配置、行情源、真实通知渠道或部署。未改变依赖、生成契约或前端源码。

完整 RR011–RR013、C0/C2/C3 及任意时段重启验收仍未完成。后续需接入评估事务、持久化来源/当前状态/屏障重建、遗漏官方收盘发现、查询数量上限前的候选筛选、逐渠道认领后权威校验、generation 保护、生命周期/状态集成，以及使用模拟外部服务的真实进程重启测试。已存 ELIGIBLE 凭据绝不是持续有效的发送许可；不引入外部投递恰好一次保证。ADR 0007 记录设计及回滚边界。

## 测试先行与独立审查

| 切片 | 实际 RED | 最终审查结果 |
|---|---|---|
| 交付存储 | 模块缺失；分类/辅助方法缺失；接受规范来源/截止时间/证据不一致；接受无效终态分类原因及不完整的风险为假证据 | 三轮有界代码审查结束，无剩余实质发现。补充并发、审计失败回滚、迁移中断、凭据持久化及缓存刷新用例 |
| 旧版策略 | 模块缺失；矛盾最新阶段和未来持仓被放行；同日 T+1 矛盾、来源校验前抑制无效记录、陈旧当前观察、新 occurrence 超出快照；休市日取得日期晚于认证交易时段 | 三轮有界审查结束，无剩余实质发现。56 个策略用例，包含休市日有效正例，不是给风险统一设置过期时间 |

旧版实现子任务使用 `gpt-6-astra` / `high`；独立存储与旧版评审使用 `gpt-6-astra` / `xhigh`。这些子任务设置不证明主任务模型/强度。按用户此前选择，跳过额外跨模型第二意见。评审修复收紧来源、快照和结算证据，没有放宽失败断言。既有 SQLite 迁移测试仅因增量结构更新预期最新 head/表集合；业务保留和降级断言全部保留。

## 实际验证

从 `trade-plan-monitor` 运行；排除外部 live 测试。

| 命令 | 实际结果 |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_delivery_eligibility_storage.py tests/integration/test_sqlite_repositories.py -q --tb=short` | 146 通过、1 项既有警告、14.73 秒；含 40 个新增存储用例及 106 个既有 SQLite 用例 |
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_legacy_recovery_delivery_eligibility.py -q --tb=short` | 实现 agent 最终评审修复后 56 通过，1.61 秒；最终评审者也通过全部 56 项 |
| `.\.venv\Scripts\python.exe -m pytest tests/integration/test_delivery_eligibility_storage.py tests/unit/test_legacy_recovery_delivery_eligibility.py tests/integration/test_recovery_alert_provenance.py tests/unit/test_recovery_delivery_eligibility.py tests/integration/test_notification_delivery.py tests/unit/test_notification_outbox.py tests/integration/test_sqlite_repositories.py tests/integration/test_runtime_recovery_storage.py -q --tb=short` | 最终针对性回归：385 通过、1 项既有警告、29.36 秒；包含全部 96 个新增用例 |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | 通过 |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI 快照与前端类型均为最新 |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | 3190 通过、4 项已知失败、1 项既有跳过、4 项 live 排除、1 项既有警告；492.18 秒 |

功能回归准确复现下列 4 项既有失败。本次交付增量不豁免或修复它们；未删除或跳过失败测试来宣称通过。

- `tests/integration/test_live_pipeline_acceptance.py::test_market_index_persistence_reuses_an_older_canonical_content_revision`：指数 head 更新时间预期 10:38，实际 10:36。
- `tests/integration/test_live_pipeline_acceptance.py::test_startup_batches_persisted_pending_closes_by_date_and_shared_index[index_error]`：参考健康状态预期 BLOCKED，实际 LIVE。
- `tests/unit/test_market_data.py::test_tushare_provider_errors_use_stable_codes_and_drop_raw_context[provider_error2-TRANSIENT]`：预期 TRANSIENT，实际 TIMEOUT。
- `tests/unit/test_r14_bounded_acceptance.py::test_ai_guard_allows_only_one_approved_prompt_and_counts_failed_attempt`：模拟载荷缺少 temperature 门禁要求的输入，在模拟 transport 前抛出 `BudgetDenied`。

功能回归进程在最后的休市日取得日期约束及对应一个反例加入前完成收集/导入；实际计数包含 95 个新增用例。最终 385 项针对性回归在该修复之后运行，包含全部 96 个新增用例。本轮未重跑未改动的重型回测验收文件；其此前全量通过证据仍见 `2026-09-21-runtime-recovery-increments.md`。既有跳过项为 Windows/POSIX 所有权边界。完整验收并未全绿，不声称已完成生产/重启整体验收。

空白检查及全局 Ruff 检查通过。四对文档标题数量一致，规范化配对路径后技术字面量一致，唯一例外为 ADR 英文头部说明性的 `.zh-CN.md` 后缀。对全部 16 个变更文件执行高置信度秘密模式扫描，未发现匹配；这是限定范围的卫生检查，不是凭据审计。

## 修改范围与来源

新增 `notifications/delivery_eligibility.py`、`notifications/legacy_recovery_eligibility.py`、迁移 `0019_alert_delivery_eligibility.py` 及针对性存储/策略测试；在 `notifications/outbox.py` 和 `state/models.py` 做小范围增加；更新 SQLite 预期 head 断言；成对恢复规格、ADR 0007、任务检查点及本报告。

调用方拥有事务的设计遵循 [SQLAlchemy 事务边界](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)；增量表使用现有 [Alembic operations API](https://alembic.sqlalchemy.org/en/latest/ops.html#alembic.operations.Operations.create_table)。业务规则来自已批准的项目规格，不来自这些框架文档。
