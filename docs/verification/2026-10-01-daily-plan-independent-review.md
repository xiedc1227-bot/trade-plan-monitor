# Independent review: daily-plan

> Scope changed2026-10-02: the user authorized removal of daily broker order/partial/unknown tracking in favor of explicit atomic whole-lot simulation. This document records the prior scope; its completion/test conclusions do not approve the new cleanup. Follow the [current cleanup contract/tasks](../../tasks/2026-10-02-daily-plan-simulation-cleanup.md) and revised canonical specification. Preserve the historical evidence below.

Canonical English; paired user review copy: `2026-10-01-daily-plan-independent-review.zh-CN.md`.

## R01. Verdict and checkpoint

**Final independent re-review: no remaining material findings; F1–F11 CLOSED.** R07 is the current conclusion. R03–R06 preserve earlier findings and checkpoints, including historical OPEN labels. The coordinator's final complete offline backend gate has passed; R08 records that separately attributed result.

- Date: 2026-10-01.
- Reviewer: user-requested independent `gpt-6-astra/high`, fresh review context, `/root/final_review_v2`.
- Reviewed baseline: uncommitted daily-plan changes relative to `b2572b6`, including untracked implementation, tests and documents. This is a first-round working-tree review, not a committed revision certification.
- **Round 1 verdict: Request changes. F1–F11 are OPEN.** The coordinator has assigned fixes to Sol. No finding is closed merely because a fix has been reported or started; independent re-review is pending.
- R03 preserves the original Round 1 findings and OPEN labels as historical evidence. R07 records the final independent re-review status; later implementation changes are not certified until checked.
- Review workflow: Astra design → Sol implementation → Astra independent review → Sol fixes → Astra re-review. Final full regression is owned by the coordinator.

Scope follows the resumed user instruction and D01/D11/DP-A15/DP-A19: fundamentals and announcement verification are excluded from daily monitoring, remain visible non-monitoring background, and cannot become technical facts, prerequisites or blockers. Tradability, suspension and certified calendars remain operational inputs. Existing index behavior and Schema 1/2/3, prompt v1–v6 and ta-v1 remain compatibility boundaries. The original `../docs/TradingAgents/reports/新提示词.txt` was read and not modified.

## R02. Method and evidence boundaries

The reviewer used `code-review-and-quality` and `vue-best-practices`, read the repository instructions, source template, daily specification/capability map/task context, enumerated both tracked and untracked files, and traced the new chain across domain, source review, persistence, runtime, API, notification and Vue boundaries. Existing tests were read for intent and gaps rather than accepted as proof by count.

Targeted checks used synthetic reviewed plans, temporary SQLite databases, `Chain`/`TestClient` fixture helpers, the actual daily accounting/runtime services, or pure contract/evaluator calls. Inline Python reproductions were run with `.venv/Scripts/python.exe`; they did not change source/tests. The resulting values are recorded below. Production composition was inspected without invoking a live provider. Tests supplied synthetic human policy and did not approve the historical user plan.

Evidence labels below mean:

- **SQLite/API/runtime reproduction:** temporary persisted state with the normal save/review/activate API and/or the actual runtime services; the particular command boundary is identified per finding.
- **Pure reproduction:** the actual contract/review/evaluator function was called with synthetic inputs.
- **Static production/UI trace:** directly inspected call signatures and state transitions; no claim that an independent production/browser reproduction was executed.

File paths are repository-relative. Function names are the stable precise anchors; line references mentioned during review described the first-round baseline and may move during fixes.

## R03. Required findings

### F1 — P1 — OPEN: CLEAR risk retains an obsolete plan's scope

**Files/anchors:** `src/trade_plan_monitor/decision/daily_risk.py`, `advance_daily_risks`, initial `dict(old)` branch; `src/trade_plan_monitor/runtime/daily_service.py`, risk persistence.

**Reproduction:** Save/review/activate version 1 with `involves_core=True`, `target_core_qty=0`; evaluate a normal close so both risk states persist as CLEAR. Save/review/activate version 2 with `involves_core=False`, `target_core_qty=100`. Evaluate 38.00 followed by the next exchange-session close 38.10, below 38.18. The ordinary risk becomes CONFIRMED with the old `True, 0` scope. Output included `('ORDINARY_TECHNICAL', 'CONFIRMED', True, 0)` while the current reviewed policy protects CORE.

