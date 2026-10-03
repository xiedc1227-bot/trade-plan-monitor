# Trade Plan Monitor 文档

## 从这里开始

英文文档是实施流程的权威输入；同名 `.zh-CN.md` 是语义等价的中文审阅副本。安装与日常检查见[项目 README](../README.zh-CN.md)，模块边界见[能力地图](architecture/CAPABILITY-MAP.zh-CN.md)，当前产品行为见[单一交易计划流程](specifications/monitoring/SPEC-unified-plan.zh-CN.md)。

单一 `/plans` 工作台使用 Schema 5 与 `plan-extract-v9`：原文 → 草稿 → 修改/审核 → 明确启用 → 日线/五分钟混合监测 → 提醒及明确整单模拟。基本面仅在生成计划时审核。提醒/已读绝不改变库存。冻结 Schema 1–4 读取与独立研究保留原有字节/哈希，不能授权新实时操作。

机器 API 权威位于 [`openapi.json`](../openapi.json) 和 [`openapi.runtime-status.json`](../openapi.runtime-status.json)。安装入口使用监控协议 `2`。本地验收不认证真实供应商可用性、用户数据库迁移、人工 NVDA 审阅或部署；这些仍是单独验证工作。

## 架构

- [能力地图：Trade Plan Monitor](architecture/CAPABILITY-MAP.zh-CN.md) ([English](architecture/CAPABILITY-MAP.md))

## 监控规格

- [decision-engine（确定性决策引擎）](specifications/monitoring/SPEC-decision-engine.zh-CN.md) ([English](specifications/monitoring/SPEC-decision-engine.md))
- [index-data](specifications/monitoring/SPEC-index-data.zh-CN.md) ([English](specifications/monitoring/SPEC-index-data.md))
- [index-identity](specifications/monitoring/SPEC-index-identity.zh-CN.md) ([English](specifications/monitoring/SPEC-index-identity.md))
- [界面设计契约](specifications/monitoring/SPEC-interface-design.zh-CN.md) ([English](specifications/monitoring/SPEC-interface-design.md))
- [live-production-chain](specifications/monitoring/SPEC-live-production-chain.zh-CN.md) ([English](specifications/monitoring/SPEC-live-production-chain.md))
- [local-web](specifications/monitoring/SPEC-local-web.zh-CN.md) ([English](specifications/monitoring/SPEC-local-web.md))
- [market-data（Tushare 行情数据）](specifications/monitoring/SPEC-market-data.zh-CN.md) ([English](specifications/monitoring/SPEC-market-data.md))
- [monitor-index-trends](specifications/monitoring/SPEC-monitor-index-trends.zh-CN.md) ([English](specifications/monitoring/SPEC-monitor-index-trends.md))
- [monitor-index-view](specifications/monitoring/SPEC-monitor-index-view.zh-CN.md) ([English](specifications/monitoring/SPEC-monitor-index-view.md))
- [monitor-runtime（监控运行时）](specifications/monitoring/SPEC-monitor-runtime.zh-CN.md) ([English](specifications/monitoring/SPEC-monitor-runtime.md))
- [notification-outbox（提醒发件箱）](specifications/monitoring/SPEC-notification-outbox.zh-CN.md) ([English](specifications/monitoring/SPEC-notification-outbox.md))
- [冻结计划领域与重放兼容性](specifications/monitoring/SPEC-plan-domain.zh-CN.md) ([English](specifications/monitoring/SPEC-plan-domain.md))
- [plan-index-conditions](specifications/monitoring/SPEC-plan-index-conditions.zh-CN.md) ([English](specifications/monitoring/SPEC-plan-index-conditions.md))
- [provider-contract](specifications/monitoring/SPEC-provider-contract.zh-CN.md) ([English](specifications/monitoring/SPEC-provider-contract.md))
- [runtime-recovery](specifications/monitoring/SPEC-runtime-recovery.zh-CN.md) ([English](specifications/monitoring/SPEC-runtime-recovery.md))
- [runtime-status](specifications/monitoring/SPEC-runtime-status.zh-CN.md) ([English](specifications/monitoring/SPEC-runtime-status.md))
- [source-treatment-review](specifications/monitoring/SPEC-source-treatment-review.zh-CN.md) ([English](specifications/monitoring/SPEC-source-treatment-review.md))
- [strategy-state（策略状态与持久化）](specifications/monitoring/SPEC-strategy-state.zh-CN.md) ([English](specifications/monitoring/SPEC-strategy-state.md))
- [单一交易计划流程](specifications/monitoring/SPEC-unified-plan.zh-CN.md) ([English](specifications/monitoring/SPEC-unified-plan.md))

## 回测规格

