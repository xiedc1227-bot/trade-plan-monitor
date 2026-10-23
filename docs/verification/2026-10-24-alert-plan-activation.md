# Reviewed alert-only plan activation — 2026-10-24

## Authorization and scope

The user explicitly authorized activating reviewed version `3c426adf-09d2-48ca-af3d-177caa4f8f65` (`605296-SS-WATCH-20261023`, version 1), while preserving history and simulated inventory. Review revision 1 and review ID `d28eacf1-3447-488e-8216-c31ff4e7f11e` were already confirmed in the preceding task. No new review, rule edit, inventory initialization, simulated trade or CI configuration was requested or performed.

## Activation failure and repair

The first UI activation returned an internal error. The existing production Web lifecycle defaults to an aware UTC clock, but `MonitorEventDraft.occurred_at` requires Asia/Shanghai. The activation transaction rolled back; both activation tables remained empty. The same boundary also affected supplement receipts and deactivation events when using UTC clocks.

`PersistentPlanWebLifecycle` now normalizes its default or injected aware clock through the existing `_shanghai_datetime` helper. This preserves the instant and rejects invalid/naive timestamps. Event validation, source/review binding, activation revisions, rule semantics and database schema are unchanged. No records were patched manually.

Four isolated default/UTC activation/deactivation cases reproduced strict timezone failures before the fix. After the fix, all 63 tests across `test_plan_activation_event_timezone.py`, `test_current_plan_api.py`, `test_daily_plan_chain.py`, `test_monitor_events.py` and `test_recovery_activation_fences.py` passed; Ruff passed. The new cases verify event timestamps and revisions, active pointers, and empty inventory tables. One existing Starlette/httpx deprecation warning remains. This is a targeted regression result, not a full-suite claim.

## Live result and limits

The verified local Web listener was restarted to load the fix. Activation then succeeded through the page at `2026-10-24T01:10:21.921326+08:00`, activation revision 1. The stored plan remains exactly one `RISK_ALERT`: current official daily close `LT 2659 FEN`, with the fixed source date `2026-10-15`. There are no ordinary buy/sell rules or risk/liquidation branches. Plan payload and hash remain unchanged.

At `2026-10-24T01:10:47.640239+08:00`, health reported `RUNNING / STANDBY / SESSION_CLOSED` and included the exact active version and hash. The plan scope was `AWAITING_FIRST_EVALUATION`, with 0/1 completed official-close evaluations. Activation and healthy off-session standby do not prove a completed condition evaluation or notification delivery. No synthetic reminder was injected into the user's plan.

Read-only before/after comparisons preserve all three plan versions, unchanged other drafts, all review provenance and all four simulated-inventory tables. Only the target version's activation state/status changed as authorized. Local snapshots and server logs are retained outside the repository in `../Temp/plan-activation-20261024/`; no local database or configuration secret is included in these code/document changes. No commit or push was performed during activation.

## Commit preparation

The subsequent user-authorized commit includes only the clock fix, its regression file, this bilingual report, [compact verification evidence](evidence/2026-10-24-alert-plan-activation/verification.json) and [the activation page](evidence/2026-10-24-alert-plan-activation/activated.png). A fresh read-only comparison confirmed that activation, plan history, review records and inventory remain identical to the successful activation snapshot. The 63-test result applies to the unchanged source bytes recorded by LF-normalized SHA256 values; no redundant test run or service restart was needed for this documentation-only preparation. No CI workflow, local database, raw database snapshot, configuration or key is included.
