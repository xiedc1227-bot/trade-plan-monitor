# Trade Plan Monitor Documentation

> Canonical agent-facing English index. The human-review Chinese version is `README.zh-CN.md`; both documents must remain semantically equivalent.

This directory contains the project's design, specification, decision, operating-guide, and verification material. Unsuffixed documents are canonical English inputs; matching `.zh-CN.md` files are Chinese review copies.

## Architecture

- [Capability map](architecture/CAPABILITY-MAP.md) ([Chinese](architecture/CAPABILITY-MAP.zh-CN.md)) — product boundary, module ownership, dependencies, and build order.

## Monitoring Specifications

- [Plan domain](specifications/monitoring/SPEC-plan-domain.md) ([Chinese](specifications/monitoring/SPEC-plan-domain.zh-CN.md))
- [AI plan drafting](specifications/monitoring/SPEC-ai-plan-drafting.md) ([Chinese](specifications/monitoring/SPEC-ai-plan-drafting.zh-CN.md))
- [Market data](specifications/monitoring/SPEC-market-data.md) ([Chinese](specifications/monitoring/SPEC-market-data.zh-CN.md))
- [Strategy state](specifications/monitoring/SPEC-strategy-state.md) ([Chinese](specifications/monitoring/SPEC-strategy-state.zh-CN.md))
- [Decision engine](specifications/monitoring/SPEC-decision-engine.md) ([Chinese](specifications/monitoring/SPEC-decision-engine.zh-CN.md))
- [Notification outbox](specifications/monitoring/SPEC-notification-outbox.md) ([Chinese](specifications/monitoring/SPEC-notification-outbox.zh-CN.md))
- [Monitor runtime](specifications/monitoring/SPEC-monitor-runtime.md) ([Chinese](specifications/monitoring/SPEC-monitor-runtime.zh-CN.md))
- [Local Web application](specifications/monitoring/SPEC-local-web.md) ([Chinese](specifications/monitoring/SPEC-local-web.zh-CN.md))

## Backtesting Specifications

- [Backtest umbrella specification](specifications/backtesting/SPEC-backtest.md) ([Chinese](specifications/backtesting/SPEC-backtest.zh-CN.md))
- [Historical data and datasets](specifications/backtesting/SPEC-backtest-data.md) ([Chinese](specifications/backtesting/SPEC-backtest-data.zh-CN.md))
- [Deterministic engine](specifications/backtesting/SPEC-backtest-engine.md) ([Chinese](specifications/backtesting/SPEC-backtest-engine.zh-CN.md))
- [Results and retention](specifications/backtesting/SPEC-backtest-results.md) ([Chinese](specifications/backtesting/SPEC-backtest-results.zh-CN.md))
- [Durable jobs](specifications/backtesting/SPEC-backtest-jobs.md) ([Chinese](specifications/backtesting/SPEC-backtest-jobs.zh-CN.md))
- [REST API](specifications/backtesting/SPEC-backtest-api.md) ([Chinese](specifications/backtesting/SPEC-backtest-api.zh-CN.md))
- [Web workflows](specifications/backtesting/SPEC-backtest-web.md) ([Chinese](specifications/backtesting/SPEC-backtest-web.zh-CN.md))

## Architecture Decisions

- [ADR 0001: Isolate durable backtest jobs from deterministic results](decisions/0001-isolate-backtest-jobs-from-results.md) ([Chinese](decisions/0001-isolate-backtest-jobs-from-results.zh-CN.md))
- [ADR 0002: Use Asia/Shanghai for all backtest time](decisions/0002-use-asia-shanghai-for-backtest-time.md) ([Chinese](decisions/0002-use-asia-shanghai-for-backtest-time.zh-CN.md))

## Guides

- [AI model selection](guides/ai-model-selection.md) ([Chinese](guides/ai-model-selection.zh-CN.md)) — historical task-to-model recommendations retained for development reference.

## Verification Evidence

- [Backtest production-fake acceptance](verification/backtest-acceptance.md) ([Chinese](verification/backtest-acceptance.zh-CN.md))
- [Tushare live contract acceptance](verification/tushare-live.md) ([Chinese](verification/tushare-live.zh-CN.md))
- [T059 release acceptance](verification/release-acceptance.md) ([Chinese](verification/release-acceptance.zh-CN.md))

## Root-Level Entrypoints

The repository root intentionally retains [README.md](../README.md), [README.zh-CN.md](../README.zh-CN.md), `openapi.json`, `pyproject.toml`, `.env.example`, and `.gitignore`. These are project, tool, or machine-contract entrypoints rather than development-process documents.
