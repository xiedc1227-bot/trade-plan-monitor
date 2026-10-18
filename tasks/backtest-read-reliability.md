# Backtest read and progress reliability

## BR-01 — Metadata reads

- [x] Replace immediate rejection of short read overlap with bounded admission on the existing metadata owner: 8 waiting reads, 5-second deadline, one physical call. Keep mutations, overload, cancellation, shutdown, SQLite faults and job authority fenced. Use the same path for history, job status, library and preparation reads.

## BR-02 — Progress and transport

- [x] Admit existing confirmation/repair fields through strict frontend validation. Recover transient incomplete detail pages after terminal summaries without repeating extraction. Enforce the existing 50000-node/32-depth and 2 MiB limits in adaptive server detail pages, retaining all source evidence. Backtest/library GET retries at most 3 attempts, 1 second apart; preparation recovery remains separate and bounded. Show required legacy supplement controls, retaining exact review and frozen-input checks. Preserve progress, explicit unknown-result confirmation, cancellation and same-body/key mutation retry.

## BR-03 — Verification and status

- [x] Focused red/green regressions and production-path browser verification completed; paired documents record evidence and limits. Frontend: 72 files / 1105 tests passed, plus type/build checks. Backend: 108 result/thread/contract checks passed with 1 platform skip; 176 preparation/production checks passed, plus 31 service checks. Actual-service concurrent read evidence and retained four-plan progress are recorded in [BR-V01–BR-V04](../docs/verification/2026-10-18-backtest-read-reliability.md). No paid AI request or new actual-source replay is part of this repair.
