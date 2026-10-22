# Empty-array extraction contract verification — 2026-10-22

## EA-V01 — Outcome and scope

**PASSED for the four requested synthetic cases in final run `run-v4`.** Generation used the unchanged Chinese generic prompt saved in README, followed by the actual `extract_plan` pipeline with configured `deepseek-flash`. Both normal sources passed parsing, strict source mapping and executable-structure validation with no issues, assumptions or warnings. The two blocked cases produced no importable source and were not sent to extraction. No candidate was saved, reviewed or activated.

This uses synthetic prices, not current market data or trading advice. English documentation received parity review; live generation used Chinese. The original failed verification is retained in [the previous report](2026-10-22-generic-plan-prompt.md).

## EA-V02 — Cause and changes

- Empty candidate arrays were bound as the JSON string `"[]"`. The trusted internal contract now provides actual JSON-array examples for `ordinary_rules`, `risk_branches` and `alert_rules`, requiring source-backed `value=[]` and `unit=JSON`. These examples do not authorize inventing empty rules.
- Corrected the final-check wording that could prohibit all containers despite the required empty-array exception. Explicitly distinguish `levels=null` from an object containing registered null children.
- Clarified that every `DAILY_*` condition, including an independent price reminder, requires registered daily monitoring settings and evidence bindings. Registered defaults in monitoring/trading/execution settings still require bindings.
- Compact canonical-clause JSON and concise model explanations preserve exact excerpts, spans, all policy bindings and configured budgets. No schema, source validator, response normalizer or approval gate was relaxed.
- A live response with missing monitoring also exposed a root-validation diagnostic crash: an empty error location could not become a `ValidationIssue`. Root errors now use path `plan`; the invalid candidate remains blocked. This changes error reporting, not eligibility.

## EA-V03 — Final case matrix

| Case | Result | Verified details |
|---|---|---|
| `sse-one-alert` | Complete pass | `600010.SH`, `SSE`, max 500; exactly 1 official daily-close alert, `LT "1207" FEN`; 0 ordinary rules, 0 risk branches |
| `szse-two-alerts` | Complete pass | `000858.SZ`, `SZSE`, max 800; exactly 2 official daily-close alerts, `LT "7432" FEN` and `GT "8567" FEN`; 0 ordinary rules, 0 risk branches; no old-symbol parameter leakage |
| `missing-position-limit` | Correct block | `600519.SH`; missing holdings/cost/max quantity not fabricated; A is `暂不提供可导入正文。`; no extraction request |
| `unsupported-index-buy` | Correct block | `600036.SH`; required automatic index-linked quantities/confirmation/pause cannot be represented; no BUY with the dependency removed and no unauthorized reminder fallback; no extraction request |

The normal candidates retain source identities, reference metadata and required nulls. `to_executable()` confirms structural validity only; it does not approve or activate a plan.

## EA-V04 — Live method, budgets and retained attempts

The same four case inputs were reused unchanged. The runner reads README, asks the configured provider for JSON-wrapped A/B, then passes the exact decoded A string into production extraction. B is not included in extraction. No returned source or response was repaired. The runner never opens application storage; separate preservation snapshots use read-only SQLite access.

- README prompt SHA-256: `4a3756d32bd49884e0d4e5f1a0291a75e76cedf5ca83697550219554e382ad6a`.
- Unchanged configuration: `deepseek-flash`, input 50000 characters, output 4096 tokens, timeout 30 seconds, max retries 2.
- Four diagnosed contract iterations: 16 generation calls, 7 extraction provider calls, 23 actual provider attempts. There was no blind unchanged retry to obtain a pass.
- `run-v1`: empty-array types corrected; one source invented null child bindings, both omitted monitoring; the second exposed the diagnostic crash. Both negative cases blocked correctly.
- `run-v2`: one-alert case passed; two-alert response hit 4096 tokens and was rejected as `AI_OUTPUT_TRUNCATED`. Both negative cases blocked correctly.
- `run-v3`: concise output instructions added, but the two-alert request exceeded the input budget and was rejected before provider invocation. One-alert and both negative cases passed. Repetitive contract wording was then shortened.
- `run-v4`: all four expectations passed. One-alert request: 48324 characters, extraction output 2808 tokens. Two-alert request: 49865 characters, extraction output 4012 tokens. Both completed with `finish_reason=stop`.

The two-alert sample has only 135 input characters and 84 output tokens of remaining budget. Larger inputs are not certified; input overflow, truncation or invalid evidence must continue to block. Passing these samples is not a guarantee of deterministic future model output.

All original A/B text, provider content strings, request text, hashes, results and failed iterations are retained in [the evidence directory](evidence/2026-10-22-empty-array-contract/verification.json). Response hashes cover exact parsed provider content strings, not HTTP wire bytes. No secret configuration values are included.

## EA-V05 — Regression checks

Tests first failed on missing typed examples; negative string/null/object bindings remained rejected. The missing-monitoring diagnostic test reproduced the crash before the fix. Frozen, unmodified successful provider responses now replay through the real parser and reviewer; previous real `"[]"` failures still fail. The replay also checks complete binding coverage, exact JSON types, canonical-clause preservation and the 50000-character input limit.

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_current_review_contract.py tests/unit/test_current_plan_extraction_security.py tests/unit/test_empty_array_contract_replay.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/unit -q -m "not live" --tb=short
.venv/Scripts/python.exe -m pytest tests/contract tests/history tests/replay -q -m "not live" --tb=short
```

Results: 44 focused tests passed; final complete unit directory 3445 passed; focused integration 213 passed; contract/history/replay directories 13 passed and 4 explicitly live tests deselected. The 44 focused tests are included in the unit total. Lint and formatting passed for the changed extraction and test files. Existing Starlette/httpx deprecation warnings remain. Exact integration selection and test logs are in `evidence/2026-10-22-empty-array-contract/checks.json`.

The default all-directory test command has a pre-existing duplicate-module collection conflict. Importlib mode also fails existing bare cross-test imports. Running directories separately avoids those collection errors. The full integration run was stopped during long-running unrelated backtest acceptance and is **not claimed as passed**; focused extraction/review integration results and logs are recorded alongside the evidence. No tests were deleted, disabled or weakened.

## EA-V06 — Preservation and manual review

Read-only before/after snapshots match for the saved `SNGC-OBS-20261022` version, review provenance, activation tables, actual/simulation inventory, risk state, target daily history, storage constraint and configuration hash. The saved plan remains `DRAFT`, review revision 0, no confirmation, exactly 1 alert, 0 ordinary rules and 0 risk branches. Active-plan and activation tables remain empty.

The current generic prompt's trading principles, index effects and human checks are unchanged. Actual holdings, costs, position caps, valid orders, corporate disclosures, market/index evidence, unsupported strategy dependencies and any future approval still require their specified verification. The two synthetic accepted candidates are regression evidence only. No live prices, broker orders, plan approval, activation or inventory changes were performed.
