# C1 SDK call boundary verification

## SCBV-01 Status and scope

Status: **REVIEWED / approved for local commit**.

The coordinator released the source freeze after the baseline full run and authorized implementation of the [reviewed boundary contract](2026-09-27-c1-sdk-call-boundary-contract.md). The two initial independent Sol rounds approved the design only. The subsequent independent code review found a P2; after repair, independent re-review confirmed no remaining source P1/P2. This report distinguishes author runs from reviewer runs and does not claim a passing full repository suite. The coordinator confirmed paired-document consistency and authorized only the 10-file local commit.

The resolver completes real certification-wrapper preparation and resolves the inner SDK callable before the per-invocation final guard. It uses nominal type recognition, no optional dynamic-attribute protocol discovery, and no shared mutable hook. Private callback arguments are consumed locally. The common module imports only the standard library; the existing sentinel class and controller remain unchanged.

Included paths are the two stock minute proof endpoints, DAILY_BARS, DAILY_LIMITS, INDEX_DAILY, and INDEX_REALTIME_MINUTES. Final production guards recheck time after authority reads, including the original legacy certification bounds and the realtime index's strict semantic expiry. STOCK semantic mode does not acquire legacy expiry rules. Ordinary calls without the optional hook retain their existing wrapper path.

## SCBV-02 Exact file ownership

This slice owns exactly these **10 files**:

| File | Change |
| --- | --- |
| `src/trade_plan_monitor/market_data/sdk_call_boundary.py` | New nominal resolver contract and callable validation |
| `src/trade_plan_monitor/market_data/tushare.py` | Prepare stock permission calls before final guard; preserve ordinary paths |
| `src/trade_plan_monitor/market_index/tushare.py` | Prepare daily/realtime index permission calls before final guard/S |
| `src/trade_plan_monitor/runtime/production.py` | Certified resolver implementation and final same-time mode/window checks |
| `tests/unit/test_sdk_call_boundary.py` | 73 offline protocol/provider cases |
| `tests/integration/test_production_sdk_call_boundary.py` | 49 owner/controller/persistence cases |
| `docs/verification/2026-09-27-c1-sdk-call-boundary-contract.md` | English contract and design-review record |
| `docs/verification/2026-09-27-c1-sdk-call-boundary-contract.zh-CN.md` | Matching Chinese contract |
| `docs/verification/2026-09-27-c1-sdk-call-boundary-verification.md` | English implementation verification |
| `docs/verification/2026-09-27-c1-sdk-call-boundary-verification.zh-CN.md` | Matching Chinese verification |

No existing test assertions were removed, weakened, skipped, or marked xfail. Other working-tree changes, including position/R13/R14/R17 fixture alignment and A07 startup-minute coverage, belong to other work. They were not edited, staged, or included in this slice's test commands. `tushare_client.py` and `request_control.py` are unchanged.

## SCBV-03 RED to GREEN evidence

| Stage | Observed result |
| --- | --- |
| PB01 before production changes | **2 failed**: both real-wrapper stock minute cases entered the SDK instead of raising when certification advanced the fake clock from 14 to 16 seconds |
| Nominal resolver and provider ordering implemented | PB01 plus existing daily/minute/index parser and transport selection: **364 passed** |
| Realtime index final-expiry cases before time-guard fix | **2 failed, 20 passed**: expiry at or before final S reached the SDK and failed only afterward, instead of returning DEFERRED before SDK entry |
| Legacy stock expiry cases before time-guard fix | **2 failed, 4 passed**: DAILY_BARS and DAILY_LIMITS similarly failed after entry; legacy equality and STOCK semantic compatibility controls passed |
| New boundary files before the code-review P2 | **114 passed**: 73 unit and 41 integration cases |
| Pre-P2 historical adjacent provider/transport/ordinary-path regression | **471 passed** across 8 existing unit files |
| Pre-P2 historical adjacent production permission/certification regression | **310 passed** across 11 existing integration files |
| Author post-P2 boundary rerun (A1) | **122 passed**: 73 unit and 49 integration cases |
| Author post-P2 affected production rerun (A2) | **178 passed** across 5 existing integration files |
| Independent post-P2 code-review rerun (I1), relayed by coordinator | **146 passed, 1 warning in 45.92s**: the 122 boundary cases plus 24 existing realtime index cases |

