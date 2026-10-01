# Interface design verification — 2026-10-01

## Scope and result

Presentation refinement of the installed monitor-contract `2` interface and shared compatibility components, against `UI01`–`UI08` in [the design contract](../specifications/monitoring/SPEC-interface-design.md). The inspected states have no remaining obvious actionable layout or interaction defect. Award recognition remains subjective.

The result uses warm ink, mineral text, amber actions, an original threshold mark, numbered navigation, and tabular figures. Monitoring facts, market context, actions, and diagnostics have distinct hierarchy. Routes, REST/WebSocket contracts, provider authority, monitoring rules, source dates, activation/review boundaries, and manual trading decisions remain unchanged.

## Eight-dimension review

| Dimension | Implementation and final check |
|---|---|
| Typography | Shared page introduction, responsive 30–44px titles, smaller supporting copy, and consistent numeric type; reviewed Chinese text and long diagnostics. |
| Whitespace | One shared page gutter, 4px spacing rhythm, aligned section dividers, controlled panel padding, and two-column desktop diagnostics. Removed duplicate page padding. |
| Visual hierarchy | Snapshot counts precede the workspace; wide layouts separate market and monitoring status; narrow layouts show status first. Empty plans have a clear next action. |
| Color | Semantic amber/green/red/cyan palette; status retains textual meaning. Automated WCAG 2.1 A/AA checks passed in the tested routes and states, including the v2 overview at 200% text. |
| Motion | Restrained 360ms entrance translation and 160ms control feedback; reduced-motion preference disables nonessential movement. Removed the opacity entrance that briefly reduced contrast. |
| Microinteractions | Clear selected navigation/index tabs, hover/press feedback, visible focus, Escape closes mobile navigation and restores toggle focus; the next Tab reaches the main action. |
| Responsive | Verified 320/768/1024/1440px and 100%/200% text with no page-level horizontal overflow. Tables retain local scrolling; chart containers contain canvas resizing. |
| Originality | Custom threshold mark, PLAN / MONITOR identity, numbered navigation, purposeful monitoring composition, and a custom empty-plan illustration; no copied assets or fabricated data. |

## Verification results

Run from `web/`:

| Check | Result |
|---|---|
| `npm run type-check` | Passed |
| `npm test -- --run` | Final pre-commit regression: 820 tests, 58 files passed |
| `npm run build` | Passed; installed assets refreshed |
| `npm run build:runtime-status-preview` | Passed |
| `npx playwright test tests/e2e/accessibility.spec.ts tests/e2e/dashboard.spec.ts tests/e2e/plans.spec.ts tests/e2e/alerts.spec.ts tests/e2e/backtests.spec.ts tests/e2e/interface-design.spec.ts` | Final pre-commit regression: 20 tests passed, 36.0s |
| `npx playwright test tests/e2e/runtime-status-sqlite.spec.ts tests/e2e/runtime-recovery.spec.ts` | 2 tests passed, approximately 4.4 minutes |
| `git diff --check` | Passed |

The two real-runtime checks used an isolated owned Python runtime and SQLite. They covered reminder source dates, an actual coordinator stall, and restart recovery through the normal installed entry. They ran before the follow-up presentation and plan-startup changes; the final unit, type, build, and 20-test browser checks cover those refinements. Existing thresholds and assertions were preserved; title and palette expectations were updated to the intended presentation. The new v2 check covers empty/active plans, all four breakpoints, 200% text, full WCAG A/AA checks, keyboard focus, and reduced motion.

## Visual evidence

Reviewed the production bundle served by the existing local service at `http://127.0.0.1:8765/`: dashboard, plans, alerts, system, and backtests. Saved browser captures in [assets/interface-design](assets/interface-design/):

- [Desktop dashboard](assets/interface-design/dashboard-desktop.jpg)
- [Mobile dashboard](assets/interface-design/dashboard-mobile.jpg)
- [Mobile lower sections](assets/interface-design/dashboard-mobile-market.jpg)
- [Tablet status and market detail](assets/interface-design/dashboard-tablet.jpg)
- [Plan workspace](assets/interface-design/plans-desktop.jpg)
- [Alert center](assets/interface-design/alerts-desktop.jpg)
- [System diagnostics](assets/interface-design/system-desktop.jpg)
- [Backtest workspace](assets/interface-design/backtests-desktop.jpg)

