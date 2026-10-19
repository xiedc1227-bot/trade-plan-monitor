# Specification: One Trade Plan Workflow

> Canonical English contract. The matching review copy is `SPEC-unified-plan.zh-CN.md`.

## U01. Authority and boundary

The user's correction on 2026-10-02 restores the original single plan capability: paste source → AI draft → edit and review → explicitly activate → monitor conditions → reminders and explicitly requested simulated trades. This contract supersedes the separate daily-plan product and the live legacy/explicit family selection. A condition's period is a data requirement, never a separate plan business type. Existing board-index research and backtesting are independent; this change adds no index judgment.

Fundamentals are reviewed by the user when generating the plan. They are not monitored facts, runtime blockers, or simulation gates. Exact source exclusions remain visible and review-bound. No broker orders, execution tracking, partial fills, unknown orders, reservations, or client allocation are introduced.

## U02. Current model

The only new executable contract is Schema 5, `CONDITION_PLAN`, `condition-plan-v1`. Frozen Schema 1–4 bytes, hashes and audit records retain their original interpretation; the format number is internal history information, not a product selector. New extraction uses one server-owned prompt and review path. Old drafts require a newly extracted, edited and reviewed version; they are never silently converted or rehashed.

Each ordinary rule contains one explicit condition tree, quantity, validity, independent-signal policy, confirmation and execution window. Source-defined ALL/ANY composition is preserved. Conditions may combine existing completed daily leaves and completed five-minute leaves. Optional `alert_rules` preserve source-defined reminder-only technical conditions, with explicit confirmation and no trading quantity, liquidation target or inventory effect; they cannot authorize simulation. Optional levels, zones and technical exit branches are included only when supported by the source or an explicit reviewed human supplement. Missing meaning stays unresolved; no strategy threshold, branch, quantity, date or grouping is invented. Only `position.max_qty` is mandatory; optional CORE/TACTICAL allocation metadata is policy, never initialized inventory.

## U03. Time and evidence

`OFFICIAL_DAILY_CLOSE` confirms from official completed daily evidence and uses `NEXT_EXCHANGE_SESSION_ONLY` for ordinary simulation. `COMPLETED_BAR_CLOSE` with `timeframe_minutes=5` confirms from a complete five-minute bar and uses `CURRENT_SESSION`. These values must be explicit and consistent. Mixed trees use one evaluation cutoff: daily leaves cannot consume provisional intraday closes or future official bars; minute leaves cannot consume incomplete, gapped or later-received minutes. Fixed and dynamic references, adjustments, formula version and warm-up retain their existing proven semantics.

Data acquisition freezes plan version, hash and activation revision before I/O and rechecks them in the commit transaction. Recovery obtains only the required evidence and a valid minute quote; a daily-only plan must not require legacy `ta-v1` five-minute indicators. Missing data blocks the dependent condition rather than inventing a pass. Technical risk latches retain official-close confirmation, T+1, priority and reviewed removal. Nonquantified technical judgments require the explicitly scoped human evidence named by the plan; technical removal evidence does not require an announcement institution, title or HTTPS URL.

Scoped technical review facts explicitly record `satisfied=true` or `satisfied=false`; an absent fact remains unknown. The latest eligible review at the cutoff applies, while contradictory assertions at the same cutoff block evaluation. Negative technical facts cannot negate tradability, full-session suspension, independent-event or signal-invalidation control evidence. Composite risk conditions retain every consumed leaf evidence ID so a later risk review cannot replay already consumed evidence.

Minute replay can reuse a decision only while its persisted source bucket, plan/review/activation, scoped facts, risks and relevant inventory remain current. A later source correction requires reevaluation. Send-time reminder admission rechecks those scoped facts and the current source evidence; a previously queued positive reminder cannot remain eligible after its evidence becomes stale or false.

Current runtime status requires a committed completion proof bound to runtime generation, configuration revision, active plan identity, the latest applicable completed target, calendar and consumed source/state evidence. A read must revalidate that proof; missing or changed authority leaves the preserved evaluation cached and read-only. Reading status never acquires data or changes business records. A rule's explicit confirmation period also determines its target when its condition contains only reviewed technical facts.

## U04. One operation path

`/plans` is the sole current workspace. It shows source, structured candidate, omissions, bindings, review, saved versions, activation and simulation state. Save creates an inactive draft. Review binds source/content/evidence/revision. Activation is a separate command. Changing source or content invalidates earlier approval. Neither extraction, alerts, acknowledgement, review nor refresh changes holdings.

Current formal API operations use `/api/v1/plan-extractions`, `/api/v1/plan-drafts`, `/api/v1/plan-imports`, `/api/v1/plan-review-previews`, `/api/v1/plan-review-supplements`, `/api/v1/plan-review-confirmations`, `/api/v1/plan-activations`, `/api/v1/plan-deactivations`, `/api/v1/plan-facts`, `/api/v1/simulation-position-confirmations`, `/api/v1/simulation-position-inventory`, `/api/v1/plan-risk-reassessments`, `/api/v1/simulated-trades` and `/api/v1/plan-runtime/{symbol}`. No current route uses a separate `/daily-*` operation family. AI provider configuration is read-only in the API and loaded once from the project file. Old `dailyMapping` wire fields and internal `Daily*` names remain shared review/accounting compatibility details, never a second current workflow.