- [统一计划历史回放](specifications/backtesting/SPEC-unified-replay.zh-CN.md) ([English](specifications/backtesting/SPEC-unified-replay.md))
- [backtest-api](specifications/backtesting/SPEC-backtest-api.zh-CN.md) ([English](specifications/backtesting/SPEC-backtest-api.md))
- [backtest-data](specifications/backtesting/SPEC-backtest-data.zh-CN.md) ([English](specifications/backtesting/SPEC-backtest-data.md))
- [backtest-engine](specifications/backtesting/SPEC-backtest-engine.zh-CN.md) ([English](specifications/backtesting/SPEC-backtest-engine.md))
- [backtest-index-data](specifications/backtesting/SPEC-backtest-index-data.zh-CN.md) ([English](specifications/backtesting/SPEC-backtest-index-data.md))
- [backtest-index-view](specifications/backtesting/SPEC-backtest-index-view.zh-CN.md) ([English](specifications/backtesting/SPEC-backtest-index-view.md))
- [backtest-jobs](specifications/backtesting/SPEC-backtest-jobs.zh-CN.md) ([English](specifications/backtesting/SPEC-backtest-jobs.md))
- [backtest-results](specifications/backtesting/SPEC-backtest-results.zh-CN.md) ([English](specifications/backtesting/SPEC-backtest-results.md))
- [backtest-web](specifications/backtesting/SPEC-backtest-web.zh-CN.md) ([English](specifications/backtesting/SPEC-backtest-web.md))
- [backtest（历史数据与确定性交易回测）](specifications/backtesting/SPEC-backtest.zh-CN.md) ([English](specifications/backtesting/SPEC-backtest.md))

## 设计决策

- [ADR 0001：隔离持久化回测任务与确定性结果](decisions/0001-isolate-backtest-jobs-from-results.zh-CN.md) ([English](decisions/0001-isolate-backtest-jobs-from-results.md))
- [ADR 0002：所有回测时间统一使用 Asia/Shanghai](decisions/0002-use-asia-shanghai-for-backtest-time.zh-CN.md) ([English](decisions/0002-use-asia-shanghai-for-backtest-time.md))
- [ADR 0003：共用板块指数数据，使用方式由交易计划决定](decisions/0003-share-board-index-data-and-let-plans-own-usage.zh-CN.md) ([English](decisions/0003-share-board-index-data-and-let-plans-own-usage.md))
- [ADR 0004：使用权威投影可用性与原子实时状态](decisions/0004-use-authoritative-projection-availability-and-atomic-live-state.zh-CN.md) ([English](decisions/0004-use-authoritative-projection-availability-and-atomic-live-state.md))
- [ADR 0005：版本化显式计划规则并保留历史含义](decisions/0005-version-explicit-plan-rules.zh-CN.md) ([English](decisions/0005-version-explicit-plan-rules.md))
- [ADR 0006：使用有界服务端处理完成混合原文复核](decisions/0006-review-mixed-source-with-bounded-treatments.zh-CN.md) ([English](decisions/0006-review-mixed-source-with-bounded-treatments.md))
- [ADR 0007：将恢复交付元数据与提醒身份分离](decisions/0007-separate-recovery-delivery-metadata.zh-CN.md) ([English](decisions/0007-separate-recovery-delivery-metadata.md))

## 操作与约定

- [Tushare 真实认证](operations/live-certification.zh-CN.md) ([English](operations/live-certification.md))
- [当前计划回放使用指南](operations/unified-replay.zh-CN.md) ([English](operations/unified-replay.md))

## 指南

- [文件命名](guides/file-naming.zh-CN.md) ([English](guides/file-naming.md))

## 必要验收依据

- [统一计划回放验证](verification/2026-10-03-unified-replay.zh-CN.md) ([English](verification/2026-10-03-unified-replay.md))
- [单一计划流程验证](verification/2026-10-03-unified-plan.zh-CN.md) ([English](verification/2026-10-03-unified-plan.md))
- [回测生产 fake 验收](verification/backtest-acceptance.zh-CN.md) ([English](verification/backtest-acceptance.md))

## 维护规则

保留现行规格、有用的冻结兼容契约、已接受设计决策及可复用操作/开发指南。保留最近一次已执行的当前验收，以及回归测试读取的回测验收契约；记录结果仅适用于声明范围和日期。不得为删除文档而降低阈值或移除安全断言。

把长期有效约束归并到维护文档后，删除被替代提案、已完成交接、阶段测试/排障报告、重复证据索引、过期模型分工指南、迁移清单及旧日志/截图。历史源码保留在 Git。同步更新两种语言和入站链接，再删除空目录。新的过程记录不应成为永久开发入口。

契约测试所需的历史文档字节保存在 `tests/history`，并锁定原始身份，不进入当前开发索引。清理文档时保持其断言与授权边界不变。
