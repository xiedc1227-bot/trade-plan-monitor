# AI source-review contract verification — 2026-10-22

## AI-RC-01 Scope and invariants

The initial complete `deepseek-flash` response represented the requested alert correctly but failed source review. All 38 evidence paths used a `draft.` envelope prefix; identity/display metadata and unregistered nulls were bound, and `PRODUCT_CONTRACT` bindings carried source clause IDs. A syntax-valid draft was not a passed extraction.

This change updates only the trusted instructions assembled by `build_current_plan_prompt` in `src/trade_plan_monitor/ai/plan_extraction.py`. Schema 5, `plan-extract-v9`, source splitting, JSON parsing, `semantic_values`, the source reviewer, activation, and simulation authorization remain unchanged. There is no output normalizer, prefix stripping, metadata filtering, inferred parameter, or post-response repair.

The exact Chinese source is frozen in [source.txt](../../tests/fixtures/ai/current-review-contract/source.txt). It is byte-identical to the user's final compact body, SHA256 `d672ee69ade8c1cbcee496bf5c88976d305227f9d985be151391c25a16aaab65`. The human research appendix was not submitted. Unverified report time remains null; the existing software-contract MACD warmup remains 26. No trading principle or threshold was changed.

## AI-RC-02 Trusted contract correction

The prompt now publishes a structured source-review contract after the JSON Schema and before untrusted source data:

- `bindings.path` and `clauses.paths` use plan-root paths without `draft.`.
- `plan_id`, `version`, `name`, and the entire `metadata` subtree remain in the draft for identity/display and are excluded from policy bindings. `symbol` and `market` remain required source-bound runtime scope, including in mixed identity clauses.
- Unregistered nulls and containers are not bound. The existing explicit-null exceptions `levels.low_buy` and `levels.pressure`, empty arrays, non-null leaves, and `ALL`/`ANY` type-string structure remain reviewable. Unknown required trading parameters stay null and block review.
- `PRODUCT_CONTRACT` has empty `clause_ids` and null `supplement_id`. Source-origin bindings retain exact source-clause references; no AI-created human authority is permitted.
- Evidence values match JSON-serialized candidate types. Decimal reference values remain strings; integer-fen conversions retain their existing exact-price checks.
- Non-policy headings and display commentary can be `CONTEXT` with an explicit semantic role and explanation. Real directives, deadlines, missing trading parameters, and technical requirements cannot be hidden as context. `BACKGROUND` retains its exact registered-exclusion boundary.

Concrete metadata, mixed-null, identity-scope, and software-constant examples resolve ambiguity in the envelope schema. The server continues rejecting incompatible output rather than adapting it.

## AI-RC-03 Regression and runtime evidence

The new [regression module](../../tests/unit/test_current_review_contract.py) contains 12 cases. It checks the prompt against the existing semantic path and product-binding contracts, replays the unchanged original failing response, and replays the unchanged successful response through the real parser and reviewer. Negative mutations cover binding and clause path prefixes, metadata, unregistered nulls, product origins with source IDs, Decimal type mismatches, and missing source clauses. A missing required position limit remains null and blocks review.

| Check | Result |
| --- | --- |
| Focused extraction/security/source-review/integration regression | 94 passed; 1 existing Starlette/httpx deprecation warning |
| All unit and offline contract tests | 3,433 passed; 4 `live` tests deselected; 1 existing warning; 58.45 seconds |
| `python -m ruff check --no-cache src tests` | Passed |
| Formatting check for changed Python files | Passed |
| In-memory mutation removing required scope declarations | Expected test failure detected; contract restored; no source mutation |
| Complete backend suite | Not completed; not counted as passed |

Windows asyncio requires local loopback sockets, so offline tests ran outside the restricted socket sandbox. An explicit new workspace `--basetemp` avoided an existing system temporary-directory permission problem. The ordinary complete-suite command has an existing integration/unit `test_backtest_service_contract.py` module-name collision. Importlib mode also needs the legacy test directories on `PYTHONPATH`; that compatibility invocation collected 7,607 offline tests but was interrupted after prolonged lack of progress in integration tests. No test assertion or runtime validator was weakened. Frontend code was unchanged.

### Real AI extraction

After the user's explicit authorization, the same source was sent to the configured `https://api.deepseek.com/chat/completions` using `deepseek-flash`, via `ConfiguredAICommandService.extract -> extract_plan`, the same current extractor used by the Web. Project defaults were retained: input limit 50,000 characters, output limit 4,096 tokens, timeout 30 seconds, retry limit 2. The successful request used 48,400 prompt characters, completed in one provider attempt, and returned `finish_reason=stop` with 14,196 prompt tokens and 3,469 completion tokens.

The final unmodified response passed exact source review with all 15 clauses and 32 bindings:

| Acceptance item | Actual result |
| --- | --- |
| Extraction status | `SUCCEEDED` |
| Draft present and structurally valid | Yes |
| Validation issues / assumptions / warnings | 0 / 0 / 0 |
| Ordinary BUY / SELL rules | 0 / 0 |
| Liquidation branches | 0 |
| Technical alerts | 1: `RISK-ALERT-01`, `RISK_ALERT` |
| Alert condition | Latest official completed daily `close`, `offset=0`, strictly `LT` fixed `2659 FEN` |
| Confirmation | `OFFICIAL_DAILY_CLOSE` |
| Added volume, indicator, human-fact, or index conditions | None |

The first post-fix real request still attempted metadata/null bindings and was rejected. The second returned a reviewable draft but omitted `symbol`/`market` evidence, producing two blocking issues. Neither was counted as success or repaired. After clarifying the contract, the third request met all acceptance criteria. Final source and response bytes were copied unchanged to fixtures; the response SHA256 is `f75114a2e9f943e4c7a10e887adf0a36a2e67750d1f81d9290434b5b0497d9c4`.

See [machine-readable live evidence](evidence/2026-10-22-ai-source-review-contract/live-verification.json), [original rejected response](../../tests/fixtures/ai/current-review-contract/deepseek-before.json), and [accepted response](../../tests/fixtures/ai/current-review-contract/deepseek-after.json). The live prompt hash matches the final implementation.

## AI-RC-04 Authority and limits

Real extraction used the nonpersistent CLI service. No plan/account database was opened by that workflow, no plan was approved or activated, and no simulation inventory was initialized or modified. `config/app.yaml` remained byte-identical. Tests used fixed providers and temporary stores; the separately authorized real call was explicit.

This result certifies this exact source/response and unchanged strict review, not arbitrary future model output. New incompatible responses must still fail closed. It introduces no index linkage, dynamic quantity, fundamental monitoring, automatic trading, or custom alert-message feature. Human review and explicit activation remain separate requirements.
