# R13 independent offline reacceptance

Date: 2026-09-13, Asia/Shanghai. Task `01a098d6-b8b2-7953-80de-942d4ea78fdd`; coordinator `01a093fc-f8d3-73d1-b759-ad76c7451697`. Canonical English; the paired `.zh-CN.md` is the equivalent Chinese review copy.

## 1. Decision and scope

**Complete offline acceptance is NOT PASSED; do not recommend C6 approval yet.** N01–N04 and the tested original monitoring requirements have fresh offline closure evidence, including four real OS-process restart cases. A newly reproduced P2 layout failure remains in the mandatory complete browser gate. R14 real-provider/user-visible acceptance remains **NOT_RUN**. The coordinator owns the final checkpoint decision.

| Central question | Independent conclusion |
| --- | --- |
| Is the objective aligned and the plan faithfully converted? | Yes for the unchanged literal source, the finite supported grammar, and the independently supplied test policies. Exact fields, source spans, units, logical structure, review identities and numerical oracles agree. This does not establish arbitrary Chinese-language or actual-model accuracy. |
| Does the current reviewed version enter the actual monitoring chain? | Yes in isolated offline execution: ordinary browser creation/review/public activation → real composition/scheduler/provider adapter → explicit evaluation → atomic SQLite result/state/event/outbox → IN_APP and visible browser reminders. Provider boundaries are synthetic. |
| Are required reminders visible and false reminders avoided? | The tested BUY/SELL/pure-risk, boundaries, incomplete data, replay, revision, disablement, expiry, browser recovery and process-restart cases meet their bounded oracles. Full product acceptance is withheld because the complete browser gate is not green; real market-window delivery is untested. |

This is an existing-plan monitor, not a strategy generator, stock selector, broker, order system or profitability evaluation. Read/acknowledgement is never a fill; holdings change only through separate inventory operations.

Starting workspace: `main/cc328adb4f79b9673705cb67e67520da2dfd667b`, plus 12 protected user modifications and four R00 untracked files. No branch switch, reset, stash, user-hunk staging, dependency installation, live AI/market request, external message/channel delivery, trading, production database, actual holding, push or publication occurred. The sole authorized external task callback is the final coordinator handoff. Historical `R13-business-acceptance`/`R13-matrix`/`handoffs/R13` and their original NOT PASSED evidence remain unchanged.

## 2. Immutable source and independent expectations

`tests/fixtures/ai/explicit-plan-literal-source-v3.json` is unchanged. Its entire source, with only the authorized `测试股票` → `003043.SZ` substitution, states previously held/sellable100, maximum300; completed5m close in inclusive[9.80,10.00] AND current volume ≥1.5 × the arithmetic mean of the preceding five completed5m bars → BUY100; inclusive[10.80,11.00] → SELL100; close<9.50 → RISK_ALERT with quantity=null. Source inventory prose never writes the ledger.

The original literal journey supplies eight separate USER_SUPPLEMENT policies: TRADING_DAY, 2026-09-14, CONTIGUOUS_TRADING_BARS, three ONCE_PER_ACTIVATION choices, BLOCK_BOTH and RISK_ONLY. Missing policies and unconfirmed source treatments remain blocking. These choices are test input, not text attributed to the user’s original plan.

The independent production-pipeline oracle uses [100,100,100,100,600]: arithmetic mean200, median100, threshold300. Current200/299 do not buy;300/301 buy only when the price predicate also holds. Six buy-price neighbors cross all four volume values; nine sell/risk neighbors independently test inclusion and strict risk inequality. The original ALL journey remains separate from the correction journey’s deliberate ANY/BUY200 successor and subsequent ALL/BUY100 successor.

R08 SPEC-executable-plan-extension/ADR0005 and R11 SPEC-source-treatment-review/ADR0006 are the contract inputs. Schema1/2, historical mapping/evidence hashes, prompts v1–v4 and legacy research-fill semantics are retained. Explicit mode remains finite: no arbitrary operators, tree restructuring, sequencing, strategy generation or Schema3 portfolio backtest support is inferred from this acceptance. UNKNOWN inventory/sellability remains null and blocks only dependent trades; known holdings, sellability, limits and applicable rules bound quantitative outputs. Pure risk needs neither unrelated volume nor inventory.

## 3. Fresh production and browser evidence

