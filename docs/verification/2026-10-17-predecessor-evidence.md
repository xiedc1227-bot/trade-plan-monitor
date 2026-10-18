# Original predecessor evidence and four-source verification

## PE01. Evidence recovered

On 2026-10-17 (Asia/Shanghai), read the original [盛新锂能中期波段交易计划 conversation](https://chatgpt.com/c/6aa21e11-9d54-83ea-8a91-3c401c270008) through the connected browser. The local production preparation database has no reviewed predecessor; its four records are drafts or failed older collections. The monitoring plan library is empty. Research output is not a substitute for a reviewed production predecessor.

The original conversation does resolve both previously requested facts:

- The 2026-09-23 update explicitly states a maximum of **300 shares**. This precedes the first file's confirmed 2026-09-24 effective date. The same-stage clarification after that file also repeats 300. No later 2026-09-28 value is backfilled into the earlier plan.
- The 2026-09-16 clarification says that an ordinary first close below **25.99**, followed by another close that does not reclaim it, confirms **full liquidation**, executed the following trading session. The separate **26.40** rule concerns only the tactical lot. Full liquidation maps to retained CORE and TACTICAL quantities of **0**, not a fixed sale of the historical 200 shares. No historical holdings are copied into the new account.

The four exported files omit these earlier clauses. Their omission is an incomplete source context, not a new question about the user's strategy. `plans.json` and `entry-fields.json` were not used as plan evidence.

## PE02. Automatic handling

Recognize the literal maximum-position label, including `最大计划持仓`. Bind an explicit ordinary full-exit sentence to its exact risk price and original clause spans, and derive full-liquidation targets. Missing, negated, interrogative, severe-only, or differently priced statements do not supply ordinary scope. The fixed risk priority is a product constant: ordinary 3, severe 2. An AI priority of 1 must not become a user question.

If the ordinary branch has no suspension-confirmation policy, report `PLAN_PARAMETER_REQUIRED: risk_branches.0.suspension_confirmation_policy` and one business question, `risk-suspension`, instead of a generic parameter/processing error. The current contract requires a choice between `RESUME_FIRST_CLOSE` and `RESTART_ADJACENT_PAIR`; neither is invented from the words “next trading day.” Weekends and exchange holidays are not individual-stock suspensions.

On 2026-10-17 the user answered “复牌首个收盘继续确认.” The second plan now has `RESUME_FIRST_CLOSE`, recorded through the existing correction/review API as a `HUMAN_SUPPLEMENT` bound to the corrected candidate hash. This is an explicit user decision, not a claim that the original document contained the setting. `user-confirmation.json` preserves that evidence; no production plan-library record was changed.

## PE03. Verification and artifacts

The isolated directory `data/verification/2026-10-17-predecessor-continuity/` contains the original-context provenance in `predecessor-evidence.json`, four importable text files, recorded-AI replay results, public confirmation projections, and frozen research candidates. Only files 1 and 2 have appended, verified predecessor excerpts; the original research files are unchanged. These context-bearing inputs can be imported without manually entering maximum position or exit scope. The application does not automatically retrieve the external conversation.

`prepare.py` replays recorded real AI responses through current extraction and validation. It makes no new AI request. The first three diagnostic candidates are prepared independently; the fourth uses the third's exact reviewed research predecessor. This is not proof of a newly generated four-step AI update chain. Research review is explicitly labelled and does not approve records in the production library.

| Effective date | Result |
|---|---|
| 2026-09-24 | Maximum 300 and zero opening inventory are source-backed; research review succeeds with unknown cash. |
| 2026-09-28 | Full-exit scope and fixed priority resolve automatically; the user's `RESUME_FIRST_CLOSE` supplement resolves the last policy blocker and research review succeeds. |
| 2026-09-30 | Policy validation and isolated research review succeed. |
| 2026-10-09 | Actual third-to-fourth update replay and research review succeed; no processing issues. |

All unit tests plus the relevant library, source-confirmation, review, and actual-successor integration tests: **3,302 passed**, with one existing Starlette/httpx deprecation warning. New focused regressions cover literal maximum, full-exit targets, wrong price, negation, questions, severe-only scope, fixed priority, and the real second response's business confirmation. Ruff passes.

Bounded calls to the configured market provider retrieved 42 calendar rows, 23 daily bars, 23 adjustment-factor rows, six daily limits, and six source minute batches of 241 rows. Strict historical normalization accepts **240 minutes per session**, **1,440 total**, for 2026-09-24, 2026-09-28, 2026-09-29, 2026-09-30, 2026-10-08, and 2026-10-09. `market-quality.json` records this verification. Retrospective availability uses the existing research convention of daily 15:20 and limits 09:30; it is not contemporaneous collection evidence. Raw prices and factors are retained.

## PE04. Continuous-backtest status

**The four-plan continuous replay completed after the user's confirmation.** `resume.py` corrected and reviewed the second candidate, composed the four reviewed plans, froze the real market dataset, and called the native `run_frozen_loop` path. The published job is `COMPLETED`; reopening the result store returns the identical report. The isolated script initially omitted job heartbeats, so publication required the existing expired-lease recovery path in `publish_completed.py` (attempt 2). The staged report was verified and reused without rerunning or changing market/account facts; the script now sends heartbeats during evaluation.

- Run ID: `39a6efa77ecde5696f2ac9e8198c9c4ee88f4ab25c17b89cd0b324a048c8216b`.
- Period: 2026-09-24 through 2026-10-09, six trading sessions and 1,440 normalized minute bars; 1,468 evaluations include calendar/boundary events.
- Exactly three `REPLACED` events occur on 2026-09-28, 2026-09-30, and 2026-10-09, in the reviewed order. The opening cash remains `UNKNOWN` and inventory remains zero throughout; successor source descriptions do not reset this account. There are no trades in this run, so it does not independently demonstrate carrying a filled position through a switch.
- The published audit contains 2,955 events and passes `verify_loop_events`. `verify_completed.py` also checks all transition identities, maximum 300, full-exit targets 0/0, the explicit `RESUME_FIRST_CLOSE` choice, and the final account. `continuous-report.json`, `continuous-audit.ndjson`, `continuous-summary.json`, and `completed-job.json` retain the evidence. The earlier `summary.json` is the pre-confirmation diagnostic snapshot.
- Rechecked the suspension and predecessor regressions: **15 passed**. These overlap the earlier 3,302-test run and are not added to it as distinct tests.

**This validates completion and continuity of the workflow, not strategy profitability.** There are zero order intents and zero fills. The current native frozen replay supplies no verified daily price-basis series (`loop_replay._Frames._inputs` uses `series=None`), producing `PRICE_BASIS_UNVERIFIED` in 1,465 evaluations. Downloading raw daily prices and adjustment factors alone does not repair that adapter limitation; it is an implementation/data-evidence issue, not another missing source parameter. Qualitative stabilization, retest, and volume facts also remain unverified. Cash is unknown, so equity, interval return, and maximum drawdown are unknown (`null`), not zero. The run must not be interpreted as evidence that the strategy had no trading opportunities.

The isolated simulation uses `FOLLOW_REMINDERS` and explicit illustrative costs: commission 0.0003, minimum commission 500 fen, stamp duty 0.0005, transfer fee 0.00001, and buy/sell slippage 1 fen each. These are reproducibility inputs, not verified broker charges; no fees were incurred because there were no fills. Production library records and the running application were not modified by this research verification.

Follow-up (2026-10-17): the daily-series limitation and new-preparation cash requirement were addressed in [DB-V01–DB-V05](2026-10-17-daily-basis.md). This historical report retains its original run and results.
