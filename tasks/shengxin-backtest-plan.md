# Shengxin Lithium conversation backtest

## SX01. Source and scope

Source: [盛新锂能中期波段交易计划](https://chatgpt.com/c/6aa21e11-9d54-83ea-8a91-3c401c270008), read through the browser because the chat reader returned only the latest five turns. Initial prompt: 2026-09-10 11:03 +08:00; latest update discusses 2026-09-29 and was submitted on 2026-09-30. Read-only extraction and isolated research are authorized. Preserve existing implementation changes and production state.

## SX02. Extracted authority

- Initial holdings: 100 shares CORE, reported cost CNY 40.105/share; maximum 300. Pressure 29.30–29.80, observation zone 28.50–29.00, core risk line 25.99. Initial BUY is disabled even after elementary stabilization, pending a new platform and improved risk/reward. CORE is excluded from ordinary tactical sales.
- Ordinary trades require completed daily price structure, candle/volume, and technical evidence; execute only next exchange session, within the corresponding zone. One independent signal grants one quantity. No automatic buy on touching a zone.
- Ordinary risk: first official close below 25.99 freezes additions; second adjacent exchange-session close below it confirms liquidation including CORE, earliest next session. Severe risk needs reviewed structure AND deterioration; missing evidence must not be inferred. Fundamental invalidation requires official evidence.
- User reported BUY 100 at 28.50 on 2026-09-10 17:03; actual execution date was not explicitly supplied. User reported selling all 200 before 2026-09-16 10:41; prices and exact execution times were not supplied. These are actual operations, not proof of plan-confirmed signals.
- Later versions change tactical thresholds (27.40 then 26.40) and zones (26.40–26.70). Ordinary 26.40 risk applies to TACTICAL only; 25.99 applies to all holdings. After the sale, holdings are zero. Do not apply these later versions retrospectively to the initial plan.

## SX03. Ordered tests

- [x] T01 — Read the initial prompt and updates; preserve source timestamps and distinguish actual transactions from recommendations.
- [x] T02 — Retrieve stock daily/minute data, adjustment factors, SZSE calendar, daily limits and 399001.SZ daily data through the configured provider; retain raw responses and safe acquisition metadata in `data/research/shengxin-20261003/`.
- [x] T03 — Freeze an isolated verified dataset, normalize through the existing provider adapters, and run the current engine with the initial fixed plan. Start 2026-09-11 09:00, end 2026-09-30, warm-up from 2025-09-01. Precommit a 100-share ordinary-risk simulation request at 09:31:12 on each exchange session; only the current monitor can permit it. No ordinary BUY authority.
- [x] T04 — Compare with an independent two-close risk oracle and a hold benchmark. Test 09-16 intraday breach versus recovered close, 09-24 first breach, 09-25 holiday, 09-28 second breach, and one permitted execution on 09-29. Report engine receipt and separate costs. Re-run to establish reproducibility.
- [x] T05 — Record chronological plan updates and the post-sale observation gates. Actual-history monetary P&L stays null until execution prices/dates are supplied. Rolling whole-conversation results remain distinct from the fixed initial-plan run.
- [x] T06 — Deliver paired extraction/test report and usable research files, with actual supported coverage and unresolved evidence.

## SX04. Explicit assumptions and acceptance

Research uses retrospective provider observations, not certified historical arrival logs. Daily admission time is assumed 15:20 +08:00, minute receipt follows the existing 12-second historical profile. Factors use each historical date as anchor and never expose later rows. The initial fixed-plan scenario assumes the already-held 100 shares are sellable on 09-11; records a study mark of 28.50, not the reported accounting cost 40.105. The integer-fen lot contract records total lot cost: the study baseline is 285000 fen; the original reported accounting cost would be 401050 fen. Initial cash CNY 0.01 is a research ledger constant, not the user's cash balance; no buys are authorized. Fees are a research estimate: commission 0.03%, minimum CNY 5, sell stamp duty 0.05%, transfer fee 0.001%, directional slippage 4 bps. All money is reported as simulation, not broker execution.

Acceptance: no fabricated actual sale prices, no rewritten original risk line, no future plan updates/factor anchors, no ordinary sale of CORE, no orders/delivery, complete 240 normalized minutes per open session, explicit risk request outcomes, deterministic report identity. Missing severe/fundamental/manual evidence remains unknown and limits conclusions.
