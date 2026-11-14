# Implementation plan and tasks: plan-monitor-assurance

Status: IMPLEMENTING — 2026-10-27. PMA-D01–D06 and implementation are approved; task marks reflect actual evidence. [Chinese copy](plan-monitor-assurance.zh-CN.md) · [six proposed decisions and module map](../docs/specifications/monitoring/SPEC-plan-monitor-assurance.md).

## PMA-P01 — Authority, dependencies and slicing

The user approved PMA-D01–D06 and explicitly ordered implementation through all stages or a user-decision blocker. Real extraction is authorized within the shared48-attempt ceiling; no repeated authorization is required. User database migration remains prohibited. Keep `tasks/plan.md` and `tasks/todo.md` unchanged. Baseline for the investigation is `a5546ad`; T01 records the actual future starting revision without overwriting historical evidence.

Implement `source-condition-coverage` before corpus signoff and current readiness, then verify all three together. Use the existing strict source/review/runtime authority. Each slice targets3–5 files. A parent listing several independent seams is explicitly split into the named sequential children, each at most5 files and separately tested; do not edit all seams in one sweep. Independent read-only review or corpus preparation may be delegated; shared contract/storage/authority changes remain sequential.

Future additive migration development/tests use disposable databases only. User migration, real plan review/activation, inventory/cost confirmation, notification test sends and live market acquisition remain separately authorized. D05 plus an explicit implementation instruction is required for bounded real extraction; no synthetic substitute closes that checkpoint. Truth ambiguity, necessary resource/version/budget expansion and unavoidable compatibility changes are decisions, not grounds to silently relax acceptance.

## PMA-P02 — Verification commands and evidence rules

Commands run from `trade-plan-monitor/`. New test/script names below are prospective: create the test first, observe the expected independent failure, then implement. An absent file, empty selection, interrupted run, skipped assertion or approved specification is not a pass. Use separate backend-directory processes to avoid existing duplicate basenames. Local socket tests use an environment permitting loopback communication and project-local disposable `--basetemp`; do not touch real stores.

