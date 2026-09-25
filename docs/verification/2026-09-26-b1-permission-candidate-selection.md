# B1 permission candidate selection: offline read-only verification

## Scope

`B1` adds a raw per-operation permission reservation read and a read-only six-scope candidate selector. It does not connect the RUNNING/DEGRADED scheduler, reserve or run a physical probe, advance a cursor, clear a permission block, or write market data. `B2` retains the durable reservation callback, O/F alternation, and 30-second local checks for a blocked scope without a current anchor.

## Selection contract

- One bounded SQLite read snapshot supplies completed persisted SSE days, today's persisted SSE row, at most ten ACTIVE plans, and relevant official daily bars. A corrupt or failed read propagates. The calendar candidate may use an open or closed completed day in the last seven days, including a weekend row for calendar proof. The shared completed open-day pool uses at most 366 days and requires both persisted `is_open=True` and `weekday() < 5`; a spurious weekend-open row cannot displace a valid weekday anchor.
- `DAILY_LIMITS` requires a legacy plan symbol eligible today and an open completed day. `DAILY_BARS` conservatively uses every persisted ACTIVE legacy symbol (at most ten), including a plan whose one-day activation has ended but whose pending or historical official close remains unfinished. This is a bounded potential-consumer set, not a claim that every symbol needs a call today. Official persisted `(S,D)` pairs form the preferred pool; remaining relevant open-day pairs form the fallback pool. Both are ordered by descending `D`, then ascending `S`, are disjoint, and together contain at most 3,660 pairs. This slice peeks at the first preferred pair, otherwise the first fallback pair. An explicit-only active plan creates neither physical candidate.
- `INDEX_DAILY` requires certified READY index scope and an open completed SSE weekday, independent of stock plans. Historical index candidates require a completed persisted SSE weekday-open anchor, including through the existing seven-day helper. Realtime index candidates require today's unique persisted SSE weekday-open row. Both retain their own certification and local readiness checks.
- Candidate reads do not reserve controller work or call the SDK. Effective due time is the maximum of raw per-operation reservation, local defer, and shared 429 cooldown. The cheap next-due read scans only controller/local times, including blocked scopes without current demand or anchor, and does not scan SQLite. A selector chooses only currently due candidates, ordered by raw reservation and a read-only round-robin tie position. Repeated peeks do not advance that position.

## Verification

Fake SDK and temporary SQLite tests cover seven-day and 366-day boundaries, weekend-open exclusion from the completed open-day pool, explicit-only plans, a one-day legacy plan expired today with either a durable pending close or a proven missing historical close, O/F filtering and the 3,660-pair bound, one read transaction, read-fault propagation, all six same-due scopes, local defer, shared 429 without raw-order mutation, and no SDK calls or reservation on repeated peeks. The focused integration file passed **8 tests**. The adjacent regression command passed **76 tests**; full Ruff and `git diff --check` passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_permission_candidate_selection.py tests/integration/test_production_certification_gate.py tests/unit/test_request_recovery_admission.py -q
.\.venv\Scripts\ruff.exe check .
git diff --check
```

No real Tushare request, notification, user database change, push, or deployment occurred. B1 alone does not establish periodic recheck liveness or physical probe fairness; those remain B2 work. B2 must review the conservative `DAILY_BARS` demand before physical execution so an ACTIVE legacy symbol with no current close obligation cannot cause needless repeated calls.

A later bounded consistency fix excludes spurious weekend-open rows from historical and realtime index permission candidates while preserving weekend calendar proof. Its additional RED/GREEN tests and current regression results are recorded in `2026-09-26-b2-weekend-permission-candidate-consistency.md`.
