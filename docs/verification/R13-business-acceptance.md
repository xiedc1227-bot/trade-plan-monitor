# R13 independent offline business acceptance

Date: 2026-09-13, Asia/Shanghai. Task: `01a096d2-805d-7761-92e1-c773709c4b6b`. Canonical English; the paired `.zh-CN.md` is the Chinese review copy.

## 1. Verdict and scope

**Complete offline business acceptance is NOT PASSED.** The literal plan now reaches real extraction parsing, reviewed public activation, production scheduling, deterministic decisions, SQLite and visible browser alerts within an isolated synthetic run. Two P1 gaps remain: the mandatory IN_APP channel rejects every explicit event, and ordinary ALL/ANY correction cannot complete review. Previously corrected fields also disappear from the editor. Existing browser gates have additional failures. No business implementation was changed to conceal these results.

| Question | Answer |
| --- | --- |
| Is the objective aligned? | Substantially yes. Schema3 expresses the original buy/sell/five-minute risk plan without introducing the legacy episode, CORE/TACTICAL or daily-close requirement. Finite supported semantics and explicit human supplementation remain the boundary. |
| Is the chain complete? | The tested literal happy path produces visible, traceable reminders, but complete usability and delivery-consumer compatibility are not closed. Public activation is open despite the IN_APP consumer gap. |
| What verification level is established? | Independent OFFLINE execution with real Chromium, parser, public business APIs, SQLite and production scheduler; separate numeric, lifecycle and fault-injection probes. Actual AI semantic accuracy, fresh supplier data and an actual market-window user-visible loop are NOT_RUN. |

R13 is an acceptance exercise, not a profitability assessment. Completing this report does not complete checkpoint C6 or mark R13-A accepted. R14 calls have not been started and require separate bounded authorization.

Baseline: `main/fa316833e8c5d4b427acef4f8500d1e9714a2dd1`, including the 12 pre-existing user modifications and four R00 untracked files. Final verification applies to this shared working tree, not a clean checkout. `remediation/evidence/R13/workspace-before.json` captures exact starting file hashes; the final protection check is recorded separately. No reset, stash, branch switch, user-file staging, dependency installation, push or publication occurred.

## 2. Source, independent oracle and isolation

The immutable input is `tests/fixtures/ai/explicit-plan-literal-source-v3.json`. Its full `sourceText`, including line breaks, was submitted; only the authorized `测试股票` → `003043.SZ` replacement exists. The source states existing/sellable 100 and maximum 300, inclusive completed-five-minute buy range [9.80,10.00] AND current volume >=1.5 times the preceding five completed bars' arithmetic mean, BUY100, inclusive sell range [10.80,11.00], SELL100, and close <9.50 → pure RISK_ALERT. No reminder or acknowledgement is a fill.

The eight separate USER_SUPPLEMENT values are `activation.mode=TRADING_DAY`, `activation.trading_day=2026-09-14`, `rules[0].condition.conditions[1].history_scope=CONTIGUOUS_TRADING_BARS`, three `repeat_policy.mode=ONCE_PER_ACTIVATION`, `conflict_policy.trade_conflict=BLOCK_BOTH`, and `conflict_policy.risk_conflict=RISK_ONLY`. They were entered in ordinary controls, not inserted in the source. Missing source-only policies block activation. Source inventory statements remain review treatments; inventory stays UNKNOWN until independent dated registration.

The independent numeric oracle uses [100,100,100,100,600]: sum1000, arithmetic mean200, median100, threshold300. Current200/299 must not buy, 300/301 must buy when price qualifies. Six price neighbors [979,980,981,999,1000,1001] fen cross all four volumes. Separate cases cover sell neighbors, risk949/950/951, temporary incomplete satisfaction followed by final1001, and historical alert status after replacement/disable/expiry. These production-pipeline probes use explicitly identified trusted test-plan/inventory setup; they do not replace the unseeded public browser journey.

The main browser run used `tests/browser/explicit_server.py` and `web/tests/e2e/explicit-sqlite.spec.ts`, an empty temporary SQLite database and a free loopback port. It seeded only calendar/market history, never plans, review, ACTIVE or inventory. Only AI HTTP and the market SDK were faked. Browser business APIs were not route-mocked. The controlled route advances time; the real scheduler owns deadlines. Synthetic READY certification is a test prerequisite, not real certification. No actual `127.0.0.1:8765` operation occurred; some in-process TestClient URLs use that string without a network connection.

