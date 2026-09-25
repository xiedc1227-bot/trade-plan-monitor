# B2 DAILY_LIMITS permission maintenance: offline internal slice

## Scope

The new `_maybe_recheck_daily_limits_permission` method handles only blocked `DAILY_LIMITS`. It shares the permission maintenance lock with `INDEX_DAILY`, reselects the globally first raw-due candidate inside that lock, and advances the in-memory permission cursor only through the controller's durable `on_reserved` callback. It does not connect a RUNNING/DEGRADED scheduler or another physical permission scope.

The owner reads `legacy_symbols` and the exact completed persisted SSE weekday-open anchor together in one bounded SQLite snapshot before reservation and again after the provider response. No today-eligible ACTIVE legacy demand, no anchor, or temporarily unavailable stock authority causes a fixed local `now + 30s` defer when the previous check is due. Repeated entry and the pure due getter do not slide that time or reserve work. Explicit STOCK semantics require the `stk_limit` scope and the same semantic revision; the supported legacy mode uses its stock certification without semantic bindings. Configuration, certification, generation, stop and calendar epoch are rechecked through queue and worker admission. The SDK worker reads no database.

The provider's private `_physical_start` callback runs immediately before `_fetch_frame`, outside its broad exception sanitizer. The frozen 31.25-second market guard applies before queueing, at queue admission, at worker entry, and just before SDK transport. Response validation rejects a clock rewind before capture or a date change without reapplying the future market-start guard. `stk_limit(D)` is a date-wide permission proof: a newly activated legacy symbol can satisfy terminal demand, while no remaining legacy demand or only explicit plans cannot clear the block. A trusted completed Friday may be probed on Saturday for an eligible MANUAL legacy plan; a false weekend-open row cannot become the anchor. The proof writes no business daily-limit rows or calendar cache.

## Verification

RED first failed because the internal method was absent. A separate RED showed that rejecting `semantic_bindings=None` would strand the supported legacy stock-certification mode. Fake SDK and temporary SQLite tests cover one legal request and own-scope unlock, fixed local defers for absent demand/anchor/authority, shared 429 and global due order, real legacy construction and invalid explicit STOCK binding, weekend anchor selection, durable reservation and callback faults, queue abort/stop/invalid response/timeout, physical-start revocation with zero SDK calls, restored configuration and semantic revocation, same-value calendar epoch change, exact anchor reread, serial `INDEX_DAILY` interleaving, midnight and clock rewind rejection, a valid response near the next market deadline, and terminal demand changes during the SDK request. The focused and adjacent command passed **138 tests**; full Ruff and `git diff --check` passed.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_production_daily_limits_permission_maintenance.py tests/integration/test_production_index_daily_permission_maintenance.py tests/integration/test_permission_candidate_selection.py tests/integration/test_permission_candidate_rotation.py tests/unit/test_daily_permission_proofs.py tests/unit/test_permission_reservation_ack.py tests/integration/test_production_semantic_gate.py -q
.\.venv\Scripts\python.exe -m ruff check .
git diff --check
```

The later scheduler integration must prove that permission work does not consume a market-deadline cursor. Other permission scopes, RUNNING/DEGRADED dispatch, and end-to-end C1 acceptance remain OPEN. No real Tushare request, notification, user database change, push, or deployment occurred.
