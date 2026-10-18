# Risk exits by holding cohort — 2026-10-18

## CR-V01 — Source meaning and executable policy

This completes the execution boundary in RW-V04. The four actual `.txt` originals are from `data/research/shengxin-plan-extraction-20261010`; `plans.json` and `entry-fields.json` are not plan sources. Confirmed effective days remain 2026-09-24, 2026-09-28, 2026-09-30 and 2026-10-09. Maximum position remains 300 shares, and the confirmed suspension policy remains `RESUME_FIRST_CLOSE`. Funding is `POSITION_LIMIT_ONLY` with no initial-cash limit.

The fourth source excludes new holdings from the former 25.99 stop; it does not cancel old-holding protection. Its reviewed ordinary exit retains two official closes below 25.99, zero core/tactical targets and the suspension policy, with `holding_scope: {mode: BEFORE_TRADE_DATE, trade_date: 2026-10-09}`. Lots acquired before that day remain protected. Same-day/later buys are excluded from that old exit and follow the new plan's two ordered 100-share entries. The source supplies no new-position stop, so none is invented. Its 24.20 stay-flat instruction is not converted into a stop. No additional manual source fact was required for scope support.

Earlier plans and their exact reviewed lineage remain unchanged. The first is independent; the remaining three pin their immediate reviewed predecessor. The fourth risk change is `MODIFY`, not `REVOKE`. Its other risk fields remain equal to the third policy. Existing frozen results were not rewritten.

## CR-V02 — Extraction and evidence

The user's authorization covers original texts, reviewed predecessor strategies, previous unapproved candidates and correction diagnostics sent to official `api.deepseek.com`, model `deepseek-flash`. Six fresh physical HTTP calls were made during this repair. Requests reproduced an incorrect entire-rule/context assessment, correction failures and the final accepted focused assessment. Replaying an already captured response locally is not counted as a new provider call. The first three exact reviewed actual-source records were revalidated and reused; they were not freshly sent again.

The final unedited live scope response says `existing_positions: UNCHANGED`, `new_positions: EXCLUDED`, with exact clause references. Omission of an old-position change inherits the reviewed predecessor. The focused path corrects processing contradictions without promoting ambiguity or discarding non-risk changes. Every expanded candidate still passes the ordinary source/binding/update validators and bounded stored-codec round trip before review. An earlier oversized expanded response cannot be saved as a falsely readable `VALID` candidate. No source or model response was edited into acceptance.

Private v5 delta operations carry explicit `scope_change`. Date boundaries derive from the confirmed effective day and intersect previous windows. Stable identities support separate ordinary exits for old/new holdings with different prices. Missing direction is automatically corrected within the existing three-attempt budget; genuine uncertainty remains distinct. Local evidence is in `data/verification/2026-10-18-cohort-risk/`; unchanged response fixtures are in `tests/fixtures/ai/cohort-scope-live.json`. Credential headers are not retained.

## CR-V03 — Exact execution beyond a zero-fill source run

The production lot ledger now supplies acquisition date, known sellability and origin version. Scoped risk states retain stable identity, confirmation evidence and scope across plan switches. Old-only pending/confirmed risk does not block an otherwise authorized new-cohort entry. Execution recomputes exact allocations atomically, enforces T+1 and official tradability, and never substitutes excluded new lots for an unavailable old lot. Overlapping obligations cannot debit the same lot twice. Fulfillment checks eligible holdings, not total inventory.

Deterministic production integration tests use real SQLite sessions, the ordinary simulation path and cost ledger. A new 100-share buy is allowed while old protection is pending and records its plan version. When old risk confirms, selling the old 100 shares releases exactly 301050 fen of old cost and records 95147 fen realized PnL; the new 100 shares and their 397604 fen cost remain intact, and the old obligation becomes `FULFILLED`. Separate ordinary identities independently confirm against 38.18 and 36.00. A three-version sequence preserves the first breach through a suspended session, uses the first resumed close as the second confirmation, allows a new buy, and later sells only the old lot without moving its cutoff.

Additional unit/matrix cases cover unknown opening acquisition dates with known observation, unavailable old holdings, per-branch prices, repeated scope intersection, different Chinese/English wording, old/new scope directions and genuine ambiguity. These controlled mixed-holding cases prove execution that the actual zero-fill run cannot exercise.

## CR-V04 — New actual continuous replay

The newly reviewed chain used the existing frozen real market dataset, warmup from 2026-09-01 and replay through 2026-10-09, including all four effective days. No market-provider call, synthetic market substitution or account reset was used. The full retained audit passed `verify_loop_events`; three replacements occur on 2026-09-28, 2026-09-30 and 2026-10-09.