The **114/471/310** groups are historical pre-P2 evidence, totaling **895 passed across 21 files at that earlier revision**; they are not final acceptance of the P2 repair. Post-P2 author runs A1/A2 total **300 passed across 7 files**. Independent I1 overlaps A1 entirely and A2 in the 24 realtime index cases. Do not add I1 to A1/A2 or add post-P2 runs to the historical 895 as distinct tests. Commands and file selections are identified in SCBV-05. Integration groups emitted the existing Starlette/httpx deprecation warning. Ruff passed for the four source files and two new tests; the two P2-modified files passed Ruff again. Scoped diff/whitespace and bilingual structure checks passed.

Hash-stability statements apply only within the corresponding revision's verification interval. Source/tests did change between the historical 114/895 runs and the P2 repair. After the author's post-P2 A1/A2 runs, no source/test edits were made during report reconciliation; independent I1 concerns that repaired revision. This is not a claim of unchanged hashes across the P2 modification.

Fixture-construction corrections made while authoring tests are not counted as behavioral RED evidence. Earlier full-suite results or prior boundary-freeze counts are not substituted for the new tests above.

## SCBV-04 PB01–PB13 evidence map

| ID | Local evidence |
| --- | --- |
| PB01 | `test_pb01_real_wrapper_cannot_enter_at_16_seconds_after_guard_at_14`, both stock minute endpoints |
| PB02 | `test_all_proofs_resolve_and_certify_before_final_guard`: legal certification/resolution delays, exact trace, one S and matching evidence |
| PB03 | Same six-endpoint matrix advances time in dynamic endpoint resolution; expired admission makes zero SDK calls |
| PB04 | `test_realtime_index_final_s_rechecks_expiry_after_authority_io` and `test_stock_final_time_preserves_legacy_and_semantic_rules`: strict index expiry, inclusive legacy equality, expiry crossing and rollback below observed_at |
| PB05 | STOCK semantic cases in the stock final-time matrix remain successful beyond the legacy evidence expiry |
| PB06 | Real-wrapper production matrix covers legal delay, expiry, epoch revocation, market collision, stop and configuration change for four owner paths; the drain tests cover DAILY_BARS cancellation during certification. `test_final_authority_io_rechecks_memory_fences_before_sdk` adds generation/admission revocation inside final authority IO after wrapper preparation for all four owners |
| PB07 | Six-endpoint sentinel identity matrix plus real controller/persisted-state checks; cancel/timeout drain tests distinguish a late sentinel from previously recorded timeout backoff |
| PB08 | Dynamic fake SDK rejects any non-operation lookup. Installed DataApi lookup tracing permits only the actual operation and asserts exact endpoint kwargs |
| PB09 | Real certification wrapper around installed default/direct query routes reaches the strict stock minute parser through offline transport substitutes |
| PB10 | Concurrent and nested provider calls retain separate hooks/S; nested nominal wrappers finish all checks before the guard; no callable preparation is shared |
| PB11 | Stock minute S/latest and R-S boundary cases; real DAILY_BARS owner cancellation/timeout during certification or SDK execution retains the permission block, releases the maintenance lock and drains the physical slot before subsequent work |
| PB12 | Real wrappers, real owners/controllers and temporary SQLite for DAILY_BARS, DAILY_LIMITS, INDEX_DAILY and INDEX_REALTIME_MINUTES; reopened persisted reservation checks, no supplier backoff for local rejection, once-only existing rotation callbacks and zero worker SQL |
| PB13 | Ordinary daily/history kwargs and official rows, ordinary wrapper rejection, and adjacent provider/client/index/historical regressions |

The stock minute owner wiring is still a separate slice: these tests cover its provider proof boundary, not a newly implemented stock minute owner. Existing INDEX_REALTIME_MINUTES rotation behavior is preserved rather than adding a new reservation callback.

## SCBV-05 Reproduction

Run from `trade-plan-monitor/` using the existing virtual environment. These reproducible selections exclude live services, the separate A07 test, and unrelated fixture-alignment work. A1/A2 are the author's post-P2 selections; I1 is the independent review selection reported by the coordinator. Historical 114/895 counts belong to the pre-P2 source/test revision and cannot be reproduced by treating the updated files as that old revision.

