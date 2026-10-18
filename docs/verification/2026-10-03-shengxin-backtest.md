# Shengxin Lithium source extraction and backtest

## SX01. Source and research boundary

Source: [盛新锂能中期波段交易计划](https://chatgpt.com/c/6aa21e11-9d54-83ea-8a91-3c401c270008). The initial user prompt is dated 2026-09-10 11:03 +08:00. The final update, posted on 2026-09-30, evaluates 2026-09-29. Browser reading recovered the initial prompt and intermediate updates that were absent from the recent-five-turn chat reader. The uploaded report itself was not exported; its quoted generation time/reference price are source claims, not independently verified report metadata.

This study distinguishes (1) a real-data replay of the fully specified initial 25.99 ordinary-risk branch, (2) necessary price gates after the user's actual liquidation, and (3) the actual trade history, whose monetary P&L remains unknown. It does not certify a complete automated replay of every discretionary change, announcement, or severe-risk judgment in the conversation.

## SX02. Extracted plan and chronology

| Source availability | Authority or reported transaction | Research treatment |
|---|---|---|
| 09-10 11:03, initial prompt and first response | Existing 100 shares, cost 40.105, maximum 300; CORE 100, TACTICAL 0; pressure 29.30–29.80, low-buy observation 28.50–29.00, risk 25.99 | Initial fixed-plan baseline; BUY disabled; ordinary CORE sales prohibited |
| 09-10 17:03 | User: “我在28.5买入了100股” | Actual BUY claim; execution date/time not explicit. Not a confirmed initial-plan BUY signal |
| 09-11 morning/afternoon | TACTICAL failure review at 27.40; afternoon recovery changes the conditional exit assessment | Preserve intraday source chronology. No invented full-session severe fact or minute-volume baseline |
| 09-14 intraday | Hold 200, no additions; next pressure 28.35–28.50; 26.40 becomes short-term observation | A later assessment, not retrospective replacement of the initial 25.99 risk line |
| 09-15 14:30 and 09-16 premarket | TACTICAL 26.40: ordinary two closes/severe one close; all holdings 25.99: ordinary two closes/severe one close | Separate tactical scope from whole-position risk; confirmed closes govern timing |
| 09-16 10:41 | User: “破位后我逐步卖出了200股” | Actual liquidation claim; exact prices, times and allocation unknown; holdings become zero |
| 09-17 09:11, evaluates 09-16 | Candidate stabilization; 100 shares only on next-session return to 26.40–26.70, no chase at 26.97 | 09-17 low 26.75 does not enter the zone; no permitted pullback execution |
| 09-18, evaluates 09-17 | No buy; updated pressure 27.30–27.80 | Do not backdate this update into 09-17 trading |
| 09-21/09-22 | Pressure 27.30–27.60; 09-19 was a non-trading day | No fresh 09-19 close or trade |
| 09-23, evaluates 09-22 | Pressure 27.70–28.00; wait for pullback or completed breakout/retest | No buy on merely touching an intraday high |
| 09-24, evaluates 09-23 | Pressure 27.30–27.70; need a fresh stabilized daily close back above 26.70 | 09-23 close 26.62 is insufficient; the later lowered pressure cannot create an earlier sell |
| 09-28, evaluates 09-24 | Cancel low-buy after first close below 25.99; zero holdings | Update arrives after the evaluated date; fixed original risk rule already governs earlier closes |
| 09-30, evaluates 09-29 | Pressure 25.50–26.00, low-buy disabled; recover 25.99, then a fresh retest before reconsidering 100 | No backdating the new 25.50–26.00 zone to earlier sessions |

Common rules: completed daily price structure plus candle/volume plus at least one improving/weakening technical indicator for ordinary trades; next exchange-session execution within zone; one independent signal per planned quantity; no cost-driven risk-line movement; no spontaneous conversion of a losing TACTICAL lot into CORE. Broad reference is 深证成指 399001.SZ; it adjusts confidence, not individual price levels or standalone trade authority. A fundamental exit requires official evidence; absent announcements are not proof of no bad news.

## SX03. Data and reproducibility

Research acquisition used the existing configured Tushare-compatible endpoint (`api.quicksync.cn`), without displaying credentials. Local market stores had no stock bars. Initial sandbox requests timed out; a bounded permitted network request and subsequent acquisition succeeded. Retained responses contain 263 stock daily bars, 263 factors, 263 index daily bars, 403 calendar rows, 3374 source minute rows and 14 daily-limit rows. These include 09-10 data; the current-engine study begins 09-11.

Normalization uses the existing historical provider adapters, including strict 241-row source-minute verification and 240 canonical minutes per open session. The frozen 09-11–09-30 dataset has 13 open sessions and 3120 canonical minutes. All obtained factors are 1.674; equivalence to raw prices here follows retrieved factors, not a fabricated factor-1 default. Each day's proof exposes only factors through that date and anchors to that date. Retrospective 15:20 official-close availability and the existing 12-second minute receipt profile are explicit research assumptions, not historical collection attestations.

The [exchange calendar notice](https://investor.szse.cn/disclosure/notice/general/t20260917_622911.html) confirms 09-25–09-27 closure and 09-28 reopening. Public [daily prices](https://hk.investing.com/equities/weihua-a-historical-data) independently corroborate key OHLC anchors. Exact study calculations use the retained same-provider rows.

Files are retained under `data/research/shengxin-20261003/`: raw responses, `research-market.sqlite`, `fixed-plan.json`, `fixed-research.json`, `initial-lots.json`, `fixed-report.json`, `fixed-summary.json`, `independent-oracle.json`, `post-sale-price-gates.json`, `actual-trade-input.json`, `rejected-input-summary.json`, and repeat-check `verification.json`. Reproduce offline from the project root:

```powershell
.venv/Scripts/python.exe scripts/replay_shengxin_research.py --data data/research/shengxin-20261003
.venv/Scripts/python.exe scripts/replay_shengxin_research.py --data data/research/shengxin-20261003 --verify-repeat
```

The script cannot contact a provider; it feeds saved frames into existing strict adapters and calls `OfflineBacktestRunner`. No production configuration/database write, live activation, notification, broker order, commit, push or deployment occurs.

## SX04. Scenarios and assumptions

Initial fixed-plan ordinary-risk slice: 100 CORE shares; BUY authority absent; original pressure is irrelevant to ordinary sale because no TACTICAL shares exist. The actual discretionary 100-share purchase is excluded from this strict-plan scenario. Review metadata is an explicitly labelled present-day research-operator declaration, not production review or historical user approval. Severe technical conditions retain missing reviewed facts; fundamental exits are outside this supported slice.

Start 2026-09-11 09:00, end 2026-09-30, warm-up 2025-09-01. The pre-existing lot is assumed sellable by 09-11, with acquisition date 09-09 used only for this assumption. Period equity is rebased to the known 09-10 close 28.50, rather than accounting cost 40.105. The lot contract holds total cost in fen: 100 shares at 28.50 require 285000, not the per-share quote 2850. The original 100 shares at 40.105 would have total reported cost 401050 fen, which is exactly representable but measures a different return interval. Research initial cash is CNY 0.01, a bookkeeping constant, not the user's cash. No BUY operation can spend it.

The explicit operation script requests a full 100-share ordinary-risk simulation at 09:31:12 on every open study session. This is a precommitted research execution policy; it is not a claim that the user acted that way. The current monitor independently permits or blocks each request. Study fees: commission 0.03% with minimum CNY 5, sell stamp duty 0.05%, transfer fee 0.001%, directional slippage 4 bps. These are configurable estimates, not broker charges or a current legal fee certification. Monitor receipt price and research price/fees are separate.

## SX05. Independent checks and results

Independent close oracle: 09-16 low 25.94 but close 26.97, so no ordinary core-risk exit; 09-24 close 25.69 is the first breach; 09-28 close 24.44 is the second adjacent exchange-session breach; the earliest ordinary-risk execution session is 09-29. 09-25 is not an extra confirmation session. The 09-29 09:31 minute has close 24.81; this is a possible monitor quote, not the user's sale price.

Stock hold benchmark, 09-10 close 28.50 to 09-30 close 25.01: -12.2456140351% before hypothetical liquidation costs. Same-period 深证成指, 13617.6698 to 12887.6198: -5.3610493625%. These comparisons share a time interval, not an equal-risk portfolio allocation.

Post-sale necessary-price-gate check covers nine sessions, 09-17–09-30: 09-17/18/21/22 never return to 26.40–26.70; 09-23 close 26.62 does not reclaim 26.70; 09-24/28/29/30 close below 25.99. No completed breakout/retest is established by the tracked price sequence. These gates reject new buys without inventing missing candle, technical, announcement or independent-signal approvals. They are a price-gate check, not a complete rolling engine execution. Actual transaction P&L is null.

The current engine permits exactly one of 13 explicit requests: SELL 100 on 2026-09-29 09:31:12 +08:00. The other 12 are blocked with `DAILY_SIMULATION_RISK_NOT_EXECUTABLE`. The monitor receipt is 24.81/share; after the configured 4 bps directional slippage and fen rounding, the research sale price is 24.80. Commission, stamp duty and transfer fee total CNY 6.27; sale proceeds net CNY 2473.73. Final inventory is zero.

| Measure | Fixed initial-plan risk slice |
|---|---|
| Initial study equity, including CNY 0.01 ledger cash | CNY 2850.01 |
| Final study equity | CNY 2473.74 |
| Study P&L | CNY -376.27 |
| Study return | -13.2024098161% |
| Same-period stock hold return, before liquidation costs | -12.2456140351% |
| Same-period 399001.SZ return | -5.3610493625% |

The fixed risk slice underperforms the hold benchmark in this interval: the stock recovered after the hypothetical exit. This short slice does not estimate the performance of the entire rolling conversation or a strategy over multiple market regimes.

Accepted dataset identity: `9069e30832e51371e9d0e758bd94180098740bd73025d3dc1ff243b966cd5c10`. Accepted first report identity: `65954b7e99d9bc5377c5ff01ce334916991aabd0644c3b9d554c01bfdc420fff`. Independent calendar/price checks and economic assertions passed; a repeated full replay produced the identical report hash. Verification is retained in verification.json. Script lint/formatting and paired documentation checks passed. The first exploratory run was rejected before delivery because it supplied the per-share quote 2850 as total lot cost. `rejected-input-summary.json` retains that rejection; none of its return figures are accepted. The corrected input is 285000. The runner itself was not changed.

## SX06. Remaining evidence and interpretation

Needed for actual realized P&L: the 28.50 BUY execution date, each 09-16 SELL quantity/price/time, and actual fees if exact net P&L is required. The reported 200-share liquidation differs from ordinary close-confirmed core-risk execution; do not claim the plan instructed that intraday sale. Later rebound does not establish whether the actual operation was profitable.

Complete rolling-plan replay also requires explicit effective times for revisions, audited discretionary candle/technical/severe/fundamental facts, and state continuity across replacements. Current replay terminates one authority on `REPLACE`; it does not automatically start and execute a second plan. Two ordinary risk thresholds with different holding scopes cannot be silently collapsed into one 25.99 branch. This report provides tested supported slices and an extraction/test plan; it does not relabel them as a full certified conversation-strategy return.
