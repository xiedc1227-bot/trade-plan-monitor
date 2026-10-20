# Reviewed plan reuse

## PR-O01. Workbench source

Open **Backtests → New backtest → Reviewed workbench plans**. Select one exact reviewed version. It may be inactive; an unreviewed draft is unavailable. Selection does not call AI or start a run. Review the original text if needed.

Confirm the effective trading date, historical availability (optional; defaults to 09:30 on that date), information cutoff, initial account timestamp, inventory status and supporting evidence or explicit research assumption. These dates describe research assumptions, not proof that a plan was historically published. Unknown inventory remains unknown and blocks simulated trades; choose verified empty inventory only when supported. Known lots use CORE/TACTICAL buckets, 100-share quantities, optional cost in yuan, acquisition date and sellable quantity. Unknown facts stay blank. Funding uses `POSITION_LIMIT_ONLY`, without a cash budget or live inventory reads.

Confirm research context once, then set response, costs and optional end date and start the run. The existing automatic data preparation and monitoring loop are reused. `FOLLOW_REMINDERS` simulates eligible actions; `OBSERVE_ONLY` does not fill orders. Existing blockers and execution rules still apply. The `selectionId` link restores the frozen research context. Later workbench edits or activation changes do not alter it. If saving or submission has an uncertain outcome, use the displayed same-request retry and retain its key/body.

## PR-O02. Existing prepared plans and results

The secondary **Plan update timeline and source preparation** entry retains the existing library, original-text preparation, extraction/review, unfinished preparation recovery and continuous multi-plan replay. The current maximum is 256 chain entries. This increment supports one workbench version per run; mixed-source or multiple-workbench schedules are unavailable. The two plan stores retain their current authoring/review responsibilities.

Existing `preparationId` links and historical result links, details and exports remain usable. New workbench results identify the actual plan version/review and frozen research selection. Accepted runs own copied inputs; execution and result reads no longer require either source plan store. Current JSON/YAML plan import is removed: `POST /api/v1/plan-imports` returns 404, and its direct client/form is removed. Internal codecs and original-text preparation remain supported.

## PR-O03. Storage and operational boundary

On first preparation-store use, tagged schema 1 upgrades transactionally to 2 by adding only `backtest_plan_selection`. Existing preparation documents and idempotency receipts retain exact bytes. No production database is modified by the test suite. Older binaries reject this upgraded store; preserve a coherent database backup before a deployment that may require binary rollback. This change adds no monitoring/market/result SQL migration, provider, dependency, worker owner or concurrency limit.

New copied inputs use `monitor-loop-stored-input-v3`; their selection-bound input uses `workbench-loop-input-v1` and the existing `backtest-run-v5` execution formula. Existing input/report codecs, hashes, exports and prepared-chain semantics remain unchanged. See [design](../specifications/backtesting/SPEC-plan-reuse-unification.md) and [verification](../verification/2026-10-19-plan-reuse-unification.md) for the precise contract and executed checks.

## PR-O04. Reproducible browser verification

Browser tests use isolated Chrome for Testing `157.0.8103.6`, pinned in `web/test-browser.json`. This build includes Chromium's [completed no-store response fix](https://chromium-review.googlesource.com/c/chromium/src/+/8508456) at main revision `1712735`; the selected build is revision `1717349`. System Chrome `155.0.8059.80` can report a fully read response as `net::ERR_ABORTED`. Updating application request handling or filtering those events is unnecessary.

From the project root, prepare the test browser once, then run the checks:

```powershell
.venv/Scripts/python.exe scripts/setup_test_browser.py
npm --prefix web run test:e2e -- tests/e2e/streamCompletion.spec.ts
npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/monitor-loop-backtest.spec.ts
```

With Python on PATH, `npm --prefix web run setup:test-browser` is equivalent. The installer downloads the exact official artifact into the ignored `web/.test-browsers/157.0.8103.6/` cache and reuses a completed installation. It does not install/update system Chrome or download anything during ordinary test runs. A missing browser fails with the setup command; tests do not silently fall back to an affected browser. Chrome for Testing is a development verification prerequisite, not a product runtime dependency.

The existing Chrome project, viewports, assertions, 5-second expectation timeout and zero retries remain unchanged. A new regression requires 1000 complete stream reads with zero failed requests, checks a separately delivered end-of-body, and verifies that a real caller cancellation still emits a failed request. See PR-V05 in the verification report for cancellation results and PR-V06 for the subsequent narrow-layout repair.


## PR-O05. Maintain a plan update timeline

Create a timeline from the first source; stock code/name are extracted and confirmed during review. Open an existing timeline and use **Update trading plan** to append a later effective-date source to its exact reviewed endpoint. Review the existing add/modify/retain/revoke differences before saving. Only the newest source is editable; a draft does not change the reviewed timeline. Independent approvals for the same stock remain separate. If a timeline has alternative endpoints, select one path explicitly.

The timeline page replaces manual per-plan checkboxes and the composition button. **Start replay** automatically freezes the complete selected path through the existing server composition checks, then reuses automatic data preparation and continuous replay. Opening a timeline is read-only. The end-date field defaults to the current Asia/Shanghai calendar date when the form is created and may be edited; clearing it keeps the existing server fallback. The first-plan/account start and all cost, risk, funding and T+1 rules remain unchanged.

