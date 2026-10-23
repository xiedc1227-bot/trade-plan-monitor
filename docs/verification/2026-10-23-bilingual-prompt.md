# Bilingual prompt live verification — 2026-10-23

## Result and scope

**Not fully accepted; bilingual extraction outcomes are not identical across all five cases.** English produced two successful reminder drafts and two correct refusals; the exit/reassessment case failed extraction through output truncation. Fresh Chinese control produced three successful reminder drafts and two correct refusals. Both languages also have appendix deviations, so machine success alone is not full acceptance.

Used the unchanged README.md and README.zh-CN.md prompts at commit `369ba177e57213b968fd3aa35c0f929fa06150fa`. No README, extraction contract, production code, model budget or historical evidence was changed. This is verification only; no commit or push was performed.

## Method and acceptance

One English round followed by one Chinese control round used the same five synthetic cases, software context and JSON delivery wrapper as [the previous verification](2026-10-23-clarified-prompt.md), `run-v7`. Their equality is asserted in the offline analysis. Only the README prompt language changed; the supplied facts and wrapper stayed Chinese. This tests the English reusable prompt under identical inputs, not a fully English end-user conversation.

Configured `deepseek-flash`: 50,000 input characters, 4096 output tokens, 30-second timeout, 2 maximum retries. Actual totals: 10 generation calls + 6 extraction calls = 16 provider attempts, with no retries. No live market retrieval. Started at 2026-10-23 15:33 UTC (23:33 UTC+08:00).

The harness copies the previous checks and cases. It accepts cost vocabulary and the prescribed validity sentence in either language, and equivalent English source-condition wording. The exact validity assertion now runs for negative cases too, matching the previous manual acceptance requirement for all five cases. It does not accept a near-synonym as the required exact sentence. A's heading, refusal string, schema and source-review checks remain unchanged. Appendix scope/accuracy are also reviewed manually with the same standard for both languages.

Only original A is sent to the real production extractor; refusal strings are not extracted. Raw generation/extraction responses, including the truncated response, are preserved. No response repair, source compression, binding removal, prompt revision, increased limit or retry-until-pass occurred.

## Paired results

| Case | English | Fresh Chinese | Comparison |
| --- | --- | --- | --- |
| sse-one-alert | SUCCEEDED; 1 alert | SUCCEEDED; 1 alert | All draft fields identical except generated `plan_id` |
| szse-two-alerts | SUCCEEDED; 2 alerts | SUCCEEDED; 2 alerts | Entire draft identical |
| missing-position-limit | Exact refusal | Exact refusal | Both refuse without guessing maximum holdings |
| unsupported-index-buy | Exact refusal | Exact refusal | Both preserve the unsupported dependency; no unauthorized substitute |
| source-exit-reassessment | INVALID_OUTPUT; AI_OUTPUT_TRUNCATED; no draft | SUCCEEDED; 2 alerts | No validated English draft exists to establish equivalence |

All five successful drafts have zero issues, assumptions and warnings, no ordinary/risk rules, and pass structural conversion and source review. Both negative A strings equal `暂不提供可导入正文。`. Costs remain in B for all ten generations, without fee/PnL calculations or cost fields added to A. Both source-condition B outputs retain exit before the 2026-11-03 close and reassessment after the 2026-11-04 close.

Against historical Chinese `run-v7`, the fresh single-alert drafts both use `reference.as_of=2026-10-21` where the historical output used `null`; English also has a different generated plan ID. The fresh bilingual pair agrees on the actual date and matches the supplied facts. The two-alert drafts exactly match the historical draft. These are not claims that every historical byte is reproduced.

## Failure evidence and interpretation

### Extraction budget

The exit/reassessment A strings each contain 891 characters and become equal after whitespace normalization **for diagnosis only**. The English output splits root fields over 20 lines; Chinese groups them into 11 lines. Original, unnormalized A was submitted in both runs.

| Measurement | English | Chinese |
| --- | --- | --- |
| Extraction prompt tokens | 14391 | 13997 |
| Extraction completion tokens | 4096 | 3690 |
| Finish reason | length | stop |
| Result | AI_OUTPUT_TRUNCATED | SUCCEEDED |

The English response expands source clauses for the split root fields and is cut off near the final confirmation binding. The observed extra representation consumes the fixed output budget. This supports a formatting/token-pressure explanation; one pair does not establish a language-wide failure rate or isolate all model variation. The current validator correctly rejects the incomplete response without creating a draft. Evidence completeness was not weakened to obtain success.

### Appendix deviations

- English, all five cases: paraphrases validity into Chinese (for example `计划在人工停用前持续有效`), preserving meaning but omitting both the prescribed English sentence and its prescribed Chinese counterpart. Exact wording fails 0/5 pass; semantic validity remains present in 5/5. This is a delivery deviation, not a changed trading lifetime.
- Both languages, `sse-one-alert`: label unrelated history, volume, reports and index gaps as “currently necessary missing inputs,” even while explaining they do not affect the reminder. This repeats a previously rejected appendix pattern.
- English, `unsupported-index-buy`: incorrectly writes `S1/S2` in its capability explanation instead of `S0/S1`, and lists unrelated missing parameters. The A refusal and unsupported dependency remain intact.
- English, `source-exit-reassessment`: adds “wait for manual activation” operating-process wording. It does not actually activate anything or claim extraction passed.
- Chinese, `unsupported-index-buy`: adds a future request to supplement unspecified report conditions, beyond waiting for the required capability.
- Chinese, `source-exit-reassessment`: “the above account information is not written into A” follows a list including maximum holdings, making the explanation ambiguous; actual A correctly retains `position.max_qty=800`.

Fresh Chinese automated checks pass 5/5; manual deviations prevent a full clean acceptance claim. English automated checks pass 0/5 because every appendix misses the exact validity sentence, with one additional extraction failure. Do not equate this 0/5 delivery score with failure of all machine policies.

## Verification, preservation and limits

All six original extraction responses were replayed offline with their original request/provider identity, content, finish reason and usage: five successes and the one truncation rejection reproduced exactly, including source mappings and issues. Existing contract, empty-array, source-review and security regressions: **50 passed in 1.67s**.

The harness uses configured AI and the pure extraction function; it does not open the application database, save a draft, confirm review, activate a plan or mutate inventory. Configuration hashes before/after each round match. Existing tracked files remain unchanged; only this paired report and new verification evidence were added. This is not a global database snapshot claim about other concurrent activity. The native-memory route remains paused.

Do not declare bilingual equivalence or repeat unchanged prompts until a preferred result appears. A later, separately authorized prompt-only correction could enforce compact root grouping and exact validity wording, narrow B to the current blocker and resolve the `S0/S1` explanation, followed by the same five-case check. No such correction was applied here.

Evidence: [comparison and replay](evidence/2026-10-23-bilingual-prompt/comparison.json), [manual review](evidence/2026-10-23-bilingual-prompt/manual-review.json), [content manifest](evidence/2026-10-23-bilingual-prompt/manifest.json). `run-en-1` and `run-zh-1` preserve full requests, original responses, A/B texts and production extraction results. Hashes use UTF-8 text with CRLF normalized to LF for checkout portability. The live harness is `verify_live.py`; offline reproduction is `analyze.py` in that directory.
