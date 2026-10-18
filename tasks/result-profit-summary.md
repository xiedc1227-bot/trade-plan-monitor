# Result profit summary

## PS-01 — Display contract

Show a read-only profit summary at the top of every loaded backtest result, before actions, tabs and detailed diagnostics. Display total PnL, realized PnL, floating PnL and the resolved backtest end date. Loop results use the server's `cost_pnl_fen`, `realized_pnl_fen` and `unrealized_pnl_fen`. Preserve null as unavailable and zero as 0.00 yuan, even when missing capital makes equity valuation unavailable. Do not infer live-account returns from a historical result or add a principal return percentage.

Reuse the existing result request and exact integer-fen formatting. Legacy results with explicit PnL fields use their exact sum; old research results without those fields show unavailable, not invented zero. The cutoff is the backtest end date, not job completion or today's date. Where retained, show the actual evidence cutoff in Shanghai time. No API, report, replay or stored-result change is required.

## PS-02 — Verification

Cover positive/negative/zero/unknown values, exact large integers, date semantics, prop updates, legacy compatibility and top placement across tabs without extra requests. Build and inspect the actual four-plan result at desktop and narrow widths. Update English/Chinese README, operations and verification records together.

Complete: focused 69 tests and frontend full 1079 tests passed, with type/build checks and actual desktop/mobile verification. See [PS-V01–PS-V03](../docs/verification/2026-10-18-result-profit-summary.md).
