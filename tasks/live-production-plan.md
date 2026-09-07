# Implementation Plan: Live Production Chain

> Canonical agent-facing English version. The human-review Chinese version is `live-production-plan.zh-CN.md`; both documents must remain semantically equivalent.

## Overview

Implement the accepted P0 `LPC` work package in contract-first vertical slices while preserving the nine existing WEBF13 changes and all historical identities. The user has already approved implementation; each behavior still follows RED → GREEN → focused verification.

## Architecture Decisions

- ADR 0004 owns typed normal unavailability, successful-shape compatibility, additive migration 0009, complete persisted results, atomic state/events/outbox, and commit-before-publication.
- Stock and board-index provider certifications are independent. Approval to test Tushare does not permit secret exposure or a market-window guess.
- The browser consumes generated contracts and never probes Health to reinterpret a dashboard error.

## Phases and Checkpoints

1. P0 contract and registration: `LPC001`–`LPC002`.
2. Persistent state: `LPC003`–`LPC004`.
3. Stock runtime: `LPC005`–`LPC006`.
4. Separate board-index runtime/certification: `LPC007`–`LPC008`.
5. Web contract and browser: `LPC009`–`LPC010`.
6. Integrated production and evidence: `LPC011`–`LPC012`.

After every phase, run focused tests, Ruff/type checks for changed surfaces, `git diff --check`, and a candidate secret scan. The final checkpoint runs all offline pytest, Ruff, migration/restart/transaction tests, OpenAPI/type generation, Vitest, `vue-tsc`, Google Chrome Playwright, Vite build, and bilingual report parity.

## Parallel Work

- `live-state-store` and provider/harness tests may proceed in parallel after `LPC002`.
- OpenAPI/Vue RED tests may proceed against the frozen union contract while store/runtime implementations are built.
- Migration order, runtime integration, generated artifacts, production process acceptance, and all real Tushare calls remain sequential.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Old ledger appears reconstructable | Fabricated decision | require complete `evaluation_result`; otherwise typed `AWAITING_FIRST_EVALUATION` |
| Transaction partially commits | Divergent head/event/alert | one Unit of Work plus rollback and restart tests |
| Duplicate quote fetch | quota and inconsistent evidence | one batch object per deadline, injected into every evaluation |
| Index failure blocks all plans | violates ADR 0003 | explicit path dependency tests and per-index failure values |
| Browser uses transport as domain state | misleading availability | typed 200 union; remove Health fallback |
| Token reaches artifacts | credential compromise | one-shot secret injection, fixed-code failures, content scan |
| Unsuitable-window certification | false timestamp claim | record `NOT_RUN_MARKET_WINDOW`; defer label decision |
| Runner exits after healthy startup | health remains falsely live or tasks leak | fresh-runtime supervisor, three restarts after `1`/`2`/`4` seconds, degraded health during backoff/exhaustion, terminal cleanup failures |

## Open Questions

No offline implementation question is blocking. LPC006 actionable stock composition remains dependency-blocked until LPC005 records a fresh `READY` profile with a verified `SourceTimeLabel`; fresh index readiness remains independently evidence-gated.
