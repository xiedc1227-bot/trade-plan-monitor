# Bilingual generation-prompt correction verification — 2026-10-23

## Outcome

**All five paired A outputs are identical, all three paired validated drafts are identical, and neither language truncates in this round.** Exact validity wording, compact roots, S0/S1 naming and removal of unnecessary supplementation requests meet the requested checks. Some extra appendix statements remain, so this is not full compliance with every prose instruction.

## Changes and boundaries

Only the generation-prompt blocks in README.md and README.zh-CN.md changed: four compact root lines; the shared exact sentence `计划持续有效，直至人工停用。`; S0/S1 instead of the incorrect capability-boundary S1/S2; exclusion of unrelated background gaps and absent report conditions from supplementation requests; cost in B without accidentally excluding required position.max_qty from A. The existing S1/S2 trading-condition definitions elsewhere were not changed.

Reminder templates and README content outside the prompt blocks are unchanged. This task changed no extraction contract, production code, model configuration or budget. Previous uncommitted evidence is preserved: all 104 entries in the prior evidence manifest were rehashed successfully. No commit or push was made. Native-memory work remains paused. Concurrent changes appeared in web/src/runtime-status/{App.vue,DashboardView.vue,store.ts,stream.ts} and web/tests/unit/runtimeConnectionBanner.spec.ts during verification; they were left untouched and excluded from this task's scope and findings.

## Live method and results

One English round and one Chinese round used the same five cases and identical software/delivery wrapper as the previous verification. Only README prompt language changed; case facts and wrapper remain Chinese. This is not a fully English user-input test.

Configured `deepseek-flash`: 50,000 input characters, 4096 output tokens, 30 seconds, 2 maximum retries. Actual: 10 generation calls, 6 extraction calls, 16 provider attempts, no retries. Original A was submitted without repair to the real production extractor. Negative refusal text was not sent for extraction.

| Case | English | Chinese | Paired comparison |
| --- | --- | --- | --- |
| sse-one-alert | SUCCEEDED; 1 alert | SUCCEEDED; 1 alert | A and entire draft identical |
| szse-two-alerts | SUCCEEDED; 2 alerts | SUCCEEDED; 2 alerts | A and entire draft identical |
| missing-position-limit | Exact refusal | Exact refusal | A identical; no guessed maximum |
| unsupported-index-buy | Exact refusal | Exact refusal | A identical; dependency retained |
| source-exit-reassessment | SUCCEEDED; 2 alerts | SUCCEEDED; 2 alerts | A and entire draft identical |

All six positive sources use four compact root lines. Their drafts have zero issues, assumptions and warnings; no ordinary or liquidation rules; valid structural conversion and source review. All ten B outputs preserve the exact validity sentence and supplied cost. Both relevant B outputs retain exit before the 2026-11-03 close and reassessment after the 2026-11-04 close. No fees/PnL calculation, unauthorized substitute, unrelated supplement request or activation occurs.

Both unsupported cases retain S0/S1 (ASCII or full-width slash) and block the entire rule. Background data gaps are described as unused research context, not necessary inputs. Cost-only explanations no longer imply that position.max_qty should be excluded from A.

## Before/after and evidence

| English exit/reassessment measurement | Previous failed round | Corrected round |
| --- | --- | --- |
| A lines | 20 | 11 |
| Extraction prompt tokens | 14391 | 13996 |
| Extraction completion tokens | 4096, truncated | 3709, complete |
| Finish reason | length | stop |
| Result | AI_OUTPUT_TRUNCATED; no draft | SUCCEEDED |

The corrected response leaves 387 tokens below the unchanged output cap. This is one observed successful response, not a guaranteed margin or population-level performance claim. Chinese exit/reassessment also completes at 3709 tokens. No source clauses or bindings were dropped to obtain success.

The initial harness incorrectly interpreted “standalone sentence” as “must occupy an entire line.” It therefore flagged one English and four Chinese outputs even though each contains the exact sentence with its preceding sentence boundary and punctuation. Original `verify_live.py`, responses and summaries remain unchanged. Offline `analyze.py` records the initial findings and separately verifies sentence boundaries; this resolves the five harness false positives without modifying model text or production validation. The corrected automated check passes 10/10. Same-paragraph exact sentences pass; paraphrases and prefixed fragments do not.

All six original extraction responses replay exactly, including source mappings and diagnostics. Existing contract, source-review, empty-array and security regressions: **50 passed in 1.69s**. Both rounds' configuration hashes are unchanged; the harness never opens the application database or saves/activates a plan. This is not a snapshot claim about unrelated concurrent database activity.

## Remaining prose deviations and stopping point

- English unsupported B still says other trading parameters are undefined, without listing them or requesting input.
- Chinese unsupported B still lists price, quantity, confirmation and deadline categories after saying they will not be invented. This exceeds the prompt's narrow appendix scope, although no supplementation is requested and the refusal is unchanged.
- Both single-alert appendices and the Chinese two-alert appendix still mention absent report exit/reassessment periods rather than omitting that topic. They add no deadline or waiting action.

The requested machine consistency and removal of extra supplementation requests are demonstrated in this round. Do not describe the appendices as perfectly minimal or fully instruction-compliant. Stop after this paired round; no further prompt edits or retry-until-pass sampling were performed. Historical failures and current original harness failures remain available.

Evidence: [comparison and replay](evidence/2026-10-23-bilingual-prompt-correction/comparison.json), [manual review](evidence/2026-10-23-bilingual-prompt-correction/manual-review.json), [documentation/preservation checks](evidence/2026-10-23-bilingual-prompt-correction/documentation-checks.json), [manifest](evidence/2026-10-23-bilingual-prompt-correction/manifest.json). The [previous report](2026-10-23-bilingual-prompt.md) and original failed response are unchanged. Manifests hash UTF-8 text with CRLF normalized to LF. Reproduce the offline review with `analyze.py` in the evidence directory; the live harness there records the initial line-based check and must not be mistaken for the corrected sentence-level acceptance.
