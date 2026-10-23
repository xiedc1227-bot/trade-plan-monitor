# Four-part generation prompt verification — 2026-10-23

## Change

The English/Chinese README prompts now have four main sections: necessary inputs; trading principles and market effects; the verified A format; and an on-demand B appendix. The copied trading, risk, deadline, index and position rules retain their wording apart from heading nesting. Both A examples match the previous committed format exactly. Other A instructions are consolidated by purpose rather than repeated as separate checklists.

Real AI verification is moved out of the copyable prompt into the paired [procedure](../operations/trade-prompt-ai-verification.md). B has no fixed section count, required table or requirement to fill unrelated research. Inputs remain report, actual shares and maximum shares. No cost/fee/order/fill/cash/simulation/mode/count/identity inputs are restored. No production code, strict validation, tests or provider budgets change.

The Chinese prompt shrinks from 10452 to 7014 characters; English from 28546 to 18520. The final Chinese prompt was sent to the provider; English received semantic parity review, not separate live calls.

## Real verification

The same four synthetic inputs and strict runner from the preceding [plan-only verification](2026-10-23-plan-only-prompt.md) are used unchanged. No market fetches or real stock recommendations are involved. Model `deepseek-flash`; budgets remain 50,000 input characters, 4096 output tokens, 30 seconds and 2 maximum retries.

| Sample | Final `run-v2` result |
| --- | --- |
| `600010.SH`, actual 0, maximum 500 | Full `SUCCEEDED`; 1 official daily-close reminder, `LT 1207 FEN`; 0 ordinary rules, 0 risk branches |
| `000858.SZ`, actual 200, maximum 800 | Full `SUCCEEDED`; 2 official daily-close reminders, `LT 7432 FEN` / `GT 8567 FEN`; 0 ordinary rules, 0 risk branches |
| `600519.SH`, maximum unknown | A exactly `暂不提供可导入正文。`; no extraction call; only maximum requires confirmation |
| `600036.SH`, mandatory runtime index-linked 200/100 shares and S0/S1 switching/pause | Same exact blocking A; no extraction; no weakened BUY or unauthorized reminder fallback |

Accepted candidates have no issues, assumptions or warnings, match the typed predicates/metadata/cap/symbol and pass strict source review and structural conversion. Raw A and responses were not modified. Every provider call used one attempt. All 12 calls across two runs are archived with their original requests/responses and hashes in [evidence](evidence/2026-10-23-structured-prompt/verification.json).

First-run failure is retained: the missing-cap A appended an explanation after the required blocking sentence, so its exact-source check failed. The single existing blocker instruction was clarified to prohibit appended explanations, and the prompt was revalidated. The unsupported B also listed generic future parameters; its existing relevance instruction was tightened without adding new sections. No unchanged-prompt retries or output repair occurred.

Final B has no fee calculations or deleted-input requests. Normal pending lists are empty; the missing-cap case asks only for the cap. However, the unsupported-case appendix still expands unselected future strategies and generic missing parameters/deadlines despite the relevance instruction. This is an observed model prose deviation, not an A policy or an additional README requirement. It remains unedited and requires human review. A model independently choosing six headings is permitted; six headings are no longer mandatory. Machine acceptance does not certify all prose as compliant.

## Regression and preservation

The existing focused command `.venv/Scripts/python.exe -X utf8 -m pytest tests/unit/test_compact_prompt_replay.py tests/unit/test_current_review_contract.py tests/unit/test_empty_array_contract_replay.py tests/unit/test_current_plan_extraction_security.py -q` reports **50 passed in 2.27s**. It retains truncation rejection, empty-array typing, binding/provenance, missing-input and unsupported-condition checks.

Read-only [before/after preservation](evidence/2026-10-23-structured-prompt/preservation.json) matches: original 神农集团 draft remains unconfirmed `DRAFT`, review revision 0, 1 reminder and 0 ordinary/risk rules. Active state is empty; protected inventory/risk/history/review/configuration hashes match. No application draft was saved, review confirmed, plan activated or inventory changed. Other tasks' files are untouched. No commit or push was requested.
