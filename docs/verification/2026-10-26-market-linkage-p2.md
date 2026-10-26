# Verification: market-linkage-p2

Status: PASS — 2026-10-26. MLP2-T01–MLP2-T18 and C01–C06 are complete; MLP2-A01–MLP2-A12 are accepted within the approved non-live scope. Baseline: `8db00c425706945d69a39ae0d3ffe1d85348d626`. The user approved all six decisions and implementation on 2026-10-26. [Chinese review copy](2026-10-26-market-linkage-p2.zh-CN.md) · [tasks](../../tasks/market-linkage-p2.md) · [operations](../operations/market-linkage-p2.md).

## MLP2-V01 — Contract and arithmetic stages

T01 existing quantity/exception baseline: 74 passed in 0.65s. T02–T06 focused policy and historical codec/hash regression: 303 passed in 2.41s, including the initial 46 P2 unit cases. Initial core tests failed before implementation; later boundary additions were checked against independent expected quantities and fen values. C01/C02 accepted. These overlapping runs are not a unique-case total.

Schema 8 is opt-in, with condition-plan-v4, pretrade-policy-v1 and review hash plan-review-content-v5. Strict models reject mixed fixed/derived quantities, incomplete tables, unsafe arithmetic and implicit fees/gates. Source-defined tiers derive Q0 before unchanged P0/P1 market factors. Synthetic fee oracles test minimum commissions, per-component ceiling, inclusion, scope/expiry, equality, overflow and risk-return arithmetic.

## MLP2-V02 — Source, storage and execution stages

P0/P1/P2 source review: 27 passed in 1.46s. Initial P2 lifecycle/storage/authority group: 57 passed in 3.21s. Real API review→activation→runtime→simulation covers ordinary, WEAK_MINIMUM and BROKEN_STRONG. The expanded P2 integration group passed79 cases in 42.77s before the final worker/source additions. Required economics can block at quote175 and recover at161 without resizing; PREVIEW_ONLY never vetoes. Actual risk SELL simulation succeeds despite an impossible BUY gate. Read-only previews reject client prices and cannot grant authority.

Storage reuses versioned JSON; no SQL structural migration is required. New optional fields are omitted from old records. Temporary SQLite reopen, tampering, revision conflicts, concurrent consumption and atomic rollback are covered. User databases are untouched. Exact historical OpenAPI comparisons strip only enumerated P2 additions and retain every previous-route/field assertion.

## MLP2-V03 — Replay and browser stages

Required-fee replay/concurrency group: 26 passed in 27.93s. Real frozen workers, publication and projection checks with P1 regression: 14 passed in 157.50s. Both routes retain explicit authorization events and independent operations, live-state isolation and recorded/scenario provenance. Future receipt/availability mutations cannot affect earlier decisions. Identical OHLC values with different bar IDs or Decimal trailing zeros preserve consumed authority; corrected technical values change it.

P0/P1/P2 Chrome journeys passed15 cases in 3.1m before the final presentation refinement. They cover source omissions/manual review, both exception paths, fee modes, failed/recovered gates, correction, consumption and reload. Widths320/768/1024/1440 retain no horizontal overflow; external request audits are empty. Final presentation also uses readable, deduplicated fee reasons and rejects late results after a plan-version change. The final combined run passed 15 cases in 3.2m; after expanding readable fee details, all 6 P2 journeys passed again in 1.5m. Reviewed screenshots: [WEAK_MINIMUM](assets/2026-10-26-market-linkage-p2-weak.png), [BROKEN_STRONG](assets/2026-10-26-market-linkage-p2-broken.png).

## MLP2-V04 — Failures and repairs

