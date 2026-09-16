# R26 AI timeout offline diagnosis and remediation

Canonical English; `R26-ai-timeout-diagnostics-20260916.zh-CN.md` is the equivalent Chinese review copy. Status **OFFLINE_COMPLETE / DIAGNOSTIC_GAP_FIXED / HISTORICAL_REMOTE_CAUSE_UNKNOWN / LIVE_NOT_RUN**.

## Scope and safety

R26 investigated the first and only R25 AI timeout without replaying it. This work made **zero** DeepSeek POSTs, market-data calls, balance/model-list probes, webhooks, broker actions, claims, plan activations or holding changes. It did not run R25 `--execute`, reuse the consumed R25 run/window/allowance, print credentials, or retain provider exception text, headers, response content, source text or prompts in diagnostics.

## Reconstructed path

The frozen R25 candidate selected `plan-extract-v5`, `max_tokens=8192`, one user message, `temperature=0`, `thinking={"type":"disabled"}`, `response_format={"type":"json_object"}`, `stream=false` and `max_retries=0`. `AIBudgetTransport` admitted the exact approved `LITERAL` request once and then delegated to `httpx.AsyncHTTPTransport(retries=0, trust_env=False)`.

The production path was:

1. `scripts/r25_extraction_acceptance.py` submitted `LITERAL` through `ConfiguredAIWebLifecycle`.
2. `extract_plan` built the v5 request and called `OpenAICompatibleProvider`.
3. `_request_once` nested `asyncio.timeout(30)` around `httpx.AsyncClient.stream(..., timeout=httpx.Timeout(30))`.
4. The adapter collapsed built-in `TimeoutError` and every `httpx.TimeoutException` subtype to `AIProviderErrorCode.TIMEOUT`.
5. Extraction and the diagnostic sidecar consequently retained only `stage=provider`, `providerErrorCode=TIMEOUT`, `path=unknown`, `attempts=1` and no usage.

HTTPX 0.28.1 officially distinguishes connect, read, write and pool timeout exceptions. Python 3.14 documents that `asyncio.timeout()` cancels the enclosed work and converts that cancellation to `TimeoutError` outside the context. Sources checked on 2026-09-16: https://www.python-httpx.org/advanced/timeouts/, https://www.python-httpx.org/exceptions/ and https://docs.python.org/3/library/asyncio-task.html#timeouts.

## Evidence boundary

### Proven

- The complete R25 session lasted 30.735763 seconds, but the AI operation itself ran from `2026-09-16T09:41:54.912308+08:00` through `09:42:24.918282+08:00`: 30.005974 seconds.
- Both the local overall deadline and HTTPX connect/read/write/pool inactivity limits were 30 seconds. Provider retries and transport retries were zero.
- The request physically started once. R25 received no validated response envelope, finish reason, usage or returned-model identity. It stopped without resubmission and preserved empty activation/business tables.
- The pre-R26 adapter irreversibly collapsed all five locally observable timeout categories. The retained R25 v1 sidecar therefore cannot identify the historical phase.

### Reasonable inference, not proof

- The 30.005974-second AI duration is consistent with one of the configured local 30-second boundaries firing. Because the boundaries were equal and only the collapsed category was retained, it does not establish which boundary won.
- A future `READ` result would mean no response-body chunk arrived within the read interval; it would still not distinguish provider computation, upstream queuing or a network receive stall. `CONNECT` covers the connection establishment phase and does not safely separate DNS, TCP and TLS from the retained exception class.

### Unknown

R25 cannot prove whether DeepSeek received, completed or billed the request, whether the failure occurred during connection/TLS, write, pool acquisition, response read/remote processing, or whether the outer local deadline fired first. The successful `trade_cal` request proves only that its separate market route worked; it says nothing about the AI route. R19's earlier `finishReason=length` was a validated response truncation and is not evidence about this timeout.

## Remediation

The confirmed local defect was diagnostic loss, not a proven bad timeout threshold or provider defect. R26 keeps all existing request fields, the configured timeout value, provider retry policy, transport retry policy, stop behavior, idempotency, audit and cleanup semantics unchanged.

The sanitized provider error now carries only:

