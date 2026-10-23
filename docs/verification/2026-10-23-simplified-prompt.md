# Simplified input prompt — live verification, 2026-10-23

## SP-V01 — Outcome

**NOT_FULLY_PASSED.** The configured `deepseek-flash` generated all four cases. One of two normal sources passed complete extraction; the other hit the 4096-token output limit and returned `AI_OUTPUT_TRUNCATED` with `draft=null`. Both expected blocking cases correctly withheld importable source. The separate requirement to avoid reintroducing deleted input requirements also did not fully pass.

This is a synthetic prompt/extraction test, not current market research. There was no live market-data call, response repair, relaxed validation, configuration change or repeated attempt to obtain a green result.

## SP-V02 — Inputs and method

The runner read the exact Chinese prompt block from README. SHA-256: `3cec277c53d188c0d96c16d82b1d2931ed965381eab5e1653e212eeda7dcdc4a`.

The same four scenarios retained their symbols, holdings, limits, price predicates and unsupported dependency. To test the reduced input requirements, the case text omitted broker-order status, supplied draft identifiers/versions, explicit count form wording and preassigned CORE/TACTICAL allocation. Natural-language requests for independent reminders or a trade draft remained. The two independent conditions themselves determine the two-alert expectation; the user need not fill a reminder-count field.

Generation returned JSON-wrapped A/B. The exact decoded A string was passed to the production `extract_plan` pipeline; B was separately inspected for follow-up requests and capability claims. Blocked A was required to equal `暂不提供可导入正文。` and was not sent to extraction. No application draft was saved.

Unchanged provider configuration: `deepseek-flash`, 50000 input characters, 4096 output tokens, 30-second timeout, maximum 2 retries. Actual calls: 4 generation, 2 extraction, 6 provider attempts. Each case ran once. English documentation received parity checks, not separate live generation.

## SP-V03 — Case results

| Case | Result | Evidence |
|---|---|---|
| `sse-one-alert` | Complete extraction pass | `600010.SH`, max 500, exactly 1 `RISK_ALERT`, official daily close `LT "1207" FEN`; 0 ordinary rules, 0 risk branches; no validation issues, assumptions or warnings; executable structure available |
| `szse-two-alerts` | Extraction blocked | A defines `000858.SZ`, max 800, `LT "7432" FEN` and `GT "8567" FEN`, with no trade/liquidation rules. Provider output reached 4096 tokens, `finish_reason=length`; `AI_OUTPUT_TRUNCATED`, accepted draft absent |
| `missing-position-limit` | Correct generation block | `600519.SH`, unknown limit not guessed; A withholds importable source and B identifies required `position.max_qty`; no extraction call |
| `unsupported-index-buy` | Correct generation block | `600036.SH`, required automatic index-linked quantity/confirmation/pause unsupported; no stripped BUY, invented human fact or unauthorized reminder fallback; no extraction call |

Generated normal sources did not inherit the prior stock's prices or limit. New draft identifiers were generated without asking the user for technical IDs or versions. Structural validity of the first candidate does not mean review or activation.

## SP-V04 — Deleted-input and appendix review

- No case requested broker pending orders, partial fills or fill-status records.
- No case asked the user to enter plan identifiers/versions, choose a mode, specify a reminder count or provide simulation inventory. Reporting the selected mode/count and saying simulation is out of scope are not input requests.
- **Deviation:** the two-alert appendix B.6 lists `底仓/机动仓划分未定。` under future pending items although no trade rule depends on allocation. This is not a direct question, but reintroduces an input the simplified prompt was intended to eliminate; the acceptance requirement is not met.
- The unsupported-index appendix mentions checking allocation only if a future rule depends on it. That conditional statement differs from the irrelevant pending item in the reminder-only case; no allocation was added to A.
- **Additional deviation:** the two-alert appendix speculates that a second research-evidence dimension might be required for the explicitly supplied synthetic independent thresholds. No such extra gate was added to A, but this is an unnecessary confirmation suggestion.
- **Additional deviation:** the unsupported-index appendix B.5 says `执行才产生真实委托。` This misstates the current tool's capabilities: it does not execute broker orders. No actual order action occurred.

Follow-up work should address redundant model output within the existing budgets and require B to list only missing information that an actual current rule depends on. Independent reminders must not acquire allocation prerequisites, and broker execution must not be attributed to the tool. This verification did not modify the prompt body or implementation after observing failures and did not repair any response.

## SP-V05 — Evidence and state preservation

[Manifest](evidence/2026-10-23-simplified-prompt/verification.json), [manual output review](evidence/2026-10-23-simplified-prompt/manual-output-review.json) and the four case files retain exact A/B strings, provider response content, request text, hashes, usage and extraction results. Hashes cover provider content strings, not raw HTTP bytes. The mechanical pipeline summary and manual semantic findings remain separate. No credential values are included.

Read-only before/after snapshots match for configuration, existing draft/review provenance, activation tables, actual/simulation inventory, risk state, target daily history and storage constraint. Existing `SNGC-OBS-20261022` remains `DRAFT`, review revision 0, no confirmation, 1 alert, 0 ordinary rules and 0 risk branches. No plan was saved, reviewed or activated; no inventory was changed. Historical evidence remains intact.