**Consequence:** A risk that had never triggered can later authorize selling CORE contrary to the active reviewed version.

**Required fix/regression:** Refresh untriggered CLEAR scope from the applicable reviewed branch. Preserve PENDING/CONFIRMED obligations and reassessment causal metadata. Test scope changes in both directions before first breach, and verify edits cannot weaken an already latched obligation. Evidence: SQLite/API/runtime reproduction. Acceptance: DP-A03/DP-A16.

### F2 — P1 — OPEN: Order reports can corrupt reservation authority

**Files/anchors:** `src/trade_plan_monitor/state/daily_accounting.py`, `report` linked-intent validation and `snapshot` order folding; `src/trade_plan_monitor/decision/daily_lifecycle.py`, `own_reserved > remaining`.

**Reproduction:** For one BUY100 signal, register two PENDING100 reports with different `external_id` values and current revisions through the real accounting service in temporary SQLite. Both writes succeed. The next runtime evaluation raises `ValueError: pending order quantity exceeds immutable signal remainder`. Then submit a CANCELLED1 report for the first external ID with `side=SELL`, `bucket=CORE`, `signal_id=None`; it is accepted and changes aggregate BUY reservation from 200 to 100 by overwriting that order's identity.

**Consequence:** Accepted reports can release unrelated BUY capacity or permanently break subsequent evaluation. Per-report quantity validation does not enforce the original signal's aggregate authority.

**Required fix/regression:** Preserve external-order ownership (symbol/side/bucket/signal), validate explicit state transitions and aggregate outstanding quantities against linked remaining authority, and preserve actual fills/idempotency. Genuine out-of-intent transactions need the explicit unlinked audit path; they must not silently acquire signal authority. Cover multiple orders, partial fills, UNKNOWN reconciliation, incompatible cancellation, retries and rollback through public APIs. Evidence: SQLite/accounting/runtime reproduction. Acceptance: DP-A11/DP-A12/DP-A18.

### F3 — P1/P2 — OPEN: Successor versions leave old signals permanently READY

**Files/anchors:** `src/trade_plan_monitor/runtime/daily_service.py`, `run_inputs` successor-version `continue`; `src/trade_plan_monitor/decision/daily_lifecycle.py`, `confirm_daily_signal` prior-state gate.

**Reproduction:** A Friday confirmation becomes READY100 on Tuesday. Activate version 2. Evaluate Wednesday at 16:00. The historical signal remains `READY`, with `executable_qty=0`, `new_order_qty=100`, and `SUCCESSOR_EQUIVALENCE_REVIEW_REQUIRED`. The successor branch skips expiry/reset persistence. Subsequent independent confirmation is rejected because the previous signal remains READY.

**Consequence:** A routine version replacement permanently blocks legitimate later independent signals and shows misleading new-order authority on a historical signal.

**Required fix/regression:** Advance historical lifecycle/expiry without granting execution, zero both executable/new-order projections, and support verified new independent evidence across versions/plan IDs. Preserve old consumption and unknown orders. Test READY and partially filled replacement, expiry, reset/event rearm, and restart. Evidence: SQLite/API/runtime reproduction. Acceptance: DP-A07/DP-A09/DP-A18.

### F4 — P1 — OPEN: SELL reservations and UNKNOWN orders are ignored

**Files/anchors:** `src/trade_plan_monitor/decision/daily_lifecycle.py`, SELL execution branch; `src/trade_plan_monitor/decision/daily_risk.py`, `risk_execution`; `src/trade_plan_monitor/runtime/daily_service.py`, send-time checks.

**Reproduction:** Actual TACTICAL100, reported sellable100, and another UNKNOWN SELL100 against the same holdings. The ordinary evaluator returns READY, executable100, new_order100 and no blockers. The risk evaluator also returns RISK_EXIT with TACTICAL100 and assigns the same settled lot100, with no blockers. PENDING SELL is likewise not deducted.

**Consequence:** The monitor can authorize selling holdings already committed to another order or possibly already sold.

**Required fix/regression:** Reconcile sell-order reservations against bucket/lot availability, distinguish continuing own intent from new orders, and keep UNKNOWN execution locked while retaining the confirmed risk obligation. Apply the same authority at send time. Test ordinary/risk overlap, external PENDING/UNKNOWN SELL, partial fill/cancellation and explicit outstanding-order completeness. Evidence: pure reproduction and runtime call tracing. Acceptance: DP-A08/DP-A12/DP-A16/DP-A18.

