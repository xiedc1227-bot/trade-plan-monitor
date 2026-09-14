# R17 contract repair and failure diagnosis

## 1. Scope and evidence

This is an offline repair following `R17-execution-20260914-afternoon.md`, not another live acceptance run. The original R17 evidence and failed business-acceptance conclusion remain valid. No new AI or market-data provider requests were made, no one-shot authorization was reused, and no production database or credentials were changed. The 12 pre-existing tracked edits and four R00 untracked documents were retained.

## 2. Confirmed contract repairs

- `diagnosticStatus` was emitted by the backend but absent from the client's allowed keys and stale generated OpenAPI/TypeScript artifacts. The client now accepts omitted/null values and the exact `RECORDED` / `WRITE_FAILED` enum. Invalid values and unrelated unknown fields remain rejected.
- The three preserved R17 HTTP 200 responses now pass through the actual TypeScript client unchanged. They retain their real `PROVIDER_ERROR` / `INVALID_OUTPUT` outcomes; accepting a response does not turn extraction into success.
- A failed status GET retains the accepted operation and last known status. The new query-recovery button polls the same operation with GET only; it does not submit another paid extraction. Explicitly stopping the local wait releases the editor without claiming server cancellation.
- A separate successful-response mismatch was reproduced using the actual backend serializer: partial v4 drafts may contain zero field bindings, while the client required at least one and imposed a different upper bound. The client now matches the backend's 0–10,000 bound. The serialized synthetic fixture still contains activation-blocking review issues. A Python fixture check and TypeScript consumption test protect this shared boundary.

## 3. Calendar diagnosis

The R17 audit records exactly one physical `trade_cal` attempt and zero pre-network budget rejections. The runtime starts with the SSE calendar even when no plans are active. Thus an empty plan database does not explain why the calendar request failed; it explains why no plan evaluation or activation could follow.

The failure location is the startup reference refresh: request admission/transport/normalization, the current-date availability check, or reference persistence. The old composition collapsed all exceptions into `REFERENCE_REFRESH_FAILED`. The preserved health response, audit, and empty reference tables do not distinguish those paths. They cannot establish a token, quota, network, response-schema, or database root cause for the historical request.

The repaired composition retains bounded categories in provider health and a content-free warning:

| Category | Meaning |
| --- | --- |
| `REFERENCE_BLOCKED_PERMISSION`, `REFERENCE_RATE_LIMITED`, `REFERENCE_TRANSIENT`, `REFERENCE_TIMEOUT`, `REFERENCE_INVALID_RESPONSE`, `REFERENCE_ERROR` | Existing sanitized request-controller outcome; no provider text is copied |
| `REFERENCE_QUEUE_FULL`, `REFERENCE_CLOSED` | Local request admission/lifecycle outcome |
| `REFERENCE_DATA_UNAVAILABLE` | Request completed, but usable current calendar/reference history was absent |
| `REFERENCE_STORAGE_ERROR` | Reference persistence raised a SQLAlchemy error |
| `REFERENCE_REFRESH_FAILED` | Other uncategorized exception; no speculative interpretation |

The existing `nextRetryAt` is retained when supplied by the request controller. It is metadata, not a new retry policy. Successful reference refresh clears stale reference errors and retry metadata. Permission, rate-limit, transient, timeout, response, admission, missing-data, storage, generic-error, and recovery paths are covered offline. Exception strings, traceback, source text, tokens, and provider bodies are not logged by this diagnostic addition.

## 4. Extraction diagnosis

- **LITERAL:** the preserved result is a provider-stage timeout after one attempt, before a model response reached parsing. It is not evidence of a JSON or mapping parser failure. The offline real-adapter test keeps the 30-second setting and zero retries, injects a transport timeout, and verifies one attempt, no draft, no usage, and no sensitive exception text. It does not establish the remote reason for the historical delay or its billing.
- **SEM-AMB-01 / SEM-UNS-01:** the model returned `finishReason=stop`, passed JSON/schema parsing, and failed the source/current-draft mapping boundary. The old diagnostic recorded only `MAPPING / unknown`; the raw model output was not retained, so the exact offending field cannot be reconstructed.
- Mapping failures now identify server-constructed locations such as `source_clauses[0].excerpt`, `.start`, `.end`, `.clause_id`, or `field_bindings[0].path`, `.unit`, `.value`, `.origin`, and `.clause_ids`. Domain model validation keeps its safe schema path/type. Indices remain bounded and untrusted field paths or content are not echoed. Existing source-evidence checks remain enforced.
- An additional offline bug was found: a `STRUCTURE` binding addressing a scalar raised `AttributeError`, which could be misreported as a provider failure. It now produces `INVALID_OUTPUT` with the mapping field location. This is a separately reproduced defect, not a claim about the two historical R17 outputs.

## 5. Verification

All commands run from `trade-plan-monitor/` unless noted. New behavioral regressions were demonstrated failing before their corresponding fixes.

| Check | Result |
| --- | --- |
| `npm --prefix web test -- --run` | 665 passed |
| `npm --prefix web run type-check` | Passed |
| `npm --prefix web run build` | Passed; refreshed both browser distribution and packaged Python web assets |
| `npm --prefix web run test:e2e -- tests/e2e/ai-diagnostic-contract.spec.ts` | 3 passed in real Chrome with local intercepted responses; no external requests or duplicate POST |
| Focused Python regression suite | 134 distinct checks covered: initially 133 passed and the stale bilingual specification fingerprint failed; after synchronizing both specifications, all 14 OpenAPI checks passed on rerun |
| `python -m scripts.generate_frontend_types --check`, targeted Ruff checks, `git diff --check` | Passed |
| Complete Python suite, `python -m pytest -m "not live" -q` | Interrupted during the additional ten-symbol/252-day backtest capacity test after more than ten minutes; no failure assertion had been reported, but the complete suite is NOT claimed as passed |

The focused Python selection includes `test_r17_failure_diagnostics.py`, `test_ai_plan_extraction_v4.py`, `test_ai_diagnostics.py`, `test_ai_browser_contract.py`, `test_ai_provider_contract.py`, `test_r15_extraction_diagnostics.py`, `test_certified_production_runtime.py`, `test_monitor_production_composition.py`, `test_explicit_runtime_production.py`, and `test_openapi_snapshot.py`. No tests, capacity thresholds, or authorization guards were disabled or weakened. The additional full-suite process was stopped; unrelated running processes were left alone.

Browser verification covers QUEUED → RUNNING → failure for both diagnostic enum values and recovery from a malformed status response. This is a real browser against simulated API responses, not a live provider acceptance run. Historical R17 replies are separately replayed unchanged in the TypeScript test. The new successful fixture is explicitly synthetic and compared against backend serialization.

## 6. Remaining evidence boundary

The UI contract regression is repaired. Calendar and mapping failures can now retain useful diagnostics on a future authorized run. The exact historical calendar error, the two historical offending mapping fields, and the remote cause of LITERAL's timeout remain unproven because the necessary evidence was not captured. A new bounded live session would need fresh authorization; the R17 one-shot session cannot be reused. Live extraction, review, activation, fresh market evaluation, and visible IN_APP delivery remain separate unfinished acceptance criteria.
