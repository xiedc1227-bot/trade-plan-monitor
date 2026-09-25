# S3-02 short crossed market minute: offline verification

## Scope

This bounded slice handles one still-actionable `REALTIME_MINUTE` deadline crossed while an earlier installed runtime handler is awaiting provider work. `MarketSessionScheduler.elapsed_market_deadlines` enumerates original market deadlines from the prior cursor through the observed clock without the future-only filter used by `next_deadline`. It excludes maintenance deadlines. After a handler returns, `RuntimeLifecycleService.run` may execute exactly one elapsed minute through the existing production pipeline if its original `bar_end` is no more than 90 seconds old. The original deadline identity and runtime generation remain unchanged; the existing activation, provider, data, and commit gates still decide the result.

## Offline evidence

The real installed `runtime.run` loop, temporary SQLite database, and fake SDK execute `10:04:12` market work. Its already-started SDK call advances the injected clock to `10:05:13`, crossing the original `10:05:12` deadline by one second. Before the change, the loop silently selected the later `10:06:12` deadline. The test first failed on the missing `10:05:12` execution, then passed when that original deadline was consumed exactly once under the same runtime generation. The fake response leaves a `10:04` minute gap; the `10:05` execution advances the persisted symbol-health projection to `GAPPED` and creates no evaluation or alert. This is the existing data gate's concrete blocked outcome, not a manufactured decision. A focused scheduler test proves the elapsed query still returns `10:05:12` when `next_deadline` sees only `10:06:12`.

Two additional offline cases move the injected clock from `10:04:12` to `10:04:11` after the handler, or forward beyond the two-day review bound. They first failed because the runner exited and the supervisor reported `RUNTIME_RUNNER_FAILED`. The bounded scheduler review now raises `MarketDeadlineReviewError`; `runtime.run` exposes read-only `DEGRADED` with `MARKET_DEADLINE_REVIEW_UNAVAILABLE`, clears next poll/retry, preserves the original cursor, and waits for explicit stop. The existing lifecycle test scheduler substitutes implement the elapsed-review contract; shutdown after in-flight work skips new review and work.

## Remaining boundary

This does not classify multiple elapsed deadlines, an expired minute, an official-close attempt, a wake that returns after its deadline, or ordinary cross-day recovery. The two clock-anomaly cases above only preserve a visible unresolved state; they do not recover missed work. Those boundaries need the S3-04 consumer and visible unresolved-scope handling before claiming complete crossed-deadline recovery. The existing `INDEX_RECOVERY` cursor behavior and original multi-index recovery/five-minute cutoff remain S3-05 work. No new pending table, public health field, endpoint, live Tushare call, user database migration, external notification, push, or deployment was used.