| Stage | Current implementation object / location | Fresh evidence |
| --- | --- | --- |
| Composition and lifecycle | `web/monitor_composition.py:671` `create_monitor_composition`; `runtime/service.py:2507` `RuntimeLifecycleService`; `runtime/scheduler.py:73` `MarketSessionScheduler` | Ordinary unseeded browser journeys and process restart run the owned background lifecycle. |
| Current plan and acquisition | `runtime/production.py:214,242,514` `ProductionMonitorPipeline`; `runtime/service.py:2290` `RuntimeDeadlineCoordinator`; `runtime/symbol_service.py:141` `SymbolService` | Real active version/hash/revision selection, SDK normalization, completed cutoffs and scheduler deadlines. No direct browser evaluation shortcut. |
| Evaluation and commit | `runtime/explicit_service.py:85,115,167` `ExplicitRuntimeEvaluationService`; `decision/explicit_conditions.py:198`; `decision/explicit_rules.py:269` | Independent arithmetic oracle, validated decision-result-v2 hashes, atomic ledger/occurrence/event commit, transaction rollback and duplicate/revision guards. |
| Delivery and current eligibility | `notifications/channels.py:178,348` `InAppChannel`/`_require_event`; `notifications/dispatcher.py:220`; `notifications/outbox.py:290,307,331` | Strict AlertEvent/ExplicitAlertEvent union; fresh SQLite first-attempt IN_APP DELIVERED; old events remain historical after replacement/disable/expiry. |
| Review and presentation | `web/plan_service.py:653`; `web/alert_service.py`; `web/src/components/plans/ExplicitPlanSupplementForm.vue`; `web/src/composables/useMonitorStream.ts` | Current review/hash/revision independently reject stale activation409; repeated ordinary edits; visible reminders and reconnect without manual refresh; ACK leaves100. |

Backend locations are relative to `src/trade_plan_monitor/`. The [scenario matrix](../../remediation/R13-reacceptance-matrix.md) records input/expected/actual/test/evidence level for S01–S09, F01–F09 and N01–N05.

All ordinary explicit browser runs start from an empty temporary SQLite database and a free loopback port. Only calendar/history are seeded. Plans, review, ACTIVE and inventory are created through ordinary controls and real business APIs, without route mocks. Only AI HTTP and market SDK are fake; controlled time releases the real scheduler. Synthetic READY certification is a test prerequisite, not fresh supplier certification. Other existing UI fixture tests are labelled browser-component evidence.

The unchanged literal run observes299/no BUY at10:05,300/BUY100 at10:10,SELL100 at10:15 and RISK_ALERT/null at10:20. All three are visible and acknowledged; inventory stays100 until the test’s explicit independent reduction. The correction run re-reviews versions3–8, rejects separately stale reviewId/contentHash/revision, executes version5 ANY/BUY200 and version8 ALL/BUY100, and preserves the original source. Six AI boundary failures preserve the prior active version; automatic browser disconnect/reconnect displays the committed SELL and subsequent risk without manual refresh.

`remediation/evidence/R13-reacceptance/final-sqlite-lineage.json` independently joins every retained event to its reviewed version, planHash, activationRevision, cutoff and canonical validated resultHash. The unchanged ALL, corrections and four OS-restart databases contain13 checked events, each with one IN_APP attempt and DELIVERED. Browser visibility, database persistence, channel delivery and acknowledgement are separate assertions; none is used as a substitute for the others. Raw recorded journeys/screenshots are under `final-journeys/`; `verify_evidence.py` rechecks only these test-owned databases read-only.

## 4. Real active-process restart

The additive `r13-active-process-restart.spec.ts` uses the same source but explicitly supplies EACH_QUALIFYING_BAR for all three rules. Its separate synthetic tape appends a qualifying BUY bar at10:30, volume301. Thus an exhausted once-per-activation policy cannot explain a deduplication pass. The normal literal tape/fixture remains unchanged.

Every case uses ordinary source entry, full current review/public activation, and independent100/100 registration; generates and visibly acknowledges BUY at10:10; closes its browser; terminates the exact service PID reported by the test endpoint; verifies service and launcher exit plus ECONNREFUSED; and starts a different OS PID on the same temporary SQLite database. Resume mode does not reseed history, plans, reviews, ACTIVE or inventory. No service-object alias is labelled a process restart.

| Case | Expected and observed |
| --- | --- |
| ACTIVE | Same completed tape/startup recovery and10:11 produce no duplicate. Original acknowledged event identity remains. SELL10:15 and risk10:20 appear; the same BUY rule emits a distinct10:30 event. All four are visibly acknowledged; every durable inventory field and revision remain unchanged. |
| REPLACE | Ordinary price correction9.80→9.81 is saved/reviewed/activated as version3 before exit. Revision/pointer survive; version2 BUY remains historical, not current; subsequent SELL belongs to version3. |
| DISABLE | Public deactivation survives; old BUY remains historical and acknowledged; no further event through10:15. The no-active explicit-runtime API correctly returns404. |
| EXPIRE | The second process starts on2026-09-15 after the reviewed TRADING_DAY. Old event is not current; further scheduler advancement through10:15 creates no reminder. Original dated inventory is unchanged. |

