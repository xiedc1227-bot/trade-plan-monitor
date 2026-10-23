# Restored holding-cost input verification — 2026-10-23

## Scope

Real generation used the current Chinese README prompt, including the restored optional per-share holding-cost input and preservation in B. English received parity review, not separate provider calls. Both A format examples are unchanged. No production code, extractor, Schema, validator or provider configuration was modified.

The same four synthetic cross-symbol cases were reused, restoring their original cost phrases that the preceding plan-only runs had removed. Other sample facts and existing extraction assertions remain unchanged. The runner adds cost-preservation checks for B and rejects cost text introduced into A. Raw responses are not repaired. Synthetic values are not current market data.

## Results

One run, `run-v1`, passed. The configured model was `deepseek-flash`; all 4 generation and 2 extraction calls completed with `stop`, one provider attempt each. Limits stayed at 50,000 input characters, 4096 output tokens, 30 seconds and 2 maximum retries.

| Sample | Cost retained in B | Policy result |
| --- | --- | --- |
| `600010.SH`, actual 0, maximum 500 | `无` | Full `SUCCEEDED`; exactly 1 official daily-close reminder, `LT 1207 FEN`; no ordinary/risk rules |
| `000858.SZ`, actual 200, maximum 800 | `80.00元/股` | Full `SUCCEEDED`; exactly 2 reminders, `LT 7432 FEN` and `GT 8567 FEN`; no ordinary/risk rules |
| `600519.SH`, maximum unknown | `未知`, not zero | Exact blocking A `暂不提供可导入正文。`; no extraction; only the maximum requires confirmation |
| `600036.SH`, actual 400, maximum 1200 | `35元／股` | Same blocking A; no extraction; mandatory automatic index-linked sizing/confirmation/pause remains unsupported, without weakened BUY or unauthorized reminder fallback |

Normal candidates have no issues, assumptions or warnings, matching source bindings, metadata, symbol, limits and typed predicates, and structurally executable drafts. All four B responses were read manually: no commission, tax, slippage, breakeven, PnL, net return or monetary holding-cost calculations were added. The two-alert B computes only available share capacity, which remains within plan scope. Cost stays in B and is not added to undefined A fields. This does not establish an automatic transfer from B into program accounting or verification of an accounting feature.

## Remaining prose deviations

The two-alert appendix suggests data for a hypothetical future trade strategy. The unsupported appendix mentions generic missing parameters/deadlines and a future software-capability scenario. The missing-cap appendix expands an imagined future source and labels the threshold with a synthetic reference-close source; this proposed source was neither imported nor extracted, and must not be treated as verified threshold provenance. These unnecessary expansions were preserved unchanged. They do not affect the actual A blocking results or cost preservation, but require human review before reuse. There was no prompt revision or retry to select a preferred response.

## Evidence and preservation

Original prompts, requests, response strings, source hashes, extraction results, cost lines and runners are retained in [evidence](evidence/2026-10-23-cost-input-prompt/verification.json). Manual review and regression records are separate JSON files in that directory. Final README prompt hashes match the actual run; exact A examples match the committed baseline.

Existing strict regression command `.venv/Scripts/python.exe -X utf8 -m pytest tests/unit/test_compact_prompt_replay.py tests/unit/test_current_review_contract.py tests/unit/test_empty_array_contract_replay.py tests/unit/test_current_plan_extraction_security.py -q` reports **50 passed in 2.36s**.

Read-only [before/after snapshots](evidence/2026-10-23-cost-input-prompt/preservation.json) match. The original 神农集团 draft remains unconfirmed `DRAFT`, review revision 0, with 1 reminder and 0 ordinary/risk rules; active state remains empty. Protected inventory, risk, history/review and configuration hashes are unchanged. No plan was saved, review confirmed, plan activated or actual/simulated inventory modified. Other tasks' evidence is untouched. No commit or push was performed.
