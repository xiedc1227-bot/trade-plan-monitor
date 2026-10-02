# Trade Plan Monitor 文档

无语言后缀文档是英文权威输入，匹配的 `.zh-CN.md` 是中文审阅副本。索引对照2026-10-02当前程序整理。

## 当前入口与未完成事项

- 日线：Schema4 / `plan-extract-v7` 已实现监控与显式整手模拟；基本面退出监控，新增大盘指数判断暂缓。当前契约、完成记录和验收以以下日线文档为准。
- 运行恢复：正常Web入口使用监控协议 `2`，已批准D1–D8 / A01–A13离线实现完成。D9/A14是旧提醒关联实际卖出登记的独立待审核需求，不属于日线模拟。C5用户证据审核及实际环境上线不列为已完成。
- Schema1/2/3、既有指数条件和回测继续保留。旧版规格及验收的历史路径数、测试数量和认证有效期不代表当前全量状态或实时可用性。
- 启动和常用验证命令以[项目README](../README.zh-CN.md)为入口；API机器契约为 [`openapi.json`](../openapi.json) 与 [`openapi.runtime-status.json`](../openapi.runtime-status.json)。

## 架构

- [能力地图：daily-plan](architecture/CAPABILITY-MAP-daily-plan.zh-CN.md)（[英文](architecture/CAPABILITY-MAP-daily-plan.md)）
- [能力地图：实时监控生产链路](architecture/CAPABILITY-MAP-live-production-chain.zh-CN.md)（[英文](architecture/CAPABILITY-MAP-live-production-chain.md)）
- [能力地图：本地 AI 辅助交易计划监控系统](architecture/CAPABILITY-MAP.zh-CN.md)（[英文](architecture/CAPABILITY-MAP.md)）

## 监控规格

- [规格：ai-plan-drafting（AI 计划草稿转换）](specifications/monitoring/SPEC-ai-plan-drafting.zh-CN.md)（[英文](specifications/monitoring/SPEC-ai-plan-drafting.md)）
- [规格：daily-plan](specifications/monitoring/SPEC-daily-plan.zh-CN.md)（[英文](specifications/monitoring/SPEC-daily-plan.md)）
- [规格：decision-engine（确定性决策引擎）](specifications/monitoring/SPEC-decision-engine.zh-CN.md)（[英文](specifications/monitoring/SPEC-decision-engine.md)）
- [规格：executable-plan-extension（R08 / F06）](specifications/monitoring/SPEC-executable-plan-extension.zh-CN.md)（[英文](specifications/monitoring/SPEC-executable-plan-extension.md)）
- [规格：index-data](specifications/monitoring/SPEC-index-data.zh-CN.md)（[英文](specifications/monitoring/SPEC-index-data.md)）
- [规格：index-identity](specifications/monitoring/SPEC-index-identity.zh-CN.md)（[英文](specifications/monitoring/SPEC-index-identity.md)）
- [界面设计契约](specifications/monitoring/SPEC-interface-design.zh-CN.md)（[英文](specifications/monitoring/SPEC-interface-design.md)）
- [规格：live-production-chain](specifications/monitoring/SPEC-live-production-chain.zh-CN.md)（[英文](specifications/monitoring/SPEC-live-production-chain.md)）
- [规格：local-web（本地 Web 应用）](specifications/monitoring/SPEC-local-web.zh-CN.md)（[英文](specifications/monitoring/SPEC-local-web.md)）
- [规格：market-data（Tushare 行情数据）](specifications/monitoring/SPEC-market-data.zh-CN.md)（[英文](specifications/monitoring/SPEC-market-data.md)）
- [规格：monitor-index-trends](specifications/monitoring/SPEC-monitor-index-trends.zh-CN.md)（[英文](specifications/monitoring/SPEC-monitor-index-trends.md)）
- [规格：monitor-index-view](specifications/monitoring/SPEC-monitor-index-view.zh-CN.md)（[英文](specifications/monitoring/SPEC-monitor-index-view.md)）
- [规格：monitor-runtime（监控运行时）](specifications/monitoring/SPEC-monitor-runtime.zh-CN.md)（[英文](specifications/monitoring/SPEC-monitor-runtime.md)）
- [规格：notification-outbox（提醒发件箱）](specifications/monitoring/SPEC-notification-outbox.zh-CN.md)（[英文](specifications/monitoring/SPEC-notification-outbox.md)）
- [规格：plan-domain（交易计划领域模型）](specifications/monitoring/SPEC-plan-domain.zh-CN.md)（[英文](specifications/monitoring/SPEC-plan-domain.md)）
- [规格：plan-index-conditions](specifications/monitoring/SPEC-plan-index-conditions.zh-CN.md)（[英文](specifications/monitoring/SPEC-plan-index-conditions.md)）
- [规格：provider-contract](specifications/monitoring/SPEC-provider-contract.zh-CN.md)（[英文](specifications/monitoring/SPEC-provider-contract.md)）
- [规格：runtime-recovery](specifications/monitoring/SPEC-runtime-recovery.zh-CN.md)（[英文](specifications/monitoring/SPEC-runtime-recovery.md)）
- [规格：runtime-status](specifications/monitoring/SPEC-runtime-status.zh-CN.md)（[英文](specifications/monitoring/SPEC-runtime-status.md)）
- [规格：source-treatment-review（R11 混合原文闭环）](specifications/monitoring/SPEC-source-treatment-review.zh-CN.md)（[英文](specifications/monitoring/SPEC-source-treatment-review.md)）
- [规格：strategy-state（策略状态与持久化）](specifications/monitoring/SPEC-strategy-state.zh-CN.md)（[英文](specifications/monitoring/SPEC-strategy-state.md)）