Other pre-existing frontend journeys use explicitly mocked business API responses and are classified as browser-component evidence. The installed-process test uses an isolated empty database and no provider credentials. Live-marker tests were deselected before their credential/configuration fixtures. No paid AI, market quota, external Webhook/message, broker, order, real fill, production database or real holding was accessed or changed.

## 3. Actual production chain and fresh evidence

| Stage | Inspected implementation at baseline | Fresh execution evidence |
| --- | --- | --- |
| Composition and background lifecycle | `web/monitor_composition.py:91,544,671,696,715`; `RuntimeLifecycleService` and `MarketSessionScheduler` | Real composition in the isolated browser server, 22 clock deadlines. |
| Current active snapshot and acquisition | `runtime/production.py:214,242,290,514`; `RuntimeDeadlineCoordinator` in `runtime/service.py:2290`; `SymbolService` in `runtime/symbol_service.py:141` | Real active version2, certified-test SDK minute acquisition, frozen cutoff; no browser-triggered direct evaluation. |
| Explicit dispatch and deterministic evaluation | `runtime/service.py:2440`; `runtime/explicit_service.py:85,115`; `decision/explicit_conditions.py:198`; `decision/explicit_rules.py:269` | Exact mean/range oracle, BUY/SELL/quantity-null RISK_ALERT. |
| Atomic result/state/event/outbox | `runtime/explicit_service.py:167`; SQLite `explicit_evaluation_ledger`, `explicit_rule_occurrence_state`, alert/outbox rows | Four validated result hashes; three retained events. Separate rollback/retry/rebuilt-service tests cover durable deduplication. |
| Mandatory delivery consumer | `web/monitor_composition.py:698`; `notifications/channels.py:182,343`; `notifications/dispatcher.py:220` | **FAILED**: IN_APP raises on ExplicitAlertEvent, records CHANNEL_FAILURE and bounded retries. |
| API and browser presentation | `web/alert_service.py`; explicit runtime API; `useMonitorStream.ts:117,154`; real plans/dashboard/alerts pages | Correct persisted condition facts and all three reminders were visually inspected. Acknowledgements leave inventory100. |

Source paths in this table are relative to `src/trade_plan_monitor/` except the named frontend file. [Requirement and scenario matrix](../../remediation/R13-matrix.md) supplies test objects and F01–F09 dispositions.

Main independent browser artifacts are in `remediation/evidence/R13/`. The server-created directory was `C:/Users/xiedc/AppData/Local/Temp/tpm-r12-browser-v9bgfe21`; durable copies include `browser-evidence.json`, `browser-checkpoints.json`, seven PNGs and `lineage.json`. The JSON contains zero browser console warnings/errors and zero external browser requests, with one fake AI request. This does not assert that every other test had a clean console.

| Time on synthetic 2026-09-14 | Actual result | Cumulative alerts | Inventory |
| --- | --- | --- | --- |
| 10:05 | 299 / mean200 / threshold300: no BUY | 0 | 100/100 |
| 10:10 | 300 / mean200 / threshold300: BUY100 | 1 | 100/100 |
| 10:15 | completed close1080: SELL100 | 2 | 100/100 |
| 10:20 | completed close949: RISK_ALERT, quantity=null | 3 | 100/100 |
| Acknowledge all | Three independent acknowledgements | 3 | 100/100 |
| Explicit actual-inventory reduction, then disable and 10:25 | No new event; historical events currentActionable=false | 3 | 0/0 after the separate reduction only |

All three events bind plan version2, activationRevision1 and planHash `cbb71570023277674140a16ea0ea772827a4371a08f7e7f8b4b2706fc30d2e06`. `lineage.json` was read from only this temporary DB with `mode=ro`, joins each cutoff/event to the ledger resultHash and validates stored result JSON with the canonical domain validator. BUY eventId `e5928068-29c4-5554-9469-80e72628afdf` binds resultHash `dd42449e7c5586bbed1f5b95ea950677ca0e26824b456d0f9492a2ebdaddbd99`. The SELL and risk identities and all four result hashes are retained in that file. API/browser presence, channel DELIVERED and human acknowledgement are separate claims; the channel failure is not erased by the visible page.

The separate `r13-live-stream.spec.ts` real browser journey also passes: remain on the alerts page without manual refresh, receive BUY, disconnect the browser while SELL is generated, reconnect and receive SELL, then receive RISK_ALERT. Acknowledge all and verify inventory100. `stream-evidence.json` and `stream.png` preserve this second unseeded ordinary/public/production-composition run. Browser-offline simulation is not a real supplier outage; IN_APP failures still exist independently of automatic page refresh.

## 4. Confirmed residual findings and minimum revalidation

