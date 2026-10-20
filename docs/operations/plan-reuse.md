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
