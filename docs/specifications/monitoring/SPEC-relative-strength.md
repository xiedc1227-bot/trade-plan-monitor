# Specification: relative-strength

Status: APPROVED — on 2026-10-24 the user approved all six decisions and specifications and explicitly authorized ordered implementation. Progress is governed by acceptance evidence; unfinished tasks are not shipped capability.
Implementation evidence is maintained in [the verification report](../../verification/2026-10-24-market-linkage-p0.md).

## RS01 — Objective and dependencies

Evaluate the prompt's exact stock-versus-board strength test, with inspectable arithmetic. Depends on `market-regime` identity/cutoff evidence and admitted stock daily data. Existing index RETURN facts may be reused only after matching dates, availability and formula semantics. Stock relative strength is not an RSI indicator or a discretionary benchmark ranking.

## RS02 — Windows and comparison

For n in {5, 20}, calculate `stock_return_n = stock_close[D] / stock_close[D-n] - 1` and `index_return_n = index_close[D] / index_close[D-n] - 1`. D-n counts exchange sessions on the verified aligned calendar, not calendar days or the nth available stock bar. Require complete aligned 21-session stock/index histories for both returns; calculate stock MA20 from the last 20 completed stock closes.

Stock prices use one frozen, admitted QFQ series comparable to the current quotation; index prices use original points. Do not mix stock adjustment vintages, providers within a series, or revise earlier backtests with later adjustment knowledge. Cross-series source differences must be visible and admitted by existing comparability rules, never silently spliced.

`STRONG` requires ALL of: 5-session stock return strictly greater than index return; 20-session stock return strictly greater than index return; D stock close greater than or equal to D stock MA20. Equal returns fail outperformance; equality to MA20 passes. Compare exact Decimal values, not rounded percentages.

## RS03 — Unknowns, output and authority

Return `STRONG`, `NOT_STRONG` or `UNKNOWN`, with all three predicate outcomes. A definitively false predicate makes NOT_STRONG even if another is unknown; otherwise any missing predicate makes UNKNOWN. Missing sessions, suspensions without eligible observations, zero/invalid denominators, unavailable adjustment basis or mismatched endpoints cannot be fabricated. No carry-forward closes or shorter replacement windows.

`RelativeStrengthEvidence` includes endpoint dates/prices, both returns for both windows, return differences, stock close/MA20, per-predicate outcomes, source/basis/formula hashes, cutoff and reasons. UNKNOWN never grants an exemption. STRONG alone never authorizes buying or overrides technical risk; P0 exception routes remain blocked.

## RS04 — Acceptance and verification

| ID | Required evidence |
| --- | --- |
| RS-A01 | Independent calculations prove 5/20-session returns, identical endpoints, MA20 and exact equality behavior. |
| RS-A02 | Missing/suspended days, wrong endpoints, zero denominators, mixed adjustment bases and unavailable facts cannot grant strength. |
| RS-A03 | All combinations of true/false/unknown retain child evidence and apply the specified three-valued result. |
| RS-A04 | Replay freezes dates, revisions and adjustment basis; future-data mutations cannot change earlier strength, and STRONG never bypasses P1 or risk. |

Implementation files: `decision/relative_strength.py`, focused unit tests and shared runtime/replay tests under the package structure in MLP07. Verification command from `trade-plan-monitor/`: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_relative_strength.py tests/integration/test_market_linkage_replay.py -q`. No new external dependency or live probe is needed for these tests.
