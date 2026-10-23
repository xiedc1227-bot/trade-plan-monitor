# Unified plan validity verification — 2026-10-23

## Scope and corrections

Real generation used the Chinese README prompt with restored holding cost and simplified general validity. English received semantic parity review rather than separate live calls. A examples, production code, Schema, source review, configuration and budgets remain unchanged.

The original four cost-input cases are unchanged. They have no explicit source exit/reassessment requirements, so a fifth, clearly separate contrast derives from the two-alert case: retain human exit before the 2026-11-03 close and reassessment after the 2026-11-04 close in B, while A still contains only the two independently authorized reminders. This tests preservation in human rules, not machine execution of exits or an actual market plan.

Two diagnosed corrections were necessary. In `run-v1`, all actual extraction/blocking results were correct, but three importable B responses omitted the general validity, and the two-alert A omitted the documented heading. The existing instructions were clarified to explicitly require validity in B and retain A's first line. In `run-v2`, only the one-alert B still omitted validity. The single validity instruction was moved from trading principles into B's output requirements, without duplicating it or restoring fixed appendix sections. `run-v3` then passed all five cases. Failed sources and responses remain unchanged in evidence.

## Final results

| Case | Cost retained in B | Result |
| --- | --- | --- |
| `600010.SH`, maximum 500 | `无` | Full `SUCCEEDED`, 1 reminder, 0 ordinary/risk rules |
| `000858.SZ`, maximum 800 | `80.00元／股` | Full `SUCCEEDED`, 2 reminders, 0 ordinary/risk rules |
| `600519.SH`, maximum unknown | `未知`, not zero | A exactly `暂不提供可导入正文。`; no extraction; only maximum requires confirmation |
| `600036.SH`, mandatory automatic index linkage | `35元／股` | Same exact blocking A; no extraction; no weakened BUY or unauthorized reminder |
| Separate source-condition contrast on `000858.SZ` | `80.00元／股` | Full `SUCCEEDED`, 2 reminders, 0 ordinary/risk rules; both dated human rules retained in B |

All five B responses use the exact general wording `计划持续有效，直至人工停用`, without reviewed-replacement or `PLAN_ACTIVE` process wording. All five were manually read: no fee, tax, commission, slippage, breakeven, PnL, net-return or monetary holding-cost calculations were introduced. Share-capacity arithmetic is still plan scope. All accepted candidates have zero issues, assumptions and warnings, matching typed predicates, metadata, symbol, limits, source review and executable structure. Costs remain outside A.

The contrast B preserves `2026-11-03收盘前退出` and `2026-11-04收盘后重评` as human management rules and expressly prevents the reminders replacing or delaying them. The indefinite plan validity does not extend those conditions.

Model: configured `deepseek-flash`. Limits: 50,000 input characters, 4096 output tokens, 30 seconds, 2 maximum retries. Three rounds used 15 generation calls and 9 extraction calls, 24 provider attempts in total; every call used one attempt. The final round used 5 generation and 3 extraction calls. No response was repaired, stripped, filled or manually corrected; no validation was relaxed.

## Limits and evidence

Some explanatory deviations persist outside A: the unsupported B expands future/unselected alternatives and generic missing parameters; the missing-cap B wrongly associates the reminder threshold's source with the synthetic reference close. These explanations remain unedited and require human review, and are not accepted machine source or proof of threshold provenance. No assertion of perfect appendix compliance or arbitrary-policy coverage is made.

Original prompts, requests, response strings, hashes, extraction results and runners are archived in [evidence](evidence/2026-10-23-validity-prompt/verification.json), including both failed rounds and the final README prompt hashes. Real verification remains a separate procedure outside the copyable prompt.

## Regression and preservation

The existing strict command `.venv/Scripts/python.exe -X utf8 -m pytest tests/unit/test_compact_prompt_replay.py tests/unit/test_current_review_contract.py tests/unit/test_empty_array_contract_replay.py tests/unit/test_current_plan_extraction_security.py -q` reports **50 passed in 2.09s**. No production or test code was changed.

Read-only [before/after state](evidence/2026-10-23-validity-prompt/preservation.json) matches: original 神农集团 draft is unconfirmed `DRAFT`, review revision 0, with 1 reminder, 0 ordinary/risk rules and no active state. Protected inventory, risk, history/review and configuration hashes match. No application draft was saved, review confirmed, plan activated, or actual/simulated inventory changed. Other tasks' files are untouched. No commit or push was performed.
