# Generic prompt deduplication and capability clarification — 2026-10-23

## Change scope

Updated the generation prompt in README.md and README.zh-CN.md together. Consolidated unknown-data, reminder-only and document-authority constraints; made data collection conditional on current needs instead of a 250-session target; removed unused L, the duplicate root-field example and the unselected static-branch workflow suggestion. B is organized by whether A is provided or blocked, without prescribed sections or filled-out tables.

Holding-cost input and exact preservation, software-owned fee/PnL calculations, general validity, original trading principles and market effects remain. No input was added. Clarified that B cost is not automatically entered into an account; incomplete candidates differ from fully executable validation; ordinary quantities and maximum holdings require positive multiples of 100, ordinary buys target TACTICAL and cannot establish CORE. Automatic index switching is unsupported while static stock conditions are assessed individually. Block quantities that cannot satisfy both actual market rules and the software contract, without rounding to force acceptance.

The verified reminder-only A template is unchanged, including root paths, parent scopes, empty arrays, types and source requirements. The required literal first line “计划根字段语义值” is explicitly enforced in final delivery instructions. Fixed references use factual source labels; purpose explanations stay in B. README text outside the prompt and the independent live-AI verification procedure are unchanged.

## Same samples and live calls

Reused the identical verify_live.py and five cases from the earlier validity verification; sample facts and automated assertions are unchanged. The Chinese README prompt was sent to the provider. English was reviewed for semantic parity, not separately provider-tested. Synthetic cases did not fetch live market data.

Configured deepseek-flash retained 50000 input characters, 4096 output tokens, 30-second timeout and 2 maximum retries. Seven rounds each generated five cases and extracted the three positive cases: 35 generation calls, 21 extraction calls, 56 provider attempts. This was not repeated sampling of an unchanged prompt: every round followed a documented formatting or appendix finding and a prompt revision. No original response repair, manual heading insertion, binding removal or relaxed validation occurred.

## Intermediate findings and final results

- Rounds 1–2: extraction itself passed for the three positive cases, but A omitted the mandatory heading, so overall acceptance failed.
- Round 3: machine checks passed; unsupported-case B still listed unrelated parameters and suggested a static branch.
- Round 4: machine checks passed; reminder B calculated addition capacity and blocked B expanded conditional alternatives.
- Rounds 5–6: machine checks passed; B still followed the market section's static-branch workflow text. Round 5 also placed background data gaps under current necessary missing inputs in one reminder.
- Round 7: after removing the conflicting static-branch workflow sentence, the checks below passed. All rounds, failed outputs and human observations remain archived.

| Case | Final result |
| --- | --- |
| sse-one-alert | SUCCEEDED; 1 alert, 0 ordinary rules, 0 risk branches; cost none preserved |
| szse-two-alerts | SUCCEEDED; 2 alerts, 0 ordinary rules, 0 risk branches; cost 80.00 preserved; no prior-symbol leakage |
| missing-position-limit | A exactly “暂不提供可导入正文。”; waits only for the maximum, no guessed quantity; unknown cost preserved |
| unsupported-index-buy | A exactly “暂不提供可导入正文。”; index dependency retained, no reminder downgrade or buy rule; cost 35 preserved |
| source-exit-reassessment | SUCCEEDED; 2 alerts, 0 ordinary rules, 0 risk branches; cost 80.00 and exit before the 2026-11-03 close / reassess after the 2026-11-04 close preserved in B |

All three positives have zero issues, assumptions and warnings and structurally convert; this grants neither review nor activation. Negative cases block at generation; per the separate procedure, refusal text is not sent to the extractor and is not called an extraction success. Every B retains “计划持续有效，直至人工停用”, no fee/PnL calculations and no requests for removed inputs.

One prose observation remains: final unsupported B restates in one sentence that other trading parameters were undefined, but does not request them, suggest another branch, invent values or put them into A. This is not a guarantee of perfectly minimal prose; the raw text is preserved without repair.

## Regression, preservation and limits

Existing strict extraction/source/empty-array/security regression: 50 passed in 1.70s. Input fields and the reminder template are unchanged in both READMEs. Core levels, ordinary confirmation, risk and source-condition sections and the market sizing table remain consistent. Capability clarification did not modify production models or validators.

Read-only before/after snapshots match: Shennong version daa0387c-26b2-4e5f-8ea1-b4ea142ecedb remains DRAFT, review revision 0, unconfirmed and inactive, with 1 reminder and 0 trade/liquidation rules. Protected inventory, risk, history and configuration state are unchanged. No sample was saved, inventory initialized, review confirmed or plan activated. Other tasks were untouched; no commit or push was performed.

These cases cover single/double reminders, symbol changes, missing maximum, unsupported index dependencies and source-condition preservation, not every board, every trading strategy or every future model output. Paired reports, original requests/responses, hashes, per-round results, human observations and protected snapshots are linked from [verification](evidence/2026-10-23-clarified-prompt/verification.json), [manual review](evidence/2026-10-23-clarified-prompt/manual-review.json) and [documentation checks](evidence/2026-10-23-clarified-prompt/documentation-checks.json).
