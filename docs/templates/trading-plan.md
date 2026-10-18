# Trading plan generation template

Chinese review copy: [trading-plan.zh-CN.md](trading-plan.zh-CN.md).

## TP-T01. Instructions to the plan author / AI

Generate one plan for one security and one effective exchange date using the fields below. Cite the supplied original evidence for each value. Distinguish proposed policy from observed market facts. Do not invent historical observations, approval, thresholds or trades. Ask for missing policy choices together. A maximum position is a ceiling, not permission to buy the remaining shares. This template defines completeness requirements; it does not supply investment parameters or retroactively reinterpret old plans.

## TP-T02. Identity and continuity

- Security code and name; effective trade date in `YYYY-MM-DD`. Writing time is optional.
- Previous reviewed plan identity, if any. Explicitly list rules retained, modified, added and cancelled; identify old rules by their meaning and evidence.
- Actual starting holdings, lot costs and sellability where known. Subsequent holdings descriptions are comparison facts and cannot reset the simulated account.
- Maximum holdings in shares and the date any change becomes effective; separate per-order quantities, reserved shares and CORE/TACTICAL restrictions.
- Backtest funding: `POSITION_LIMIT_ONLY`. Do not request initial cash or infer cash from position limits. Preserve fees and trade PnL; capital return and account-equity drawdown are unavailable without a capital model.

## TP-T03. Executable condition contract

For every rule specify all fields: action and quantity/target holdings; hard prerequisites versus optional preferences; AND/OR relationships; indicator formula; data field and frequency; numeric threshold and comparator (including equality); lookback window; price adjustment basis; evaluation time; order of events and expiration; execution window; cancellation and repeat policy. Explain required data and whether the current engine supports the proposed condition. A quantified condition that the engine/data cannot evaluate still requires implementation or reviewed evidence; do not promise automatic execution.

Replace ambiguous phrases using explicit choices, not silent defaults:

| Phrase | Required definition |
| --- | --- |
| Obvious lower wick | Formula for wick/body or full range, threshold, handling of a zero body/range, and completed daily bar requirement. |
| Stabilizing bullish candle | Close/open comparison, low/previous-low comparison if intended, and how many completed sessions are required. |
| Volume not abnormally large | Volume or turnover, comparison baseline excluding or including today explicitly, lookback sessions, ratio and equality. |
| Hold above / retest without breaking / rise again | Prices and OHLC fields for each stage, closing or intraday confirmation, event order, allowable delay, and reset conditions. |
| No further weakening relative to an index | Exact index code, return or ratio formula, aligned dates, lookback, threshold and unavailable-data policy. |
| Two closes no longer declining | Specify two consecutive completed exchange sessions and `close[t] >= close[t-1]`; explicitly choose suspension handling. |

Use explicit alternatives: `(A OR B OR C) AND D`. “Preferably” is a preference, never an unannounced hard gate. If the source specifies only one measurable alternative, retain it alongside unresolved alternatives; do not demand confirmation for the measurable part.

## TP-T04. Risk and unresolved items

Specify exit scope (all applicable current holdings or an explicit subset), priority, confirmation sessions, recovery/cancellation rule, suspension handling, next-session execution and conflict behavior. Do not treat an entry-repair threshold as a stop unless explicitly authorized. Separate structural warnings from executable orders.

End every plan with one consolidated list: missing policy choices; unsupported data/conditions; source contradictions. Mark each item unknown and state which rule it affects. Do not conceal these in generic “please confirm everything” text. Preserve exact original citations for known values. New template definitions apply only to the new reviewed plan, never retrospectively to earlier plans.
