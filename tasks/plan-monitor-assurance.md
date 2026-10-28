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

- [ ] Deliver and verify.
- Depends on: T10.
- Files/scope: sequential T11a focused read composable, pure source-span/presentation helpers and their two tests (4); T11b small coverage container/row/span components and `SourceCoverageReview.spec.ts` (4); T11c0 exact workspace intent/load/mutation snapshots and focused concurrency test, optionally one small owner helper (2–3); T11c1 actual workspace/workbench/review coverage wiring and a new actual-owner `PlanWorkbenchCoverage.spec.ts` (4); T11d extraction-summary presentation and focused existing/new tests (at most4); T11e1 isolated no-I/O browser fixture server and its real-lifecycle integration test (2), then T11e2 real-Chrome journey and bounded evidence (2–4). Each child is independently tested and committed before editing a shared owner. Independent T11c0 and T11e1 may use the frozen T10 API while T11b proceeds; T11c1 waits for both workspace and presentation owners, and real browser journey acceptance waits for all UI children. Use the T10 typed client, never cast the generic condition-plan request into a coverage page. Keep historical preparation details historical; a preparation ID is not a live plan-version ID. Preserve source code points and CRLF in escaped readonly highlighting. Existing-fixture reconciliation, if needed, is a separate justified at-most5-file child preserving original assertions and raw sources.
- Acceptance: A01,A03,A11; Verify: V05 unit/type/build. Source spans, partial conditions, AI versus server treatment, human adjustments and no generic waiver; stale contexts discard responses and defaults do not acknowledge blockers.

### PMA-T12 — Close historical/legacy regression boundaries

- [ ] Deliver and verify.
- Depends on: T11.
- Files/scope: T12a adds `test_source_coverage_compatibility.py`, `test_source_coverage_occurrence_compatibility.py` and `test_source_coverage_frozen_compatibility.py`, plus a separate reconciliation of the original workbench positive fixture (4 files). Preserve its original assertions and retain the generic-source blocking negative. T12b independently closes the reproduced fresh-workbench-run admission race with a real source-owner writer fence, existing final-job admission seam, actual-store race/replay tests and only necessary synthetic seam-fixture alignment (at most5 files); split any further owner repair before editing. The fence rechecks exact current source/review after input copying and remains held through actual job commit. Missing capability fails closed; completed same-key receipts and old frozen codecs remain historical. These independent children may proceed in parallel after T11 because their implementation owners do not overlap; each is tested, reviewed and committed separately before C04. No cross-database atomicity claim follows from an early read or an unchanged hash.
- Acceptance: A05,A06; Verify: V03 plus historical codecs/replay. Exact legacy reads and old frozen bytes remain; legacy cannot grant current coverage; new-source saves/reads/reuse cannot downgrade policy or rearm consumed signals.

### PMA-C04 — Reviewed-source workflow checkpoint

- [ ] Coverage UI/API/current guards and history regression pass. A01–A06 and applicable A10/A11 covered. Real-provider and readiness acceptance still pending.

### PMA-T13 — Freeze corpus, provenance and independent truth

- [ ] Deliver and verify.
- Depends on: T01; execute after C04 in the selected sequential order.
- Files/scope: source bundle, truth bundle, manifest and `test_extraction_acceptance_corpus.py` (4 files); use further reviewed3–5-file children if original redaction artifacts require them.
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

- [ ] Deliver and verify.
- Depends on: C04; execute after C05 in the selected sequential order.
- Files/scope: `web/plan_readiness_models.py`, pure dependency/summary helper and `test_plan_readiness.py` (3 files).
- Acceptance: A09,A10; Verify: focused V04. Six axes, summary precedence, alert-only/money-mode N/A, FALSE versus missing/first/normal close waiting, and execution state separation are exact.

### PMA-T17 — Project current readiness through read-only authority

- [ ] Deliver and verify.
- Depends on: T16.
- Files/scope: T17a service/GET/router and `test_plan_readiness_api.py` (at most5); T17b both generated profiles and projection test (5); T17c paired API-owner appendix and contract regression (at most4).
- Acceptance: A05,A09,A10; Verify: V04,V07. Coherent current generation/activation/target/freshness; zero provider/business writes/heartbeats; explicit upgrade/cached/unknown states, no READY token or current-book/research inference.

### PMA-T18 — Present per-rule readiness and delivery truth

- [ ] Deliver and verify.
- Depends on: T17.
- Files/scope: readiness component/composable, workbench adapter, `PlanReadiness.spec.ts` and focused existing detail regression (5 files).
- Acceptance: A09–A11; Verify: V05 unit/type/build. Six axes, actual scope, official-close waiting, first evaluation, stale/unknown, queue/retry/delivered distinction and source links; no one-click automatic repair/activation.

### PMA-C06 — Readiness projection checkpoint

- [ ] V04/V05/V07 focused checks pass for A09/A10 and applicable A11; no read path acquires data or grants authority. This does not mark the user's installation ready.

### PMA-T19 — Prove readiness edge cases and risk independence

- [ ] Deliver and verify.
- Depends on: T18.
- Files/scope: `test_plan_readiness_scenarios.py`, pure summary tests, scoped current notification/risk regressions and justified repairs only (3–5 files).
- Acceptance: A05,A06,A09,A10; Verify: V04 plus existing runtime-read ownership, official-close and P3 risk tests. Cover every MRD-S07 case, stale-response/context races, read-only side effects and quote/book changes without new occurrences.

### PMA-T20 — Audit the actual installation read-only

- [ ] Deliver and verify.
- Depends on: T19.
- Files/scope: explicit `scripts/audit_plan_readiness.py`, offline audit test, paired installation report (4 files).
- Acceptance: A09,A10; Verify: V10,V08. Record actual schema/plans/scope/review/activation/runtime/evaluation/channel facts with timestamps; missing prerequisites remain NOT_READY. Never launch/migrate/activate/send/fetch to manufacture success. Positive real readiness, if absent, is an explicitly unfulfilled operational result, not an engineering PASS claim.

### PMA-T21 — Accept complete browser journeys

- [ ] Deliver and verify.
- Depends on: T15,T20.
- Files/scope: `source-coverage.spec.ts`, `plan-readiness.spec.ts`, isolated fixture server and bounded screenshot/evidence assets (3–5 source files).
- Acceptance: A01,A05,A09–A11; Verify: V05. Reproduce misclassified mandatory clause and block, repair legitimately and re-review, stale proof rejection, healthy FALSE/close waiting/missing data, independent risk path, notification truth, reload and320/768/1024/1440/accessibility; zero external requests outside the separately authorized extraction campaign.

### PMA-C07 — Integrated purpose checkpoint

- [ ] A01–A11 have actual corresponding evidence. Distinguish reviewed source completeness, real extraction results and installation diagnosis. A screenshot or ACTIVE label cannot substitute for a missing axis.

### PMA-T22 — Complete non-live regression and capacity

- [ ] Deliver and verify.
- Depends on: T21.
- Files/scope: justified failures split by root cause into at most5-file repairs, paired verification-report updates.
- Acceptance: A12; Verify: V06,V07. Reconcile initial failures/exact reruns, exclusions and overlapping counts; run capacity alone. Do not change old goldens, weaken assertions, add skips or increase resource thresholds to pass.

### PMA-T23 — Update bilingual operating and capability documents

- [ ] Deliver and verify.
- Depends on: T22.
- Files/scope: T23a operations/report pair updates (4); T23b README/docs-index pairs (4); T23c capability-map pair (2). Keep stage-specific status and links accurate.
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

This is a reviewable implementation proposal, not executed work. No new task may be claimed complete from writing its checkbox.