### F5 — P1/P2 — OPEN: Source exclusions can hide technical policy

**Files/anchors:** `src/trade_plan_monitor/domain/daily_scope.py`, `require_nontechnical_exclusion`; `src/trade_plan_monitor/ai/daily_review.py`, `build_daily_review` INVENTORY_ASSERTION treatment; `src/trade_plan_monitor/ai/daily_extraction.py`, allowed clause dispositions.

**Reproduction:** Source `股价低于39.45元时买入100股。` can be selected in full as HUMAN_SCOPE_SELECTION. Review returns `issues=()` and BACKGROUND: the finite guard misses this concrete price/quantity/buy policy. Separately, `收盘跌破38.18元时停止加仓。` can be labelled INVENTORY_ASSERTION with no paths and a sufficiently long concrete-sounding reason; review again returns no issues. The latter disposition is also available to AI output.

**Consequence:** Required technical source policy can disappear from the review/activation contract through a non-policy classification.

**Required fix/regression:** Close both suppression routes for common concrete technical price/action/quantity statements, retain legitimate actual-inventory assertions and exact fundamental exclusions, and preserve technical remainder coverage. No universal natural-language classifier is required. Test the exact counterexamples, mixed clauses, unknown fundamental wording, AI dispositions, preview and saved review. Evidence: pure review-validator reproduction. Acceptance: DP-A02/DP-A03/DP-A15/DP-A19.

### F6 — P1 — OPEN: One technical fact can satisfy all three evidence dimensions

**Files/anchors:** `src/trade_plan_monitor/domain/daily_plan_models.py`, `DailyEnabledRule` and `DailyTradePlan.semantic_contract`; `src/trade_plan_monitor/decision/daily_conditions.py`, REVIEWED_FACT matching; `src/trade_plan_monitor/decision/daily_lifecycle.py`, ordinary confirmation.

**Reproduction:** Set `price_structure`, `volume_or_candle` and `technical` to the same `REVIEWED_FACT` with `fact_kind=TECHNICAL`. The complete Schema 4 plan is accepted. Runtime matching is by fact kind/date, so the same fact satisfies all three roots. The same structural weakness permits one indicator leaf in every root.

**Consequence:** A standalone technical fact/indicator can authorize ordinary trading despite the required independent price-structure, volume/candle and technical evidence dimensions.

**Required fix/regression:** Validate each dimension's permitted evidence families and successful ALL/ANY paths; an irrelevant alternative must not bypass its required dimension. Preserve valid composite conditions. Add contract/draft issues and a real review/activation/runtime negative case, alongside valid three-dimension cases. Evidence: complete-model pure reproduction plus evaluator trace; no independent end-to-end F6 execution was claimed. Acceptance: DP-A03/DP-A04/DP-A05.

### F7 — P1 — OPEN: Production immediate reevaluation calls a non-callable Clock

**Files/anchors:** `src/trade_plan_monitor/runtime/production.py`, `ProductionMonitorPipeline.__init__` daily service construction; `src/trade_plan_monitor/runtime/daily_service.py`, `reevaluate_version`; `src/trade_plan_monitor/runtime/clock.py`, Clock/SystemClock; `src/trade_plan_monitor/web/monitor_composition.py`, daily reevaluation callback.

**Trace:** Production passes `clock=clock` (the scheduler Clock object) to the daily service, while `reevaluate_version` executes `self._clock()`. Clock/SystemClock implements `now()` and `sleep_until()`, not `__call__`. The public FACT/POSITION/REPORT routes commit their mutation before invoking this callback. The browser fixture instead injects `lambda: chain.now`, hiding the mismatch.

**Consequence:** Real production immediate reevaluation raises `TypeError: 'SystemClock' object is not callable` after the user mutation has committed; the request fails and the expected runtime update does not occur.

**Required fix/regression:** Use one explicit clock contract consistently. Exercise the actual ProductionMonitorPipeline construction and public mutation callback with an offline Clock/provider, not another specially constructed callable-clock service. Verify committed responses and new runtime/outbox state. Evidence: static production trace. Acceptance: DP-A03/DP-A18/DP-A20.

