# Backtest functional acceptance — 2026-10-18

Chinese review copy: [2026-10-18-backtest-functional-acceptance.zh-CN.md](2026-10-18-backtest-functional-acceptance.zh-CN.md).

## BA-01 — Conclusion and baseline

**Functional acceptance is complete within the agreed scope.** The implementation baseline is `7046d2e2f7eda8cb61127921a3a8da20ec3fc8ca`, merged into `main` and verified against GitHub. This record consolidates existing executed evidence; this documentation update does not rerun AI extraction, replay, browser checks or test suites. It does not certify arbitrary source interpretation, investment returns, deployment or unmeasured capacity.

The current workflow is **prepare one original at a time, then combine reviewed plans for one continuous backtest**. The plan count is not fixed at four; composition accepts 1–256 reviewed plans under existing limits. Older records describing batch preparation, a whole-rule cancellation in the fourth source or unsupported holding-scoped execution are historical. The current corrected chain and execution evidence are [CR-V01–CR-V05](2026-10-18-cohort-risk-execution.md); existing frozen results remain unchanged.

## BA-02 — Completed scope

| ID | Capability accepted | Evidence |
| --- | --- | --- |
| BA-S01 | One-source preparation without a complete/update selector; extract explicit effective trading dates and ask about missing/ambiguous dates before extraction. Authoring and historical-availability times are optional. | [Preflight](2026-10-16-preparation-preflight.md), [single-plan library](2026-10-16-single-plan-library.md), [unified preparation](2026-10-16-unified-preparation.md) |
| BA-S02 | Successors use the exact reviewed predecessor; preserve unmentioned rules and propose source-backed retention, modification, addition and cancellation. Bounded repair, request/output budgets and processing-error classification are implemented. Approval remains explicit. | [Generic inheritance](2026-10-17-generic-inheritance.md), [source confirmations](2026-10-16-source-confirmations.md), CR-V01–CR-V02 |
| BA-S03 | Compose reviewed plans by effective date, retain one account across plan switches, freeze input/market evidence and admit the verified daily-price basis. `POSITION_LIMIT_ONLY` applies the position cap without a cash-budget restriction. | [Daily basis](2026-10-17-daily-basis.md), CR-V04, RP-V01–RP-V20 in the [verification history](monitor-loop-backtest.md) |
| BA-S04 | Keep inherited protection for old holdings when new entries are excluded. Evaluate and execute by matching lots, preserve pending confirmation across versions and apply T+1, exact allocations and cost accounting. | CR-V01–CR-V03 |
| BA-S05 | Results show each plan's non-execution reasons, distinguish unmet market conditions, unquantified conditions and extraction/validation problems, and compare actual prices with requirements. Full rule comparisons include holding scope. | CR-V04–CR-V05 |
| BA-S06 | The result header shows total, realized and floating PnL plus the backtest end date. Zero and unknown remain distinct; no principal return percentage is required. | [PS-V01–PS-V03](2026-10-18-result-profit-summary.md) |

## BA-03 — Actual sources and continuous replay

The four originals are the `.txt` files from `data/research/shengxin-plan-extraction-20261010`; `plans.json` and `entry-fields.json` are not plan inputs. Confirmed effective dates are 2026-09-24, 2026-09-28, 2026-09-30 and 2026-10-09. The source-defined maximum is 300 shares; the separately confirmed suspension policy is `RESUME_FIRST_CLOSE`. Later holdings descriptions do not reset the account. These are this sample's facts, not defaults for future plans.

| Item | Verified result |
| --- | --- |
| Current run | `9050185da63d7961aa29228542fa024d127ac4d754af10e3066cbc26e09abeb2` |
| Report | `935be980b2d0e78ee5386b196f1bc4bea6fc3af88a4b306b9cde92eb9bf251df` |
| Replay | 1468 evaluations, 2961 audit events, 3 version replacements, 0 intents, 0 fills |
| Review | All 4 policies passed; no holding-scope, lot-processing or change-processing blocker |
| Fourth plan | Old 25.99 exit retained for holdings acquired before 2026-10-09; newer purchases excluded. This is `MODIFY`, not `REVOKE`. |
| Result header | Total/realized/floating PnL each 0.00 yuan; end date 2026-10-09; evidence cutoff 2026-10-09 23:59:59 Asia/Shanghai |