```powershell
# A1: author post-P2 boundary selection, 122 passed
.venv/Scripts/python -m pytest tests/unit/test_sdk_call_boundary.py tests/integration/test_production_sdk_call_boundary.py -q --tb=short
# H1: historical pre-P2 provider/transport selection, 471 passed
.venv/Scripts/python -m pytest tests/unit/test_stock_minute_permission_proofs.py tests/unit/test_minute_permission_transport.py tests/unit/test_daily_permission_proofs.py tests/unit/test_realtime_index_permission_parser.py tests/unit/test_tushare_client.py tests/unit/test_tushare_market_index.py tests/unit/test_tushare_permission_probe.py tests/unit/test_tushare_historical.py -q --tb=short
# H2: historical pre-P2 production selection, 310 passed
.venv/Scripts/python -m pytest tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_daily_bar_permission_preparation.py tests/integration/test_daily_bar_permission_demand.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/integration/test_permission_weekend_candidate_consistency.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_index_historical_permission_probe.py tests/integration/test_production_certification_gate.py -q --tb=short
# A2: author post-P2 affected production selection, 178 passed
.venv/Scripts/python -m pytest tests/integration/test_production_index_realtime_permission_probe.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_daily_bar_permission_maintenance.py tests/integration/test_production_certification_gate.py -q --tb=short
# I1: independent post-P2 review selection, 146 passed
.venv/Scripts/python -m pytest tests/unit/test_sdk_call_boundary.py tests/integration/test_production_sdk_call_boundary.py tests/integration/test_production_index_realtime_permission_probe.py -q --tb=short
.venv/Scripts/python -m ruff check src/trade_plan_monitor/market_data/sdk_call_boundary.py src/trade_plan_monitor/market_data/tushare.py src/trade_plan_monitor/market_index/tushare.py src/trade_plan_monitor/runtime/production.py tests/unit/test_sdk_call_boundary.py tests/integration/test_production_sdk_call_boundary.py
git diff --check -- src/trade_plan_monitor/market_data/tushare.py src/trade_plan_monitor/market_index/tushare.py src/trade_plan_monitor/runtime/production.py
```

## SCBV-06 Remaining boundaries and handoff

S is a call-site marker before the prepared inner SDK callable, not socket transmission time. Post-S work is limited to pure value/in-memory checks and invocation; operating-system scheduling and work inside the SDK remain possible. No forced interruption or atomic observation of external state is claimed. Response snapshot validation and controller clearing remain separate operations.

INDEX_HISTORICAL_MINUTES still lacks the final provider seam. Calendar permission, historical stock and ordinary business paths have no new final-boundary acceptance. Their passing compatibility tests do not close that gap. No scheduler or A07 production change is included.

The coordinator's pre-change full suite reported **18 failed, 4778 passed, 1 skipped, 4 deselected**. Those position/R13/R14/R17 failures are a separate investigation; this slice does not claim a green full suite. The separate A07 expected RED is not part of the 895 passing tests.

The coordinator authorized a local commit of exactly the 10 owned files after independent review and paired-document reconciliation. After that commit, release the `production.py` writer for the next owner. This slice does not close INDEX_HISTORICAL_MINUTES, stock minute owner wiring, A07, C1, or C3. No push, deployment, real provider call, or user-database access occurred.

## SCBV-07 Independent code-review P2 and repair

The coordinator relayed the independent Sol code review: its initial **114 passed** run did not cover revocation inside the final authority read. The reviewer reproduced one SDK call after admission was revoked during the final `_index_certification_current()` call. `_realtime_index_probe_current()` had already checked generation/admission before that read; response validation failed afterward, but could not prevent the SDK call.

The new eight-case matrix injects revocation only after real wrapper preparation has finished, inside the owner's final certification read. Before repair it produced **2 failed, 6 passed, 41 deselected**: realtime index failed for both generation and admission, while DAILY_BARS, DAILY_LIMITS and INDEX_DAILY passed both controls. Each failed case observed exactly one SDK call instead of zero.

The production repair only moves the existing realtime index certification check before its existing generation/admission checks. It introduces no new predicates and leaves historical index code outside the agreed scope. Targeted GREEN: **8 passed, 41 deselected**. Rejected calls retain their durable reservation and add no supplier backoff/cooldown. The other included owners already order these two fences after certification; their unchanged controls remain passing. Stock minute owner wiring remains separate.

Source/tests were declared stable after this repair and targeted GREEN. The coordinator subsequently relayed independent re-review: I1 produced **146 passed, 1 warning in 45.92s**; a separate inline rerun of the original P2 scenario produced **SDK calls=0 / DEFERRED**. The reviewer found no remaining P1/P2, confirmed Ruff/diff checks and source/test hash stability over that repaired-revision rerun, and accepted the paired documents' distinction between pre- and post-P2 evidence. The P2 is independently confirmed fixed, and the coordinator authorized the 10-file local commit. This documentation-only reconciliation changes neither source nor tests.
