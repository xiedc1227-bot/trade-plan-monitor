# Trade Plan Monitor 文档

> 中文审阅索引。英文权威版为 `README.md`；两份文档必须保持语义一致。

本目录集中保存项目设计、规格、决策、运维指南和验证材料。无语言后缀的文档是英文权威输入；同名 `.zh-CN.md` 文件是中文审阅副本。

## 架构

- [能力地图](architecture/CAPABILITY-MAP.zh-CN.md)（[英文](architecture/CAPABILITY-MAP.md)）——产品边界、模块归属、依赖和构建顺序。

## 监控规格

- [计划领域](specifications/monitoring/SPEC-plan-domain.zh-CN.md)（[英文](specifications/monitoring/SPEC-plan-domain.md)）
- [AI 计划草稿](specifications/monitoring/SPEC-ai-plan-drafting.zh-CN.md)（[英文](specifications/monitoring/SPEC-ai-plan-drafting.md)）
- [行情数据](specifications/monitoring/SPEC-market-data.zh-CN.md)（[英文](specifications/monitoring/SPEC-market-data.md)）
- [板块指数身份](specifications/monitoring/SPEC-index-identity.zh-CN.md)（[英文](specifications/monitoring/SPEC-index-identity.md)）
- [共用板块指数数据](specifications/monitoring/SPEC-index-data.zh-CN.md)（[英文](specifications/monitoring/SPEC-index-data.md)）
- [计划负责的指数条件](specifications/monitoring/SPEC-plan-index-conditions.zh-CN.md)（[英文](specifications/monitoring/SPEC-plan-index-conditions.md)）
- [策略状态](specifications/monitoring/SPEC-strategy-state.zh-CN.md)（[英文](specifications/monitoring/SPEC-strategy-state.md)）
- [决策引擎](specifications/monitoring/SPEC-decision-engine.zh-CN.md)（[英文](specifications/monitoring/SPEC-decision-engine.md)）
- [通知 Outbox](specifications/monitoring/SPEC-notification-outbox.zh-CN.md)（[英文](specifications/monitoring/SPEC-notification-outbox.md)）
- [监控运行时](specifications/monitoring/SPEC-monitor-runtime.zh-CN.md)（[英文](specifications/monitoring/SPEC-monitor-runtime.md)）
- [本地 Web 应用](specifications/monitoring/SPEC-local-web.zh-CN.md)（[英文](specifications/monitoring/SPEC-local-web.md)）
- [监控指数视图](specifications/monitoring/SPEC-monitor-index-view.zh-CN.md)（[英文](specifications/monitoring/SPEC-monitor-index-view.md)）

## 回测规格

- [回测总规格](specifications/backtesting/SPEC-backtest.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest.md)）
- [历史数据与数据集](specifications/backtesting/SPEC-backtest-data.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-data.md)）
- [确定性引擎](specifications/backtesting/SPEC-backtest-engine.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-engine.md)）
- [结果与保留](specifications/backtesting/SPEC-backtest-results.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-results.md)）
- [持久任务](specifications/backtesting/SPEC-backtest-jobs.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-jobs.md)）
- [REST API](specifications/backtesting/SPEC-backtest-api.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-api.md)）
- [Web 工作流](specifications/backtesting/SPEC-backtest-web.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-web.md)）
- [回测指数数据](specifications/backtesting/SPEC-backtest-index-data.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-index-data.md)）
- [回测指数视图](specifications/backtesting/SPEC-backtest-index-view.zh-CN.md)（[英文](specifications/backtesting/SPEC-backtest-index-view.md)）

## 架构决策

- [ADR 0001：隔离持久化回测任务与确定性结果](decisions/0001-isolate-backtest-jobs-from-results.zh-CN.md)（[英文](decisions/0001-isolate-backtest-jobs-from-results.md)）
- [ADR 0002：所有回测时间统一使用 Asia/Shanghai](decisions/0002-use-asia-shanghai-for-backtest-time.zh-CN.md)（[英文](decisions/0002-use-asia-shanghai-for-backtest-time.md)）
- [ADR 0003：共用板块指数数据，使用方式由交易计划决定](decisions/0003-share-board-index-data-and-let-plans-own-usage.zh-CN.md)（[英文](decisions/0003-share-board-index-data-and-let-plans-own-usage.md)）

## 已批准提案

- [共用板块指数数据，使用方式由计划决定](proposals/PROPOSAL-market-index-context.zh-CN.md)（[英文](proposals/PROPOSAL-market-index-context.md)）

## 指南

- [AI 模型选择](guides/ai-model-selection.zh-CN.md)（[英文](guides/ai-model-selection.md)）——为开发参考保留的历史任务与模型配置建议。

## 验证证据

- [回测生产 fake 验收](verification/backtest-acceptance.zh-CN.md)（[英文](verification/backtest-acceptance.md)）
- [Tushare 真实契约验收](verification/tushare-live.zh-CN.md)（[英文](verification/tushare-live.md)）
- [T059 发布验收](verification/release-acceptance.zh-CN.md)（[英文](verification/release-acceptance.md)）

## 根目录入口

仓库根目录有意保留 [README.md](../README.md)、[README.zh-CN.md](../README.zh-CN.md)、`openapi.json`、`pyproject.toml`、`.env.example` 和 `.gitignore`。它们是项目、工具或机器契约入口，不属于开发过程文档。