### N01 · P1 · Mandatory IN_APP rejects Schema3 events

Actual browser SQLite has eight IN_APP attempts: all CHANNEL_FAILURE, BUY ultimately FAILED on attempt4; SELL and risk remain RETRY_PENDING at shutdown. `InAppChannel.deliver` calls `_require_event`, which checks `type(event) is AlertEvent` and rejects `ExplicitAlertEvent`. The dispatcher converts the exception into a retryable failure. Independent production-pipeline tests reproduce this for BUY, SELL and RISK_ALERT: three failures against the required DELIVERED outcome.

Impact: durable reminders can be read through the API and direct committed-event publication, but the mandatory delivery consumer never succeeds. `publicActivationAvailable=true`, `isolatedTrustedReviewOnly=false`, `pendingRequirements=[]` accurately describe the current API response, not a verified all-consumers capability. This violates the R08 E06/E09/E10 readiness contract.

Minimum repair: explicitly support the versioned event union in required channel validation and payload handling, preserve legacy validation and pure-risk quantity=null, and decide capability availability using the actual supported consumers. Do not merely relabel failures as success. Re-run `test_r13_channel_acceptance.py`, existing delivery/transport regressions and the full browser journey; independently inspect IN_APP attempts and persisted event identities.

### N02 · P1 · Ordinary logical correction cannot complete review (F08 remains open)

The new actual-browser correction test starts with the unchanged literal source and publicly reviewed active version2. Price980→981 and BUY quantity100→200 save as versions3/4, preserve source, change contentHash, reset reviewId/canActivate and successfully complete new review. Reusing the original review for each successor returns409 and leaves version2 active.

Changing `rules[0].condition` ALL→ANY creates version5, but `UNMAPPED_PLAN_FIELD` at `rules[0].condition.type` has only `REPLACED_BY_REVIEWED_CONTENT`. Its checkbox is disabled and the ordinary form cannot complete review. `ExplicitPlanSupplementForm.vue:148,161,200` updates the selected STRUCTURE binding while the corresponding scalar `.type` binding is not updated; server reconciliation removes its now-invalid old binding. This is a confirmed capability failure with safe rejection, not an activation bypass.

Also, `editableBindings` at line48 permits only SOURCE origins. After each correction the field is USER_SUPPLEMENT and disappears from ordinary editable choices, so a second correction of that price/quantity/logic is unavailable. The final browser test preserves four failing assertions (one unreviewable logical edit and three missing editable fields). Evidence: `corrections.log`, `corrections-evidence.json`, `corrections.png` and `web/tests/e2e/r13-corrections.spec.ts`.

Minimum repair: update a logical operator and all required value/structure bindings as one human-supplement edit; retain both original source and changed-content provenance; allow current supported USER_SUPPLEMENT fields to be edited again. Re-run sequential price/quantity/logic edits, a second edit of each, stale-review rejection, current re-review and public activation. A user-approved ANY plan is deliberately changed scope and must never be counted as passing the original ALL oracle.

### N03 · P2 · Responsive detail-page regression

At viewport320 and 200% text, the existing symbol-detail test measures scrollWidth412 > clientWidth320. An independent repeat reproduces this, and the screenshot visibly clips the date controls. Later widths and the concluding axe assertion in that case are not reached. Impact is ordinary review usability at that tested layout; it is not a trading-rule defect. Minimum repair: constrain the offending detail controls/layout and re-run all four widths and accessibility checks without reducing thresholds.

### N04 · P2 · Existing browser gate fixtures/lifecycle audit need repair

Four dashboard cases fail because the newly required `/api/v1/plan-versions?offset=0&limit=100&status=ACTIVE` is unhandled by their Vite/API fixture and returns404. The position-command case has stale inventory/manual-risk fixture coverage and a global `role=alert` selector matching two unrelated errors. The real isolated literal page does not exhibit those mocked-API404s. Preserve the assertions and update complete fixture contracts/scoped expectations; do not suppress console errors.

The installed-process restart case reaches the restarted typed empty-database response, then fails its console audit with ERR_CONNECTION_REFUSED while the page remains open through intentional server downtime; temporary-directory cleanup also reports Windows EPERM. A repeat reproduces both. This does not prove active-plan restart failure, nor does it provide a passed installed-process gate. Separate intended offline transitions from unexpected requests and correct test-owned cleanup. The EPERM is an observed OS error; no automatic-approval rejection reason was supplied, and no cleanup escalation or bypass was attempted.

## 5. Verification ledger

