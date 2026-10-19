# Completed-result read isolation

## RR-01 — Root cause and repair

The four-plan result read repeatedly verified the same frozen input and occupied the metadata owner for longer than its 5-second read-admission deadline. Concurrent job, dataset and duplicate result requests returned 503. Preserve all evidence validation and historical bytes; separate expensive result projections from task/admission metadata, share only overlapping identical reads, and combine input/report/diagnostics in one read snapshot.

## RR-02 — Implementation and boundaries

- [x] Read copied facts once per result projection and retain report binding, complete retained-event digest, typed rows, diagnostic bounds and expiry handling. No persistent result cache, stored projection or report rewrite.
- [x] Add one lazy, owned result-reading thread, at most one physical call, 8 observers and 8 distinct in-flight keys. Different keys wait at most 60 seconds for admission. Metadata keeps its existing 8/5-second bound. Key by operation/run/source and include pin state for summary responses. No execution authority or extra heavy-job worker.
- [x] Share only in-flight identical requests; each later read verifies storage again. Observer cancellation cannot cancel another observer or release physical work. Include the result owner in shutdown, error translation and physical-drain accounting.

## RR-03 — Verification and status

- [x] Confirmed the original failure with local concurrent GETs: first result 200 in 19.448 seconds; job, dataset and duplicate result 503 after 5.066–5.071 seconds.
- [x] Related backend 155 passed; result API 25 passed. Regression covers responsive job reads during a held projection, duplicate/cancelled observers, fresh subsequent reads, bounded overload/queue timeout, shutdown, corrupted audit and expired evidence. Removing request sharing makes the regression fail; exact bytes restored.
- [x] Restarted only after checking no pending/running tasks and physical drain. Two identical real four-plan scenarios returned all 200; result 4.736/7.513 seconds, concurrent metadata 0.025–0.249 seconds. Eight mixed reads of new/old reports, jobs, datasets, result list and status also all returned 200. Both full report responses and all 50 saved owned files were unchanged. Actual browser displayed profit summary, four diagnostics and rule comparisons without a read-failure prompt. No replay, download or AI request.
- [x] Updated paired specification, operations, task status and [verification](../docs/verification/2026-10-18-result-read-isolation.md). This is the follow-up to [AD-V03](../docs/verification/2026-10-18-automatic-backtest-data.md#ad-v03--four-actual-plans), not an unbounded-load or never-503 guarantee.
