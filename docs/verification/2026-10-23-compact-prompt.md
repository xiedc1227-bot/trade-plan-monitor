# Compact prompt verification — 2026-10-23

## Scope and outcome

The current README prompt passed the same four synthetic cross-symbol/missing-input samples with the configured `deepseek-flash`. Two normal sources passed complete extraction and source review; the two negative cases blocked generation of importable policy. No deleted input was requested in the final appendices, and no broker-order capability was claimed.

This changes the English/Chinese prompt and adds six regression cases with unchanged live response fixtures. No production extractor, source splitter, Schema, validator or provider configuration changed. Original trading, index-state sizing/confirmation/pause, risk priority and source-deadline principles remain. No plan was saved, approved or activated; no real or simulated trade occurred.

## Diagnosis and correction

The [previous simplified prompt](2026-10-23-simplified-prompt.md) produced a two-alert extraction truncated at 4096 output tokens. Repeated paths and provenance consumed the fixed budget. An initial compact JSON experiment made this worse: the unchanged canonical splitter treats commas as clause boundaries, producing 31 clauses and a 50,926-character request, rejected by the 50,000-character input limit before a provider call.

The final format uses explicitly scoped lines, for example `alert_rules[0]: kind=RISK_ALERT ...` and `alert_rules[0].condition.reference: mode=FIXED ...`, with space-separated fields. All fields, exact source text, dates, units, comparison direction and confirmation remain. The same two-alert sample now produces 11 canonical clauses, a 48,478-character request and 3701 output tokens. Every required semantic binding and canonical clause remains verified; no output is patched or shortened after generation.

The appendix now lists only current blockers. Independent reminders do not require allocation or repeated threshold confirmation; unspecified deadlines retain verified `PLAN_ACTIVE`/`MANUAL` defaults. Explicit source deadlines still apply. Tool capability text states that broker orders are unsupported. Application activation state is separate from candidate document content.

## Real validation

Budgets stayed at 50,000 input characters, 4096 output tokens, 30-second timeout and 2 maximum retries. Model: `deepseek-flash`. Final run: `run-v5`, four generation calls and two extraction calls. Each call made one provider attempt. The samples are synthetic software checks, not current market research or investment recommendations.

| Sample | Final result |
| --- | --- |
| 包钢股份 `600010.SH`, maximum 500 shares | `SUCCEEDED`; exactly 1 `RISK_ALERT`, official daily close `LT 1207 FEN`; 0 ordinary rules, 0 risk branches |
| 五粮液 `000858.SZ`, maximum 800 shares | `SUCCEEDED`; exactly 2 independent alerts, official daily close `LT 7432 FEN` and `GT 8567 FEN`; 0 ordinary rules, 0 risk branches |
| 贵州茅台 `600519.SH`, maximum unknown | A is exactly `暂不提供可导入正文。`; no extraction call; pending confirmation is only `position.max_qty`, with no invented limit |
| 招商银行 `600036.SH`, mandatory automatic index-linked 200/100-share buys and S0/S1 switching/pause | Same blocking A; no extraction call; no reduced individual-stock BUY and no unauthorized reminder fallback |

Both accepted sources have no issues, assumptions or warnings, complete source coverage, matching typed bindings and structurally executable candidates. That structural status does not authorize activation. No old `605296.SH`, 300-share limit or 26.59 threshold leaked into these sources.

All five iterations are retained in [evidence](evidence/2026-10-23-compact-prompt/verification.json):

| Run | Pipeline | Appendix review and next correction |
| --- | --- | --- |
| `run-v1` | Two-alert input rejected; other cases correct | Replace comma-delimited JSON source with scoped lines |
| `run-v2` | All four cases correct | Allocation and nonblocking research gaps still appeared in pending confirmations; constrain section 6 and actual activation wording |
| `run-v3` | All four cases correct | Reconfirmation of explicit thresholds and hypothetical allocation checks remained elsewhere; constrain sections 3/4 |
| `run-v4` | All four cases correct | Unspecified deadline incorrectly listed as pending; restate existing defaults |
| `run-v5` | All four cases correct | Acceptance met: no deleted-input requests or false broker capability; normal pending lists are empty |

Total for this correction: 20 generation calls, 9 extraction calls, 29 provider attempts. Every retry followed a diagnosed prompt correction; unsuccessful/intermediate output remains intact. Full prompts, requests, responses, hashes, pipeline results and the runner are retained. Raw B correctly describes the generation stage as not yet extracted; subsequent real extraction results are recorded separately, not spliced into the response.

Minor prose limitations remain: some appendices print a redundant “not involved/omit” row, and the unsupported case's research summary still mentions an absent deadline, while its decision paragraph applies the default and its pending list excludes it. These do not request deleted inputs or change machine policy. The fixed budget is not a guarantee for arbitrary larger condition trees. Human review remains necessary for future real plans.

## Regression and preservation

- Six new regression cases replay both accepted original responses, reject missing maximum/unsupported index types, verify a missing source binding still blocks activation, and reject the original truncated response unchanged.
- Focused extraction/source/security regression: **50 passed**.
- Non-live unit suite in a fresh workspace temporary directory: **3476 passed**, one existing Starlette deprecation warning.
- Related integration regression: **82 passed**, one existing Starlette deprecation warning. Exact commands are recorded in `regression.json` in the evidence directory.
- New test lint/format and `git diff --check` passed. README language structure and machine examples match.

Initial test attempts exposed a new test's mistaken expectation that missing bindings fail parsing rather than block source review, then a mistaken Python attribute name. Both test assertions were corrected to the existing explicit activation blocker; production validation was untouched. An initial full unit run also hit 185 system-temp permission setup errors; the corrected isolated run above passed. An initial integration selector referenced a removed test file and collected no tests; the corrected selector uses existing files. No tests were skipped to obtain a pass.

Read-only before/after snapshots are identical: the original 神农集团 draft remains `DRAFT`, review revision 0, unconfirmed, with 1 reminder and 0 ordinary/risk rules; active-plan state remains empty. Protected inventory, risk, history/review records and configuration hashes match. See [preservation](evidence/2026-10-23-compact-prompt/preservation.json). Other tasks' native-build experiment changes were not edited or included.