Exact commands, exit codes, elapsed times and evidence filenames are recorded in `remediation/evidence/R13/commands.json`. Full-backend final status is recorded in `backend-result.json` and `backend.xml`. The full run selected every existing offline backend case using `-m 'not live'`, including capacity and traced-memory gates, and completed with 2591 passed, 1 skipped, 4 deselected and 1 existing Starlette deprecation warning in 2328.09s (2330.0623207s command elapsed). The sole skip requires POSIX ownership semantics on this Windows host; the four deselections are marked real-provider cases. No thresholds, assertions, defaults or skips were weakened.

Frontend baseline gates: 642 tests in45 files pass; type-check and build pass. The existing full26-case browser suite returns19 passed/7 failed. Its literal SQLite journey passes. Added AI-fault browser journey passes six fault variants after real ordinary activation. Added correction journey fails as N02. R13 numeric/lifecycle tests and three deliberately unsatisfied delivery regressions are reported separately from the original full collection; new files were added after that collection began.

| Final verification scope | Result | Command elapsed seconds |
| --- | --- | --- |
| Original complete offline backend | 2591 passed / 1 platform skip / 4 live deselected; exit0 | 2330.0623207 |
| Original frontend unit suite | 45 files / 642 passed; exit0 | 6.6407936 |
| Frontend type-check / production build | Both passed; exit0 | 4.2594451 / 1.3590101 |
| Original complete browser suite | 19 passed / 7 failed; exit1 | 83.1434259 |
| New R13 numeric, incomplete-bar, lifecycle and delivery regressions | 37 passed / 3 failed (N01); exit1 | 111.4283168 |
| New ordinary correction browser probe | 1 failed, four assertions (N02); exit1 | 10.3746759 |
| New AI fault browser probe | 1 passed, six variants; exit0 | 7.0887846 |
| New automatic reminder/reconnect browser probe | 1 passed; exit0 | 37.7905102 |
| Independent repeat of three original browser failures | 3 failed (N03/N04); exit1 | 10.2742269 |
| Final type-check with all new browser files | Passed; exit0 | 3.8381399 |
| Ruff on the three new Python files | Passed; exit0 | Not independently recorded |

The final type-check initially detected an unused local binding in the new stream probe; removing that unused read changed no behavior, and the rerun above passed. Final protection verification matches all16 pre-existing file hashes. The original browser and new acceptance failures remain visible; this report does not claim a green repository.

Harness development failures are not product findings: initial correction locator exact-label matching/timeouts were corrected using the actual select control; one added wait incorrectly assumed reviewed-policy fields disappeared before review; the AI-fault probe initially used an incorrect response property before switching to documented `draftPlanJson`; an initial S03 recovery subprobe used a mutable fake historical tape and correctly failed recovery. S03 was separated from restart and re-run with its own intended assertion; existing rebuilt-service dedup tests retain the restart requirement. An unsupported screenshot CLI flag was replaced by the isolated diagnostic Playwright config. These attempts never changed product behavior or acceptance thresholds. Logs retained where available; final reproducible probes and final outcomes control the conclusions.

OpenAPI expectation remains exactly50 paths=35 live+15 backtest and SHA-256 `1aed810d751d7c1dee623b1eb6afb7f2538928c8ea091bdf79027dd34e58951a`. No expected snapshot or specification value was edited. Schema1/2 and historical extraction prompts v1–v4 remain unchanged. The 20-case semantic-v2 corpus is case-specific simulated-provider evidence, not actual AI accuracy; the withdrawn keyword20/20 claim is not reinstated.

Authored documentation and test-source whitespace checks pass. The all-artifact diff check reports whitespace emitted by test runners inside raw logs, JUnit failures and captured error contexts; these verbatim evidence files are preserved. `format-check.json` records both scopes and the nonzero raw-artifact result.

## 6. Remaining real-world boundary and handoff

NOT_RUN: paid/real AI conversion of representative explicit, ambiguous and unsupported sources; real market SDK authentication/permission/quota/time-label verification for this revision; fresh completed-bar monitoring in an actual market window; naturally observed buy/sell/risk cases; real disconnect/recovery and user-visible receipt under those conditions. External channels and trading were not called. Existing historical supplier evidence is not fresh R13 evidence.

After N01/N02 and required gate failures are repaired, repeat their independent regressions and the applicable offline gates. A future R14 proposal must name provider/model, physical requests including retries, cost/quota caps, symbols/endpoints, duration/market window, temporary database, reviewed test plan and allowed notification channels. Unobserved branches stay NOT_RUN. Only the coordinator may arrange follow-up; this task creates no successor and sends one final authorized handoff after all writes, commit and readback.
