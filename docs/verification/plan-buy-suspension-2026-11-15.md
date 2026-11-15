# Plan BUY suspension verification — 2026-11-15

## PBS-V01 — Candidate and verdict

**PASS for PBS engineering acceptance: PBS-A01–PBS-A12 and PBS-C01–PBS-C03.** Independent final A03 and A11 reviews passed. This does not approve deployment or actual monitoring readiness.

Source candidate: `1fe185470ec2f81f01a6c6c9ae289f3eea49598eae4b6cc0388c4e1b68c3ab41`; [29-file manifest](../../build/pbs/t12/final/manifest.json), anchored to `adc382184de9fb11583d858beae27382183570d9`. Candidate calculation is SHA256 of `json.dumps(manifest, sort_keys=True).encode()` with default separators and no newline. The five-file A11/UI candidate is `4c4860549ff50ca3d8e6d0a289a5b7796dce255069e66ecc4e29e67483d9c28d`; [A11 manifest](../../build/pbs/t12/a11/manifest.json). Report hashes are separate to avoid circular hashing. [Final handoff](../../build/pbs/t12/final/handoff.json) and [hashed evidence index](../../build/pbs/t12/final/evidence-index.json) bind the retained artifacts.

## PBS-V02 — Acceptance map

| ID | Result and evidence |
| --- | --- |
| PBS-A01 | PASS: T04/T08 coverage and source-bound rejection distinguish raw sources from explicit clarification; original 03/04 bytes are unchanged. |
| PBS-A02 | PASS: transition/data-adapter cases cover 2419/2420/2421, low-only breach, completed bars, interval and basis; actual A03 close 2430/low 2419 and close 2420 do not latch. |
| PBS-A03 | PASS: real SDK → committed SQL → runtime versus engineering guard plus existing confirmation/execution logic. Independent expected BUY quantities at 09:35/09:40/09:45/09:50 are 100/100/0/0 for closes 2430/2420/2419/2435. Future close 3000 cannot rewrite prior results; old immutable EVALUATION records are checked after the final step. Native preparation precedes same-bar BUY and invalidates READY without a fill. |
| PBS-A04 | PASS: state/recovery/activation cases cover rebound, day change, restart, ordinary copies, restore, correction and isolation; final browser preserves the original trigger after replacement. |
| PBS-A05 | PASS: T07/T08 pending/ready/first/second BUY, stale/direct request and commit-race checks; final runtime invalidates READY with quantity 0 and no SIMULATION, preserving completed holdings/consumption. |
| PBS-A06 | PASS: retained risk/notification cases and final browser comparison; page-triggered SELL simulates 100 shares while BUY stays latched. |
| PBS-A07 | PASS: recovery covers missing calendar/history/basis, resumption/correction/restart. Actual scheduler advances its own guard, yields to another active realtime request or real next deadline, and clears reservation on error/cancellation; serial ownership/join/fences remain. |
| PBS-A08 | PASS: exact receipt/activation/race cases and actual page requests. Save/review leave old active owner; exact activation switches versions. Before strategy start, no inherited guard proof; own 09:45→09:50 coverage binds new owner/source/content/review/revision and yields runtime BUY READY 100, with old trigger retained. No extra first-bar wait. |
| PBS-A09 | PASS: T09 read-only interception and final readiness API regression; GET acquires no data and transitions no guard. UNVERIFIED, health and BUY eligibility remain distinct. |
| PBS-A10 | PASS: T10 two-profile projections/round trips and unchanged historical goldens; unsupported frozen operations reject explicitly. Generated profile check passes. |
| PBS-A11 | PASS: final real browser journey, four states × four widths, exact request bindings, new-owner proof and normal cleanup; independent A11-R01–A11-R04 closed. |
| PBS-A12 | PASS: final scoped regression, UI/type/build/generated/quality gates below and independent review of frozen source/evidence. |

| Checkpoint | Verdict and retained independent evidence |
| --- | --- |
| PBS-C01 | PASS: T01–T04; [T02](../../build/pbs/t12/c01-t02/), [T03](../../build/pbs/t12/c01-t03/), [T04](../../build/pbs/t12/c01-t04/independent-evidence.json). |
| PBS-C02 | PASS: T05–T08; [final review](../../build/pbs/t12/c02-t08/final-review.json). Later scheduler correction separately accepted in [A03 review](../../build/pbs/t12/review-a03/scheduler-review-3.json). |
| PBS-C03 | PASS: T09–T12; [T09](../../build/pbs/t12/c03-t09/final-review.json), [T10](../../build/pbs/t12/c03-t10/final-review.json), [T11](../../build/pbs/t11/final/handoff.json), [final A11 review](../../build/pbs/t12/review-a11/final.md) and [verification](../../build/pbs/t12/review-a11/final06-verification.json). T09 fingerprint failures were closed by T10 without changing old goldens. |

## PBS-V03 — Commands and final results