### F8 — P1/P2 — OPEN: Risk reassessment and completion lack durable lifecycle boundaries

**Files/anchors:** `src/trade_plan_monitor/web/daily_service.py`, REASSESSMENT mutation; `src/trade_plan_monitor/decision/daily_risk.py`, `advance_daily_risks`; `src/trade_plan_monitor/runtime/daily_service.py`, reevaluation and risk persistence; `src/trade_plan_monitor/notifications/daily_models.py`, risk event identity.

**Reproduction:** Confirm severe risk using the two technical facts. POST a successful independent reassessment with current reviewed targets and later removal proof. Stored status becomes CLEAR. The next `reevaluate_version`, using the unchanged head's official close and original facts, sets the risk back to CONFIRMED. During this reproduction shared F1 edits were beginning; the causal defect is reuse of the superseded cause, not a particular intermediate patch. Separately, the first-round source has no transition that writes FULFILLED after holdings reach the retained targets.

**Consequence:** Accepted removal evidence is ineffective; completed reductions continue to appear as CONFIRMED/RISK_EXIT0 and block later independent trading. Reusing a constant branch/cause identity can also collide with an earlier notification when a genuinely new risk arises.

**Required fix/regression:** Persist the reassessment cutover and superseded evidence/cause boundary, update the current projection after reassessment, and distinguish future new risk occurrences from the removed one. Implement target completion according to D07: reaching the reviewed targets may complete the obligation; do not invent an additional mandatory clearance gate. Preserve old signal consumption, unknown execution and independent-signal requirements; neither reassessment nor FULFILLED may resurrect an old remaining quantity. Cover unchanged-evidence replay, later new evidence, completion and new notification identity. Evidence: SQLite/API/runtime reassessment reproduction plus static completion/identity trace. Acceptance: DP-A09/DP-A16/DP-A18.

### F9 — P2 — OPEN: Incremental human supplements cannot be completed in the UI

**Files/anchors:** `web/src/composables/useDailyWorkbench.ts`, `supplement`/`refreshPreview`; `src/trade_plan_monitor/web/routers/daily_plans.py`, `_preview`; `src/trade_plan_monitor/state/daily_review_store.py`, supplement registration equality check.

**Trace:** Every supplement action refreshes preview. Preview removes all HUMAN_SUPPLEMENT bindings even when the exact candidate content hash has not changed. The client sends only the new items with `expectedRevision=0`; after the first registration, the same candidate's stored revision is 1. A second batch conflicts, while the prior mapping authority has already been dropped. Saving also requires the registered supplement collection to match the mapping exactly.

**Consequence:** The normal workflow of adding a few definitions, checking, and continuing cannot complete. The one-batch browser fixture does not cover this behavior.

**Required fix/regression:** Preserve server-registered authority for unchanged exact content, merge incremental supplements using the returned revision, and restore continuation state after preview/reload. Changed content must still invalidate stale authority. Test two batches → preview → save/review/activate, and a changed-content negative case. Evidence: static UI/API/persistence trace; no independent browser reproduction was executed. Acceptance: DP-A02/DP-A03/DP-A20.

### F10 — P1 — OPEN: Missing one official close leaves ordinary risk unrecoverable

**Files/anchors:** `src/trade_plan_monitor/runtime/daily_service.py`, `run_inputs` passes only the last series bar to risk advancement; `src/trade_plan_monitor/runtime/production.py`, `_recover_pending_close_batches` excludes DailyTradePlan and `prepare_daily_inputs`.

**Reproduction:** Friday official38.00 creates PENDING at risk line38.18. The monitor misses Tuesday. On Wednesday, provide a fully certified series containing Friday38.00, Tuesday38.10, Wednesday39.00 and evaluate Wednesday's official close. Result is still PENDING with `NEXT_OFFICIAL_CLOSE_UNVERIFIED`, although Tuesday's required evidence is present. Later days remain later than the expected second close and cannot resolve the gap.

**Consequence:** A risk confirmed by Tuesday's close is not ready for Wednesday execution, and the obligation is stuck indefinitely. Startup during the valid next-session ordinary window likewise needs a reachable close-reconstruction path, not only restoration of an already-created signal.