## Iterations and boundaries

Follow-up panel alignment: the wide workspace uses shared grid rows so the monitoring panel begins at the index surface, below its heading. This follows the [MDN subgrid guidance](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Grid_layout/Subgrid), avoiding a fixed offset when text wraps. Narrow layouts retain status-first stacking. `interface-design.spec.ts` passed both checks in 4.8s, including empty/active plans, 320/768/1024/1440px, 100%/200% text, less than 1px difference between the wide panel top edges, and WCAG A/AA checks. `npm run build` passed. Updated screenshot: [aligned panels](assets/interface-design/dashboard-aligned.jpg).

Follow-up index selector scrolling: removed the unnecessary `overflow-x: auto` that also made vertical overflow `auto`. The four-column/two-column selector grid needs no internal scroll container; long labels and values can wrap. A new browser regression checks focus, held-button feedback, no vertical scroll container, and successful index selection at 320px/1440px. The regression rejected the previous vertical overflow setting and passed after the fix. The dashboard and interface browser suites passed 7 tests in 8.4s; type check and production build passed. Screenshot: [index selector without internal scrolling](assets/interface-design/dashboard-selector-no-scroll.jpg).

Follow-up turnover actions: moved the trend-error copy and retry button beside the full-day turnover estimate. A conditional presentation class adds the action column only when the slot exists; below 40rem the actions stack below the figures. Related unit checks passed 23 tests and dashboard/interface browser checks passed 7 tests in 8.1s; type check, production build, and diff check passed. The live error-state view confirmed a 24px gap to the right of the estimate and matching vertical bounds. Screenshot: [turnover actions on the right](assets/interface-design/dashboard-turnover-actions.jpg).

Follow-up chart border: removed the trend card's state-colored left border and its health-specific overrides. The surrounding index surface now supplies the same neutral border on all four sides, confirmed in the live browser. Status labels retain their existing semantics. The 21 market-index unit checks, production build, and diff check passed. Screenshot: [uniform chart border](assets/interface-design/dashboard-uniform-border.jpg).

Follow-up plan startup (`UI08`): render `PlanWorkbench` independently of the AI configuration request, with progress shown inside the provider panel. Early source input is editable and persists in the same editor when the request succeeds; configuration failure keeps the workspace and input visible. Submission remains blocked until an enabled configured provider is available, and the actual provider limit is rechecked without discarding early input. Regression assertions reproduced the previous missing workbench in pending/failure states. The related 37 unit tests, 3 plan browser journeys (7.8s), type check, production build, and diff check passed. The delayed-response browser check covered 1440px/320px and verified no automatic mutation; after improving screenshot framing it passed again in 2.1s. Screenshots: [configuration pending in the isolated browser](assets/interface-design/plans-config-loading.jpg), [installed local plan workspace](assets/interface-design/plans-immediate-live.jpg).

Corrected 320px/768px header overflow under 200% text, the root navigation's overly broad active styling, transient entrance contrast, repeated page gutters, competing plan headings, unclear empty-chart presentation, and narrow-screen monitoring priority. The final entry review also reproduced a missing first-load dashboard title: observing the route title as well as its path fixes startup without changing query-only focus behavior. The regression assertion failed before the fix and passed afterward. Then reran affected checks and the final regression batch.

The live local service had no active plans and no available current intraday index series. Screenshots show its actual stored point, original cutoff, unavailable-series explanation, and retry control; no decorative curve or replacement market data was introduced. Populated plans and chart series were separately checked with deterministic fixtures; reminder/source/recovery behavior was checked with the isolated real runtime. Visual screenshots are a point-in-time review, and automated axe checks do not replace a complete assistive-technology audit.

No new dependency, backend change, production plan submission, external AI request, or deployment was made for this design change. At the user's request, the Git handoff groups the work into workspace/market presentation and plan-startup experience commits, with paired design and verification documentation and saved screenshots. The pre-commit review found no required correctness, security, or performance change; the remote branch matched the local base before committing.