The sample's numeric entry prerequisites fail independently of qualitative unknowns. CR-V04 lists each plan's prices and requirements; source 2 cancels the old BUY and grants no replacement direct buy authority. Zero fills do not prove that exits occurred. Separate deterministic production-path mixed-lot tests prove old-only sales, retained new holdings, pending-confirmation continuity and exact costs (CR-V03).

## BA-04 — Verification evidence

| Check | Recorded outcome |
| --- | --- |
| Backend unit suite | 3328 passed |
| Selected related integration cases | All 656 cases passed across the recorded runs; the final 46 rechecks are not an additional 46 distinct cases |
| Latest full frontend suite | 71 files, 1079 tests passed after the profit-summary change |
| Static/contract checks | Type checking, production build, both generated-contract checks, targeted Ruff and whitespace checks passed |
| Actual browser | Corrected four-plan rule comparisons, scope and price diagnostics verified; profit summary verified at 1440 × 1000 and 390 × 844 without horizontal overflow or application console errors |
| Live AI | Authorized DeepSeek `api.deepseek.com` / `deepseek-flash` calls and captured-response regressions cover actual sources and differently worded cases; correction/reviewer assistance is disclosed in GI-V01–GI-V03 and CR-V02 |

These results come from [CR-V05](2026-10-18-cohort-risk-execution.md#cr-v05--result-page-and-validation) and [PS-V02–PS-V03](2026-10-18-result-profit-summary.md). They do not mean that the entire backend integration suite or a new capacity campaign completed on the final version. Historical Windows 600/600-second load checks remain dated evidence in RP-V19/MV43, not a new certification for this baseline.

## BA-05 — Retained limits

- **Source semantics:** qualitative rebound, volume, retest/hold and index-relative-strength descriptions without executable thresholds remain unknown. The system shows these separately and does not authorize trades from unknown conditions. Reviewed predecessor inheritance and automatic repair do not replace semantic review or guarantee first-call interpretation of arbitrary wording. Sources 3 and 4 needed reviewer-guided corrections during the recorded generic verification.
- **Zero-fill sample:** the actual chain validates review, continuity and diagnostics, not observed actual-sample buy/sell fills or positive returns. Deterministic execution tests provide the separate fill evidence. No new-position stop is invented where the fourth source provides none.
- **Capacity and regression scope:** the latest broad integration invocation was stopped during the legacy ten-symbol × 252-day capacity workload. No thresholds were lowered and no capacity pass is claimed. The selected related integration cases passed; full integration/capacity recertification remains separate verification work.
- **Data and assumptions:** this run reused frozen historical market data, not a new live-provider certification. Two midnight evaluations retained `PRICE_BASIS_UNVERIFIED`; trading-session price-basis checks succeeded. Preloaded plans without declared availability use the disclosed effective-day 09:30 opening assumption. `POSITION_LIMIT_ONLY` does not model capital constraints or provide principal returns. Missing/stale evidence remains visible.
- **Operating boundary:** one unfinished operation, same-process owned threads, existing finite budgets and latest-30 result retention remain. A bounded concurrent read can return 503 and need retry. This acceptance does not add broker execution, unrestricted concurrency, strong process isolation or deployment guarantees. Existing Starlette/httpx deprecation and isolated-test router warnings remain recorded.

## BA-06 — Task closure

The original RP-T01–RP-T20 repair tasks and the delivered preparation, inheritance, price-basis, diagnostics, comparisons, cohort exits and profit-summary increments are **complete within BA-02's scope**. BA-05 records retained limits, not silently completed guarantees or new implementation tasks. The current [task status](../../tasks/todo.md) and [repair plan](../../tasks/plan.md) link here; their dated progress entries and earlier failed/superseded evidence are preserved. New requirements or recertification work need their own scope and evidence.