**Required fix/regression:** Advance missing certified official dates in chronological order through the durable state machine, preserving actual confirmation/earliest-execution dates. Make the catch-up reachable from real startup/late-data production paths. Never deliver expired historical ordinary authority. Test a missed risk-confirmation close, next-session startup ordinary recovery, later recovery after expiry, missing versus suspended sessions, and restart. Evidence: temporary SQLite/runtime reproduction plus production recovery trace. Acceptance: DP-A06/DP-A07/DP-A13/DP-A18.

### F11 — P1 — OPEN: A CORE-protecting branch lowers another branch's CORE target

**Files/anchors:** `src/trade_plan_monitor/decision/daily_risk.py`, `risk_execution`, `affected` and `target = min(... eligible ...)`.

**Reproduction:** A valid plan has ordinary risk `involves_core=False`, targetCORE100, and severe risk `involves_core=True`, targetCORE200. Actual CORE300 is fully sellable. With both risks confirmed, the current calculation returns targetCORE100 and sells CORE200. Only the severe branch affects CORE; its target200 requires selling100. Actual inventory may differ from proposed allocation, so this case cannot be dismissed using the plan's suggested CORE amount.

**Consequence:** Combining obligations sells more CORE than any applicable CORE branch authorized.

**Required fix/regression:** Take retained-target minima only across branches that affect that bucket. With no applicable branch, protect the bucket entirely. Test mixed CORE involvement as well as both-protected/both-involved cases, with actual inventory differing from plan targets. Evidence: pure evaluator reproduction. Acceptance: DP-A10/DP-A16.

## R04. Additional observations and reviewed boundaries

- The narrow `. ! ?` punctuation-trim change in daily source remainder handling is consistent with retaining meaningful technical remainder spans. AI-produced HUMAN_SCOPE_SELECTION is rejected by `DailyExtractionOutput`; this does not close F5's other routes.
- Risk allocation currently rounds the aggregate executable bucket quantity according to reviewed declaration rules before assigning internal lot debits. It can combine actual fills40+60 into a legal100-share sale; it does not inherently require two separate orders40/60. The user's screenshot feedback nevertheless correctly identifies misleading UI wording. The coordinator assigned a display fix: legal aggregate order quantity first, internal40/60 allocation only as explicitly labelled accounting detail. That UI fix is not yet independently re-reviewed here.
- Reviewed daily formula code keeps MACD histogram at `2*(DIF-DEA)` in its separate v2 path. New source exclusions do not require announcement clearance in the intended contract. These observations are not a whole-feature approval.
- Complete-plan activation is separate from source review and actual holdings/fills. The actual historical plan remains incomplete and unactivated.

## R05. Coverage, limits and next review

Material review covered the new daily domain/model/validation/hash dispatch; source extraction/review/exclusion and saved review binding; official/QFQ data admission and indicator/condition evaluation; account confirmation/report folding and persistent state; ordinary and risk lifecycle; runtime transaction/scheduler/provider composition and immediate reevaluation; alert identity/current delivery; public daily routes; Vue workbench, review, operations and recursive field editor; and the principal new unit/integration/browser tests.

Focused reproductions above are independent evidence. Reported implementation-agent test counts, builds and browser success are supporting context only and were not rerun or represented as the reviewer's own complete verification. No full backend/frontend regression was run by this reviewer, no live market/AI/notification request was made, no production DB or secret was read, and no source/test file was changed. The unchanged index/legacy behavior requires the coordinator's final relevant/full suite; static dispatch review alone does not certify every old path. Previously activated obsolete three-branch development data and every late/corrected-provider-data scenario were not independently exercised in this round.

Next: receive a stable Sol handoff, re-review F1–F11 and the aggregate-order UI correction with focused regression evidence, inspect interactions between fixes (especially CLEAR/reassessment/cause identity, reservations/completion, and successor/catch-up authority), then update this paired report with actual closed/open status. Only after material findings are resolved should the coordinator's final complete offline suite and bilingual feature verification establish completion.

## R06. Round 2 independent checkpoint

**Historical Round 2 checkpoint verdict: Request changes.** Independently verified fixes close the original F1, F2, F3, F5, F6, F7, F9 and F11 defects within the evidence below. F4, F8 and F10 remain OPEN; further fixes are in progress and are not certified by this checkpoint.

