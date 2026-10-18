# Single-plan preparation and reviewed-plan composition

Chinese review copy: [single-plan-library.zh-CN.md](single-plan-library.zh-CN.md).

## SP01. Approved scope

Implement the user's approved workflow: prepare one original at a time, explicitly associate an update with an immutable reviewed predecessor, and select reviewed plans when constructing a backtest. Keep automatic effective-date extraction and confirmation when ambiguous; authored/available timestamps remain optional. No fixed four-file assumption. Preserve existing preparations and replay contracts. Never read `plans.json` or `entry-fields.json` as plan evidence.

## SP02. Design and boundaries

Reuse the revisioned preparation store, worker and frozen schedule instead of adding another extraction engine. A single preparation contains one editable source plus a server-owned immutable reviewed prefix when linked to a predecessor. The library lists reviewed single preparations; an update requires the exact predecessor manifest hash. A composition selects 1–256 reviewed entries, orders them by effective date, rejects duplicate dates/assets and missing or mismatched predecessor versions, initializes the account only from the first entry, and preserves all provenance. Later holdings assertions never reset the account. Existing batch records remain readable.

Reviewed library entries cannot be edited in place. Creating an update or a replacement creates a new preparation. All mutations retain revision/idempotency checks and shared job admission. No new dependency or database table is needed. The browser never constructs authoritative frozen plans.

AI requests retain the complete original and evidence. Backtest extraction receives a dedicated complete-output budget and deadline. Compact wire evidence references canonical source clauses; deterministic expansion must not invent policy. Unsupported or ambiguous source content remains reviewable and blocks approval where necessary. Arbitrary unknown fields, invented units, human supplements and fabricated facts must not be silently accepted.

## SP03. Components and implementation order

1. Backend library commands and reviewed dependencies; reuse existing preparation progress/review endpoints.
2. Backtest AI budget, compact extraction contract and actionable evidence validation.
3. `usePlanPreparation` owns current extraction state; a library composable owns listing, selection and immutable composition. A focused library component exposes input kind/predecessor and reviewed selection through props/events. `BacktestNewView` composes these surfaces. The source form reads exactly one file.
4. Unit/integration/browser checks, live AI verification with the actual TXT files, and equivalent English/Chinese docs.

## SP04. Acceptance and verification

- One file per new preparation; multiple selected files are rejected, not concatenated.
- Unreviewed/stale/wrong-date predecessors are rejected before any AI call; a reviewed prefix cannot be edited or re-extracted.
- Reload retains library entries and exact dependency bindings. Combination cannot omit an update's immediate reviewed predecessor or mix assets/dates.
- Freeze/replay keeps one continuous account and uses only approved versions.
- Live checks use effective dates 2026-09-24, 2026-09-28, 2026-09-30, 2026-10-09. Report genuine unresolved strategy/account facts instead of approving them automatically.
- Run focused `python -m pytest`, `npm.cmd run test -- --run --maxWorkers=4`, `npm.cmd run type-check`, `npm.cmd run build`, API generation checks and the relevant Playwright journey. Protect existing rejection tests; add successful and adversarial regression cases.

## SP05. Task checklist

- [x] Backend library, predecessor and composition invariants.
- [x] Extraction contract/budget regressions and fixes.
- [x] Single-source interface and reviewed-plan selection.
- [x] Runtime/browser and real AI verification.
- [x] Bilingual operations/specification/verification updates.