This establishes forced local OS-process recovery with fake provider inputs, not graceful production shutdown, power-loss durability, external recipient exactly-once delivery or real supplier reconnection. Initial probe failures are preserved: a test shutdown route closed the listener without the launcher exiting inside15s; the next probe incorrectly clicked an already-disabled acknowledged button, compared changing read cutoff as ledger data, and expected200 from a correctly absent runtime. The final probe verifies exact ledger state while allowing only the read cutoff to advance. These were harness/expectation corrections, not business repairs or weakened business oracles. The four earlier recorded processes were independently confirmed already exited during authorized cleanup.

## 5. Actual gates and residual finding

| Command scope | Actual result |
| --- | --- |
| Complete backend `-m "not live"`, including original R13-added files | 2634 passed /1 POSIX-ownership skip on Windows /4 live deselected /1 existing warning;2572.52s |
| Complete frontend units | 644 passed /45 files;5.10s |
| Frontend type check and build, initial and after additive test changes | Passed |
| Initial complete browser suite | 29 passed /1 failed;2.7m |
| Unchanged failing narrow backtest gate, bounded repeat | 0 passed /5 failed; same320px/200% boundary violation |
| Additive layout measurement probe | Executed; records all four routes before/after font/render stability. Its successful completion is not a passing layout gate. |
| Focused active OS restart suite after harness corrections | 4 passed;1.8m; the later final suite additionally advances the expired next-day scheduler. |
| Final complete browser suite after additive tests | 34 passed /1 failed;4.5m (35 total, including the diagnostic probe) |
| Canonical fresh SQLite lineage / generated types / scoped lint / protection | Passed;13 event lineages; generated types current; scoped lint clean;16 protected files unchanged |
| Real AI, real market, actual market-window user-visible loop, R14 | NOT_RUN; not authorized in this step |

Command JSON/logs/XML are retained under `remediation/evidence/R13-reacceptance/`. Counts from overlapping runs are not added. The backend collection contains2639 items, with4 live cases deselected before their credential/client fixtures and2635 selected. The completed run has one skip at `tests/integration/test_backtest_production_composition.py:492`: requires POSIX ownership semantics on this Windows host. Its one warning is the existing Starlette TestClient/httpx deprecation. Capacity/memory gates are not interrupted or weakened. Additive browser tests are recorded separately from the initial30-test collection.

**N05 · P2 · CONFIRMED · Backtest pages overflow at320px/200% text.** The unchanged gate fails in the complete suite and in5/5 focused repetitions. A separate measurement probe, after `document.fonts.ready` and two animation frames, records stable page scroll widths338,476,617,411 against clientWidth320 for `/backtests`, `/backtests/new`, `/backtests/data` and the result route. The first five diagnostic elements in the old test are intentionally scrollable navigation children; full inspection finds uncontained hero/form/result content as well. This is not established to be an AppShell user-hunk defect. Relevant sites include `BacktestRunsView.vue:110`, `BacktestNewView.vue` hero/grid layout and `DatasetScopeForm.vue:411,418,444`, plus result descendants. Screenshots corroborate the measured overflow.

Minimum follow-up: bound intrinsic grid/flex/control widths in the affected backtest views/components; preserve intentional labelled table/navigation scrollers and the protected AppShell changes. Re-run the unchanged four-width/200% gate, interactive controls, axe and full browser suite. Do not clip the document, lower text scaling/widths, delete assertions or add retries to hide it. No business/CSS repair was made in this independent acceptance.

N01–N04 are closed for their specific freshly rechecked offline scopes; N05 prevents the full browser gate and therefore complete C6 recommendation. Real-model semantic correctness and fresh supplier/user receipt are unverified boundaries, not additional reproduced defects.

## 6. Protection, artifacts and handoff

`workspace-before.json` and `workspace-before.diff` record the exact input tree. Final protection compares all16 protected files with this task’s starting bytes;15 also match the original R13 manifest, while the dashboard whole-file change comes from authorized N04 commits. Its only user diff remains the original09:35/10:35 two bars and second openPoints1231.25. Immutable source and historical report hashes are checked separately. Only this task’s additive test harness/probes, evidence and three bilingual report/matrix/handoff pairs are staged.

See [handoff](../../remediation/handoffs/R13-reacceptance.md) for exact local commits and final gate records. No successor or R14 is started. Any later R14 proposal must specify the actually selected supplier/model, physical requests including retries, cost/quota caps, symbol/endpoints, market window/duration, temporary database, user-reviewed plan and notification channel before separate authorization; no credential or unsupported value is guessed here.

Large original traces remain at `C:/Users/xiedc/.codex/visualizations/2026/09/13/01a098d6-b8b2-7953-80de-942d4ea78fdd/r13-reacceptance-traces/`; `trace-archive.json` maps original/archive paths, byte sizes and SHA-256. After strengthening cleanup-error propagation, the four OS cases were separately rerun:4 passed/1.8m and type check passed; no business or gate-threshold change followed.

Authored source/documents/JSON use scoped whitespace checks; original runner logs retain their captured whitespace.