- `timeoutKind`: fixed enum `CONNECT`, `READ`, `WRITE`, `POOL`, `OVERALL_DEADLINE` or `UNKNOWN`;
- `timeoutElapsedMs`: non-negative monotonic elapsed milliseconds for the failing physical attempt.

Extraction propagates those fields into `ExtractionDiagnostic`. Sidecar schema version 2 persists them without raw exception strings, provider bodies, headers, credentials, prompts, source text or direct IP addresses. Historical v1 evidence remains immutable and readable.

## Offline verification

TDD red phase: the new focused test initially failed during collection because `AIProviderTimeoutKind` did not exist. After the minimal implementation:

- R26 focused tests: **9/9 passed**. They cover all four HTTPX timeout subtypes, the separate local overall deadline, monotonic elapsed milliseconds, propagation into extraction, v2 sidecar persistence, metadata consistency and secret/exception-text exclusion.
- AI provider, diagnostic, R17, R19, R25 and R26 focused regression group: **80/80 passed**, with one pre-existing Starlette/httpx deprecation warning.
- Ruff on all changed Python files and `git diff --check`: passed.

These offline tests prove the new classification behavior with mocks/fakes. They do not retroactively classify R25 or prove a real provider success.

## Next minimal real-validation proposal (not authorized and not run)

| ID | Proposed bound |
|---|---|
| R26-N01 | Answer one question only: can the unchanged frozen `LITERAL` v5/8192 request reach a terminal result on the production DeepSeek path, and if not, which new fixed timeout category is recorded? |
| R26-N02 | Use one fresh candidate/run/claim and fresh isolated SQLite database plus v2 diagnostic sidecar. Use the production configured AI composition directly; do not start the market/reference lifecycle and permit **zero market calls**. |
| R26-N03 | Permit exactly **one** physical AI POST for `LITERAL`, zero retries and zero resubmission. Keep the request source, prompt and body fields unchanged: `deepseek-v4-pro`, v5, 8,192 output tokens, non-thinking JSON, non-streaming, temperature 0. |
| R26-N04 | Keep the evidence-backed 30-second provider/HTTPX setting unchanged. Bound the candidate to 45 seconds total, including at most 15 seconds for cooperative cleanup. Do not increase the threshold, switch models or add retries without new evidence. |
| R26-N05 | Stop after any terminal success or failure. Missing diagnostic, uncertain receipt/query, model mismatch, invalid/truncated output or failed literal oracle stops without another POST. A success writes only the isolated review artifact; plan save and activation remain forbidden and human review remains required. |
| R26-N06 | Generate and display a fresh exact egress review package. Even if source/prompt hashes are unchanged, the consumed R25 approval/allowance is not authority for this new candidate; fresh content-and-destination approval is required before any POST. |
| R26-N07 | Recheck the official route and price at actual execution time. The 2026-09-16 snapshot maps `deepseek-v4-pro` to `DeepSeek-V4-Pro-0813` and lists peak USD 1.32/M cache-miss input and USD 3.96/M output. With the conservative 19,000-input-token arithmetic bound and full 8,192 output tokens, one peak request is estimated at USD `0.05752032` before tax/account adjustments; off-peak is USD `0.02876016`. Actual tokenization, cache, output length, billing and taxes remain unknown. No recharge or account probe is included. |
| R26-N08 | Because the proposal has zero market calls, it neither consumes nor relies on the stock certificate expiring `2026-09-16T14:48:40.405317+08:00` or the five-index certificate expiring `2026-09-18T10:20:44.522358+08:00`. Any later expansion to market validation must recheck applicable certificates at its real start time and must not silently reauthenticate. |

The official DeepSeek pages checked on 2026-09-16 document `POST /chat/completions`, `deepseek-v4-pro`, non-thinking mode, JSON output, the 8,192-token request value and the current route/prices: https://api-docs.deepseek.com/api/create-chat-completion/ and https://api-docs.deepseek.com/quick_start/pricing/.

## Conclusion

R26 completed the available offline work. It fixed a verified local observability defect while preserving one-shot safety and all business-state protections. The historical R25 remote cause remains unknowable from retained evidence, and no live success is claimed. The next proposal is review material only; R27 is not opened automatically.