| Identity | Value |
| --- | --- |
| Manifest | `cda3f3979433de0c26aa825a41d3841401ebbb53c073a1d2408e390bf4ca1315` |
| Fourth reviewed manifest | `5ca7180f704e0d3f0bb2e90490b5e21024a9f1041d227ea3bc56c05b919d4694` |
| Run | `9050185da63d7961aa29228542fa024d127ac4d754af10e3066cbc26e09abeb2` |
| Report | `935be980b2d0e78ee5386b196f1bc4bea6fc3af88a4b306b9cde92eb9bf251df` |
| Dataset | `b983a206bce80882c2ac2fe10f25acbafb680f36f6f9ffeacd0b111e5b0446b1` |

Completed: **1468 evaluations, 2961 audit events, 0 intents, 0 fills**. All four policies passed review. There are no scope/holding-cohort/update-processing blockers. Two midnight evaluations retain `PRICE_BASIS_UNVERIFIED` before that session's factor availability; trading-session basis is admitted. No cash or capital return is fabricated. This run's zero holdings do not prove that an exit filled.

| Plan | Result evidence |
| --- | --- |
| 2026-09-24 | 25.69 close fails above 26.70; 26.62 → 25.69 fails two non-decreasing closes. Candle/volume criteria remain visibly unquantified. |
| 2026-09-28 | Reviewed policy has no direct buy rule; risk/observation is not buy authority. Representative closes are 24.44 and 25.05. |
| 2026-09-30 | No earlier qualifying close at/above 25.99 in the new recovery window; 25.01 prior close on 2026-10-08 fails. Lows 24.82/24.86 fail [25.50, 26.00]. Retest/volume/index criteria remain separate. |
| 2026-10-09 | No earlier qualifying recovery above 25.99/26.40 in the new window; latest 25.35 is not a prior-close confirmation. Low 24.36 fails [25.70, 26.00]. Retest criteria remain visible. Old 25.99 protection remains scoped, not cancelled. |

The result store was backed up before publishing the separately identified new run through normal immutable-input, audit and publication checks. Old runs remain readable.

## CR-V05 — Result page and validation

The result page adds a holding-scope summary inside each full rule comparison: inherited old protection, cutoff, price, targets and exclusion of new buys. Full comparison fields retain previous/current values. Timeline risk states display scope; authorized and filled scoped exits show exact lot allocations. The actual run has no fills, so no actual exit allocation is fabricated. Existing per-plan reasons, classification and actual-versus-required prices remain available.

The four exact reviewed records were also copied to the actual local preparation library after backup, retaining manifests, timestamps and predecessor references. All eight entries are readable; no historical approval was overwritten. A pre-scope cancellation diagnosis remains readable through frozen history, while current predecessor/composition validation still rejects it. This repairs an old `FROZEN_BINDING_CONFLICT` that prevented reading the whole library.

Final service process `38828` serves localhost port `8765`, monitor contract 2, `RUNNING` / `STANDBY`. Its job list was empty before restart. Production HTTP checks read the new four-version result, four comparisons, eight library entries and the earlier result. Comparison counts (`RETAIN / MODIFY / ADD / REVOKE`) are 0/0/11/0, 9/1/2/1, 10/2/2/0 and 8/6/1/0. The fourth risk changes only scope.

The browser showed all four diagnoses and prices, plus the fourth scope summary with 25.99, two-close confirmation and new-position exclusion. A concurrent bounded read returned 503 after restart; explicit retry recovered. The final build was reloaded. Evidence: `data/verification/2026-10-18-cohort-risk/result-scope.jpg`, `result-page.txt` and `web-check.json`. No manual scope question or fabricated fill was shown. Additional component cases prevent tactical-only severe exits from being labelled as full-position price stops.

Backend unit suite: **3328 passed**. Frontend full suite: **1071 passed**, followed by **10 passed** in affected result suites after the final display precision correction. Type checking, production build, both generated-contract checks, targeted Ruff and whitespace checks passed. Existing Starlette/httpx deprecation and isolated-test router warnings remain; no Vue runtime error was observed in the scope view.

The broad integration invocation was stopped during the unrelated legacy ten-symbol × 252-day capacity workload; no capacity pass is claimed, and no assertion/threshold changed. Related integration checks completed with 655 passes and one outdated assertion: an older unapproved real response also exceeds the existing evidence-expansion budget. The fixture remains unchanged; its regression now requires rejection before persistence rather than expecting a stored unresolved candidate. Final rechecks: **46 passed**, covering that case, the actual four-source chain, mixed-lot execution, source confirmations, library history and both OpenAPI snapshots. Thus every one of the 656 selected integration cases has passed; no case was skipped or removed to obtain acceptance.
