# S3 current-day business SDK boundary

## BSB-01 Scope and status

Implementation and independent code review passed; five-file local commit approved. This is only the concrete-provider prerequisite approved in A07-F2-04/05 of the paired `2026-09-27-s3-startup-minute-repair-contract`. F2/F3, A07 and S3-04 remain OPEN. No acquisition owner, recovery persistence, scheduler, shared lock, generic protocol or production default is changed here.

The five-file slice is `market_data/tushare.py`, `tests/unit/test_current_day_business_sdk_boundary.py`, the narrow signature assertion in `tests/unit/test_market_data.py`, and this paired report. Other writers' `production.py`, tests and documents are excluded. No real provider, notification, user database, push or deployment was used.

## BSB-02 Implemented boundary

Concrete `TushareMarketDataProvider.current_day_minutes` accepts optional keyword-only `_physical_start: Callable[[], None] | None = None` and passes it to the existing `_fetch_frame` mechanism. The generic `MarketDataProvider.current_day_minutes(symbol)` contract stays unchanged. Ordinary omitted/None calls retain their existing parsing, request arguments and exception classification.

For an opted-in invocation, the existing resolver completes real certification-wrapper checks and inner endpoint lookup before the local hook. The hook runs immediately before the resolved SDK callable, outside provider exception classification. It is never sent as an SDK argument, installed on shared provider/controller state or reused for another call. Guard exceptions preserve identity; real SDK errors retain existing classification. The future F2 owner must supply its captured clock/source/cancellation guard; this seam does not itself implement that authority policy or stop late responses from persisting.

## BSB-03 RED and GREEN

- Initial targeted run: **17 failed in 0.91s**, because the concrete keyword was unsupported. This is interface RED evidence, not 17 separate production faults.
- After the seven-line provider diff: **17 passed in 0.76s**. A test line-length issue was then corrected without behavior changes.
- First adjacent run: **1 failed, 309 passed, 1 warning in 40.15s**. The old concrete-signature equality assertion rejected the newly approved private optional keyword.
- The assertion now explicitly permits only that keyword on `current_day_minutes`, checks keyword-only/default/type, and preserves all original parameter/type checks and exact signatures for every other method. The generic protocol was not relaxed.
- Final four-file combined run: **310 passed, 1 warning in 39.98s**. Ruff and scoped whitespace checks passed. The warning is the existing Starlette/httpx deprecation. These runs overlap and are not additive.
- Independent Sol review found no P1/P2: **17 passed in 0.74s**, then the three adjacent files from the combined command (without the new focused file) had **293 passed, 1 warning in 40.67s**. Scoped Ruff and whitespace checks passed; reviewed source/test hashes were unchanged. These independent runs are not added to author counts.

The new offline tests cover real wrapper/resolver ordering at elapsed 14/15/16 seconds, revoked-call zero SDK entry, original guard exception identity (including cancellation), no private SDK kwargs, no-hook row/argument compatibility, unchanged generic protocol, HTTP 401/403/429/500 classification, independent concurrent invocation hooks and invalid-symbol rejection. The clock and revocation policy are injected test guards, not a claim that the recovery owner is wired. This shared-worktree run is not the final integrated Step 3 gate.

## BSB-04 Commands

Run from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_current_day_business_sdk_boundary.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/unit/test_current_day_business_sdk_boundary.py tests/unit/test_sdk_call_boundary.py tests/unit/test_market_data.py tests/integration/test_production_sdk_call_boundary.py -q --tb=short
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/market_data/tushare.py tests/unit/test_current_day_business_sdk_boundary.py tests/unit/test_market_data.py
git diff --check -- src/trade_plan_monitor/market_data/tushare.py tests/unit/test_market_data.py
```

## BSB-05 Remaining acceptance

Independent review and five-file local commit approval are complete. F2 still needs invocation-local recovery wiring, immutable capture, exact missing-row selection, owned response transaction and cross-thread commit fencing; F3 still needs bounded autonomous scheduling. The original A07 cutoff/progress failures are not closed by this opt-in provider seam. Calendar and historical-index permission seams from the separate UPD proposal are not implemented here.