- Independent targeted run: `test_daily_history_regression.py`, `test_daily_orders_regression.py`, `test_daily_risk.py`, `test_daily_risk_allocations.py`, `test_daily_source_exclusions.py`, `test_daily_plan.py`, `test_daily_plan_review_service.py`, `test_daily_scope_http.py`: **39 passed**, 9.57 s. The reviewer also inspected the changed authority, dimension, exclusion and lifecycle code. F1 refreshes CLEAR scope and retains pending scope; F2 rejects aggregate over-reservation and external identity mutation; F3 expires historical authority and zeroes successor new-order projections; F5 rejects the original concrete policy-hiding paths; F6 requires the correct dimension on every successful ANY path; F11 combines only applicable bucket targets.
- Independent `test_daily_supplement_batches.py` plus `test_daily_production_reevaluation.py`: **5 passed, 1 failed**, 3.54 s. F7's actual production-created service with a non-callable clock now handles fact, position and actual-fill commands. F9's registered human supplements survive two batches, repeat preview, reload and activation; edited content loses prior authority, forged client supplements are ignored and duplicate version save is a controlled conflict. The failed test is F10 below. These are independent runs, not copied implementation results.

### F4 — OPEN: Residual reservations and retained-target interaction

`daily_lifecycle.check_daily_execution` originally treated a signal's own UNKNOWN residual as available after a partial fill changed its projected state. Independent pure reproduction: SELL planned100/filled40, actualTACTICAL60/sellable60, own UNKNOWN60 returned executable60/new_order60 without blockers. The UNKNOWN100 → actual40 remainder must stay locked regardless of signal display state.

`daily_risk.risk_execution` subtracts pending sells from sellability but also must subtract them from the required reduction. Independent pure reproduction: actualTACTICAL200, sellable200, reviewed target100, pendingSELL100 returned another executable100. Existing plus new orders would reduce holdings to0 instead of100.

The inverse boundary also fails: accounting retains a fully filled former UNKNOWN order with quantity0. Independent pure reproduction: old UNKNOWN SELL quantity0 plus actual/sellableTACTICAL100 and target0 returned executable0/unavailable100 with `SELL_ORDER_RECONCILIATION_REQUIRED`. Filter zero balances or normalize terminal order state without releasing a real UNKNOWN60 remainder. All three counterexamples were sent to the implementation owner; subsequent edits await re-review.

### F8 — OPEN: Completion must not revive consumed authority or suppress new causes

Independent SQLite/API/runtime reproduction: Friday BUY100 is READY Tuesday; Friday severe evidence confirms risk; actual CORE SELL100 fulfills the risk on Tuesday10:00. A fresh tradable quote one second later makes the **same old BUY signal** READY with executable100/new_order100. Risk completion is valid under D07, but it cannot undo `RISK_OR_REVIEWED_INVALIDATION`; preserve old consumption and reservations, require a genuinely independent later signal. The existing new-history test waited until the close and therefore missed this same-window path.

The date-only completion/reassessment cutover also suppresses a genuinely new cause at Tuesday's later official close after Tuesday10:00 completion. Code inspection confirmed `close_date <= cause_cutover_date` discarded the whole day. Use the consumed close/evidence and actual cutover time so the later official close can create a distinct cause, while immediate replay remains CLEAR. Fixes are being applied; this checkpoint does not certify them.

A further independent SQLite/API/runtime reproduction confirmed the original cause-dedup defect remains: Friday severe risk emits an event Tuesday; Tuesday reassessment clears it without changing holdings; fresh Tuesday severe evidence confirms a new cause; Wednesday current inventory/quote again permit selling the same openingCORE100. The second risk is CONFIRMED with Tuesday confirmation date, but `event_ids=()` because both `risk_action` values are identical. The stable symbol/kind risk_id and `daily_alert_key` omit the distinct cause evidence/date. Include cause identity in alert deduplication and validate that cause at send time.

### F10 — OPEN: Real production recovery still rejects the required daily evidence

The reviewer independently ran the real composition/lifespan recovery test. At Friday's first actual scheduler OFFICIAL_CLOSE, expected PENDING was CLEAR with `DAILY_SESSION_OR_BASIS_UNVERIFIED`; recovery never reached its later assertions. `production.prepare_daily_inputs` requests 750 calendar days and retains 500 daily bars, while production reference refresh covers 366 days. Strict complete-session admission consequently rejects bars outside the loaded calendar. Align real certified calendar coverage with the required daily/indicator warmup window; do not shorten a fixture or bypass admission. Recheck Friday first-close admission, missed Tuesday confirmation, Wednesday startup, current QFQ anchor, original execution date and dynamic warmup requirements after the source fix.