- Windows restricted asyncio socketpair initialization stalled before application logic. A stack dump identified the environment restriction; affected commands were interrupted and rerun with local communication available, using disposable workspace databases. Interrupted runs are not passes.
- Combined default pytest collection finds pre-existing duplicate unit/integration module names; importlib collection breaks existing bare fixture imports. V06 therefore runs unit, integration, and contract/replay directories in separate processes, preserving all tests and excluding only live tests.
- The P2 schema initially exceeded the existing 50000-character extraction budget. The prompt now uses the existing named schema-outline notation while runtime parsing remains complete and strict; 44 budget/source/security cases passed in 2.36s. No budget was increased.
- A long unresolved source reason exceeded the generic 512-character API error field. That summary is now bounded while full daily review evidence remains intact; API tests verify both. Preview conflict construction now uses the existing typed error contract.
- Malformed decimal strings previously escaped as InvalidOperation; they now produce validation errors. Nullable candidates retain collection bounds. Full P2 technical values use canonical Decimal serialization, so equivalent spelling cannot invalidate authority.
- Browser setup initially attempted an exception preview before a candidate was visible. Tests now wait for the real candidate and assert its request identity; production does not bypass the current-evidence requirement.
- Full P2 research proofs duplicated across signals exceeded the existing 32 KiB result limit. Reports now deduplicate linkage and pretrade proofs, resolve all references and revalidate complete signals. The original limit, corruption assertions and Schema 7 representation remain unchanged.
- Current capability/partial-extraction fixtures still expected Schema 5–7 or plan-extract-v10. Only explicit new fields/versions were updated; historical snapshots and old-rule assertions remain pinned. The approved preview route and generated-contract digests were registered in the path whitelist and both unified specifications. The long-running integration process had loaded earlier fixtures; all 14 resulting failures passed on current code.
- Target validation originally added an unapproved endpoint-only restriction. It now accepts an explicitly sourced target within the reviewed pressure range, respecting endpoint inclusion, while rejecting targets outside it. No target is inferred.

Existing Starlette/httpx, intentional duplicate-ZIP and SQLite expression-index reflection warnings remain visible. The existing Windows POSIX-ownership skip is retained. No new skip/xfail, dependency, relaxed timeout/capacity/payload limit or live-provider call was introduced.

## MLP2-V05 — Final regression ledger

Every observed failure has a passing current-code recheck. Groups overlap and must not be summed as unique test counts. The full integration process began before the last contract fixes; the focused final groups and exact failed-node recheck cover the repaired and newly added cases. Commands are V01–V08 in the paired task list; the exact failure/capacity commands are in the reconciliation artifact.

| Check | Executed evidence |
| --- | --- |
| Backend unit final | [3712 passed, 2 warnings, 66.88s](assets/2026-10-26-market-linkage-p2-unit-final.log) |
| Contract/replay directories | [13 passed, 4 live deselected, 9.73s](assets/2026-10-26-market-linkage-p2-replay-contract-final.log) |
| Final P2 / historical API group | [115 passed, 175.29s](assets/2026-10-26-market-linkage-p2-focused-final.log) |
| OpenAPI / loop contracts | [27 passed, 33.53s](assets/2026-10-26-market-linkage-p2-contracts-final.log) |
| Frontend final | [91 files / 1270 passed, 13.33s](assets/2026-10-26-market-linkage-p2-frontend-final.log) |
| Browser | [15 P0/P1/P2 journeys](assets/2026-10-26-market-linkage-p2-browser-all-final.log); [6 final P2 journeys](assets/2026-10-26-market-linkage-p2-browser-p2-final.log) |
| Type check / build / final UI tests | [Passed; 8 focused tests](assets/2026-10-26-market-linkage-p2-ui-build-final.log) |
| Generated contracts / quality | [Both profiles current; Ruff passed](assets/2026-10-26-market-linkage-p2-quality-final.log); whitespace check passed |
| Full integration except capacity module | [Initial: 4709 passed, 14 failed, 1 existing platform skip, 5 warnings, 3065.66s](assets/2026-10-26-market-linkage-p2-integration-initial.log); [all 14 failed nodes pass on current code, 25.03s](assets/2026-10-26-market-linkage-p2-failure-recheck.log) |
| Capacity module | Initial completed prefix: 7 passed, 1 failed. [Isolated ten-symbol rerun: 1 passed, 1 warning, 1377.64s](assets/2026-10-26-market-linkage-p2-capacity-final.log); all 8 capacity cases reconciled. [Exact reconciliation](assets/2026-10-26-market-linkage-p2-reconciliation.json) |

The isolated capacity check retained 120s per symbol, 768MiB working-set delta, 512MiB market database/WAL and 192MiB result database/WAL. Final measured file sizes were 519073792 and 184938496 bytes. The initial process was interrupted only after its capacity module had completed; its seven passing cases are mapped from the captured ordered prefix. The first failure’s deferred traceback is unavailable, so a specific cause is not asserted. The same failed node passed in isolation without any limit or implementation change. Per-symbol elapsed values and working-set delta were not printed; the original assertions passed.

[Document audit](assets/2026-10-26-market-linkage-p2-doc-audit.log) checks counterpart presence, P2 IDs/checkpoints, local links and untouched protected task files. Sources, numeric thresholds, formulas and authority boundaries were also reviewed in both languages.

## MLP2-V06 — Acceptance trace