| ID | Verification / complete command |
| --- | --- |
| PMA-V01 | Existing baseline: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_current_plan_extraction_security.py tests/unit/test_p3_policy_contract.py tests/unit/test_p3_codec.py tests/unit/test_preparation_prompt_budget.py -q --basetemp=.pytest_cache/pma-v01`; separately `.\.venv\Scripts\python.exe -m pytest tests/integration/test_p3_review.py tests/integration/test_p3_chain.py tests/integration/test_p3_notifications.py -q --basetemp=.pytest_cache/pma-v01-integration` |
| PMA-V02 | New pure coverage: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_source_obligations.py tests/unit/test_source_coverage.py tests/unit/test_source_coverage_semantics.py tests/unit/test_source_coverage_normalization.py tests/unit/test_source_coverage_context.py -q --basetemp=.pytest_cache/pma-v02` |
| PMA-V03 | New authority/store/HTTP: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_source_coverage_storage.py tests/integration/test_source_coverage_authority.py tests/integration/test_source_coverage_api.py tests/integration/test_source_coverage_compatibility.py tests/integration/test_source_coverage_actions.py -q --basetemp=.pytest_cache/pma-v03` |
| PMA-V04 | Corpus/grader offline: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_extraction_acceptance_corpus.py tests/unit/test_extraction_acceptance_grading.py tests/integration/test_extraction_acceptance_runner.py -q --basetemp=.pytest_cache/pma-v04`; readiness: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_plan_readiness.py tests/integration/test_plan_readiness_api.py tests/integration/test_plan_readiness_scenarios.py -q --basetemp=.pytest_cache/pma-v04-readiness` |
| PMA-V05 | Frontend: `npm --prefix web run test -- --run tests/unit/SourceCoverageReview.spec.ts tests/unit/PlanReadiness.spec.ts tests/unit/PlanWorkbench.spec.ts tests/unit/ReviewedPlanDetails.spec.ts`; `npm --prefix web run type-check`; `npm --prefix web run build`; real isolated Chrome: `npm --prefix web run test:e2e -- tests/e2e/source-coverage.spec.ts tests/e2e/plan-readiness.spec.ts tests/e2e/p3-capital.spec.ts tests/e2e/market-linkage.spec.ts` |
| PMA-V06 | Full regressions: `.\.venv\Scripts\python.exe -m pytest tests/unit -m "not live" -q --basetemp=.pytest_cache/pma-full-unit`; `.\.venv\Scripts\python.exe -m pytest tests/integration -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --basetemp=.pytest_cache/pma-full-integration`; `.\.venv\Scripts\python.exe -m pytest tests/contract tests/replay -m "not live" -q --basetemp=.pytest_cache/pma-full-contract`; `npm --prefix web run test -- --run` |
| PMA-V07 | Isolated capacity: `.\.venv\Scripts\python.exe -m pytest tests/integration/test_backtest_acceptance.py -m "not live" -q --basetemp=.pytest_cache/pma-capacity`; no competing heavy tests/build/browser. Preserve120s/symbol,768MiB working-set delta,512MiB market/WAL,192MiB result/WAL and existing heap/query/export limits. Static/contracts: `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check`; `.\.venv\Scripts\ruff.exe check src tests`; `git diff --check` |
| PMA-V08 | Document/source audit: paired section IDs/decisions/API fields/enums/thresholds/links, original prompt hash/excerpts, protected tasks, old golden diff, no secret/raw-user material, source→criterion→actual evidence; final staged/baseline review. No test run is claimed by this documentation audit |
| PMA-V09 | Future real extraction only after D05/start authorization: `.\.venv\Scripts\python.exe scripts/run_extraction_acceptance.py --manifest tests/fixtures/plan_assurance/manifest.json --evidence-dir .pytest_cache/pma-real-acceptance --version plan-extract-v12 --max-provider-attempts 48 --no-retries --allow-real-provider`. The future entry point must enforce one shared campaign attempt ledger; the48 ceiling is not a per-command reset. Candidate-version rerun uses its actual frozen version and the same ledger; no additional calls are implied |
| PMA-V10 | Future installation read-only audit: `.\.venv\Scripts\python.exe scripts/audit_plan_readiness.py --database data/monitor.sqlite3 --read-only --output-dir .pytest_cache/pma-installation-audit`. Database-only evidence is PERSISTED_ONLY; never launch/migrate the app or fetch providers. Missing current owner authority is UNKNOWN/NOT_READY, not a guessed PASS |

Record exact commands/revisions/counts, original failures and exact reruns. Mark real/provider and installation results separately from non-live engineering results. Archive raw bytes plus a readable copy/hash manifest if terminal whitespace needs normalization; never suppress a failed outcome to satisfy formatting.

## PMA-P03 — Ordered tasks and checkpoints

### PMA-T01 — Freeze the counterexample, contracts and baseline

- [x] Deliver and verify.
- Depends on: approved package and explicit implementation instruction.
- Files/scope: new paired `CONTRACT-plan-monitor-assurance` appendix, one neutral counterexample fixture and focused baseline test (at most4 files). Freeze exact DTO/hash owners, positive-context rules, trusted historical cutover, next free migration revision and prompt/wire version baseline.
- Acceptance: A01,A05,A06; Verify: V01,V08. Reproduce both languages with145→146 clauses/128 unchanged bindings and old zero issues; the new current assessment must then be proven blocking, without claiming activation occurred.

### PMA-T02 — Define bounded obligation and proof models

- [x] Deliver and verify.
- Depends on: T01.
- Files/scope: `ai/source_coverage_models.py`, `ai/source_obligations.py`, `tests/unit/test_source_obligations.py` (3 files).
- Acceptance: A02–A04; Verify: focused V02. Exact spans/IDs/relations, known/unknown scope,4096 total/64 per clause and existing512/2000 limits; overflow blocks without truncation.

### PMA-T03 — Close the background-label and negative-keyword escapes

- [x] Deliver and verify.
- Depends on: T02.
- Files/scope: `ai/source_coverage.py`, positive-treatment seam in `ai/source_resolution.py`, `test_source_coverage.py`, `test_source_coverage_context.py` (4 files).
- Acceptance: A01,A03; Verify: focused V02. All three roles, nonempty reasons and keyword-free conditions remain blocked unless the exact span has a valid positive non-policy treatment. Preserve real context and no invented trades.

### PMA-C01 — Obligation and context checkpoint

- [x] V01,V02,V08 available-stage checks pass; A01/A03/A04 have real evidence. No current/frozen authority is opened merely by creating models.

### PMA-T04 — Compare complete predicate and relation semantics

- [x] Deliver and verify.
- Depends on: T03.
- Files/scope: focused semantic comparator, registered equivalence adapter and `test_source_coverage_semantics.py` plus at most2 helpers/tests.
- Acceptance: A02,A04; Verify: focused V02. Same-sentence omitted conjunct, AND/OR, negation/exception, comparator/unit, cycle/offset, dates, quantity, permissions and occurrence mutations are detected independently of existing bindings.

### PMA-T05 — Audit normalization and exact mixed-source treatments

- [x] Deliver and verify.
- Depends on: T04.
- Files/scope: focused normalization trace adapter, existing normalization/exclusion seam, `test_source_coverage_normalization.py`, mixed-source regression (at most5 files).
- Acceptance: A03,A04; Verify: V02 plus existing source-treatment tests. Record raw/normalized differences, prevent evaluation-only erasure, retain original code points, registered fundamental exclusions, technical remainders and scoped supplement/expiry overrides.

### PMA-T06 — Preserve incomplete candidates with coverage blockers

- [x] Deliver and verify.
- Depends on: T05.
- Files/scope: sequential T06a direct extraction (3 files), T06b compact propagation (4), T06c private derivation models (2), T06d deterministic replay (2), T06e update-result evidence (2), T06f materialization (4), each independently tested. Source scope and actual evaluator support receive focused regression slices; public persistence/authority remains T07–T09.
- Acceptance: A01,A04,A05; Verify: V01,V02. Distinguish malformed/tampered output from valid incomplete coverage; retain source/candidate/mapping, and never present SUCCEEDED as reviewable when coverage blocks. Pin v12 bytes or declare a new prompt version honestly.

### PMA-C02 — Extraction coverage checkpoint

- [x] New pure coverage and existing source/extraction regressions pass. A01–A04 covered; source normalization cannot hide mandatory omissions. Persistence/activation remains pending.

### PMA-T07 — Persist assurance without invalidating history

- [x] Deliver and verify.
- Depends on: T06.
- Files/scope: sequential T07a SQL metadata/migration/registration and independent migration tests (4 files); T07b bounded proof/store and core/upgrade tests (4); T07c immutable guards and fault injection (5); T07d independent storage attacks (1). Each slice is separately verified. User migration remains prohibited.
- Acceptance: A05,A06; Verify: focused V03. Disposable old populated databases reopen under historical verification; new proof history/CAS/retry/backup are exact; cutover cannot be forged; lossy downgrade is blocked. No user migration.

### PMA-T08 — Bind save, review, activation and reuse

- [x] Deliver and verify.
- Depends on: T07.
- Files/scope: sequential T08a save/reload/first confirmation/repository guards and independent tests (5 files); T08b unproven version-trace retention (2); T08c HTTP bindings/projection/current workbench reader (5); T08d fresh workbench-run guard (2); T08e worker private carriage (3); T08f tagged preparation auxiliary storage (4); T08g atomic finish integration (4); T08h1 initial-source proof (4), T08h2 shared whole-source analysis (3), T08h3 exact change/parent proof (5), T08h4 independent attacks (2), T08h5 inherited scope/registered operations in separately tested children (at most4 each), T08h6 aggregate ownership (3), T08h7 shared AI/human semantic analysis (3); T08i1 transaction-local current reader/review guards (3), T08i2 immutable review-receipt storage (3), T08i3 atomic current review binding (4), then T08i4 human operation/source reassessment, T08i5 inheritance/composition lineage and T08i6 fresh reuse/run guards. Remaining children each target at most5 files and are independently tested. Original historical codecs and frozen inputs remain unchanged.
- Acceptance: A05,A06; Verify: focused V03 and existing current-plan API tests. Incomplete DRAFT stays savable; old hashes stay valid; missing/stale/blocked new proof cannot confirm/activate or use a client-selected legacy mode.

### PMA-T09 — Carry coverage through current actions and delivery

- [x] Deliver and verify.
- Depends on: T08.
- Files/scope: sequential T09a action-source reader, ordinary simulation, runtime production/frame, private frozen-loop and research adapters in separately tested children (at most5 files each); T09b1 preview/decision/consume and actual replay callers (5), T09b2 rejection-cleanup tests (1), T09b3 actual P3 source/review fixture (2), T09b4 frozen worker preparation/callers (1); targeted actual-read and consumer-binding repairs are separate children (at most5 each). T09c1 send-time guard (4), T09c2 outbox reads (2), T09c3 private frozen capture (5), T09d complete literal minute sentences (4), and recorded-current/synthetic-positive test reconciliation (2) are separately verified. Complete related regression is recorded in PMA-R30.
- Acceptance: A05,A06; Verify: focused V03, P1/P2/P3 action/race/notification tests. Exact relevant coverage checked in the existing write fence; stale/race/retry/rollback yields one outcome; BUY-only omissions do not veto independent technical-risk SELL. No new occurrence/window/quantity.

### PMA-C03 — Durable authority checkpoint

- [x] Available-stage V01–V03 source/storage/authority/action/send-time selections pass for A01–A06; history/current separation, atomic guards and risk continuity are proven (PMA-R30). No API/UI-only authority bypass exists. New coverage-resource/UI workflow checks remain T10–T12/C04.

### PMA-T10 — Expose coverage resources and exact review binding

- [x] Deliver and verify (PMA-R31–R35; T11/T12/C04 remain open).
- Depends on: T09.
- Files/scope: sequential T10a1 DTO/read composition/GET/service/HTTP tests (5); T10a2 same-fresh-record plan list/detail/save/workbench summaries and narrow ACTIVE DTO handling (3); T10a3 actual extraction summary and focused tests (at most4). Existing exact review-command fields/guards remain unchanged. Then T10b both OpenAPI and TypeScript profiles plus projection test (5); T10c paired API-owner appendix and compatibility tests (at most4); T10d0 optional per-request raw-byte response bound and transport tests (2); T10d1 shared typed coverage decoder/read client, exact existing plan decoder adaptation and focused tests (3); T10d2 exact existing extraction decoder adaptation and focused tests (2). Each child is independently tested and committed before the next shared-owner edit. Preserve the default4MiB transport bound; the new resource uses its stricter1MiB raw-wire bound before JSON parsing. Existing closed response-key lists admit only the approved additions; absent historical fields remain compatible.
- Acceptance: A05,A06,A10; Verify: focused V03,V07. Exact source-bound pagination, no read writes,409/422/integrity errors, literal false authority, old projection preserved after only approved additions.

### PMA-T11 — Show source-to-rule coverage and blocked repairs

- [x] Deliver and verify (PMA-R36–R41; T12/C04 remain open).
- Depends on: T10.
- Files/scope: sequential T11a focused read composable, pure source-span/presentation helpers and their two tests (4); T11b small coverage container/row/span components and `SourceCoverageReview.spec.ts` (4); T11c0 exact workspace intent/load/mutation snapshots and focused concurrency test, optionally one small owner helper (2–3); T11c1 actual workspace/workbench/review coverage wiring and a new actual-owner `PlanWorkbenchCoverage.spec.ts` (4); T11d extraction-summary presentation and focused existing/new tests (at most4); T11e1 isolated no-I/O browser fixture server and its real-lifecycle integration test (2), then T11e2 real-Chrome journey and bounded evidence (2–4). Each child is independently tested and committed before editing a shared owner. Independent T11c0 and T11e1 may use the frozen T10 API while T11b proceeds; T11c1 waits for both workspace and presentation owners, and real browser journey acceptance waits for all UI children. Use the T10 typed client, never cast the generic condition-plan request into a coverage page. Keep historical preparation details historical; a preparation ID is not a live plan-version ID. Preserve source code points and CRLF in escaped readonly highlighting. Existing-fixture reconciliation, if needed, is a separate justified at-most5-file child preserving original assertions and raw sources.
- Acceptance: A01,A03,A11; Verify: V05 unit/type/build. Source spans, partial conditions, AI versus server treatment, human adjustments and no generic waiver; stale contexts discard responses and defaults do not acknowledge blockers.

### PMA-T12 — Close historical/legacy regression boundaries

- [x] Deliver and verify (PMA-R43–R47).
- Depends on: T11.
- Files/scope: T12a adds `test_source_coverage_compatibility.py`, `test_source_coverage_occurrence_compatibility.py` and `test_source_coverage_frozen_compatibility.py`, plus a separate reconciliation of the original workbench positive fixture (4 files). Preserve its original assertions and retain the generic-source blocking negative. T12b independently closes the reproduced fresh-workbench-run admission race with a real source-owner writer fence, existing final-job admission seam, actual-store race/replay tests and only necessary synthetic seam-fixture alignment (at most5 files); split any further owner repair before editing. The fence rechecks exact current source/review after input copying and remains held through actual job commit. Missing capability fails closed; completed same-key receipts and old frozen codecs remain historical. These independent children may proceed in parallel after T11 because their implementation owners do not overlap; each is tested, reviewed and committed separately before C04. No cross-database atomicity claim follows from an early read or an unchanged hash.
- The actual fact-collision counterexample in PMA-R45 additionally gates C04. T12c0 introduces one pure current predicate/fact ownership helper, focused unit tests and actual-source collision tests (at most3 files). T12c1 uses that frozen helper for current runtime projection/old-signal maintenance, source action authority and focused actual regressions (at most4 files). T12c2 covers remaining simulation admission, exception seed/grant/consume, source delivery/manual alerts and actual regressions in sequential children of at most5 files; do not combine more owners in one edit. A legacy unbound fact may attest only a uniquely applicable complete predicate definition in its actual original owner. Date/signal scope overlap, distinct requirements, persisted CONFIRMED causes and independent technical risk must be tested. Do not guess meanings from human testimony, merge requirements, infer ownership from an active sibling, rewrite stored facts or alter source-coverage rules/hash domains or old frozen formulas. Explicit historical replay stays historical and cannot donate live authority. Full explicit-target registration/storage/UI is a later separately tested T13 prerequisite; temporary ambiguity remains visible missing evidence, never a successful positive or an omission waiver.
- Acceptance: A05,A06; Verify: V03 plus historical codecs/replay. Exact legacy reads and old frozen bytes remain; legacy cannot grant current coverage; new-source saves/reads/reuse cannot downgrade policy or rearm consumed signals.

### PMA-C04 — Reviewed-source workflow checkpoint

- [x] Coverage UI/API/current guards and history regression pass. A01–A06 and applicable A10/A11 covered (PMA-R47:376 combined integration checks). Real-provider and readiness acceptance still pending.

### PMA-T13 — Freeze corpus, provenance and independent truth

- [ ] Deliver and verify.
- Current boundary: PMA-R48 keeps original03/04 explicitly blocked and its positive acceptance unresolved. Do not add a persistent BUY-cancellation strategy, invent a trigger/recovery rule, reclassify the positive as an accepted negative or freeze a successful full matrix. T13–T15/C05 and final acceptance remain blocked; P07's later explicit user decision permits independent engineering to proceed. Real calls remain0/48. Independent engineering is not corpus signoff.
- Depends on: T01; execute after C04 in the selected sequential order.
- Files/scope: source bundle, truth bundle, manifest and `test_extraction_acceptance_corpus.py` (4 files); use further reviewed3–5-file children if original redaction artifacts require them.
- Also apply PMA-H01/H02/H04 below: inventory which exact source conditions can already be evaluated automatically, preserve unresolved definitions, and complete the existing deferred per-condition manual-evidence binding prerequisite. Prompt wording alone does not close that prerequisite.
- Prerequisite progress: T13-H04a is delivered in `a94605e` (PMA-R49): exact private targets/parser, existing helper unit test and paired contract,4 files,112 related checks. Registration/storage, consumers and UI remain pending; neither H04 nor T13 closes. Each next child requires its own exact at-most5-file dispatch.
- T13-H04b0 is delivered in `4221db9` (PMA-R50): reject the reserved `reviewed_fact_target` marker from old unbound/kind-only paths before introducing stored targets,4 files,155 combined plus21 current/frozen checks.
- T13-H04b1 is delivered in `6fb2264` (PMA-R51): private optional FACT storage with paired contract and actual temporary-SQL tests,4 files,155 unit plus44 integration checks. Exact positive matching, public registration/update ownership guards, consumers and UI remain separate later gates.
- T13-H04b2 is delivered in `4b43792` (PMA-R52): pure exact-leaf matching and explicit private unified context,5 files,180 unit plus44 integration checks. This does not connect production consumers; public registration/update ownership guards, consumer wiring and UI remain pending.
- T13-H04b3 is delivered in `1eb810c` (PMA-R53): private ordinary-confirmation registration and immutable binding/update guards,4 files,184 unit plus81 integration checks. Other owner/period scopes, production consumers, public registration and UI remain pending. Continue unblocked prerequisites while preserving R48's positive-corpus blocker.
- T13-H04b4 is delivered in `b764362` (PMA-R54): recorded evidence rechecks use exact original native roots/positions,4 files,184 unit plus117 integration checks. Ordinary FACT admission is real private registration; recorded SIGNAL/risk targets remain explicit engineering arrangements. Actual new-signal production and the remaining admission/UI scopes stay pending.
- T13-H04b5 is delivered in `d049012` (PMA-R55): schema5 ordinary official-daily target production,5 files,201 unit plus138 focused integration checks. Minute target consumption remains blocked pending observation-instance binding. The outer `production.py` input control pool needs a separate isolation repair; old unified fixture failures are retained for T22, not accepted as passing.
- T13-H04b6 is delivered in `4c2a96c` (PMA-R56): one-line outer production-input target isolation,4 files,402 focused checks. K40's reported input-control gap is closed for the tested preparer; minute observation-instance storage/admission/consumption and the other remaining scopes stay pending.
- T13-H04b7 storage/admission is delivered in `ba37c1e`, with separately scoped date-fixture correction `f3d1fc7` (PMA-R57). The identical10-file integration selection passes208; unchanged unit/market/production checks contribute236 more distinct cases. Two generated profiles remain unchanged. Minute observation consumption remains disabled pending its own verified slice.
- T13-H04b8a/b8b are delivered in `787e70e` / `5cb9656` (PMA-R58/R59): original SQL minute-source recheck, then actual schema5 ordinary TRADE_DATE minute production. The latter passes505 focused checks and preserves44 old assertions. Public selection/registration, source-required remaining owner/schema/scope cells, H01/H02 and T18/T19 UI/joint acceptance remain pending; H04/T13 does not close.
- Acceptance: A07,A08; Verify: V04,V08.12 cases, origins/minimum original and natural-language counts, exact hashes, positive/blocking expectations and independent atom/relationship truth frozen before responses. Resolve actual intent disputes before calls.

### PMA-T14 — Implement independent grading and offline replay

- [ ] Deliver and verify.
- Depends on: T13.
- Files/scope: bounded grader module/entry seam, `test_extraction_acceptance_grading.py`, `test_extraction_acceptance_runner.py`, neutral expected-score fixture (at most5 files).
- Acceptance: A01,A02,A07,A08; Verify: V04. Deliberate omissions/inventions/logic changes cannot score PASS; correct blocking and false blocking differ; raw, replay and human-corrected results cannot be conflated.

### PMA-T15 — Run bounded real extraction acceptance

- [ ] Deliver and verify.
- Depends on: T14,C04 plus approved D05/start authorization and frozen unambiguous truth.
- Files/scope: T15a explicit runner/shared attempt ledger/offline guard tests (3–5); T15b immutable redacted campaign evidence; T15c bilingual real-acceptance report and evidence index (3). No actual-plan writes.
- Acceptance: A07,A08; Verify: V04,V09,V08.24 v12 planned outcomes; if prompt changes, separate24 actual-version outcomes, at most48 physical attempts total. No automatic retries or replacing failures. Full matrix signoff or explicit remaining failure; do not silently widen budget/limits or claim offline substitutes.

### PMA-C05 — Real extraction checkpoint

- [ ] Frozen matrix scored and actual required real runs pass for the exact deployed version; baseline failures retained separately. A07/A08 complete. Missing authorization/evidence remains pending, not an accepted shortcut.

### PMA-T16 — Define readiness states and dependency aggregation

- [x] Deliver and verify the pure model/dependency/summary scope (PMA-R65).
- Depends on: C04. P07's explicit user-approved reorder permits engineering before C05; C05/final acceptance remain required.
- Files/scope: `web/plan_readiness_models.py`, pure dependency/summary helper and `test_plan_readiness.py` (3 files).
- Delivered in `2f7aae0`:44 final readiness units pass; the preceding181-case selection includes43 earlier readiness and138 neighboring cases. T17's actual owned-read/API wiring remains separate; no installation/C05 readiness claim.
- Also apply PMA-H03 below: distinguish waiting for data/confirmation from an undefined rule or genuinely required manual evidence; reuse existing evaluators and collection ownership.
- Acceptance: A09,A10; Verify: focused V04. Six axes, summary precedence, alert-only/money-mode N/A, FALSE versus missing/first/normal close waiting, and execution state separation are exact.

### PMA-T17 — Project current readiness through read-only authority

- [x] Deliver and verify.
- Depends on: T16.
- Files/scope: T17a service/GET/router and `test_plan_readiness_api.py` (at most5); T17b both generated profiles and projection test (5); T17c paired API-owner appendix and contract regression (at most4).
- T17a1 private adapter accepted in `6557855` (R67), three files only. Full T17 stays open: complete ordinary output, independent targets/normal waits, bounded original-risk provenance, money/execution/notification projections and public/generated companions still need their separately frozen slices.
- T17a2 actual observer (`9a7e430`, R68) and T17a3 ordinary-output vertical slice (`c141ae8`, R69) are accepted only in their recorded scope. Current independently proved minute outcomes now consume actual persisted roots/leaves. Daily-dependent outcomes remain CACHED/UNKNOWN until current-source binding is repaired. Existing public serialization/generated compatibility is the next required companion; T17 remains unchecked.
- T17a3b (`4ea8119`, R70) completes that public-compatibility companion: internal evidence remains complete, old HTTP/serialization surfaces and all four H04 generated bytes are unchanged. Current daily-source ownership and the remaining readiness projections/API/UI remain open.
- T17a4 (`5b41ef8`, R71) binds the original owner's latest complete QFQ admission. Matching daily-dependent results can now be current; observed revisions, failures and source/date/permission changes revoke that claim. Legacy missing admissions remain unknown. Full-plan monitor and per-rule readiness retain their different granularity. Waiting/expiry, risk, money, execution, notification and public/UI work remain open.
- T17a5 (`f8134dd`, R72) accepts only proven simple future calendar waits, actual expiry bounds and full-leaf first-evaluation display. Frozen unit30 and integration23 are disjoint batches, not one53-case run. Complex future admission, money/execution, original-risk, notification and public/generated/UI work remain open; no overall READY or T17 completion is claimed.
- T17a6p (`22e9e21`, R73) corrects only the two current-family classification guards for existing Schema5–9. Eight focused checks pass. Real missing index input still prevents completion and retains CACHED/read-only; full P3/money readiness is unclaimed. The two unfinished T17a6 RED files remain separate, unchanged and uncommitted for resumption.
- T17a6f (`7370cc2`, R74) corrects only the relevant-book race fixture to OPEN_COST_CAP through real source/save/review/activation; original assertions and other fixtures stay intact. Four old cases pass in the frozen a6 working context, not a baseline rerun. All five unfinished a6 files stayed unchanged during this companion; resume their remaining checks without claiming final acceptance.
- T17a6 (`49dae97`, R75) accepts real monetary-input availability and unique original ordinary-signal execution facts. MARKET_VALUE_CAP does not require a cost book; OPEN_COST_CAP retains exact lot/basis checks and known-empty0/0. Three disjoint engineering batches passed21/13/14; post-review6 overlaps those cases and verifies at most2 signal point reads. Detailed money/signal/channel DTOs, current risk observations/provenance, notifications and public/generated/UI remain open; no overall READY or full T17 acceptance.
- Acceptance: A05,A09,A10; Verify: V04,V07. Coherent current generation/activation/target/freshness; zero provider/business writes/heartbeats; explicit upgrade/cached/unknown states, no READY token or current-book/research inference.

### PMA-T18 — Present per-rule readiness and delivery truth

- [x] Deliver and verify the component/engineering scope (R98); real browser journeys remain T21.
- Depends on: T17.
- Files/scope: readiness component/composable, workbench adapter, `PlanReadiness.spec.ts` and focused existing detail regression (5 files).
- Acceptance: A09–A11; Verify: V05 unit/type/build. Six axes, actual scope, official-close waiting, first evaluation, stale/unknown, queue/retry/delivered distinction and source links; no one-click automatic repair/activation.

### PMA-C06 — Readiness projection checkpoint

- [x] V04/V05/V07 focused checks pass for A09/A10 and applicable A11; no read path acquires data or grants authority. This does not mark the user's installation ready.

### PMA-T19 — Prove readiness edge cases and risk independence

- [x] Deliver and verify the engineering scenarios and existing-evidence map (R99); installation/browser/corpus gates remain separate.
- Depends on: T18.
- Files/scope: `test_plan_readiness_scenarios.py`, pure summary tests, scoped current notification/risk regressions and justified repairs only (3–5 files).
- Acceptance: A05,A06,A09,A10; Verify: V04 plus existing runtime-read ownership, official-close and P3 risk tests. Cover every MRD-S07 case, stale-response/context races, read-only side effects and quote/book changes without new occurrences.

### PMA-T20 — Audit the actual installation read-only

- [ ] Complete actual installation fact collection. Auditor engineering passes (R100,16 tests); the authorized attempt stopped before SQLite because WAL companions were unavailable. Actual schema/plan/evaluation/channel evidence remains uncollected. Independent T21 engineering may proceed under P07.
- Depends on: T19.
- Files/scope: explicit `scripts/audit_plan_readiness.py`, offline audit test, paired installation report (4 files).
- Acceptance: A09,A10; Verify: V10,V08. Record actual schema/plans/scope/review/activation/runtime/evaluation/channel facts with timestamps; missing prerequisites remain NOT_READY. Never launch/migrate/activate/send/fetch to manufacture success. Positive real readiness, if absent, is an explicitly unfulfilled operational result, not an engineering PASS claim.

### PMA-T21 — Accept complete browser journeys

- [ ] Complete remaining journeys. T21a automatic-alert/workbench/expiry/responsive engineering (R101) and T21b assisted source repair/actual cancellation (R102) are accepted; T21c exact H04 UI registration/calendar repair is accepted (R103); remaining native states/recovery are pending. Full acceptance still requires T15/C05.
- Depends on: T20 for independently verifiable engineering journeys under P07; T15 remains required for real-extraction consolidation and full T21 acceptance.
- Files/scope: `source-coverage.spec.ts`, `plan-readiness.spec.ts`, isolated fixture server and bounded screenshot/evidence assets (3–5 source files).
- Also apply PMA-H05 below: prove automatic daily evaluation after exact rule review, data-loss/recovery and the remaining explicit manual steps without fabricated confirmations.
- Acceptance: A01,A05,A09–A11; Verify: V05. Reproduce misclassified mandatory clause and block, repair legitimately and re-review, stale proof rejection, healthy FALSE/close waiting/missing data, independent risk path, notification truth, reload and320/768/1024/1440/accessibility; zero external requests outside the separately authorized extraction campaign.

### PMA-C07 — Integrated purpose checkpoint

- [ ] A01–A11 have actual corresponding evidence. Distinguish reviewed source completeness, real extraction results and installation diagnosis. A screenshot or ACTIVE label cannot substitute for a missing axis.

### PMA-T22 — Complete non-live regression and capacity

- [ ] Deliver and verify.
- Depends on: T21's relevant engineering delivery under P07; missing real-extraction/C07 evidence cannot be closed by regression results.
- Files/scope: justified failures split by root cause into at most5-file repairs, paired verification-report updates.
- Acceptance: A12; Verify: V06,V07. Reconcile initial failures/exact reruns, exclusions and overlapping counts; run capacity alone. Do not change old goldens, weaken assertions, add skips or increase resource thresholds to pass.

### PMA-T23 — Update bilingual operating and capability documents

- [ ] Deliver and verify.
- Depends on: T22.
- Files/scope: T23a operations/report pair updates (4); T23b README/docs-index pairs (4); T23c capability-map pair (2). Keep stage-specific status and links accurate.
- Also apply PMA-H05 below: document automatic conditions, once-per-definition clarification, retained human approvals and unsupported blockers separately.
- Acceptance: A03,A07–A12; Verify: V08. Explain omission blockers, allowed human changes, actual accepted extraction version, finite-corpus limits, legacy status and installation NOT_READY reasons without claiming excluded features.

### PMA-T24 — Audit all criteria and prepare local delivery

- [ ] Deliver and verify.
- Depends on: T23.
- Files/scope: T24a report/task pairs (4); T24b specification/contract pairs in separate at most4-file children; T24c scoped Git review and Chinese Conventional Commits. No push/deployment by default.
- Acceptance: A01–A12; Verify: V07,V08, exact real-run/installation evidence reconciliation. Close only genuinely completed checks; retain original source and protected task files, no sensitive/temporary databases in commits.

### PMA-C08 — Final acceptance

- [ ] All24 tasks/eight checkpoints and A01–A12 have required evidence. Report engineering, exact-version corpus and actual-installation results separately. Real installation may remain truthfully NOT_READY as scoped in D06; missing required real extraction acceptance cannot be marked complete.

## PMA-P04 — Risks and review boundary

| Risk | Required mitigation |
| --- | --- |
| Wider context blacklist still misses synonyms/implicit prerequisites | Positive narrow treatments plus unresolved default and independent obligation/relationship oracles |
| Tightening old verifier breaks persisted reviews | Historical version dispatch/current sidecar; exact populated-old-database tests |
| Safe false blocks make extraction unusable | Positive representative corpus, explicit false-block metrics, legitimate supported repair; no generic omission waiver |
| Finite benchmark mistaken for universal accuracy | Frozen independent truth, source-origin denominators, raw/assisted separation and version-specific claims |
| Full plan exceeds current prompt/output resource configuration | Preserve original limit failure; seek a concrete resource/version decision instead of truncation/relabeled cases |
| READY inferred from ACTIVE/cached/queue or irrelevant costs | Per-dependency axes, current target/owner binding and read-only side-effect tests |
| Provider budget or user-state writes expand during “acceptance” | Shared physical-attempt ledger; explicit D05 scope; migration/activation/test sends remain separate |

Task marks above refer only to paired recorded evidence. T01–T12/C01–C04 are complete. P07 permits independent later engineering; original03/04, C05 and final acceptance remain unresolved. Close only individually verified engineering work and retain unmet real/corpus criteria. Writing a checkbox never establishes acceptance.

## PMA-P05 — Reduce recurring manual verification

Added at the user's request on2026-11-01. Aim to review an exact rule definition once and then evaluate supported conditions automatically. These five pending checks extend the existing remaining tasks; keep all24 task IDs, eight checkpoints and their dependencies. This is a task-document update only, not implementation, prompt modification or acceptance. PMA-R48's original03/04 blocker, the shared48-attempt ceiling and the prohibition on user-database migration remain unchanged.

Deliver each check within its parent's existing sequential slices of at most5 files. Freeze exact file owners and any paired interface changes before implementation. Reuse existing plan fields, explicit supplements/review, evaluators, data collection and fact records; add no generic questionnaire, configuration registry, evidence platform, new worker or new trading indicator/strategy.

### PMA-H01 — Prefer supported automatic conditions

- [ ] Parents: T13,T15. Prepare a separate paired prompt supplement and a source-owned automation inventory. Distinguish already supported quantitative definitions, definitions needing explicit clarification, necessary manual facts and unsupported obligations; these are planning categories, not proposed API enums.
- Document preparation delivered in `c72b67c` (PMA-R60): [generation supplement](../docs/operations/trade-plan-automation-prompt-supplement.md) and [14-group source inventory](../docs/specifications/monitoring/INVENTORY-plan-condition-automation.md), each with its Chinese peer. This closes only the document preparation slice, not corpus/version acceptance or H01/H02 overall.
- Acceptance: preserve each condition's full meaning, AND/OR, rule, period and validity. Only source-explicit parameters or already approved exact product defaults may drive automatic mapping. Volume comparisons, candle ratios, relative strength and stabilization/repair use existing supported definitions only; do not invent thresholds or substitute a nearby formula for ambiguous prose. Keep unrepresentable requirements blocking.
- Verify: V04 corpus and V08 source/prompt audit; any extractor instruction/schema change also follows D04/V09 with a new actual version, frozen v12 baseline and the same campaign budget. Do not overwrite the original trading-plan prompt or relabel assisted corrections as automatic passes.

### PMA-H02 — Clarify a definition once through existing review

- [ ] Parents: T13,T14. Group genuinely missing parameters into one explicit source-bound review step using existing clarification/supplement mechanisms. A recorded question is not permission to choose its answer.
- Acceptance: store the answered definition with its exact source/content/review binding; preserve original raw inputs and score clarified results as assisted. The same unchanged reviewed definition does not require daily redefinition. A changed definition, scope, period or plan binding requires the existing applicable recheck/review. Unanswered meaning stays unresolved; create no satisfied runtime fact from an answer about strategy meaning.
- Verify: V04 grading mutations for omitted/invented parameters, repeated unchanged definitions and stale review bindings; preserve raw-versus-assisted scores.

### PMA-H03 — Compute daily outcomes and wait for owned data

- [ ] Parents: T16–T19. Reuse existing deterministic evaluators and owned collection/re-evaluation paths for supported conditions. Readiness reads remain read-only and cannot trigger acquisition.
- Acceptance: distinguish complete TRUE/FALSE, expected close/bar waiting, missing/stale data, undefined rules and required human evidence. Data absence must not become FALSE or a request to manually assert that a market condition is satisfied. Restore evaluation through the existing admitted data path when data returns, preserving occurrence/quantity/consumption and source ownership.
- Verify: V04 readiness scenarios and V05 UI checks for data loss/recovery, official-close waiting, no duplicate occurrence and zero writes/network calls from reads.

### PMA-H04 — Retain only necessary, precisely bound manual steps

- [ ] Parents: T13's existing binding prerequisite,T18,T19. For conditions that legitimately remain manual, complete exact condition selection and server-side ownership validation through the existing fact registration/records/UI. Split contracts/registration, consumers, generated profiles and UI into separately tested children of at most5 files before editing.
- The ordinary public backend is accepted through `71e69ca`, `3c55545`, `39f4093` (PMA-R61/R62):343 stable combined cases, synchronized profiles and75 companion checks, retaining exact historical hashes/assertions. Existing detail suffices for T18 labels/paths; no new catalog endpoint. H04's UI/joint acceptance remains with T18/T19; this does not close H04/T13.
- Acceptance: bind evidence to its actual plan version, rule/risk/alert owner and exact condition plus the existing date/signal/confirmation scope. Different same-kind requirements and negative evidence cannot cross-satisfy; ambiguous old facts stay blocked. AI-written text cannot become an assertion that a human verified the fact. Preserve initial plan review, applicable inventory/cost and official-fact confirmations, and explicitly human-approved exception buys; do not replace them with automatic approval.
- Verify: existing actual fact catalog/current/exception-delivery regressions plus focused new binding tests and V05 UI checks; preserve original-owner independent risk and historical/frozen compatibility.

### PMA-H05 — Verify and report the actual reduction

- [ ] Parents: T14,T15,T21–T24. Extend existing fixtures/journeys/reports rather than adding telemetry infrastructure or provider runs. Keep the fixed corpus and original failures; needed supplementary automation scenarios are offline.
- Acceptance: demonstrate that an unchanged, fully defined automatically evaluable rule evaluates repeatedly without new manual technical confirmations, while genuinely required approvals remain required. Report automatic-condition, manual/undefined/unsupported-condition and actual human-step counts separately, with source and data availability. Claim no universal zero-intervention target or success from dropped conditions. Explain each remaining intervention in paired operations/capability documents.
- Verify: V04/V05/V08, followed by the existing V06/V07 final gates. This addition does not expand existing real-call or user-state authorization and changes no completed task marks.


## PMA-P06 — Per-task sessions and coordinator

On2026-11-01 the user ordered one independent session for each remaining main task and designated the originating chat as coordinator, preferring `gpt-6.1-sol`. All12 sessions have been created in the existing local project. They share this repository; separate sessions are not isolated checkouts. H01–H05 remain checks within their parent tasks, not additional independent projects.

| Task | Initial model | Reasoning | Implementation gate |
| --- | --- | --- | --- |
| PMA-T13 | gpt-6.1-sol | high | C04; only unblocked prerequisites; PMA-R48 remains |
| PMA-T14 | gpt-6.1-sol | high | T13 |
| PMA-T15 | gpt-6.1-sol | high | T14,C04; frozen truth/manifest and shared attempt ledger |
| PMA-T16 | gpt-6.1-sol | high | C04; independent engineering before C05 under P07 |
| PMA-T17 | gpt-6.1-sol | high | T16 |
| PMA-T18 | gpt-6.1-sol | high | T17 |
| PMA-T19 | gpt-6.1-sol | high | T18 |
| PMA-T20 | gpt-6.1-sol | high | T19 |
| PMA-T21 | gpt-6.1-sol | high | T20 engineering; T15 real consolidation remains required |
| PMA-T22 | gpt-6.1-sol | high | Relevant T21 engineering; capacity alone; final gates retained |
| PMA-T23 | gpt-6.1-sol | medium | T22 |
| PMA-T24 | gpt-6.1-sol | high | T23 |

This is an initial task allocation, informed by [official OpenAI model-selection guidance](https://developers.openai.com/api/docs/guides/model-selection) and validated by the local session-creation tool. A model/effort change must be explicit and recorded by the coordinator; preserve the user's preference.

- The coordinator owns dispatch, exact per-slice file scopes, shared task/report updates, acceptance review and the final summary. An execution session owns only its dispatched task/slice. It may not spawn other sessions, change dependencies or close checkpoints itself.
- Unreleased sessions perform bounded read-only preparation, report their dependency/status and then remain idle. They do not edit, run expensive suites, access user stores or call extraction providers. Preparing a session is not implementation or acceptance.
- Only one execution session may write this shared repository at a time, after an explicit coordinator release naming the exact at-most5-file slice and required checks. Release the next slice/task only after reviewing its actual diff, failure/pass evidence and compatibility. Commit only dispatched paths under the existing Chinese commit convention; no push.
- Keep the actual session IDs and dispatch state in ignored local `.pytest_cache/pma/session-dispatch-20261101.json`; it is coordination metadata, not a corpus, readiness proof, job system or completion receipt. The coordinator reads session results and sends authorized follow-ups; execution sessions need not message other chats.
- Session creation is not permission to bypass the original03/04 blocker, raise the48-attempt extraction budget, migrate user data, start the default service or send real notifications. Existing P01–P05 boundaries and all unfinished task marks remain in force.

T13 prerequisite progress: R49–R62 record exact-target backend prerequisites, producer `5cb9656`, H01/H02 document preparation `c72b67c` and the accepted ordinary public C1+B+C backend. Source-required remaining cells, UI and corpus/clarification acceptance remain pending. These slices do not close H04/T13 or original03/04 positive acceptance.

## PMA-P07 — Explicitly approved independent engineering order

On2026-11-01 the user explicitly chose to advance independently verifiable monitor-readiness and subsequent engineering while retaining C05 and final acceptance gates. This supersedes only the earlier selected execution order, not product semantics or acceptance thresholds.

Start T16 after completed C04; T17–T20 retain their engineering dependencies and boundaries. T21 may implement and verify isolated journeys after the relevant T18/T20 engineering, but real-corpus consolidation still depends on T15. T22 may verify delivered non-live engineering after those journeys; record exact revisions and rerun affected checks after later changes. T23 may document actual delivered/blocked capabilities. Full T21/C07 and T24/C08 cannot close without all originally required evidence. Partial engineering is not real-extraction or installation readiness.

T13–T15 truth/corpus/runner gates, the original03/04 decision, the shared48-attempt limit and no-retry rule remain. User-database migration, real plan approval/activation, inventory/cost confirmation, live acquisition and real test sends are not implied. Maintain one execution writer, exact bounded slices, independent task sessions and existing model choices. Do not ask again for this approved reorder.

## PMA-P08 — User shutdown pause and exact resume point

PAUSED at the user's explicit request on2026-11-02, after finishing the current T16 slice, necessary review/testing and local commit. Start no next implementation, provider run, service or automatic wakeup while paused. The user will resume after powering on; the existing P07 authorization remains valid without another approval request.

- Last code: `2f7aae0`; current T16 models/summary are accepted, with evidence in R65 and `.pytest_cache/pma/t16a/evidence.json`. Paired pause/evidence notes are in R66. User database access/migration and real extraction remain0; campaign stays0/48.
- Next: the coordinator verifies Git status and this handoff, then freezes/releases T17a's exact files using T16's committed models. T17's bounded read-only preparation is complete, implementation is not released. Reuse the current owned read/proof mechanism, at most two snapshots/eight reads/15s lease,1MiB view and zero read-time business writes/acquisition.
- T17 must validate original risk owner references through existing authoritative paths, independently of the active read context; report missing proof/review/book/current owner as UNKNOWN rather than borrowing an active sibling. Both generated profiles and strict historical/API-owner companions remain separately scoped future slices.
- Sessions: coordinator `01a169c0-fc84-7f00-992f-20977e2529ea`; T16 `01a1968c-5139-7a83-a068-e7f365e6cf2c` (frozen/idle); T17 `01a1968c-9c50-72d3-9e0d-6b730e5de423` (prepared/idle), both `gpt-6.1-sol/high`. All12 dispatch states are stored in ignored `.pytest_cache/pma/session-dispatch-20261101.json`.
- T13–T15/C05, original03/04 positive acceptance, X09/X12/corpus/resource issues and R55/T22 old fixtures remain unresolved. T17–T24/C06–C08 and H01–H05 are not closed by this pause. No push/deployment or real installation readiness is claimed.

## PMA-P09 — Explicit continuation and bounded T17 progress

The user explicitly resumed on2026-11-03 with “继续任务”. P08 records the historical shutdown pause; dispatch is now resumed under unchanged P07 authorization and all retained gates. The coordinator verified clean HEAD `406179f`, reused the existing T17 `gpt-6.1-sol/high` chat and released only its three-file private adapter. R67 records local commit `6557855`; no public endpoint or full T17 acceptance follows from it.

The producer-output, public-compatibility, current daily-source, simple calendar-wait/expiry, current-family classification and money/execution slices are recorded in R69–R84. Structured facts (`3d6427b`), native money/signal projection (`6b0559c`), existing S0 reuse (`c279a89`), risk fact carriers/public-report compatibility (`7cc1b93`) actual risk producer/origin references with precise CLEAR reassessment (`cdc6184`), exact original-risk reads (`3b08ecc`), native indexed candidate seek (`fef25b8`) and shared market-source verification (`ac977e5`) are accepted in their bounded scopes. The bounded polling consumer and original execution-evidence checks are accepted in `fb692c8`. Next complete risk/notification projection and supported future confirmation before public wiring. Complex future admission remains unverified; old FALSE or a latched cause cannot supply missing proof. Missing ordinary roots/leaves and per-rule timestamps cannot be invented from a plan head or absence of a signal. Preserve complete FALSE versus missing/first evaluation, accurate owner-relative paths and independent risk. Reuse the actual evaluator, collector owner and existing immutable-result proof; no read-time evaluator, generic evidence platform or new worker. One writer, at most5 exact files and per-slice review remain mandatory. Real calls remain0/48; no user database access/migration, real acquisition/send, push or deployment occurred in these resumption slices.


## PMA-P10 — Explicit shutdown pause on 2026-11-13

The user requested recording progress and then pausing for shutdown. T17a14's exact five files are frozen and locally reviewed, with 44 final focused cases passing; R84 records the evidence and limits. HEAD remains `bd0bc32`; implementation and these paired progress notes are uncommitted. No task is running or released to continue. Resume only after the user requests it: verify Git and `.pytest_cache/pma/t17a14/evidence.json` hashes, commit the accepted five-file slice and paired evidence, then continue remaining independently authorized engineering. T17/C06 are still unchecked; P07, C05/original 03/04 blocking, 0/48 and no user database migration remain unchanged. Do not edit `tasks/plan.md` or `tasks/todo.md`.


On 2026-11-13 the user explicitly resumed. The coordinator matched the frozen source/evidence hashes and committed the five accepted files as `fb692c8`; the shutdown description above is historical. Independent engineering resumes under P07, without repeating the passed 44-case batch. Remaining gates and protected files are unchanged.

T17a15 risk fact shape and paired field appendix are accepted as `0c7d5aa` (R85), with 190 focused checks. Actual risk consumer/summary and production/race acceptance remain next; no T17/C06 closure.

T17a16 actual risk consumer/summary is accepted as `7c4404c` (R86): 48 disjoint focused checks; default prior-day reuse and other unobserved owners remain UNKNOWN. Next are notification configuration/event facts, supported future confirmation and public/generated/UI work. T17/C06 remain open.


T17a17 actual notification configuration is accepted as `c32ec2b` (R87):44 focused checks, no public/eligibility/delivery projection yet. Next wire bounded exact native events and channel receipts, then supported future confirmation and public/generated/UI work. Configured/enabled and historical STOPPED facts never establish current sending eligibility. T17/C06 remain open.


T17a18 exact native notification history is accepted as `d31cb36` (R88):71 unique checks, bounded event/classification/receipt reads and coherent retries. Notification axis/eligible remain UNKNOWN/null; native exception reader positives do not establish complete owned exception readiness. Next add narrowly supported actual IN_APP service verification, then supported future confirmation and public/generated/UI work; T17/C06 remain open.

T17a19 actual IN_APP service verification is accepted as `b6f3113` (R89):33 unique checks, with original expiry and instance/cancellation/read-race fencing. Only pure ALERT_ONLY complete FALSE with no applicable obligations can reach READY_FOR_MONITORING. Broader supported notification consumers, future confirmation and public/generated/UI work remain next; no eligibility, full T17/C06 or installation claim follows. All P07/C05/final gates and0/48 remain unchanged.

T17a20 exact delivered-alert fulfillment and Schema5 empty-signal complete FALSE are accepted as `249c639` (R90):21 unique checks and paired MRD-S09.1. Actual service gates and null eligibility remain unchanged; broader risk/candidate/WAIT and higher-schema ordinary claims remain unproved. Next complete supported staged confirmation and public/profile/generated/UI wiring. T17/C06 and all P07/C05/final gates remain open;0/48 is unchanged.

T17a21 verified whole-fill staged waits are accepted as `29bd760` (R91):20 unique checks and paired MRD-S10. Exact consumed predecessor and actual successor FALSE support official-close/later-day minute waits; same-day minute and source-admitted AFTER+manual acceptance remain unavailable. Existing shared manual exclusion stays conservative. Next wire actual v1/v2 owner lifetime and public/generated contracts, then UI. T17/C06 and P07/C05/final gates remain open;0/48 is unchanged.

T17a22 actual dual-profile owner/lifetime wiring is accepted as `5b35edd` (R92):19 unique passes, real v1/v2 current proofs, cancellation/drain/storage and generation recovery, unchanged legacy responses. V1's other old direct reads are not covered by the new readiness lease. Next deliver public GET, strict additive/historical projection and both generated companions, then UI. T17/C06 and corpus/final gates remain open;0/48 unchanged.

T17a23 public exact-version GET is locally accepted as `0dbdd07` (R93):26 unique passes. Generator check remains pending/exit1 with four H04 artifacts unchanged. Next add exact readiness projection ahead of unchanged historical checks, adapt the integration baseline to fixed H04 projection, synchronize paired API-owner records and generate all four outputs. T17/C06 remains unchecked; original03/04/C05/final and0/48 stay unchanged.

T17a24 exact projection and paired API-owner records accepted as `9fd55c4` (R94):69 unique passes. Next T17a25 writes four candidate artifacts plus narrow pre-projection path registration, then actual generated-contract checks. T17/C06 and original03/04/C05/final gates remain open;0/48 unchanged.

T17 engineering handoff accepted in R95: `76031b3` materializes exact contracts,35 unique passes (13 overlap witha24); `0680a57` records paired API acceptance. Owned read/API/contracts are delivered with declared UNKNOWN limits. Next T18 UI then T19 joint scenarios; C06 and original03/04/C05/final remain open,0/48 unchanged.

T18a workbench foundation accepted as `eb04136` (R96):133 unique passes across132 focused and20 final checks with19 overlap; type/build pass. Next H04 exact leaf selector and remaining target/detail presentation, then T19/T21 joint/browser acceptance. T18/C06 stay open; original03/04/C05/final and0/48 unchanged.

T18b exact manual leaf UI accepted as `cdebd59` (R97):111 unique checks (107+33 with29 overlap); no added confirmation step. Late refresh failure review finding fixed and tested. Next T18 target/provenance/required-input detail, then T19/T21 native/public/browser combination. Full H04/T13/T18/C06 and corpus/final gates remain open;0/48 unchanged.

T18 component engineering and C06 focused checkpoint accepted in R98 (`4dd617f`):173 unique checks including38 readiness, type/build pass. T19 native/public combinations and T21 real browser journeys remain separate; no actual installation readiness is claimed. H04/T13, original03/04/C05/corpus/final and0/48 unchanged.
