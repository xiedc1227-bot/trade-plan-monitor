# Contract inventory: market-linkage-p0

## MC01 — Authority and baseline

The user approved MLP-D01–MLP-D06 and authorized implementation on 2026-10-24. Inventory baseline: `c7378a4`, branch `main`. This appendix implements the documentation portion of MLP-T01; acceptance remains subject to baseline verification and the checks below. No production capability is implied.

## MC02 — Observed boundary inventory

All paths below are relative to `src/trade_plan_monitor/` unless prefixed `web/`.

| Boundary | Actual readers/writers | Required change |
| --- | --- | --- |
| Executable format | `domain/plan_codec.py`, `domain/unified_plan_models.py` | Explicit Schema 6 dispatch; preserve Schema 1–5 serialization and rejection semantics |
| Draft / validation | `domain/daily_plan_validation.py`, `domain/unified_plan_validation.py` | Explicit linked draft branch; no fallback to Schema 4 |
| Hashing | `domain/plan_hash.py`, `state/daily_repository.py` | New content domain; unchanged old canonical JSON and hashes |
| AI extraction | `ai/plan_extraction.py`, `ai/extraction.py`, `ai/loop_plan_extraction.py` | Version-aware candidate and source bindings, no approval authority |
| Updates / preparation | `ai/plan_update_extraction.py`, `ai/preparation_wire.py`, `ai/plan_delta_wire.py`, `ai/predecessor_patch.py`, `ai/update_review.py` | Preserve linked policy in full and patch flows; reject silent conversion |
| Review | `ai/daily_review.py`, `state/daily_review_store.py`, `web/plan_service.py`, `web/daily_service.py` | Content and source bindings include every strategy leaf; approval invalidation |
| Persistent state | `state/daily_state_models.py`, `state/daily_repository.py` | Closed new evidence payload and linked signal variant, old records unchanged |
| Execution | `decision/unified_lifecycle.py`, `state/simulation.py` | Persist frozen full quantity, never recompute from fixed rule quantity |
| Runtime | `runtime/daily_service.py`, `runtime/production.py` | Paired stock/index acquisition and explicit linked dispatch |
| Read/send authority | `runtime/status_authority.py`, `web/runtime_status_read_service.py`, `notifications/outbox.py`, `notifications/dispatcher.py` | Completion and send checks bind both consumed evidence sets |
| Replay | `backtest/run_input.py`, `backtest/runner.py`, `backtest/loop_dataset.py`, `backtest/plan_schedule.py`, `backtest/plan_updates.py`, `backtest/preparation_review.py` | Linked input and review admission; retain old frozen formats |
| HTTP | `web/routers/plans.py`, `web/routers/daily_plans.py`, `web/preparation_schemas.py` | Extend current families with explicit variants; unsupported readers fail closed |
| Browser contracts | `web/src/api/generated.ts`, `web/src/api/generated-runtime-status.ts`, `web/src/composables/usePlanWorkspace.ts` | Regenerate from actual server models; render server decisions |

## MC03 — Frozen payload decisions

Executable identity is `schema_version=6`, `execution_mode=CONDITION_PLAN`, `execution_version=condition-plan-v2`. Existing root fields retain their current types and bounds. `reference_market` is required for linked plans and derived using the existing board mapping. A linked ordinary rule has BUY/TACTICAL, daily confirmation, next-session execution, explicit `condition` as S0, explicit LOW_BUY zone, validity, independent-signal and invalidation policies. It contains `market_policy` and `quantity_policy`, and forbids `quantity`; a fixed rule forbids those two policy fields and retains `quantity`.

`market_policy` contains required `policy_version=market-linkage-v1`, `base_confirmation=S0`, `exception_policy=BLOCK_P1`. The expanded state, strength and S1/S2 definitions are exact versioned constants specified in MR03, RS02 and CS02–CS03, with explicit source-review bindings for their expanded strategy values. A version label alone is insufficient provenance. S0 remains a full user-defined tree. Required Decimal factors serialize as strings. All quantity policy fields are required as specified in QP01; no optional field default may invent a strategy.

Drafts preserve missing values as null and unresolved evidence without becoming executable. Expanded conditions count against depth 4 and leaf 50 limits. The shared quantity preflight accepts explicit Q0, factor, minimum quantity and increment; verifies strict integers and Decimal factors, returns the greatest common legal quantity or no quantity, and has no inventory or execution authority.

## MC04 — Hash and compatibility matrix