Independent complete-model admission also accepts `macd_min_observations=500` with `MACD_HIST` offset1. `DailySeries` and production cap data at500, so this condition can never obtain its required501 observations. The same boundary affects sequence500+offset1 and volume499+offset1. Either support the actual bounded history requirement or reject unsupported warmup/offset combinations during new-daily review/activation; do not approve a permanently unevaluable contract.

The final adaptive-calendar patch introduced another independently reproduced production boundary: a synthetic exchange calendar with 50 additional certified weekday holidays in the recent750-day window forces the1500-day request; the actual OFFICIAL_CLOSE then raises `ValueError: days must not exceed 1000 rows` in `refresh_references` → `_commit_trading_days` → `references.upsert_trading_days`. Preserve all certified dates using bounded batches in the same transaction. Also check the adjacent `DailySeries.session_dates` max1000 boundary when the expanded persisted calendar supplies more than1000 open sessions; do not discard bars or disable coherence validation. This source patch remains unapproved pending the fix.

### Order aggregation boundary and remaining limits

Independent temporary SQLite accounting verified one externalId with TACTICAL SELL40 then SELL60 is accepted and debits100. The same externalId with CORE SELL100 then TACTICAL SELL100 rejects the second fill because bucket identity is immutable. The current generic UI statement that internal batches may share one order must explicitly limit this to the same bucket and show bucket-specific submission/registration quantities; it must not imply cross-bucket200 can be recorded as one actual order. This is a bounded UI/contract clarification, not a request to build a broker OMS.

Round 2 has not independently run Chrome, full regressions or live integrations. The unchanged legacy/index boundaries, every corrected-provider-data scenario and previously activated obsolete development records retain R05's limitations. The coordinator owns final broad regression after the remaining fixes stabilize.

## R07. Final independent re-review

**Verdict: no remaining material findings in the reviewed daily-plan change. F1–F11 are CLOSED.** This closes the review findings; it does not substitute for the coordinator's final full offline regression or certify a live deployment/provider.

| Finding | Final status | Independently verified repair |
| --- | --- | --- |
| F1 | CLOSED | CLEAR uses current reviewed scope; pending/confirmed obligations retain their scope. |
| F2 | CLOSED | Aggregate order authority and immutable external order identity prevent reservation corruption; same-bucket actual40+60 remains recordable. |
| F3 | CLOSED | Old authority expires durably; successor projections grant no new order quantity; a later independent event can create a new occurrence. |
| F4 | CLOSED | Positive UNKNOWN residuals stay locked after partial fills, zero residuals cease blocking, external sell reservations and already-covered target reductions cannot be offered again. |
| F5 | CLOSED | The reproduced concrete technical-policy exclusion and INVENTORY_ASSERTION bypasses are rejected; human scope provenance remains distinct from AI output. |
| F6 | CLOSED | Each successful condition path proves its own price, volume/candle and technical dimension. |
| F7 | CLOSED | Actual production-created services use the clock correctly; public fact/position/fill mutations refresh the persisted current snapshot. |
| F8 | CLOSED | CLEAR replay cannot revive consumed risk evidence; FULFILLED is allowed when the reviewed target is reached; old ordinary authority remains invalidated; later independent BUY and later same-day risk causes work; new risk causes have distinct alerts and send-time cause checks. |
| F9 | CLOSED | Registered supplements survive successive batches, preview and reload with the correct revision; content changes and forged client supplements do not inherit authority. |
| F10 | CLOSED | Real scheduler/startup recovery processes missing official closes on the current QFQ basis; required history is bounded and certified; expanded calendars survive storage, admission and runtime input limits. |
| F11 | CLOSED | Retained targets combine only across branches that affect the bucket. |

Final independent runs and focused evidence:

