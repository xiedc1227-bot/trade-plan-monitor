# R13-N05 backtest reflow acceptance addendum

Date: 2026-09-13, Asia/Shanghai. Task `01a0990a-a495-7fd1-8819-60e2adf011ab`; coordinator `01a093fc-f8d3-73d1-b759-ad76c7451697`. This English file is canonical; `R13-N05-addendum.zh-CN.md` is the equivalent Chinese review copy.

## A1. Bounded decision

**N05 is CLOSED in the tested offline browser scope.** The final source at `a4984d7458183fdb4e44d25a74648d70ef4a2b84` passes the stable four-route × four-width × 200% text boundary gate and the complete 35-test Chromium suite. This addendum updates N05 only. The original [R13 reacceptance report](R13-reacceptance.md), [matrix](../../remediation/R13-reacceptance-matrix.md), and handoff retain their accurate historical **NOT PASSED** finding. The coordinator decides the combined C6 checkpoint. R14 real-provider/user-visible acceptance remains **NOT_RUN**.

No backtest capability, monitoring rule, business backend, real provider, paid AI or market request was added in N05.

## A2. Opposing red and green observations

| Observation | Actual result |
| --- | --- |
| Original R13 complete browser gate and bounded focused repeat at `c6bef15ec40c7853be06030efc0e6d80be4ee87e` | Layout gate failed; focused repeat 0/5. Stable document widths on `/backtests`, `/backtests/new`, `/backtests/data` and the result route were 338/476/617/411px at a 320px viewport. |
| Coordinator's later unchanged-source focused runs at the same commit | 1/1 and 3/3 passed. These observations remain valid, but did not capture per-route settled widths or computed text size. |
| N05's same-fixture diagnostic before CSS repair | Immediately after setting 200% root text, all four document widths were 320px; after `document.fonts.ready` and two animation frames they were 338/476/617/411px. The strengthened original gate then failed at 338px on `/backtests`. |
| N05 final diagnostic after CSS repair | All four settled document widths are 320px; no overflowing element without an intentional scrolling ancestor was measured. The final gate also checks computed root text size of 32px in the Chrome project. |

The immediate-versus-settled split explains how the old one-shot gate could report green while the rendered page was wider. The exact render frame of the coordinator's earlier green runs cannot be reconstructed; attributing those particular runs to this timing race is an inference from the reproduced split, not a captured fact. `openRoute` uses a new `page.goto` for every route, so text size is set anew; the test uses the same Vite development harness, Chrome project and fake API contract. The final gate first observes each route's actual grid styling, applies 200% text, waits for fonts and two render frames, asserts 32px computed root text, then keeps the original `scrollWidth <= clientWidth` boundary for all 16 combinations. No threshold, width, text scale, assertion or global retry was relaxed.

## A3. Minimal repair and visible behavior

The four backtest views and affected form/result descendants now use shrinkable grid columns. Native inputs/selects size inside their assigned track; long eyebrow and plan-version help text such as `canActivate=true` can wrap. At a viewport no wider than `30rem`, backtest-only nested horizontal padding is reduced so 200% text and controls retain usable line width. The labelled AppShell navigation and backtest tables keep their own horizontal scrolling. No global clipping, removed field, hidden content, reduced font or smaller control-height rule was introduced.

The [comparison](../../remediation/evidence/R13-N05/layout-comparison.json), [final measurements](../../remediation/evidence/R13-N05/final-layout-measurements.json), raw before/after diagnostic reporter records and four [final screenshots](../../remediation/evidence/R13-N05/final-layout-1.png) document the change. The diagnostic probe's successful execution alone is not counted as a passing layout assertion; the strengthened original gate is.

## A4. Final verification and limits

| Final scope | Actual result |
| --- | --- |
| `npm run test:e2e -- tests/e2e/backtests.spec.ts` | 5/5 passed: keyboard flows, serious axe checks, 16 responsive/200% combinations, diagnostic probe, request/DOM/polling/ECharts bounds. |
| `npm run test:e2e -- tests/e2e/backtests.spec.ts --grep "keeps 320/768/1024/1440" --repeat-each=3` after final readiness check | 3/3 passed; no Playwright retry was enabled. |
| Final `npm run test:e2e` | 35/35 passed in 4.2 minutes, exit 0. Includes literal ALL, corrections, automatic reminder recovery and ACTIVE/REPLACE/DISABLE/EXPIRE real local OS-process restart. |
| `npm run test -- --run`; `npm run type-check`; `npm run build` | 644/644 units across 45 files; type check and production build passed. |
| Backend, actual AI/market/window/channel, R14 | No backend source changed. The prior independent R13 backend result remains 2634 passed/1 Windows POSIX skip/4 live deselected; it was not rerun here. Real-provider and R14 checks remain NOT_RUN. |

The final browser run printed an existing Starlette/httpx deprecation warning and one Windows Python `ConnectionResetError` from an isolated test process after a local connection closed. Browser audits and the complete test command still passed; those stderr lines are not claimed as browser console errors or silently removed. They do not establish a backtest layout failure.

All 16 protected inputs match the prior protection manifest byte for byte, including 12 tracked user modifications and four R00 untracked files; the dashboard's original 09:35/10:35 two-bar, second `openPoints="1231.25"` hunk remains. The protected AppShell, market-index work, accessibility/config/specification changes, literal source and historical R13 records were not staged or edited. No reset, stash, branch switch, dependency install, production database/holding/order, external notification, push or publication occurred.