Historical reviewed OpenAPI snapshot SHA-256: `8da41a7d8d06f6a4e114570b52e88c894d0f817de365dc062bee08b28989e833`. Reviewed on 2026-10-07, Asia/Shanghai, for the existing unified research extension committed in `7a92f75`, under [SPEC-unified-replay](../backtesting/SPEC-unified-replay.md) UR01/UR03/UR04/UR05/UR06/UR08. The review covers additive `researchInput`, typed research decision/operation details, metrics/equity projections and their bounded supporting schemas. Routes, operation parameters/responses and all other existing monitor/error/job schemas are unchanged; generated artifacts match actual routes. [MV12](../../verification/monitor-loop-backtest.md#mv12-isolation-wrap-up-and-contract-review) records all 37 schema differences and executed checks. The former approval `4d1ff1d58e37b764aa057415cee1418298bc05bedbd360fbec60202f1f7cd255` remains a historical identity from `a0915f7`, not current approval. This correction approved only the then-existing unified research contract and retains that historical scope; U09 records the final review and approval of the implemented monitoring-loop preparation/service APIs.

Simulation is explicit, isolated from registered real positions and offline research fills, and applies exactly one complete positive multiple of 100 shares. Initial simulated inventory, held/sellable shares and plan targets also use multiples of 100. The server revalidates active identity, review, signal/risk authority, inventory revision, quote, calendar, T+1, CORE protection, maximum position and idempotency under one symbol transaction. No partial substitute is applied when the full authorized quantity is unavailable.

A reminder-only current plan requires current plan identity, its own activation window and condition evidence, without simulation inventory authority. Existing incompatible accounting records do not prevent a reminder, and evaluation must not mutate earlier position, signal, risk or simulation records. Historical risk cannot extend the reminder plan's activation window; simulation remains blocked without compatible accounting authority.

The notification center displays current reminder-only events and includes them under the `RISK_ALERT` filter. Their retained `REMINDER` payload marker and `alertKind=RISK_ALERT` identify review-only evidence; quantity, execution date, risk scope and simulation authority remain absent. Acknowledgement remains an independent idempotent read marker.

## U05. Removal and retention

Remove the separate daily route, page and extraction workspace, current target-contract selector and unused AI configuration write/test methods. Remove ordinary real-fill and ongoing fundamental/event-risk controls from the current plan flow. Retain frozen model codecs and historical review readers solely to interpret existing bytes; retain legacy decision logic where isolated historical backtest replay depends on it. Retain certified minute normalization, daily indicators, risk timing, simulation accounting and recovery where the one current evaluator needs them. Retained dependencies must be listed in the verification report. Historical daily acceptance cannot certify this change.

## U06. Acceptance

1. One real browser path extracts, edits, reviews, saves and explicitly activates through formal API services.
2. A current plan contains daily and minute conditions; production evaluation proves cutoff separation and activation-race protection.
3. Reminders/acknowledgement/review/refresh leave holdings unchanged. Explicit full-lot simulation preserves T+1, CORE, limits and idempotency; incompatible or partial quantities are rejected.
4. There is no second extraction workspace or live family selector. Historical bytes and hashes remain unchanged; old formats cannot bypass the current fundamental boundary.
5. Appropriate Python, frontend, formal API, production-composition and browser checks pass. Reports distinguish deterministic local evidence, unavailable external provider certification and unresolved failures.

## U07. Documentation parity

Both language versions preserve U01–U12, field names, format numbers, API paths, timing, boundaries and acceptance criteria. Current indexes point here. Keep useful frozen compatibility constraints and necessary acceptance evidence; remove superseded specifications and completed process records from the maintained tree. Historical Git evidence never authorizes current behavior.

## U08. Persistent ordinary rules (2026-10-03 scoped design)

**Decision and field contract.** A newly authored ordinary rule normally uses explicit `validity: {"mode":"PLAN_ACTIVE"}`. It follows its plan until manual deactivation or explicit activation of a reviewed replacement. There are no rule start/end fields in this mode. This is an additive Schema 5 contract, not another plan family: `CONDITION_PLAN` and `condition-plan-v1` remain. `UnifiedRule` and `UnifiedDraftRule` accept this value alongside the existing `DailyValidity` `DATE_RANGE` representation. Missing/null validity remains incomplete; only new extraction/authoring selects the explicit product default. No loader, import, save or migration fills this default into old data.

**Plan activation and source limits.** New extraction defaults to `activation.mode=MANUAL` when the source imposes no plan activation window. Existing `TRADING_DAY` and `DATE_RANGE` plan activation remain valid and bound ordinary authority. An explicit source rule deadline remains a visible `DATE_RANGE` compatibility exception with its original dates, or unresolved when it cannot be faithfully represented; it is never discarded or automatically promoted to a whole-plan deadline. The editor labels this exception as a retained source/historical restriction. Persistent conversion requires a visible source/candidate change, new evidence binding, human review and explicit activation. The rule `validity.mode` `HUMAN_SUPPLEMENT` reason must quote each complete conflicting clause and explicitly state `改为持续有效` or `convert to PLAN_ACTIVE`; deadlines without that scoped supplement continue to block review. Product-default bindings are limited to the exact new mode/default, and cannot resolve a contradictory deadline clause. Date-limit detection is a conservative guard alongside full clause review, not a general natural-language parser. Report/evidence dates and single-signal windows are not ordinary-rule deadlines.

**Lifecycle and compatibility.** `PLAN_ACTIVE` removes only the per-rule date filter when confirming a new signal. Daily signals still expire at the close of the next exchange session; five-minute signals retain `CURRENT_SESSION`. One signal authorizes one full planned quantity; a later date alone is not an independent signal. Existing identity, review, revision and send-time checks reject old ordinary authority after deactivation/replacement. Saving a draft does not replace the active version. Risk records remain latched across these operations and keep their existing explicit reassessment/removal rules; no new risk lifecycle is introduced. Shared Schema 4 `DailyValidity`, historical source/JSON/hash/review/audit bytes, and existing dated authorization remain unchanged. Historical review reconstruction must not acquire new issues merely because a rule is dated.

**Implementation scope and sequence.** (1) Extend `domain/unified_plan_models.py` and `domain/unified_plan_validation.py`; cover old canonical bytes and new explicit validity. (2) Update `ai/plan_extraction.py`, its prompt-version declarations/consumers, and `ai/daily_review.py` for exact default bindings and visible source deadlines. (3) Branch the rule validity check in `decision/unified_lifecycle.py`; change runtime/service paths only if a direct date dependency requires it. (4) Update `web/src/components/plans/planSchema.ts` and the current schema-driven editor/help as needed, regenerate affected API snapshots/types, and update current prompt references. (5) Make narrowly scoped wording edits in `../docs/TradingAgents/reports/新提示词.txt` from the repository's parent workspace. (6) Extend focused domain, extraction/review, API, production-runtime/status and browser tests; record actual results in the existing bilingual verification report, then perform independent review.

**Acceptance.** A source without rule dates yields a reviewable candidate with no invented date and activates when all other parameters/evidence are complete. New independent signals can occur on later trading days while old signals expire and cannot be duplicated. Deactivation/replacement blocks old rules/signals/queued ordinary reminders; saving alone has no effect; changed content needs fresh review. Latched risk and explicit removal, T+1, CORE, maximum quantity, whole positive 100-share simulation and idempotency remain covered. Old dated canonical bytes/hashes and authorization bounds remain identical. Explicit and ambiguous deadlines remain visible and cannot be hidden behind the new default. The formal API and one `/plans` browser flow agree with the contract. The Chinese generation template no longer treats a missing cutoff as an omission, while retaining single-signal windows and other missing-parameter semantics.

**Verification and exclusions.** Use deterministic temporary databases/fake providers only: `.venv/Scripts/python.exe -m pytest <affected tests> -q -m 'not live'`, `.venv/Scripts/python.exe scripts/generate_frontend_types.py --check`, affected Ruff checks, `npm run test -- --run`, `npm run type-check`, `npm run build`, and the current Playwright workflow. Reuse unaffected acceptance rather than repeating expensive backtest capacity runs. No other strategies, indicators, providers, recovery architecture, index features, fundamentals boundaries, accounting design, broker execution, production configuration/database, commits, pushes or deployments are in scope.


## U09. Final single-plan monitoring-loop API review (2026-10-09)

OpenAPI snapshot SHA-256: `dde2866b81a9710a51bf7817eeeb30513cfb4e844437adba7a2ef202fd52caa0`. This final scoped approval follows the implemented [monitoring-loop proposal](../backtesting/PROPOSAL-monitor-loop-backtest.md), [operations](../../operations/monitor-loop-backtest.md) and MV46 evidence. The user authorized completion and individual GitHub pushes of all remaining 20 tasks; approval here records the concrete reviewed implementation after its gates, rather than treating that authorization as verification.

Canonical monitor v2 snapshot SHA-256: `d34ffd622021a50127a6f92cbf81be8323884f1f5b2dc36e529a7ca2c0b9c807`. The approval identity above is compatibility monitor v1; both profiles have the same reviewed backtest differences, with their respective original monitoring surfaces exact.

Compared with the previously reviewed unified-research snapshot in `7a92f75`, the mounted contract has 62 paths: all 52 original paths remain, with the following 10 additions. Seven preparation paths cover create/read/source/extract/review/cancel/explicit recovery; three service paths cover inert status and explicit repair/resume/stop. No second plan family, daily successor, bulk run, simultaneous task, monitor-control or native export route is added.

| Added path | Reviewed operations |
|---|---|
| `/api/v1/backtest-preparations` | POST: 201 durable one-source preparation |
| `/api/v1/backtest-preparations/{preparation_id}` | GET: 200 durable progress |
| `/api/v1/backtest-preparations/{preparation_id}/source` | PUT: 200 revision-bound edit |
| `/api/v1/backtest-preparations/{preparation_id}/extractions` | POST: 202 explicit owned extraction |
| `/api/v1/backtest-preparations/{preparation_id}/reviews` | POST: 200 reviewed immutable manifest |
| `/api/v1/backtest-preparations/{preparation_id}/cancellations` | POST: 200 / 202 terminal or drain-pending cancellation |
| `/api/v1/backtest-preparations/{preparation_id}/recoveries` | POST: 200 explicit confirmed-ended recovery |
| `/api/v1/backtest-service` | GET: 200 inert state/capabilities |
| `/api/v1/backtest-service/recovery-requests` | POST: 202 scoped repair or exactly one selected resume |
| `/api/v1/backtest-service/stop-requests` | POST: 202 accepted owned stop |

Existing operation differences are confined to `POST /api/v1/backtest-runs` accepting the additive `PreparedBacktestRunCommand`, and GET/PATCH of `/api/v1/backtest-runs/{run_id}` accepting the additive `BacktestLoopRunView` response. Existing request parameters, receipt/status/error shapes, PATCH command and legacy branches remain exact. The three modified existing schemas are `BacktestDetailView`, `BacktestFillPage` and `BacktestRunPage`, adding the native event/fill/summary branches only; other properties and 100-item bounds remain exact. There are 108 additive reachable schemas, covering bounded preparation/source-review, shared Schema 5 conditions, opening-account/known-unknown facts, native causal reports and closed service commands. No original schema is removed or otherwise modified. Both generated profiles are checked against mounted routes.

Preparation mutations preserve local-origin/idempotency guards, strict revision bindings, single-source input, 3 attempts, closed candidate variants and unknown/cancelled-call drain fences. Submission freezes one reviewed plan/account with one resolved cutoff; replay consumes copied evidence and adds no provider/AI work. Native results preserve exact money, provenance, causal receipt identities and ordered paging. Internal stored fill keys bind the run while public receipt identifiers and exact legacy verification remain stable. Native loop exports continue returning 409 before streaming; frozen supported exports remain compatible.

Service status is inert and controls bind boot `epoch`, `expectedRevision`, original body/key and at most one selected `resumeJobIds` entry. Accepted 202 control receipts are not cleanup completion. READ_READY/READY never authorize backlog automatically. One unfinished task blocks new and mutually exclusive operations until terminal state or explicit evidence-backed recovery. Cancellation-in-progress and unknown work keep the slot; owned late work blocks replacement until physical drain. Real bounded SQLite BUSY/LOCKED metadata conflicts use the existing 503/Retry-After envelope, preserve original request retry and do not change other SQL faults. Service/thread limits and the five-experiments-per-ten-minutes measured-load boundary remain those documented in ML15–ML17/ML-O08/ML-O09.

U04/MV12 retain the historical `a0915f7` approval mismatch and the separately reviewed correction for `7a92f75`. This U09 approval supersedes the current contract identity only after the final interface checks recorded in MV46; it does not erase earlier failures, certify live AI/market providers, approve production migration/deployment or extend the accepted shared-process limits.

## U10. Authorized index overview contract extension (2026-10-09)

OpenAPI snapshot SHA-256: `76a63344e2ff29ed50c44d4ff7a5fa1e5f5f2faf938274991f8b0b6edd194c29`. Canonical monitor v2 snapshot SHA-256: `a2d99ac2c89cca1dd031cf2045251be24524550da80f1012df1e36cb0a4d595f`. The user authorized implementation and acceptance of [SPEC-index-close-display-repair](SPEC-index-close-display-repair.md) ICDR01–ICDR10 on 2026-10-09. U09 retains its historical monitoring-loop approval and scope.

The scoped comparison against the U09 snapshots proves that both profiles retain every existing path and schema unchanged. Each profile now has 63 paths: the sole added operation is readonly `GET /api/v1/market-indexes/overview`, with five supporting schemas: `MarketIndexLatestAcquisition`, `MarketIndexOverviewData`, `MarketIndexOverviewItem`, `MarketIndexOverviewResponse`, and `MarketSessionView`. It introduces no plan, accounting, provider or execution operation. Generated snapshots/types match the actual route. Executed acceptance and rollout results are recorded in the [paired verification report](../../verification/2026-10-09-index-close-display-repair.md).

## U11. Daily continuity concrete API review (2026-10-11)

OpenAPI snapshot SHA-256: `7fc0340a8b2a07414f09dc09f2fd894f4be6aeb3aa4401323cea8c0c691f4a43`. Canonical monitor v2 snapshot SHA-256: `b9d8b1e79b3c0b4637c91095ad34cff671b96c3d6cc39150eefd05218cacbf65`. Generated TypeScript SHA-256: compatibility `5dccf9683a0def43a65dcee44fcbeddb6b0b212c70b7b0139a0cd5d18461b047`; canonical `80d3a8e49f490a26f3daee1ed5411caf0f1eae27d281c548a21c7e21a03bb477`.

Under RP05-A03 standing authorization, this approval records independent review of both actual generated diffs against U10, based on implementation through `05cad3e` plus the public create-discriminator correction. Authorization is distinct from verification. U09/U10 historical identities remain. Each profile now has 64 paths: only readonly `GET /api/v1/backtest-preparations/{preparation_id}/items` is added. The seven existing preparation operations and run POST/GET/PATCH gain explicit v2 branches (10 existing operations total); their operation IDs and error responses remain exact. No paths or old schemas are removed. Only `PreparationCreateCommand`, `BacktestRunPage`, and `BacktestDetailView` change by additive unions; the other 397/410 old schemas and all monitoring operations are unchanged.

The 36 new schemas cover bounded collection creation/progress/pages, item correction/whole-chain review, source-bound candidate evidence, version transitions and continuous results. Creation requires `schema_version: backtest-preparation-v2`; other collection mutations require `schemaVersion: backtest-preparation-v2`; scheduled run submission requires `schemaVersion: prepared-loop-plan-v2`. Sources/versions remain at most 256, item pages at most 100 with exact expectedRevision and adaptive complete-item nextOffset. Revisions remain JavaScript-safe integers. The existing 4 MiB request/result and 2 MiB preparation projection bounds apply; generated array types cannot enforce runtime length limits.

`monitor-loop-result-v2` exposes ordered versions/provenance and a typed `backtest-report-v5` header through `report_schema_version`. The public header excludes the private complete schedule and raw sources, and is not independently hash-recomputable as a full private report. Backend immutable report/input verification remains mandatory. Legacy v1 preparation, v4 report bytes/hashes, supported exports, one unfinished operation, cancellation/unknown drain exclusion, one same-process worker and latest-30 retention remain. Loop exports still return 409. No new global resource, quota, live monitoring control, production migration or deployment is approved.

Independent review reproduced the optional-create-discriminator mismatch in both profiles before repair; the public subclass now matches actual HTTP dispatch while the private default remains exact. Both generated TypeScript files match their renderers. Actual contract gates and remaining UI acceptance are recorded under RP-V14; this API approval does not claim completion of RP-T15–RP-T20.

## U12. Daily continuity operational closure (2026-10-11)

RP-T01–RP-T20 and RP-C01–RP-C07 are complete under RP05-A03. The original ML-A07, ML-A11, ML-A13 and ML-A16–ML-A18 remain active acceptance and pass the recorded offline checks. One ordered source collection is extracted sequentially, reviewed as a chain and submitted once; daily replacement/continuation uses one continuous account and one result. Later account assertions cannot overwrite the ledger. Exact literal-source review and first-day opening-time repairs preserve the reviewed evidence boundaries and original server authority.

The [operations guide](../../operations/monitor-loop-backtest.md) and [verification report](../../verification/monitor-loop-backtest.md) RP-V19/RP-V20 record real Chrome business/retry/edit/exclusion coverage, complete equity, compatibility/fault tests and unchanged 600/600-second load gates. They distinguish synthetic AI/market inputs and measured shared-process limits from live-provider or maximum-capacity certification. U09/U10/U11 retain their historical scope; U11's four approved hashes remain exact and both generated profiles pass. This closure changes no public API shape or approval identity, performs no production migration/deployment and does not authorize new platform scope. Changes are local commits; no push occurs in this run.

## U13. Authorized single-plan library contract (2026-10-16)

The user's explicit single-source preparation / reviewed composition request authorizes these concrete paths in both monitor profiles: `GET /api/v1/backtest-plan-library`, `POST /api/v1/backtest-plan-library/preparations`, and `POST /api/v1/backtest-plan-library/compositions`. Preserve the exact path allowlist and existing public error envelopes. No monitoring activation contract changes.

The create body is `SingleSourcePreparationInput` (`preparation_id`, one `source`, optional exact `reviewed_base`). Composition accepts `PreparedPlanCompositionInput` (`preparation_id`, 1–256 unique `plans` references). Both writes require origin/idempotency guards and return 201. Library reads use `offset` and `limit` (1–100) and `no-store`, returning reviewed identities, hashes, source IDs, effective dates, symbol/name, predecessor reference and review time. Collection progress adds `workflow`, `editableSourceId`, and optional `baseAccount`. Existing source dates remain optional on save; effective-date preflight applies before extraction. Review and run routes retain existing versioned contracts.

The server owns chronology, immutable predecessor evidence, review, composition and continuous-account authority. Exact original write receipts remain replayable. See ML21 and SP01–SP05 for approved behavior, bounds and verification. English and Chinese copies describe the same fields and paths.

OpenAPI snapshot SHA-256: `dfdf2e1a1d33cc1f7023720c814b03ce8e8b982f6bb42ec8faeb79abfb2957be`

Canonical monitor v2 OpenAPI snapshot SHA-256: `c436a671a1734240fce9c4c758d366afb50e4e0f16e4b218117ff288a9ce41fb`

## U14. Source-confirmation contract (2026-10-16)

The user authorized source-backed repair and consolidated confirmation. Added optional `confirmationSummary` projections (`automaticFacts`, `questions`, `processingIssues`), `CONTEXT` classification, reviewable `SOURCE_INTERPRETATION`, nullable inactive zones/fixed-price reference dates, and ordered tranche signal modes. Legacy schemas retain their codecs; no review or execution approval is inferred. See [SC-01–SC-03](../../../tasks/source-confirmations.md) and the verification report.

OpenAPI snapshot SHA-256: `2d1a16ef1d13d3112abc4c3635f033ee8377c782c0c3679b97f8330b3f0a94e3`

Canonical monitor v2 OpenAPI snapshot SHA-256: `34d509fab8aa647e3404f74060d721c2cf0a2267bd6fc70738e3fa6e29b9bded`

## U15. Unified preparation and rule changes (2026-10-16)

The user authorized removal of the complete/update UI choice. Preparation defaults to the just-reviewed predecessor, with a unique latest single-asset fallback on a fresh page; ambiguous libraries require selection. Explicit new-chain selection remains available. The existing optional `reviewed_base` pins the exact immutable predecessor; API paths and schemas do not change.

Review presents `RETAIN`, `MODIFY`, `ADD` and `REVOKE` with values and evidence. Source-backed restatements can establish changes without internal rule IDs. Every unmentioned policy leaf must either have explicit retention scope, be restated unchanged with validated current evidence, or be an identical fixed product constant; otherwise inheritance remains unresolved. Cancellation must identify a unique prior rule and cannot be inferred from silence. Repeated identical compact-wire operations merge their evidence; conflicting actions remain errors. An empty account context is null only when it contains no facts, dependencies or extra keys. Represented unverified conditions remain unverified; warnings describing those conditions or inactive zones do not independently prohibit review.

Cash-only unknowns do not invalidate a previously reviewed policy for successor extraction. Source/candidate hashes, origin evidence, whole-plan review and continuous-account rules remain authoritative. See [UP01–UP03](../../../tasks/unified-preparation.md) and [verification](../../verification/2026-10-16-unified-preparation.md).

## U16. Position-only research funding and daily evidence (2026-10-17)

OpenAPI snapshot SHA-256: `de10c595c26c0ae375e3d895f28ba2b2cab8e929dba412de4aa005d1efd0f7fa`

Canonical monitor v2 OpenAPI snapshot SHA-256: `07d2b38c4eda309f402fa7540b944aaf7c92e08e2953ea082089efcb9e20763d`

The user explicitly requested removing initial-cash requirements. New source reviews use `PositionLimitFunding` with `kind: POSITION_LIMIT_ONLY` in the existing cash discriminator. No new endpoint or funding UI selector is added. Historical `KNOWN` and `UNKNOWN` inputs and their source-evidence validation remain readable with their original semantics. New buys still enforce plan authority, position limits, T+1 and quantity rules. Fees/costs and trade PnL persist; capital return/equity drawdown remain unavailable. Frozen loop datasets optionally embed bounded adjustment-factor evidence; omission preserves legacy hashes. See [operations ML-O14](../../operations/monitor-loop-backtest.md) and [verification](../../verification/2026-10-17-daily-basis.md).

## U17. Source-backed prior-close prerequisite (2026-10-17)

The user's request to diagnose zero fills and automatically handle explicit source conditions authorizes the additive Schema 5 `DailyPriorClose` condition (`type: DAILY_PRIOR_CLOSE`, `since_date`, `price_fen`, `comparator: GT | GTE`). No endpoint changes. Only complete earlier-session closes in the inclusive `since_date` window can satisfy this prerequisite; the latest daily bar is the subsequent evaluation session and cannot establish both stages. Certified price-basis/history evidence is mandatory. Missing or truncated history stays `MISSING_INPUT`; a covered window without a qualifying earlier close is `UNSATISFIED` with `PRIOR_CLOSE_NOT_SATISFIED`.

Source normalization requires an explicit, unique recovery threshold, explicit recovery-before-retest order, a statement that recovery has not occurred, and a confirmed effective date. That date bounds the new recovery window as preparation metadata. Unchanged inherited rules keep their existing window. The original recovery clause and retest clause remain evidence-bound; retest, candle, volume and relative-index wording is not assigned invented thresholds. Unknown children remain visible even when a known false prerequisite determines the `ALL` result. Review presents the known prerequisite as an automatic fact, keeping only unresolved criteria in the business question. Existing reviewed versions/results remain immutable and need a new extraction/review/run to adopt this representation.

Prompt compaction removes redundant schema titles/discriminator annotations while preserving union constraints, source text, literal values and server validation. Both generated profiles and their TypeScript types include the new condition. Verification is recorded separately in [ZF-V01–ZF-V04](../../verification/2026-10-17-zero-fill-audit.md).

OpenAPI snapshot SHA-256: `fb3f08ff3826ae1d07be99c994565bea70d1667344280b966afe5579b9845df5`

Canonical monitor v2 OpenAPI snapshot SHA-256: `172d21503bca7283c5a6eea6d0279770187c0c16e43317854e0ed0ba828e41ba`

## U18. Per-plan result diagnostics (2026-10-17)

The user's result-page request authorizes optional `planDiagnostics: LoopDiagnostics | null` on existing `BacktestLoopRunView` and `BacktestScheduledRunView`; endpoint paths, frozen report codecs, report hashes and execution behavior remain unchanged. Nested diagnostic fields use the native snake_case convention. `availability` is `AVAILABLE | EXPIRED | UNAVAILABLE`; `plans` contains 1–256 identities in frozen order. Each item includes source/version/effective date, buy-rule and fill/evaluation counts, root-outcome counts, `review_status: PASSED`, categories, examples and a sampling marker. Per-plan fills are null if the retained audit is unavailable; they are never fabricated as zero.

Examples bind an audit sequence/time and root outcome to a requirement, actual evidence and reason. Categories distinguish `MARKET_UNMET`, `QUALITATIVE_UNRESOLVED`, `PROCESSING_ERROR`, `DATA_UNAVAILABLE`, `EXECUTION_BLOCKED`, `NO_BUY_RULE`, `NO_EVALUATION` and `CONDITION_MET`. Bound examples to eight per plan and 256 total; aggregate every retained evaluation, merge repeated daily criteria and exclude stale daily repetitions from examples. Exact decimal prices retain fractional-fen precision. A current quote alongside a prior-close requirement is explicitly labelled and cannot be presented as a qualifying prior close. Satisfied `ANY` alternatives do not expose unused unknown branches as blockers.

Read from the result-owned immutable input and retained audit in one read transaction. Verify row/event identities and the exact published stream digest before returning the bounded projection; publication's semantic validation remains authoritative. Failed/unreviewed preparations are absent from completed results, so their absence cannot be diagnosed as a current extraction failure. Missing detail produces an explicit availability state. Reading diagnostics triggers no AI call, strategy mutation, manual confirmation or new run. Native view validators bind versions, source dates and fill totals; frontend validation also accepts the legitimate `POSITION_LIMIT_ONLY` mode and null `baseHash` for independently reviewed library members while retaining non-null predecessor checks. See [RD01–RD03](../../../tasks/result-plan-diagnostics.md).

OpenAPI snapshot SHA-256: `4875f2c9c4404909ea78e285bccb0d92896675e0ad5dc7554acfdf3931f016d2`

Canonical monitor v2 OpenAPI snapshot SHA-256: `1a38659bbb064a60c9c604089d2b8479d0f51bda1eff8bed36da11662a67786d`

## U19. Generic predecessor inheritance and bounded correction (2026-10-17)

The user's generic-flow request authorizes a versioned `PREDECESSOR_PATCH` interpretation: the exact reviewed predecessor supplies all unmentioned rules and fields by default. This supersedes U15's explicit-retention requirement only for new patch candidates; legacy frozen inputs keep their original interpretation. Source-cited semantic changes identify `RETAIN`, `MODIFY`, `ADD` and `REVOKE` by stable identity. No new endpoint or automatic review authority is introduced.

Additive optional metadata includes operation `intent`/`rationale`, clause `semantic_role`, `SOURCE_SEMANTIC` bindings and the preparation interpretation contract. Each failed preparation attempt may retain up to 64 `repair_feedback` entries of at most 512 characters and `repair_context_json` of at most 32000 characters. At most two automatic corrections share the existing three-attempt limit; each remains bound to the source, predecessor and worker ownership. Feedback describes processing failures. Genuine source ambiguity remains a business question, while an omitted unchanged rule needs no confirmation. Previous unapproved candidates remain untrusted correction context and cannot approve themselves.

Private AI transport now requests `monitor-loop-delta-wire-v3`, including execution-authority and temporal-order checks. These fields do not add public endpoints. Candidate storage uses lossless `source-clause-pool-v2` evidence/path deduplication with bounded expansion and backward readers; public schemas and the hashes below are unchanged. Explicitly revoked rules are removed before final collection limits and evidence-index resolution.

Both generated profiles and frontend contracts reflect these additions. This records contract scope, not successful live-model acceptance or deployment. See [GI-01–GI-02](../../../tasks/generic-plan-inheritance.md) and the [verification record](../../verification/2026-10-17-generic-inheritance.md).

OpenAPI snapshot SHA-256: `f0a049aaacea9bf5d9371bc6402c5954cd8bb4c83097cf9aa18d55e63432d0c8`

Canonical monitor v2 OpenAPI snapshot SHA-256: `bfeab749334df8adbd2324be09ab2b3e1153d3b8d6928c53928f06a49e9f44b1`


## U20 — Frozen result rule comparison

A completed continuous run exposes `GET /api/v1/backtest-runs/{run_id}/rule-changes/{source_id}` as a read-only, one-source response. `BacktestRuleChangesView` binds `runId`, `manifestHash`, `sourceId`, `versionId`, `previousSourceId`, and `previousVersionId`; `relationship` is `INITIAL`, `INHERITED`, or `INDEPENDENT`. `changes` contains at most 64 `PlanChange` values with complete `before`/`after` values and `RETAIN`/`MODIFY`/`ADD`/`REVOKE` actions. Compare final frozen policy sections and stable rule identities (risk branches use kind); ignore plan identity fields and list reordering. Do not interpret new source text or trust stale pre-correction change lists. Independent legacy versions compare adjacent policies without claiming inherited review lineage. Missing runs, sources or unsupported single-plan runs return 404.

The result UI loads one source at a time, validates run/manifest/version/predecessor identity, rejects stale responses and offers explicit retry. Show all groups and full fields, distinguish unchanged fields within modified rules, and convert integer fen values and fixed FEN references to yuan. Existing result summary limits and frozen report identities remain unchanged. No AI, replay, database migration or new trading authority is involved. Acceptance and bilingual verification follow `tasks/result-rule-comparisons.md`.

OpenAPI snapshot SHA-256: `cbc73be169c2f0a9b2758f8f93655813a6b8d17279a1340457ac30a4a320ae38`

Canonical monitor v2 OpenAPI snapshot SHA-256: `6dd7e9edf672b427782a9714e86e5bf364d50381a85b1963301914639a2b5f2c`


## U21 — Risk withdrawal applicability

The source recheck authorizes an optional `scope_assessment` on `PlanUpdateOperation`: `ENTIRE_RULE | PARTIAL_RULE | CONTEXT_ONLY | UNCLEAR`. Omitted values remain omitted in legacy serialization. New private `monitor-loop-delta-wire-v4` requires applicability assessment of every predecessor risk branch; missing assessment is a bounded AI correction, not a missing-source question. Scope-bearing retention must survive context normalization. Whole-rule withdrawal requires entire-rule authority; a new-position exclusion cannot delete protection for all holdings. Preserve prior risk/price evidence in a non-executable candidate when partial applicability cannot be represented. `UPDATE_PARTIAL_SCOPE_UNSUPPORTED` describes a system execution limitation, not manual source facts or permission to apply an unrestricted inherited exit.

Historical frozen reads retain original hashes. New library predecessor/composition use is revalidated; outdated scope returns `REVIEWED_RISK_SCOPE_RECHECK_REQUIRED`. Only already reviewed records may request historical validation. No endpoint or scoped holding-execution engine is added. See [RW-01–RW-03](../../../tasks/risk-withdrawal-scope.md) and the [source audit](../../verification/2026-10-17-risk-scope-audit.md).

OpenAPI snapshot SHA-256: `ddeb1af3aec464d7ac62410df7b3fba991994626555c12b8eb104897d474fe28`

Canonical monitor v2 OpenAPI snapshot SHA-256: `dff005b984e4c76406c7529306f7fbb88f3bd75a17036cbf2966dc1f6725c891`

## U22. Risk execution by holding cohort (2026-10-18)

The user authorized completing the scope execution boundary recorded in U21. Schema 5 risk branches add optional `holding_scope` (`mode: BEFORE_TRADE_DATE | FROM_TRADE_DATE`, `trade_date`, optional exclusive `end_trade_date`), stable `rule_id`, and paired ordinary-risk `risk_line_fen` / `risk_comparison`. At most 64 distinct risk identities are supported. Schema 4 contracts remain unchanged; absent optional fields retain historical serialization. Exact lot windows intersect later restrictions and cannot silently widen inherited protection.

An explicit exclusion of new positions becomes a source-bound scope modification, retaining the prior price, target, confirmation and suspension policy. Omitted old-position instructions inherit the reviewed predecessor. `scope_change: EXISTING_POSITIONS_ONLY | NEW_POSITIONS_ONLY` is optional operation metadata. Private `monitor-loop-delta-wire-v5` and bounded focused scope correction distinguish existing/new applicability from whole-rule revocation. A missing direction is an automatic processing correction; genuine source ambiguity stays distinct. No manual confirmation is required to compensate for engine limitations. No new stop is invented for new entries.

Risk evaluation, entry blocking and fulfillment use eligible holdings. Initial holdings can be classified by their earlier opening observation without inventing an acquisition date. New simulation batches and loop lots optionally record `plan_version_id`. Risk actions, simulation state and receipts optionally retain `lot_allocations` (`id`, `bucket`, `quantity`), bounded by the existing 500-lot limit. Execution atomically recomputes authorized allocations, enforces T+1 and known sellability, debits exact batches and releases their actual costs. Excluded lots cannot substitute for unavailable old lots. Confirmation remains latched across plan switches; clearing the eligible cohort fulfills its obligation while other holdings remain.

Existing API paths expose these additive fields; no new endpoint or trading approval is introduced. Results display applicability and lot-specific exits beside full rule comparisons. The complete comparison bound is 192 entries, accommodating disjoint old/new identities and policy sections within the 64-risk limit; operation proposals remain bounded to 64. Prior frozen runs remain historical; revised reviewed policy produces a new input/run identity. See [CR-01–CR-03](../../../tasks/cohort-risk-execution.md) and [actual verification](../../verification/2026-10-18-cohort-risk-execution.md).

OpenAPI snapshot SHA-256: `5d6dff24961ae06dafe422211775851ff1fc55cbb91267e9d5b79f8a58261404`

Canonical monitor v2 OpenAPI snapshot SHA-256: `4c033709abf001c88e6a1ae9ee667b90359b51a3f34b6d34ad63edc9ef3b73d9`

## U23. Run-list coverage-date filters (2026-10-18)

The user authorized simplifying run-list filters and separating replay cutoff from actual execution completion. Common dates mean the inclusive coverage end date `eventEnd` for every result kind. `GET /api/v1/backtest-runs` adds optional `eventEndFrom` / `eventEndTo`, each a valid `YYYY-MM-DD`; reversed ranges, invalid dates, duplicate keys and unknown query keys remain rejected. They combine with existing filters using AND and participate in the signed cursor context before SQL pagination. The store compares the canonical summary's `event_end`, not `completed_at`, job completion or today's date.

The existing filter response adds optional nullable date fields, omitted when unused so old unfiltered payloads and cursor contexts remain unchanged. The frontend validates both the echoed date filters and every returned item's coverage. Existing `completedFrom` / `completedTo` retain their original result-timestamp meaning for old API clients/links; they are not redefined as actual task completion. Historical loop `completedAt` is the evidence cutoff. Frozen reports, hashes, stored timestamps, retention and the fixed `completedAt:desc,runId:desc` order do not change. The table labels that value as result time, and static text explains the sort; actual task completion remains a separate job fact.

The UI contains stock, coverage-end dates and pin status. Following the user's further simplification, dataset hash and single-version ID have no filter controls or disclosure entrances. Page URLs drop `datasetHash` / `planVersionId` and their cursor before the first list read, returning to page 1 while retaining other conditions; internal API filters and stored identifiers remain unchanged. Old timestamp link conditions are shown only when present as explicitly labelled old-link time conditions; they are never silently converted to coverage dates. See [RF-01–RF-03](../../../tasks/run-record-filters.md) and [verification](../../verification/2026-10-18-run-record-filters.md).

OpenAPI snapshot SHA-256: `a94974a7d4b7ec26239b72574d87b4a97fd3dbda353833b5a7eb7056e398d67b`

Canonical monitor v2 OpenAPI snapshot SHA-256: `a3833f1fac7735528866dd2ab3a6989ce519657c45c9e044871a626d51784e7d`

## U24. Reliable history reads and preparation progress (2026-10-18)

Read-only metadata calls may wait for the existing owned thread: at most 8 waiting reads, each with a 5-second admission deadline. There is still at most one physical call per metadata owner. Mutations retain immediate occupied-slot rejection; heavy-job admission, thread counts, control acknowledgement, initialization watchdog and physical-drain rules are unchanged. Waiting cancellation/timeout never submits later work, and cancelling an active HTTP waiter does not release its physical thread. Completion/cleanup observes admitted readers before acquiring the metadata slot. SQL BUSY/LOCKED, overload and stopped services retain their existing 503 contracts.

Backtest history and library GET transport retries only a classified `SERVICE_UNAVAILABLE` / 503, at most 3 total attempts separated by 1 second, with abortable waits. It never retries POST/PUT, other errors or invalid success payloads. Preparation polling stays separate: every 2 seconds during existing work; initial or incomplete terminal-detail reads get at most 3 additional refreshes for transient 503/revision 409. Only a complete successful summary/detail read resets that recovery count. Navigation/unmount aborts timers and stale reads. No GET repeats extraction, review, cancellation or execution.

Frontend preparation validation accepts the existing optional `confirmationSummary`, `repair_feedback` and `repair_context_json`, preserving closed keys, source/revision binding and diagnostic bounds (64 feedback strings, 512 characters each; context 32000 characters). Preparation projections also enforce the frontend's existing 50000-node/32-depth budget alongside 2 MiB; adaptive detail pages return remaining complete items through `nextOffset` without truncating source evidence or raising limits. It does not create new source facts or bypass semantic review. A legacy candidate's required supplement controls remain visible even with a confirmation summary; a display-only summary cannot hide an outstanding review requirement. Preparation initialization logs distinguish watchdog expiry from failure class without recording source bodies or credentials.

Public schemas, OpenAPI snapshots, hashes, stored candidates and frozen reports remain unchanged. See [BR-01–BR-03](../../../tasks/backtest-read-reliability.md) and [verification](../../verification/2026-10-18-backtest-read-reliability.md).

## U25. Automatic data preparation at start (2026-10-18)

The user authorized removing the four manual preparation controls. A reviewed-source start now checks local evidence, fills missing closed historical data, verifies again and submits the frozen-plan run command. Start authorizes this bounded data preparation; a page visit/URL read never downloads data or authorizes AI. Existing sync/verification APIs remain compatible. Legacy version/dataset replay retains its already-frozen dataset.

The additive read-only contract is `GET /api/v1/backtest-run-data?preparationId=...&manifestHash=...&endDate=YYYY-MM-DD`. Optional `endDate` keeps the existing Shanghai submission-date default. `PreparedBacktestDataView` returns `preparationId`, `manifestHash`, `endDate`, `ready`, `syncScope` and `blockers`, with `Cache-Control: no-store`. The exact reviewed manifest is required; invalid, duplicate, unknown queries and stale bindings fail. Stock, start, warm-up and closed sync end come from server rules/calendar. Final submission rechecks authority, boundary and evidence before copying input. No worker, task kind, database migration or AI call is added.

Only an explicit start with missing data sequences an existing durable `DATA_SYNC`, using `allowNetwork: true` and `refresh: false`. Authoritative progress uses the existing serialized 2-second poll. Verification failure blocks `BACKTEST_RUN`. Lost mutation receipts retain the original body/key; no new intent can replace an uncertain one. Explicit failure retry rechecks cache and preserves completed downloads. Cancellation blocks continuation even after late sync success. Unmount aborts reads and prevents later commands; an already accepted server job remains inspectable/cancellable through its record. Reload never silently continues the sequence or resumes history.

If mutable cache is missing, preparation may reuse verified result-owned facts. Lookup checks at most 20 matching first-plan inputs. Schedule/reviewed authority, opening account, data requirements, stock/date/profile and exact evidence cutoff must match; preserved warm-up may be longer, never shorter. Each day/artifact hash is verified. A new submission binds its own boundary/input/dataset identities and copies the same fact bytes without rewriting old inputs/days/reports. Different cutoffs/authority or damaged evidence cannot be reused. Existing retention/maintenance remains unchanged.

Historical data management becomes read-only: remove `应用到当前 URL`, `同步历史数据`, `本地验证数据集` and `刷新已缓存表面`; keep filters, paging and task inspection/cancellation. See [AD-01–AD-03](../../../tasks/automatic-backtest-data.md). The user approved this concrete behavior; the hashes below identify the additive data-check contract, not a change to trading rules or historical reports.

OpenAPI snapshot SHA-256: `6de1b8500f2b6bb217e419c191861579bb27cdaa8ee40078c1b6e566ddee2228`

Canonical monitor v2 OpenAPI snapshot SHA-256: `6a49893bef934394a1034eed225711cc152fb47684322878b2c84b6e08f9ad95`

## U26. Isolated verified result reads (2026-10-18)

The remaining completed-result 503 is a measured metadata head-of-line timeout. Summary projection must read and verify copied input, native report and diagnostics once in one retention-consistent snapshot. Preserve copied-day canonical/hash checks, report/input/summary binding, typed retained events and their complete published digest, diagnostic budgets and expiry states. No evidence, rule, historical input, report or SQL projection is rewritten.

Unlike U24's short metadata-overlap repair, this follow-up adds one lazy owned result-reading thread, not a heavy execution worker. Summary, rule-comparison and equity projections use it. It permits one physical call, at most 8 observers and 8 distinct in-flight keys, with a 60-second admission wait for different queued work. Metadata retains 8 waiting reads and 5 seconds; mutation admission and the heavy-job slot remain unchanged. Concurrent identical result reads share active work keyed by operation/run/source; summary keys also include pin state. Remove shared work on completion; a later request verifies current stored evidence again. No persistent response cache may hide retention or corruption changes.

Observer cancellation never cancels another observer or releases physical work. Include the new owner in stop/drain accounting and preserve sanitized SQL BUSY/LOCKED, stopping and overload 503/Retry-After behavior. Public routes/schemas, OpenAPI, dependencies, database schema and AI/network authority are unchanged. Actual verification compares both complete old/new report responses and all 50 snapshotted owned files; [RR-01–RR-03](../../../tasks/result-read-isolation.md) and [verification](../../verification/2026-10-18-result-read-isolation.md) record the scoped result, not a never-503/load guarantee.