| Gate | Artifact under `build/pbs/t12/` | Result |
| --- | --- | --- |
| Runtime/recovery/coordinator/admission/lifecycle | `a03/scheduler-final-v2.xml` | 126 PASS; 0 failure/error/skip |
| Required daily-plan/readiness plus isolation fixture | `required-final.xml` | 78 PASS = 70 required + 8 fixture; 0 failure/error/skip |
| Final fixture refresh | `a11/fixture-final-02.xml` | 8 PASS; overlaps previous 8 |
| Frontend on final UI | `a11/frontend-final.xml` | 1841 PASS / 103 files; 0 failure/error/skip |
| Final real browser | `a11/browser-final-06.log` | 1 PASS / 40.2 seconds |
| Type / generated / Ruff / whitespace | `a11/type-final-05.log`, `generated-check.log`, `ruff-final.log`, `final/diff-check.log` | PASS |
| Isolated Vite build | `a11/build.json`, `a11/build.log` | PASS / 76 files |

Exact commands and working directories are in [commands.json](../../build/pbs/t12/final/commands.json). Key commands from project root, except the final Node command from `web/`:

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_plan_buy_suspension_runtime.py tests/integration/test_plan_buy_suspension_recovery.py tests/unit/test_recovery_coordinator.py tests/unit/test_request_recovery_admission.py tests/integration/test_runtime_lifecycle.py --basetemp=.pytest_cache/pbs/t12/a03-14 --junitxml=build/pbs/t12/a03/scheduler-final-v2.xml -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_daily_plan_chain.py tests/integration/test_plan_readiness_api.py tests/browser/test_plan_buy_suspension_case.py -m "not live" --basetemp=.pytest_cache/pbs/t12/required-final --junitxml=build/pbs/t12/required-final.xml -q --tb=short
node node_modules/@playwright/test/cli.js test tests/e2e/plan-readiness.spec.ts --grep "PBS real" --output ../build/pbs/t12/a11/browser-final-06 --reporter=line
```

The 70 required cases ran on scheduler v2 and final UI bytes; subsequent changes touched browser observations/cleanup only, then refreshed the eight fixture cases and actual browser. Counts are not summed across overlapping or historical runs. The build uses existing Vite configuration, disables environment files, excludes only the packaging-copy hook and writes `build/pbs/t12/a11/build-1794751729181/dist`; Vue/contract plugins remain. Both shared asset directories retain their 68-file before/after/final hashes.

## PBS-V04 — Browser proof

[Final trace, 24 viewport screenshots, public journey and lifecycle](../../build/pbs/t12/a11/browser-final-06/) cover actual offline v13 extraction → clarification → save → review → activation → native breach → rebound → SELL → replacement. Initial extraction uses one provider double and the actual configured parser/lifecycle. Replacement is explicitly `HUMAN_SYNTHETIC`: the existing test endpoint supplies only an unreviewed candidate/source/map. Clarification, intent, save, review and activation then use actual page controls/public APIs; no authority is injected. It is not an automatic replacement extraction positive.

Clarification, latched guard, replacement form and review/activation actions each pass 320/768/1024/1440 × 900 checks: stable layout, no overflow, 44px controls, keyboard/label/disabled behavior and axe with zero violations. Final viewport captures preserve the header and show unobscured focus. Actual requests match saved source/content/coverage/review identities and before/after active pointers; the new guard has its own coverage and bindings. Clock traversal leaves the SPA and reopens the exact persisted version; continuous freshness during accelerated traversal is not claimed.

Independent trace inspection finds no failed HTTP status, external host, browser error or page error. Uvicorn's actual WebSocket set changes 1→0 before stop. Final order is `PAGE_CLOSING → SPA_TRANSPORTS_CLOSED → PAGE_CLOSED → BACKEND_STOPPING → BACKEND_STOPPED`: exit 0, no signal, lifespan closed, read owner 0, runtime STOPPED and no reset/error log. This proves the fixture's orderly shutdown, not arbitrary transport-abort resilience or a machine-wide process inventory.

## PBS-V05 — Corrections and deviations

Native scheduler self-yield prevented required guard acquisition; a dedicated pending check now distinguishes its own duty while retaining other realtime work and next-deadline priority. The previously unwired reservation is installed/cleared on normal/error/cancel paths. Red evidence is retained; final 126 cases and independent review pass. RR-PBS01 is synchronized in both runtime-recovery documents. One scoped CSS rule fixes 44px native checkbox labels; [UI review](../../build/pbs/t12/review-ui/code-review.json) passes. Failed browser trials remain diagnostics: replacement normalization stayed blocked, and abrupt-close cleanup failures were corrected through normal SPA departure and actual Uvicorn connection inspection without filtering logs or weakening exit checks. An existing Starlette deprecation warning remains.

[T10 build deviation](../../build/pbs/t10/final/build-deviation.json): its default build updated ignored shared asset directories via packaging copy. No reliable earlier backup exists; restoration is not claimed. T11/T12 isolated builds make no further shared change and do not undo that side effect.

## PBS-V06 — Protected data and boundaries

[Protected check](../../build/pbs/t12/final/protected-check.json) verifies seven unchanged inputs, including originals 03/04, historical identity goldens and prompts. No protected PMA history/tasks, frozen formats or originals were rewritten. Only fresh `.pytest_cache/pbs/t12/` databases were used. User database operations, real market/provider/notification calls and pushes are 0; real extraction budget is 0/48.

Original 03/04 obligations, F083, PMA-C05/C07/C08, actual installation/monitoring readiness and user database rollout remain open. Schema10 public frozen export/preparation/replay remains unsupported and rejects explicitly. PBS engineering acceptance grants no automatic bottom recognition, real trading or broader source acceptance. Coordinator maintains task/checkpoint status and commits; this writer does not commit or push.
