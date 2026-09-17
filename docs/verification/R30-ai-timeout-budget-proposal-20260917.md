# R30 isolated AI timeout-budget acceptance proposal

Canonical English; `R30-ai-timeout-budget-proposal-20260917.zh-CN.md` is the equivalent Chinese review copy. Proposal `R30-20260917-V6-LITERAL-TIMEOUT-BUDGET-1`; run `r30-20260917-a`. Status **EXECUTION_BLOCKED_OFFICIAL_PRICE_MISMATCH / CLAIM_UNCONSUMED / ZERO_EXTERNAL_CALLS**.

Post-approval update: the immediate official price recheck displayed the higher `DeepSeek-V4-Pro-0813` peak/off-peak schedule, making both the USD `0.05884032` peak estimate and USD `0.02942016` off-peak estimate exceed the approved USD `0.01582704` package estimate. No request was sent. See `R30-ai-timeout-budget-execution-20260917.md`.

## Objective and evidence boundary

R30 answers one narrow question: did R29's local 30-second overall deadline prevent an otherwise unchanged non-streaming v6 request from reaching a terminal response? It tests one longer, hard-bounded client wait through the production provider, extraction, strict schema, mapping validation and literal oracle path.

This is a controlled hypothesis, not a remote-provider fix. R29 proved only `OVERALL_DEADLINE` at `30009` ms. It did not prove whether DeepSeek received, completed or billed the request. R27 returned a validated response in `29.542` seconds, leaving only `0.458` seconds below the former 30-second boundary, but one historical success does not establish a throughput upper bound. Output-token capacity also does not determine generation duration.

Even a successful R30 result is review-only: `humanReviewStatus=REQUIRED_NOT_PERFORMED` and `activationAllowed=false`. It does not cover the two semantic cases, market data, monitor startup, real-time evaluation, IN_APP delivery, human confirmation, plan save/activation, holdings, orders, fills or trading.

## Timeout geometry and rationale

| ID | R29 | R30 | Rationale |
|---|---:|---:|---|
| R30-T01 connect/write/pool inactivity | 30 s | 30 s | R29 did not identify these phases as the winner; no basis exists to enlarge them. |
| R30-T02 read inactivity | 30 s | 60 s | Allows a response or response chunk later than the former 30-second boundary; HTTPX defines this as per-chunk inactivity, not whole-request duration. |
| R30-T03 provider overall deadline | 30 s | 65 s | Leaves a five-second hard envelope above the read allowance and bounds the full request. |
| R30-T04 terminal observation | 31 s | 66 s | Allows the provider terminal result to be observed once without resubmission. |
| R30-T05 cooperative cleanup | up to 15 s | up to 15 s | Unchanged cleanup cap. |
| R30-T06 candidate hard total | 45 s | 81 s | `66 + 15`, with no background wait and no retry. |

HTTPX 0.28.1 documents independent connect, read, write and pool timeouts. Python 3.14 documents that `asyncio.timeout()` cancels overdue work and exposes `TimeoutError` outside the context. Sources checked at `2026-09-17T09:43:04+08:00`: https://www.python-httpx.org/advanced/timeouts/ and https://docs.python.org/3/library/asyncio-task.html#timeouts.

Production defaults and the real configuration remain unchanged. `AIProviderConfig` now accepts optional transport/read budgets; both default to `None`, preserving the former behavior of using `timeout_seconds` for every phase. Only the R30 bounded factory supplies `transport=30`, `read=60`, and `overall=65`.

## Fixed candidate contract

| ID | Fixed value |
|---|---|
| R30-C01 | A fresh atomic claim under `data/r30-ai-timeout-budget-acceptance/`; preparation and dry run do not create it. |
| R30-C02 | Start only on `2026-09-17` Asia/Shanghai after exact approval and a request to execute. AI-only extraction is not tied to an exchange session. Missing the date stops; no schedule or background wait is created. |
| R30-C03 | `LITERAL` only; physical AI POST cap `1`; retry/resubmission `0`; all market caps `0`, including `trade_cal=0`. |
| R30-C04 | `deepseek-v4-pro`; `plan-extract-v6`; `max_tokens=8192`; `temperature=0`; `thinking={"type":"disabled"}`; `response_format={"type":"json_object"}`; `stream=false`; one user message. |
| R30-C05 | Destination `POST https://api.deepseek.com/chat/completions`; no balance, model-list or account probe. |
| R30-C06 | Source SHA-256 `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`; prompt SHA-256 `7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba`; prompt size `19,359` UTF-8 bytes. |
| R30-C07 | Canonical request-body SHA-256 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`; source, prompt and every sent field are byte-identical to R29. |

The exact package is under `data/r30-ai-timeout-budget-review/`. Its package SHA-256 is `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`. It compares against R29 package SHA-256 `328620ea1d51a7b5b15128ca5f1741825478e46ec1fd6eef0f4abd271c8579f9` and records zero sent-field differences. The package change consists of local budget, purpose and current official price metadata; no credential is included.

## Official route and conservative cost snapshot

At `2026-09-17T09:43:04+08:00`, the official Chat Completions page documented `POST /chat/completions`, model alias `deepseek-v4-pro`, non-thinking mode, JSON object output and `max_tokens`. The official pricing page identified `DeepSeek-V4-Pro` at USD `0.435`/M cache-miss input, USD `0.003625`/M cache-hit input and USD `0.87`/M output. This differs from R29's earlier `DeepSeek-V4-Pro-0813` and USD `1.32`/M plus USD `3.96`/M snapshot. Sources: https://api-docs.deepseek.com/api/create-chat-completion/ and https://api-docs.deepseek.com/quick_start/pricing/.

Using a rounded-up `20,000` cache-miss input-token bound and the unchanged full `8,192` output-token cap, one request is conservatively estimated at USD `0.01582704` (`20000*0.435/1e6 + 8192*0.87/1e6`). Actual tokenization, cache allocation, output length, billing, taxes and account adjustments are unknown. Extending the local wait does not increase `max_tokens`. Recheck both official pages immediately before any approved dispatch; do not recharge or probe the account.

## Execution and stop rules

The isolated worktree contains no copied real configuration. An approved execution must receive the original configuration as an explicit read-only `--config-path` and match SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`.

Default invocation is offline-only. Live execution additionally requires the exact authorization token `R30_20260917_LITERAL_ONE_AI_ZERO_MARKET_TIMEOUT_BUDGET_ACCEPTANCE`, run ID `r30-20260917-a`, matching package/config hashes, a clean committed R30 branch, an unused claim, the eligible date, a fresh official route/price check, and explicit approval of one POST with the stated possible charge.

The first terminal success or failure stops. A connect/read/write/pool/overall timeout, missing diagnostic, unknown receipt/query, non-stop finish, model mismatch, JSON/schema/mapping/oracle failure, isolation failure or cleanup failure permits no second POST. Logs exclude source/prompt text, provider response content, exception text, credentials, headers and direct IP addresses. Success retains only an isolated review artifact; every business table remains empty.
