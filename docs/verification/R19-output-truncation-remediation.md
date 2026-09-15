# R19 AI output-truncation remediation — offline verification

Canonical English; `R19-output-truncation-remediation.zh-CN.md` is the equivalent Chinese review copy. Status **OFFLINE_PASS / REAL_PROVIDER_NOT_RUN / BUSINESS_ACCEPTANCE_STILL_FAILED**.

## Diagnosis

The preserved R18 restart evidence establishes one bounded `LITERAL` request to configured `deepseek-v4-pro`: `finishReason=length`, 5,077 prompt tokens, 4,096 completion tokens and 9,173 total tokens. No draft, mapping, review, save, activation or monitoring record was created. The application configuration and the historical R18 launcher both explicitly selected 4,096 output tokens. That is sufficient to identify output truncation at the configured ceiling as the immediate failure; it does not prove whether the provider also reached a context boundary.

The public adapter preserved only prompt/completion/total usage and the redacted finish reason. It did not retain raw response content or `completion_tokens_details.reasoning_tokens`. The request explicitly disabled thinking, so there is no evidence that hidden reasoning consumed the limit, but the exact visible-JSON/reasoning split remains unknown. The historical R17 provider and mapping causes also remain unknown.

DeepSeek's current Chat Completions documentation defines `finish_reason=length` as reaching the requested token maximum or context length, lists an 8K non-thinking default, and advises a reasonable `max_tokens` for JSON output to avoid mid-document truncation:

- https://api-docs.deepseek.com/api/create-chat-completion/
- https://api-docs.deepseek.com/guides/json_mode/

## Remediation

- New omitted configurations use a bounded 8,192-token default; the hard maximum remains 16,384. The actual DeepSeek-profile request body was verified offline with `max_tokens=8192`, `thinking={"type":"disabled"}`, JSON output, zero network and no secret exposure.
- New extraction uses immutable `plan-extract-v5`. It shares v4's schema digest `9461d3099a923e5f9fe172eeba010e0dbe44cbe9d8f93c9465be9626d08965a1`, requires minified JSON, permits omission only of empty top-level `assumptions`/`warnings`, and has golden prompt digest `8ec7e564eb9348ca6c00acee92405222b6ad13423da95dcc1b4fb167252cf4d6`. V4's golden digest remains `e91f6b32a69a60b1f35da3e5deee5acd17d326cecd0efcadd2aa99bdb36b4eb7`.
- `finish_reason=length` now returns `INVALID_OUTPUT` with fixed code `AI_OUTPUT_TRUNCATED` and message `AI output was truncated before completion; no draft was created.` It returns no draft or mapping and retains diagnostic stage `response`, reason `FINISH_REASON`.
- V5 remains compatible with the existing closed mapping, authoritative review, immutable save and explicit activation boundaries. No output is auto-repaired and no plan is auto-activated.

The real ignored `config/app.yaml` was read without printing its key and was not modified; its explicit output cap remains 4,096. The 8,192 value is a safe code/example default, not a silent override of user configuration.

## Offline evidence and limits

- Focused backend plus generated-contract suite: **173 passed**, one pre-existing Starlette/httpx deprecation warning. This includes provider request shape, prompt immutability, v4/v5 parsing, explicit review/activation, config, provider contracts, configured Web composition and OpenAPI determinism.
- R19-focused plus public review/activation integration: **9 passed**. A source-faithful 15-clause/23-binding literal fixture round-tripped after permitted empty-list omission: 7,819 to 7,788 UTF-8 bytes, with identical draft and mapping. These are serialization bytes, not a token estimate.
- Historical R14/R17/R18 boundary and guarded offline wiring suite: **55 passed** after its generated test configuration explicitly pinned frozen `plan-extract-v4`; no consumed launcher or claim was changed.
- Browser recovery unit slice: **33 passed**. It retains one accepted operation after a query failure; recovery performs exactly two GETs after the single POST and never resubmits paid work.
- Frontend type-check and production build passed after the targeted browser tests.
- A v5 integration path activates an existing reviewed plan, runs a synthetic `finish_reason=length` extraction, verifies no draft/mapping, then reads the exact unchanged active state.

No external AI or market-data request, webhook, trade, real database mutation or credential/real-configuration change occurred in R19. These checks prove contract behavior, not that a real provider will finish within 8,192 tokens or preserve semantic accuracy. Business acceptance therefore remains failed until a separately authorized candidate succeeds end to end.
