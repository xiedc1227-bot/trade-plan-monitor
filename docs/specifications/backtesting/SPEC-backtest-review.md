# Backtest result review — P0 + minimal P1

Status: Implementation authorized by the user on 2026-10-20. English canonical input; [Chinese review copy](SPEC-backtest-review.zh-CN.md). Refines [the proposal](PROPOSAL-backtest-result-ux.md); existing engine and result integrity contracts remain authoritative.

## BR01. Deliverable

Review a completed monitoring-loop run through overview, completed fills, non-trade reasons, plans/provenance and audit events. A fill opens its recorded cause in at most two navigation actions. A representative diagnostic opens its exact sequence in one action, including beyond the first 100 events. Preserve existing summary/fills/details/equity links and legacy result readers.

## BR02. Read contract

Add `GET /api/v1/backtest-runs/{run_id}/review-context`. Exactly one selector: `fillId` (public simulation ID), `eventId` (64 lowercase hex), or `sequence` (positive bounded integer). Optional `relation=CAUSES|EFFECTS` (default `CAUSES`), `limit` (default 20, maximum 100), `cursor`. Reject duplicate, unknown and incompatible parameters with existing `VALIDATION_ERROR`; absent run/identity uses `NOT_FOUND`. Cursor binds run, selector, relation, limit and selected identity/hash.

Response: `runId`, `selector`, `relation`, `selected` (typed loop event or null), `fill` (durable typed fill or null), `items` (typed related events, at most limit), `evidence` (at most 100 deterministic condition items: `sequence`, `ruleId`, `at`, `rootOutcome`, `requirement`, `actual`, `reason`), `availability=AVAILABLE|EXPIRED|NOT_RECORDED`, `projectionStatus=READY|NOT_READY`, `completeness=COMPLETE|PARTIAL`, `missingEventId`, `limit`, `hasMore`, `nextCursor`. Sequence range is 1..420001. CAUSES walks actual parent edges toward the root; EFFECTS lists direct children in sequence order. The selected record is separate from the page. A next cursor continues that relation, not the whole run. Page JSON is below 4 MiB; each event retains the existing item limit. `COMPLETE` means no known missing links in the loaded page; it does not replace `hasMore`.

Only materialized results are visible. Verify canonical row hashes and index/record identities in one read transaction. No provider, AI, replay, live-state read or index construction during GET. An expired cause preserves a retained fill and explicitly reports partial evidence. An absent old-run index reports `NOT_READY`; it never means no trades. No page-wide frontend scans to resolve a cause.

## BR03. Derived index and accounting

Maintain a derived event index during detail staging, within the same transaction, with event ID, sequence, parent, canonical detail ID and hash. Foreign-key deletion follows detail retention. Publication visibility remains controlled by the existing materialized flag. Register the additive optional schema in migration inventory; accept the previous schema without rebuilding canonical data. Provide explicit maintenance over retained verified rows in batches of at most 100, with a continuation boundary; never rewrite payloads, report hashes or reconstruct expired rows. Historical results keep their old readers.

No per-fill PnL projection or sorting ships in this slice. Show authoritative receipt price, quantity, fees, released cost and resulting holdings, label cumulative realized PnL explicitly, and keep unknown amounts unknown. `POSITION_LIMIT_ONLY` does not show capital return/equity/drawdown tiles.

## BR04. Component and navigation contract

`BacktestRunDetailView` composes existing resources plus review controls. `BacktestFillTable` receives readonly items and emits a selected fill identity. `PlanExecutionDiagnostics` receives diagnostics/response mode and emits a sequence; samples remain labelled and counts retain their original units. `MonitorLoopTimeline` emits selected event/parent identity. `BacktestEvidencePanel` receives readonly context/loading/error, emits relation/continuation/close/select, and presents outcome, structured evidence and audit disclosure. `useBacktestReview` owns URL selection, cancellation, stale-read rejection and relation loading. Pure presentation helpers map recorded enums; no generated AI explanation.

Use `fillId|eventId|sequence`, `relation` and `reviewCursor` in the existing result URL. Exactly one selection; invalid combinations show an error without lookup. Opening/closing preserves the resource cursor; Back/Forward restores selection. Previous-page links use visited signed cursors only. Move focus to the evidence heading after selection and back to its trigger on close; all controls have visible focus and 44px targets. Desktop evidence sits beside records, below 1024px it stacks; verify 320/768/1024/1440px. Use existing design tokens.

## BR05. Acceptance and verification

- BR-A01: real published fill and diagnostic sequence resolve cross-page causes without full-run downloads; direct child and cause pagination have no duplicates and reject cursor reuse with another selector/run.
- BR-A02: missing/expired evidence, unknown funding, `OBSERVE_ONLY`, blocked attempts, sampled diagnostics and unknown reason codes remain distinct; no invented totals or single-fill PnL.
- BR-A03: stale selections and run changes cannot display another record; deep links, Back/Forward, close and keyboard focus work; mobile has no document overflow and axe reports no serious/critical violations.
- BR-A04: stage/publication, hash corruption, old-schema reopening and retention tests pass; frontend contracts regenerate cleanly, unit tests/type-check/build and browser interactions pass.

## BR06. Deferred work

Full-run `review-events` filtering, index-date filtering, verified per-fill PnL, linked charts and run comparisons remain subsequent P1/P2/P3 slices. This scope delivers exact cause navigation and readable results; category controls on sampled diagnostics must explicitly state their local scope. Moderated 30/60-second usability targets remain unmeasured until a user study.
