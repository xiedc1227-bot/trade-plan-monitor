# Plan-only prompt verification — 2026-10-23

## Scope and outcome

The English and Chinese README prompts now request only the report, current actual holdings and maximum planned holdings. Holding-cost input, fee assumptions, breakeven/PnL/net-return calculations and minimum-spread research are removed. Calculations belong to software; this change does not add or claim a software accounting capability. Unrelated simulation, notification and historical-storage procedures, redundant input interpretation and forced research expansion for independent reminders are removed or condensed.

Original CORE/TACTICAL principles, ordinary daily timing, risk priority, source deadlines and index-state sizing/confirmation/pause remain. Both fenced A-format examples are unchanged against the committed baseline. No production extractor, Schema, validator, provider configuration or tests were modified.

The final real `deepseek-flash` run passed both normal sources through complete extraction and source review; both negative samples blocked importable generation. The appendices contain no fee/PnL calculations or requests for deleted inputs. Appendix prose still has limitations described below; passing extraction is not plan approval.

## Samples and real results

These are the same four synthetic cases as the [previous compact-prompt validation](2026-10-23-compact-prompt.md), with only obsolete cost phrases removed from input facts. Stock identities, holdings, limits, thresholds, dates, dependencies and expected outcomes are unchanged. No live market data was requested. The Chinese README prompt was used for real calls; English was checked for semantic parity, not separately submitted.

| Case | Final result |
| --- | --- |
| 包钢股份 `600010.SH`, actual 0, maximum 500 | `SUCCEEDED`; 1 reminder, official daily close `LT 1207 FEN`; 0 ordinary rules, 0 risk branches |
| 五粮液 `000858.SZ`, actual 200, maximum 800 | `SUCCEEDED`; 2 reminders, official daily close `LT 7432 FEN` and `GT 8567 FEN`; 0 ordinary rules, 0 risk branches |
| 贵州茅台 `600519.SH`, maximum unknown | A exactly `暂不提供可导入正文。`; no extraction call; only `position.max_qty` requires confirmation |
| 招商银行 `600036.SH`, actual 400, maximum 1200 | Same blocking A; no extraction call; mandatory automatic index-linked 200/100-share selection, S0/S1 switching and pause remain unsupported; no weakened BUY or unauthorized reminder fallback |

Both normal candidates have zero issues, assumptions and warnings, matching source bindings and structurally executable drafts. Old stock values do not leak. Their pending confirmation lists contain no missing items.

Budgets remain **50,000 input characters / 4096 output tokens / 30 seconds / 2 maximum retries**. Final extraction requests used 47,650 and 48,478 characters; outputs used 2627 and 3698 tokens. All six final provider calls finished with `stop`, one attempt each. Raw A was passed unchanged to the real production extraction function, including its normal strict source review.

## Iterations and appendix review

All four runs and raw outputs are retained in [evidence](evidence/2026-10-23-plan-only-prompt/verification.json). Every run passed the machine pipeline; further revisions addressed observed appendix overconfirmation, not Schema failures.

| Run | Observed appendix issue and change |
| --- | --- |
| `run-v1` | Unsupported case listed generic missing parameters/deadlines and alternative-branch selection; constrain pending confirmations |
| `run-v2` | Unchosen alternative requirements persisted elsewhere; extend the restriction across B |
| `run-v3` | Forced six-section expansion still elicited speculative parameter requests; make blocked B contain only known facts, blockers and current necessary confirmations |
| `run-v4` | Final: no deleted-input requests or fee calculations; normal pending lists empty; missing-cap case asks only for the cap; unsupported case explicitly declines further parameter/deadline requests |

The transport instruction for `run-v4` calls B an appendix string instead of unconditionally a six-section string, matching the conditional README format. Cases and checks were unchanged. Total: 16 generation calls, 8 extraction calls, 24 provider attempts. No output repairs or validator relaxations occurred. Requests, original response strings, hashes, results and runners are archived.

Remaining prose deviations are disclosed rather than edited: the two-reminder appendix merges content into five sections instead of six; the unsupported appendix still mentions undefined parameters including deadlines in its explanation, although its pending list explicitly says not to request them. Its statement that fixed daily-price comparisons only support LT/GT is also narrower than the actual registered comparison capabilities; LT/GT were the supplied sample examples, not a complete capability list. These statements do not enter A or change the blocking decision. Human review must correct such explanatory claims before reuse. No claim of perfect appendix conformity or arbitrary-condition coverage is made.

## Regression and state preservation

- Existing strict regression: **50 passed in 2.27s**. Command: `.venv/Scripts/python.exe -X utf8 -m pytest tests/unit/test_compact_prompt_replay.py tests/unit/test_current_review_contract.py tests/unit/test_empty_array_contract_replay.py tests/unit/test_current_plan_extraction_security.py -q`.
- Covers accepted raw responses, truncated-output rejection, empty-array typing, provenance/bindings, missing limits and unsupported conditions. No test or check was removed or weakened.
- README language review preserves the ten main sections, index formulas, authority boundaries and exact A examples. The final Chinese inner prompt matches the actual final-run prompt hash. See [documentation checks](evidence/2026-10-23-plan-only-prompt/documentation-checks.json).
- Read-only before/after snapshots match: the original 神农集团 draft remains `DRAFT`, review revision 0, unconfirmed, with 1 reminder and 0 ordinary/risk rules; active-plan state remains empty. Inventory, risk, relevant history/review records and configuration hashes match. See [preservation](evidence/2026-10-23-plan-only-prompt/preservation.json).

No application draft was saved, review confirmed, plan activated, or actual/simulated inventory changed. Other tasks' native experiment files were not edited or included. No commit or push was requested for this change.