Historical source/rule links open an independent read-only page. It cannot edit, review or start a run, and leaves the original selected endpoint and form unchanged. Uncertain freeze/run receipts must use the displayed same-request retry; keep the path, settings and key/body locked until resolved. A confirmed freeze receipt is reused on later submission retries.

A new approved update never rewrites an accepted/running replay or historical result. Run the updated timeline again to create a new result. Existing preparation/result links and exports remain supported. This increment adds no database migration, public API or live-plan activation. The workbench single-version replay entry remains available; cross-store timeline assembly, same-day replacement, backdated insertion, merge/delete/reorder and arbitrary start-date clipping are outside this increment. See [approved scope](../specifications/backtesting/SPEC-plan-update-timeline.md) and [verification](../verification/2026-10-19-plan-update-timeline.md).

## PR-O06. Read-only trading condition details

Use **查看计划及本次调整** to inspect the plan date, stock, preceding plan and approved retain/modify/add/revoke changes. Prices are displayed in yuan. Independent timelines and alternative paths remain separately selectable by their dates, review times and display order. Internal preparation/version IDs and hashes are no longer displayed as text; exact references still drive linking, selection and replay admission internally.

Expanding an entry reads its existing reviewed preparation and that source's details only. The displayed changes must match the selected manifest, source, effective date, revision and corresponding approved evidence; a mismatch or failed read shows an explicit retry message. Older records without itemized change evidence keep a link to their reviewed original text and conditions. Opening details performs no extraction, review, composition or replay submission and cannot alter the selected endpoint or form. The independent read-only source page remains available.

## PR-O07. Browse a compact timeline library

The library displays ten complete timelines per page. Each timeline initially shows its stock, date range, review time and update count; **查看更新记录** expands its reviewed updates, and **查看计划及本次调整** opens the existing condition details. Alternative endpoints stay together within their owning timeline. Display numbering continues across pages.

Changing pages or expanding records does not select a different replay endpoint or submit any operation. The current selection remains visible above the list; **定位已选时间线** returns to its page when needed. The existing **打开时间线** and **更新交易计划** actions keep their exact endpoint references and behavior. Pagination only limits presentation of already loaded complete groups; it does not truncate the plan chain or change continuous replay or historical results.

## PR-O08. Editable low-cost replay defaults

A new **创建回测运行** form prefills the following cost assumptions. Commission is a low-cost research preset, not a universal minimum broker quote; adjust it to the actual broker agreement. Rates use fractions of one.

| Field | Default | Meaning |
|---|---|---|
| `commissionRate` | `0.0001` | 0.01% commission |
| `minimumCommissionFen` | `500` | 5 yuan minimum commission |
| `stampDutyRate` | `0.0005` | 0.05% stamp duty |
| `transferFeeRate` | `0.00001` | 0.001% transfer fee |
| `buySlippageFen`, `sellSlippageFen` | `0` | Zero fen per share |

The retained scripted research form also starts both BPS slippage fields at `0`. All values remain editable, including explicit zero-cost assumptions. Clearing a required fee still fails the original validation; there is no hidden fallback on submission. Switching plans does not refill costs. These are frontend defaults for new forms only: the API still requires explicit costs, existing fee calculation/rounding is unchanged, and saved historical costs/results are not rewritten.

Stamp-duty and transfer-fee rates reference the [SSE stock investment service](https://one.sse.com.cn/onething/gptz/), checked on 2026-10-20. The preset does not automatically adjust historical tax regimes or broker-specific rates.

## PR-O09. Read-only historical cost parameters

The result summary shows **本次回测费用参数** for single-plan, workbench and continuous runs. It reads that run's saved `costs`; older result formats use the saved `assumptions.executionConfig`. It does not read new-form defaults or substitute them for saved zero values.

Commission, stamp duty and transfer fees are displayed as exact percentages: for example, `0.0003` becomes `0.03%`. Minimum commission is shown in yuan per trade (`500` fen becomes `5.00 元/笔`), and continuous replay slippage in yuan per share (`1` fen becomes `0.01 元/股`). Older proportional slippage retains its meaning: `1.25` BPS becomes `0.0125%（价格比例）`, not a fixed per-share amount. Decimal rates and fen amounts are formatted without binary floating-point rounding.

This section has no editing or submission controls. Reading it neither recomputes results nor writes historical data. Existing run/report identities, fee calculation, plan-chain execution and history APIs are unchanged. **累计费用** remains the resulting total, distinct from these input parameters.

## PR-O10. Distinguish unavailable history from an empty library

An unsuccessful library read must not display **还没有计划时间线**. Until a successful response confirms an empty library, explain that history could not be loaded and its presence is unknown; disable new-timeline creation in that failure state. Hide the previous error while retrying. If a refresh fails after a successful read, retain the loaded records and selected endpoint and label the list as the last successfully loaded data. A successful retry clears the error.

For HTTP `503`, direct the user to **服务管理** above the page. Check `/api/v1/backtest-service`; `DEGRADED` with `canRead: false` means a read capability failure, not evidence that plans were deleted. When `physicallyDrained: true`, use the existing `RETRY_PREPARATION` recovery action with `resumeJobIds: []`, then refresh the library. Do not substitute `RESUME_JOBS` or recreate plans to recover a failed list read. Recovery is explicit; the list does not automatically issue recovery commands.