Canonical JSON remains sorted keys, UTF-8, compact separators and no NaN. Full plan identity remains SHA-256 of the exact executable canonical JSON. Schema 6 review content excludes only `plan_id`, `version`, `name`, `metadata` and uses domain `plan-review-content-v3` followed by a NUL byte and canonical bytes. Schema 5 retains `plan-review-content-v2`; older domains remain byte-identical.

New linked decision evidence uses `market-linkage-evidence-v1`; linked signal calculation uses `market-linkage-calculation-v1`. Both hash the complete versioned payload using the existing domain/NUL/canonical hashing primitive. Include session, cutoff, plan/review identity, all consumed source hashes, selected route, Q0, factor and quantity. Later facts cannot enter the decision. Full evidence retains admitted receipt times for audit; the separate continuity hash excludes volatile retrieval state as specified in MC06. A pending signal references this immutable calculation; inventory eligibility is revalidated separately at execution.

| Payload | New reader | Old reader / rollback |
| --- | --- | --- |
| Schema 1–4 historical | Existing exact decoding/replay | Unchanged |
| Schema 5 fixed | Existing exact decoding/activation | Unchanged |
| Schema 6 linked | Dedicated validation and new hash domain | Explicit unsupported version; never downgrade |
| Old state/evidence | Original closed models | Unchanged |
| Linked state/evidence | Explicit versioned payload | Preserve storage, block unsupported operation |

Existing public routes remain; only typed request/response variants expand. Generated schema changes and snapshot hashes must be recorded after generation, not fabricated here. Rollback disables linked activation/execution and leaves records intact. Temporary-database migrations must not rewrite historical JSON.

## MC05 — Verification gate

Run baseline domain/review tests before product changes; preserve failures and diagnose them. Test exact old round trips, unsupported-version rejection, content-hash parity between executable/draft, strict source bindings and restart-safe persistence in their owning tasks. MLP-T01 is not complete until boundary inventory, bilingual parity and baseline diagnostics are recorded. Later task completion requires actual implementation tests, not this inventory alone.

## MC06 — Implemented storage and interface extension

The executable branch is Schema 6 / `condition-plan-v2`; research inputs use `backtest-run-v7`. Linked daily facts use `market-linkage-index-v1`; replay freezes a `market-linkage-replay-source-v1` source with exact observation timestamps, revisions, calendar scope and reference identity. Loop manifests carry optional `linked_index_source`; absent fields are excluded from legacy serialization. Stored loop bundles validate their source and schedule before workers can run. Existing runtime JSON storage accepts the explicit closed extension without a destructive migration.

`MarketLinkageDecision.evidence_hash` covers its complete canonical payload, including `QuantityCalculation.calculation_hash`. The inner calculation digest covers its own bounded operands/result/blockers; the enclosing decision binds that calculation to the rule, plan content, date and consumed evidence. `consumed_hash` separately binds source identity and policy without volatile wall-clock or inventory changes; it supports invalidation without resizing. Both digests are verified on decoding. Simulation checks the exact frozen quantity and current source authority in its existing transaction. Reads, completion proof capture/matching and reminder send admission reject superseded index evidence without modifying inventory.

Official grids use `cn-equity-buy-grid-2026-07-06` with a dated source and URL. Earlier dates and unsupported security prefixes return unknown. The legal market grid is intersected with the existing 100-share simulation grid. This does not certify any provider or BSE calendar.

No HTTP route was added. The generated artifacts add 26 reachable models and extend 15 existing models; exact Schema 5 projections are compared against `c7378a4` in both API profiles. Artifact digests are recorded in [U-MLP](SPEC-unified-plan.md). Existing `/review-context` registration corrects an older test allowlist omission; its route was already approved and implemented before this change.

Daily content identity uses `market-linkage-index-content-v1` over exact bar values, dates and source kind, excluding polling `observed_at` and batch-wide `provider_revision`. Full evidence retains both excluded fields for audit/cutoff checks. A later correction is ordered by observation time, never by the numeric content-hash revision; cached earlier inputs cannot replace it.

Stock continuity likewise excludes receipt-derived `bar_id`, `received_at`, `available_at` and `adjustment_as_of`, while retaining admitted prices, sessions, provider and basis identity. Numeric confirmation operands and strength values use canonical Decimal content; equivalent formatting is not a correction. Full decision evidence keeps original acquisition fields and operands. Daily-close replay requirements remain active even when S0 contains only `REVIEWED_FACT` leaves.
