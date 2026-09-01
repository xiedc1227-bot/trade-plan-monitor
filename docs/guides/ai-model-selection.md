# AI Model Selection Guide

> Canonical agent-facing English version. The human-review Chinese version is `ai-model-selection.zh-CN.md`; both documents must remain semantically equivalent.

| Task range | Recommended configuration | Rationale |
|---|---|---|
| `T009–T010` | Sol + `max` | Trading sessions, minute labels, and Tushare unit conversions are prone to subtle errors. |
| `T011–T020` | Sol + `xhigh` | Covers SQLite, transactions, T+1, market-data persistence, and indicator calculations. |
| `T021–T024` | Sol + `max` | The trading decision engine, state transitions, priorities, and result hashes form the core correctness boundary. |
| `T025–T041` | Sol + `xhigh` | Covers notifications, scheduling, recovery, FastAPI, WebSocket, and security boundaries. |
| `T042–T051` | Sol + `high` or `xhigh` | Vue frontend work must balance implementation quality, accessibility, and visual quality. |
| `T052–T055` | Sol + `xhigh` | Covers packaging, documentation, full-system replay, and browser workflows. |
| `T056–T059` | Sol + `max` | Covers security regressions, the ten-symbol stress test, the real Tushare contract, and release acceptance. |