## 回测规格

- [规格：backtest-api](specifications/backtesting/SPEC-backtest-api.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-api.md)）
- [规格：backtest-data](specifications/backtesting/SPEC-backtest-data.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-data.md)）
- [规格：backtest-engine](specifications/backtesting/SPEC-backtest-engine.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-engine.md)）
- [规格：backtest-index-data](specifications/backtesting/SPEC-backtest-index-data.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-index-data.md)）
- [规格：backtest-index-view](specifications/backtesting/SPEC-backtest-index-view.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-index-view.md)）
- [规格：backtest-jobs](specifications/backtesting/SPEC-backtest-jobs.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-jobs.md)）
- [规格：backtest-results](specifications/backtesting/SPEC-backtest-results.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-results.md)）
- [规格：backtest-web](specifications/backtesting/SPEC-backtest-web.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-web.md)）
- [规格：backtest（历史数据与确定性交易回测）](specifications/backtesting/SPEC-backtest.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest.md)）

## 架构决策

- [ADR 0001：隔离持久化回测任务与确定性结果](decisions/0001-isolate-backtest-jobs-from-results.zh-CN.md)（[英文](decisions/0001-isolate-backtest-jobs-from-results.md)）
- [ADR 0002：所有回测时间统一使用 Asia/Shanghai](decisions/0002-use-asia-shanghai-for-backtest-time.zh-CN.md)（[英文](decisions/0002-use-asia-shanghai-for-backtest-time.md)）
- [ADR 0003：共用板块指数数据，使用方式由交易计划决定](decisions/0003-share-board-index-data-and-let-plans-own-usage.zh-CN.md)（[英文](decisions/0003-share-board-index-data-and-let-plans-own-usage.md)）
- [ADR 0004：使用权威投影可用性与原子实时状态](decisions/0004-use-authoritative-projection-availability-and-atomic-live-state.zh-CN.md)（[英文](decisions/0004-use-authoritative-projection-availability-and-atomic-live-state.md)）
- [ADR 0005：版本化显式计划规则并保留历史含义](decisions/0005-version-explicit-plan-rules.zh-CN.md)（[英文](decisions/0005-version-explicit-plan-rules.md)）
- [ADR 0006：使用有界服务端处理完成混合原文复核](decisions/0006-review-mixed-source-with-bounded-treatments.zh-CN.md)（[英文](decisions/0006-review-mixed-source-with-bounded-treatments.md)）
- [ADR 0007：将恢复交付元数据与提醒身份分离](decisions/0007-separate-recovery-delivery-metadata.zh-CN.md)（[英文](decisions/0007-separate-recovery-delivery-metadata.md)）

