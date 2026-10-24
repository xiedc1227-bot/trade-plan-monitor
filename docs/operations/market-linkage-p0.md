# Market linkage P0 operations

[Chinese review copy](market-linkage-p0.zh-CN.md) · [Specification](../specifications/monitoring/SPEC-market-linkage-p0.md) · [Verification](../verification/2026-10-24-market-linkage-p0.md)

## MLO01 — Capability and entry

Use the existing `/plans` extraction, source review, save, review confirmation and explicit activation flow. Schema 6 / `condition-plan-v2` is selected only by a complete source-authorized linked policy. Existing Schema 5 fixed plans are unchanged and never converted automatically. A linked rule is BUY/TACTICAL, `OFFICIAL_DAILY_CLOSE`, `NEXT_EXCHANGE_SESSION_ONLY`, with complete S0, `market_policy` and `quantity_policy`; it has no fixed `quantity`.

| Capability | Implemented boundary |
| --- | --- |
| Market regime | Exact completed D; BROKEN before WEAK before NORMAL_TRANSITION; necessary missing input means UNKNOWN |
| Relative strength | Same 21 exchange-session window, stock QFQ / index points, strict 5/20-session outperformance and close >= MA20; required only for exception eligibility |
| Confirmation | Complete S0; S1 adds adjacent closes/zone/nondecrease/volume/RSI/risk; S2 adds each day's own MA20 |
| Quantity | Explicit Q0, factors `1` / `0.5`, intersection of official grid and 100-share simulation unit, floor only, full-capacity block |
| Exceptions | Both P1 exception paths remain blocked; no human action in P0 can grant exception execution |
| Signal | Freeze one entire quantity per independent occurrence; exact next-session window; source correction invalidates without resizing or restoring |
| Replay | Same decisions from frozen revisions; missing historical scope rejects; zero-trade reasons retained |

All eight expanded definitions need source bindings or independently registered human review supplements. A preset name is insufficient. Missing strategy parameters, mixed fixed/policy quantity or linked five-minute confirmation blocks complete import/review. Missing runtime evidence instead blocks the dependent decision. Independent reminders do not acquire index or inventory prerequisites.

## MLO02 — Official quantity rules

The user authorized direct official rules on 2026-10-24. `cn-equity-buy-grid-2026-07-06` applies from 2026-07-06 to recognized ordinary A-share code prefixes: SH/SZ main and ChiNext minimum/increment 100/100; STAR 200/1; BSE 100/1. The simulation unit remains 100. Q0 300 in ordinary WEAK therefore yields 100 on main boards and no ordinary quantity on STAR. No upward rounding or capacity clipping is permitted.

If unreduced Q0 is already below the market minimum in NORMAL_TRANSITION, `MARKET_QUANTITY_BELOW_MINIMUM` blocks the ordinary order. It does not direct the user to a WEAK/BROKEN P1 exception.

The evidence records exchange, article, source URL, publication/effective dates and version. [SSE rules](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml), [SSE STAR explanations](https://edu.sse.com.cn/tib/qa/), [SZSE rules](https://investor.szse.cn/lawrules/rule/trade/t20260424_620190.html), and [BSE rules](https://www.bse.cn/jygl_list/200028217.html) are the official basis. Dates before the covered version and unrecognized security prefixes return `MARKET_RULES_UNKNOWN`. This grid does not certify broker limits, live provider availability, special security states or all historical exchange versions.

## MLO03 — Runtime and corrections

The existing shared index collector requests 60 completed daily bars for linked indexes; it retains its existing scheduling, worker limits and recovery. It creates no second poller. Stock admission uses the existing QFQ history. The board map includes `899050.BJ`; this does not certify the configured provider's BSE access.

The runtime view displays market operands, selection, Q0/factor/candidate/authorized quantity, capacity, source time, official grid and blockers. The confirmed signal shows the frozen quantity. A newly calculated candidate is not a new independent trade. Actual simulation rechecks the complete quantity, inventory revision, quote, calendar, T+1, CORE and higher-priority risk inside one transaction.

Unchanged daily OHLC/volume/source content survives polling-time and batch-revision changes; the provider revision is a content hash, not an increasing counter. Full acquisition metadata remains in audit evidence. Published index corrections fence read projections, completion proofs, queued signal reminders and simulation even before reevaluation. A cached older input cannot replace the corrected head. Reads perform no acquisition or business writes. Independent reminder eligibility remains separate.

## MLO04 — Frozen replay and storage

Schema 6 research replay uses `backtest-run-v7` and binds the index dataset, board identity, requirement and formula hashes. Stored monitor-loop manifests carry `market-linkage-replay-source-v1`, with complete official index revisions and availability timestamps; result-owned copies remain usable after mutable market data changes. Admission requires 60 historical exchange sessions plus the requested period; only revisions available at each event cutoff participate. No current informational head is substituted for history.

`market-linkage-evidence-v1` includes the complete decision digest and `market-linkage-calculation-v1` the calculation digest. Signal and evaluation JSON retain this evidence in existing durable records. Old absent optional fields stay absent. No new runtime table migration is needed. A pre-feature reader must reject Schema 6 rather than reinterpret it as fixed quantity; rollback requires disabling linked operation while preserving records.

## MLO05 — Local verification and limits

Run the commands in [MLP-P02](../../tasks/market-linkage-p0.md). Browser tests create isolated SQLite files and substitute only external AI/provider responses. No user database, real order, push, deployment or live-provider certification is part of this implementation acceptance. Historical verification reports describe their own earlier code snapshots and are not rewritten as current capability claims.