| Criterion | Actual test evidence / boundary |
| --- | --- |
| MLP2-A01 | [Original-source hash and 5 excerpts verified](assets/2026-10-26-market-linkage-p2-source-audit.json), with tests/fixtures/p2_original_prompt.json; G01–G14 in paired specification; README A/B policy, capability map and operations |
| MLP2-A02 | test_p2_policy_contract.py, test_p2_review.py, test_p2_storage.py, historical codec/hash and test_market_linkage_api.py exact schema projection |
| MLP2-A03 | test_p2_sizing.py, test_p2_replay_mutations.py: tier edges, missing/future data, grid intersection and corrected/refetched inputs |
| MLP2-A04 | test_p2_composition.py:1000→500→200;100→no legal Q0;200→100, P1 exception boundaries |
| MLP2-A05 | test_p2_economics.py: synthetic B100500,T109500,Z94500,reward9000,loss6000,cost1000,spread10 |
| MLP2-A06 | test_p2_economics.py and test_p2_policy_contract.py: exact arithmetic, minimum/included fees, expiry/invalid/overflow and explicit inclusive gates |
| MLP2-A07 | test_p2_chain.py, test_p2_simulation.py, test_p2_concurrency.py and p2-pretrade.spec.ts: explicit approval and one separate whole fill |
| MLP2-A08 | test_p2_runtime.py, test_p2_simulation.py, test_p2_risk_notifications.py: frozen-policy invalidation, quote recovery and actual risk SELL bypass |
| MLP2-A09 | test_p2_api.py, test_p2_storage.py, test_p2_concurrency.py: read-only preview, rejection, reopen and atomic authority |
| MLP2-A10 | test_p2_replay.py, test_p2_replay_mutations.py, test_p2_frozen_workers.py: real reader/worker/publication, future-event invariance and existing backtest fee tests |
| MLP2-A11 | p2Review.spec.ts, p2Runtime.spec.ts, p2-pretrade.spec.ts plus P0/P1 browser regression |
| MLP2-A12 | Final ledger, exact failure reconciliation and bilingual verification: PASS |

Representative executable nodes (in addition to the complete groups above):

- MLP2-A02: `tests/unit/test_p2_policy_contract.py::test_old_reader_still_refuses_schema8`.
- MLP2-A03: `tests/unit/test_p2_sizing.py::test_exact_half_open_boundaries`.
- MLP2-A04: `tests/unit/test_p2_composition.py::test_volatility_then_market_reduction_not_reversed_or_replaced`.
- MLP2-A05: `tests/unit/test_p2_economics.py::test_specification_scenario_and_exact_gate_equality`.
- MLP2-A06: `tests/unit/test_p2_economics.py::test_included_fee_is_not_charged_twice_and_fractional_fees_round_up`.
- MLP2-A07: `tests/integration/test_p2_concurrency.py::test_full_simulation_consumes_approval_once`.
- MLP2-A08: `tests/integration/test_p2_risk_notifications.py::test_risk_exit_bypasses_failed_buy_economics`.
- MLP2-A09: `tests/integration/test_p2_concurrency.py::test_failure_after_inventory_write_rolls_back_every_effect`.
- MLP2-A10: `tests/integration/test_p2_replay_mutations.py::test_future_approval_does_not_change_prior_private_state`.

G01 retains P0/P1 linkage/strength/exception contracts. G02/G03 are the new deterministic policies; G04 checks source/evidence dimensions with human review. G05 monetary caps, G06 broker/partial-fill ledgers, G07 non100-share simulation, G08 automatic event deadlines, G09 fundamentals, G10 new provider coverage, G11 daily-linked five-minute confirmation and G12 autonomous research remain explicitly deferred or human boundaries. G13 A-only source authority and G14 existing whole-signal accounting are preserved. Tests do not claim to automate those excluded capabilities.

## MLP2-V07 — Delivery scope

Implementation changes no actual user database and sends no live notifications, provider requests or broker orders. Fees/prices used for acceptance are explicit synthetic estimates, not current market certification. Push and deployment are outside this authorization. Preserve tasks/plan.md and tasks/todo.md. Commits use the required Chinese Conventional Commit layout. All checks are reconciled; T16–T18/C06 are complete. Implementation and evidence are committed locally; no push or deployment is included.

Implementation delivery commits: `ac7cac1` (approved contracts/source), `471ebd4` (strict policy/hash), `fa2ae86` (exact sizing/economics), `642e66c` (review, runtime, UI and frozen replay). Final audit found no unresolved acceptance issue.

Archived logs normalize line endings and trailing whitespace only; outcomes, failures and warnings are retained.