## 运维与指南

- [AI 模型选择说明](guides/ai-model-selection.zh-CN.md)（[英文](guides/ai-model-selection.md)）
- [文件命名](guides/file-naming.zh-CN.md)（[英文](guides/file-naming.md)）
- [Tushare 真实认证](operations/live-certification.zh-CN.md)（[英文](operations/live-certification.md)）

## 任务完成记录

- [日线统一记录](../tasks/daily-plan-todo.zh-CN.md)（[英文](../tasks/daily-plan-todo.md)）：DPT、DSC及C1–C4已完成，包含发布结果。
- [运行恢复计划](../tasks/runtime-recovery-plan.zh-CN.md)（[英文](../tasks/runtime-recovery-plan.md)）与[任务](../tasks/runtime-recovery-todo.zh-CN.md)（[英文](../tasks/runtime-recovery-todo.md)）：保留已完成RR记录及尚未批准的D9/A14、待审核C5。
- [指数与WEBF13记录](../tasks/todo.zh-CN.md)（[英文](../tasks/todo.md)）及[实时链路LPC记录](../tasks/live-production-todo.zh-CN.md)（[英文](../tasks/live-production-todo.md)）：已完成的历史任务记录，其验收数字限定于当时范围。

## 验收证据

- [日线模拟最终验收](verification/2026-10-02-daily-simulation-cleanup.zh-CN.md)（[英文](verification/2026-10-02-daily-simulation-cleanup.md)）
- [日线模拟独立审核](verification/2026-10-02-daily-simulation-independent-review.zh-CN.md)（[英文](verification/2026-10-02-daily-simulation-independent-review.md)）
- [运行恢复最终离线门禁](verification/2026-09-30-runtime-recovery-final-gate.zh-CN.md)（[英文](verification/2026-09-30-runtime-recovery-final-gate.md)）
- [运行状态与页面验收](verification/2026-09-30-s4-offline-status-gate.zh-CN.md)（[英文](verification/2026-09-30-s4-offline-status-gate.md)）
- [Schema3回测重排验收附录](verification/R13-N05-addendum.zh-CN.md)（[英文](verification/R13-N05-addendum.md)）
- [Schema3独立再验收（附录前）](verification/R13-reacceptance.zh-CN.md)（[英文](verification/R13-reacceptance.md)）
- [回测离线验收（测试依赖）](verification/backtest-acceptance.zh-CN.md)（[英文](verification/backtest-acceptance.md)）
- [WEBF13历史验收](verification/webf13-acceptance.zh-CN.md)（[英文](verification/webf13-acceptance.md)）
- [LPC历史验收与限制](verification/live-production-chain-acceptance.zh-CN.md)（[英文](verification/live-production-chain-acceptance.md)）
- [Tushare历史契约验收](verification/tushare-live.zh-CN.md)（[英文](verification/tushare-live.md)）
- [T059历史发布验收](verification/release-acceptance.zh-CN.md)（[英文](verification/release-acceptance.md)）

## 文档保留规则

保留当前规格、API机器契约、架构决策、运维指南、有效来源映射、未完成需求及实际执行的验收记录。`verification/` 中的阶段性记录保留测试命令、结果、失败与限制；日期标明其证据范围，不作为待执行指令。`remediation/` 中早期交接仍包含其他报告未覆盖的回归依据和验收矩阵，继续保留；原始证据附件保持不变。

已移除46组（92份）过期或重复过程文档：失效的一次性R14–R32方案/准备、已被执行报告覆盖的R17–R32交接、已完成修复计划、旧指数提案及执行计划、日线旧暂停恢复/执行计划/清理交接。日线稳定DPT/DSC/C编号汇总在统一记录。引用这些旧过程的历史报告现指向已发布提交 `030075c4946bf34833a0155fde6b4deda3c79055` 中的准确文件，保留原始上下文；旧的一次性授权不因此恢复有效。后续新增或实质修改文档应同步更新中英文及本索引。