- `test_daily_orders_regression.py`, `test_daily_history_regression.py`, `test_daily_safety_boundaries.py`, `test_daily_plan.py`, `test_daily_risk.py`, `test_daily_risk_allocations.py`, `test_daily_scope_http.py`: **63 passed**, 12.32 s. The reviewer read the corresponding fixes, including persistent `risk_invalidated`, positive residual filtering, pending-target subtraction, timestamp cutovers, cause-date alert identity/send-time checks and the500-observation admission calculation.
- `test_daily_production_reevaluation.py` plus `test_daily_supplement_batches.py`: **7 passed**, 7.03 s, independently rechecking actual production composition and the two real recovery entry points before the final calendar expansion boundary was exercised.
- After the last production fix, `test_daily_production_reevaluation.py`, `test_daily_plan_boundaries.py`, `test_daily_conditions.py`: **12 passed**, 9.04 s. Tests use SDK/provider fakes and temporary SQLite with the real production factory, lifespan and scheduler deadline; recovery does not invoke a substitute `run_inputs`/`run_target` path.
- The reviewer's own unchanged inline production counterexample was rerun after the final fix:50 additional certified weekday holidays in the recent750-day window force the1500-day calendar request. It now produces **500 real bars,500 series session dates, no data blockers and ORDINARY_TECHNICAL PENDING**, while the complete runtime calendar contains1044 dates. No bar or exchange session was fabricated. The prior storage1000 and runtime1000 exceptions are resolved.
- Source review confirmed daily-only calendar lookbacks750→1500→3000, same-transaction storage batches of at most1000 without truncating the certified calendar, a3033-date bound for complete daily runtime inputs, and a separate exact raw-bar window for `DailySeries` coherence. Non-daily reference history remains366 days. Unsupported theoretical warmup/offset totals above500 are rejected; real short-listed/suspended history still yields missing input rather than fabricated observations.
- UI and notification text now explicitly require separate CORE/TACTICAL submissions and registration, and allow internal batches to share an order only within the same bucket. Independent SQLite evidence confirms same-bucket SELL40+SELL60 registration. Cross-bucket reuse of one externalId remains intentionally unsupported and is no longer promised. Chrome execution/screenshots were performed by the coordinator/helper, not claimed as this reviewer's independent browser run.

The remaining limits are evidence boundaries, not open material findings: this reviewer did not rerun the full backend/frontend suite, access live market/AI/notification services, inspect production data/secrets, exercise every provider correction scenario, or certify every previously activated obsolete development record. No source/test files were edited by this reviewer. Only this English/Chinese report pair was written. The coordinator subsequently completed the final fixed-source backend regression; R08 records the separately attributed result. Any later material source change requires targeted re-review.

## R08. Coordinator's final completion gate

The coordinator `/root` executed `.venv/Scripts/python.exe -m pytest -q -m "not live"` against the frozen production source and reported exit0: **6065 passed, 1 skipped, 4 deselected, 1 warning in3208.19s (53:28)**. This was the coordinator's full backend run, including the long backtest acceptance group; the independent reviewer did **not** run it. The reviewer read the final log summary at `C:/Users/xiedc/AppData/Local/Temp/daily-plan-final-backend.log` and confirmed the recorded counts. The warning is the existing Starlette/httpx deprecation notice. This report records the durable result; it does not depend on retaining the temporary log.

The persisted sparse-calendar test was added after that full suite had already collected its tests. The reviewer independently read and ran its temporary source with **1 passed in3.00s**, confirming actual750→1500 provider requests,1533 persisted calendar rows,1044 complete runtime dates and500 certified series observations through the production deadline. Its permanent path is `tests/integration/test_daily_sparse_calendar_regression.py`. The helper separately ran the permanent repository copy: **1 passed in5.94s**, with Ruff passing. The reviewer compared the temporary/permanent SHA256 values and confirmed identical bytes (`55fdf3ac047871a7565ba5b093c6d1eadd14a48ece890d0966eb391afa8f080b`); the reviewer's3.00s run is the temporary-copy run, not the helper's5.94s repository run. This additional regression is **not included in6065**. Unchanged production source does not require rerunning the53-minute group solely for this test-file addition.

The final review conclusion remains **F1–F11 CLOSED, no remaining material findings**. For the complete implementation checks, permanent appended-test result and compatibility/operational boundaries, see [Daily-plan offline verification](2026-10-01-daily-plan.md) and its [Chinese review copy](2026-10-01-daily-plan.zh-CN.md). Live-provider/deployment certification remains outside this offline task.
