# Daily-basis and position-only funding verification — 2026-10-17

Chinese review copy: [2026-10-17-daily-basis.zh-CN.md](2026-10-17-daily-basis.zh-CN.md).

## DB-V01. Scope and evidence

Implemented the user's daily-price-basis repair and explicit funding choice: no initial cash, with buying bounded by authorized quantities and maximum holdings. Added the bilingual [plan generation template](../templates/trading-plan.md). New template definitions never retroactively supply thresholds to old originals.

The four originals are `01-20260924-104506.txt`, `02-20260928-092555.txt`, `03-20260930-095728.txt`, `04-20261009-091956.txt` under `data/research/shengxin-plan-extraction-20261010`. Effective dates are user-confirmed: 2026-09-24, 2026-09-28, 2026-09-30, 2026-10-09. Earlier primary-source excerpts establishing 300 shares and full ordinary-risk exit remain separately evidenced in [DB predecessor verification](2026-10-17-predecessor-evidence.md). `plans.json` and `entry-fields.json` are not source plans. Originals were not rewritten.

This run reused saved real DeepSeek responses and real Tushare responses offline; it did not make a new AI request. Captures: `shengxin-source-resolution-01.json`, `shengxin-source-resolution-live-check-02.json`, `shengxin-unified-base-03.json`, `shengxin-unified-update-04.json` in `tests/fixtures/ai`. The first three captures are initial extractions; the fourth is an update against the third reviewed snapshot. They were processed through current production extraction/review/composition code in an isolated research store. This verifies a four-version continuous run and the fourth source's predecessor inheritance, not four fresh sequential AI update calls. Research review does not populate or approve the user's production plan library.

## DB-V02. Implemented behavior

- Synchronization retrieves and independently backfills adjustment factors; the immutable factor catalog is separate from the legacy raw-market schema.
- Dataset hashes own factor values, receipt times and the declared `HISTORICAL_SESSION_OPEN_V1` convention. Replay feeds arrived daily bars and admissible same-provider factors into `admit_qfq_daily`; future/foreign/missing evidence cannot become raw-price fallback. Old manifests omit the new empty field and retain their hashes.
- New source-reviewed accounts use `POSITION_LIMIT_ONLY`. No invented balance or cash-required question; buy/sell costs, fees and trade PnL still settle atomically. Existing `KNOWN`/`UNKNOWN` runs keep their original interpretation and remain readable.
- Maximum holdings, order quantities, T+1, sellability, CORE and conflict rules remain enforced. Capital return, equity and equity drawdown remain unavailable rather than invented.
- The exact first-source alternative “two consecutive closes no longer declining” becomes an executable `DAILY_CLOSE_SEQUENCE`, while volume and candle-shape unknowns remain explicit. Explicit “preferably” clauses in the fourth source are optional rather than hard buy gates. Source mappings remain checked and whole-plan review is still required.

## DB-V03. Actual continuous replay

Artifacts: `data/verification/2026-10-17-daily-basis/`. Inputs and report are local research artifacts, not committed source fixtures.

| Check | Result |
| --- | --- |
| Job | `COMPLETED` |
| Run | `c58d1974966fed54ce3d5a370fe098ac8a485aa7ad9633f5deafc4e9d5bb1163` |
| Report | `6de8966503639e97533dff3a7c4051e706e8b191ba26ea0371a73da99737c495` |
| Evaluations / audit events | 1,468 / 2,956 |
| Plan replacements | 3: 2026-09-28, 2026-09-30, 2026-10-09 |
| Evaluated market sessions | Six, with 1,440 normalized minute bars |
| Factor evidence | 23 actual `adj_factor` rows |
| Opening / final holdings | 0 / 0 shares, one continuous account |
| Maximum holdings | 300 shares in every version |
| Second ordinary-risk exit | CORE target 0, TACTICAL target 0; `RESUME_FIRST_CLOSE` |
| Reminders / intents / fills | 1 / 0 / 0 |
| Fees / cost PnL | 0 / 0 fen |
| Capital return / equity drawdown | Unavailable by design |

At 2026-09-24 15:20, the admitted daily close of 25.69 versus 25.99 produced the source's risk reminder. The reminder includes the daily bar and basis identities. No trade was authorized by that alert. Audit continuity, report publication, schedule ordering and source-derived limits passed verification.

The previous run had 1,465 `PRICE_BASIS_UNVERIFIED` evaluations. The repaired run has two, at 2026-09-29 00:00 and 2026-10-08 00:00, before that session's declared 09:30 factor availability; no trading-session evaluation has this blocker. This is intentional time gating. Historical availability is an explicit retrospective convention, not evidence of contemporaneous data collection. Zero fills do not prove strategy profitability or show that every qualitative buy condition is false.

## DB-V04. Remaining genuine policy choices

| Source | Known automatically | Still not quantified |
| --- | --- | --- |
| 2026-09-24 | 300-share ceiling from earlier primary source, first 100 shares, 26.70 close threshold, two-close nondeclining alternative | Lower-wick / bullish-stabilization shape if using that alternative; abnormal-volume threshold/window |
| 2026-09-28 | Ordinary 25.99 breach, full exit scope and user's suspension choice | No further question for these confirmed items |
| 2026-09-30 | 25.99 recovery level, 25.50–26.00 retest range, first 100 shares, event order | Retest/recovery measurement and window; abnormal-volume baseline; relative-index weakening formula/window |
| 2026-10-09 | 25.99 → 25.70–26.00 retest sequence; first 100 shares; 26.40 second-stage level; second 100 only after first completion; last 100 reserved | “Nearby”, “not breaking”, “rising again”, “holding firm” measurement/window |

These questions concern definitions, not retyping known dates/prices/quantities or filling cash. Existing originals are not assigned newly invented thresholds. Third/fourth entry-repair levels are not automatically promoted to stops; unspecified new-position exit policy remains absent. A complete replay can preserve unresolved evidence and avoid unsupported trades. Future plans should supply the template's definitions before review; quantified rules also require engine/data support.

## DB-V05. Checks and use

- 3,199 backend unit tests passed.
- 167 targeted integration tests passed (preparation, continuity, factors, account settlement and OpenAPI); the unrestricted integration run was stopped without a result, so no full-integration-suite claim is made.
- 1,055 frontend tests passed; TypeScript check and production build passed.
- Real isolated Chrome: four actual originals saved separately, dates confirmed before extraction, responsive 320/1440 layouts — passed. The browser uses a local AI stub; it does not claim fresh live AI extraction.
- Focused factor/cache, input ownership and buy/sell settlement checks; lint and generated-contract parity checked. Existing historical frozen four-plan manifest still decodes as `UNKNOWN` funding.

After updating/restarting the application, re-extract affected pending candidates and synchronize the historical data once to backfill factors before creating a new run. Existing reviewed plans/results remain immutable. Do not overwrite the previous verification report or interpret the new template as approval of missing conditions.

Follow-up: [ZF-V01–ZF-V04](2026-10-17-zero-fill-audit.md) separately audits every source's zero-fill reason and repairs the third/fourth known recovery prerequisite. This report retains its original run identity and evidence.
