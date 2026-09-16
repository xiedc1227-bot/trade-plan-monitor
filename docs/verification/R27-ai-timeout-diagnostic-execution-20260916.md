# R27 one-POST AI timeout diagnostic execution record

Canonical English; `R27-ai-timeout-diagnostic-execution-20260916.zh-CN.md` is the equivalent Chinese review copy. Proposal `R27-20260916-AI-TIMEOUT-DIAGNOSTIC-1`; run `r27-20260916-a`. Status **LIVE_ATTEMPT_COMPLETE / INVALID_OUTPUT_SCHEMA / CLAIM_CONSUMED / ONE_AI_ZERO_MARKET / FULL_WORKFLOW_NOT_PROVEN**.

## Outcome

The R27 candidate was prepared and verified on committed code, and the final live preflight returned `ready=true` on clean HEAD `6393e2aebc577901ab9a659c2d1f15876473ab8a`. The first dispatch request was rejected before process creation because the external-execution reviewer did not recognize direct authority in this task. No claim or call was consumed by that rejection. The user then directly and explicitly approved one send of the exact R27 `LITERAL` source and sole prompt to `POST https://api.deepseek.com/chat/completions` with the frozen fields and acknowledged possible cost.

Immediately before the authorized dispatch, the official DeepSeek pages again documented the endpoint, `deepseek-v4-pro` alias, non-thinking mode, JSON output and fixed request fields. They also retained the notice that the alias is currently routed server-side to `DeepSeek-V4.1-Flash` and billed at the Flash rate. No balance or model-list API was called. Sources: https://api-docs.deepseek.com/api/create-chat-completion/ and https://api-docs.deepseek.com/quick_start/pricing/.

The fresh run started at `2026-09-16T10:30:23.639967+08:00` and finished at `10:30:53.181944+08:00`, with `boundedWorkElapsedMs=29542`. Exactly one DeepSeek POST physically started. It returned a validated provider envelope with `finishReason=stop`, returned-model match `true`, and usage. The local extraction schema then rejected the output at `field_bindings[4]` with `schemaErrorType=value_error`. The terminal result was `INVALID_OUTPUT`, `stage=schema`, `reason=SCHEMA`; `providerErrorCode`, `timeoutKind` and `timeoutElapsedMs` were all absent. The literal oracle did not run, and no validated review result was retained.

## Result analysis

R27 establishes that this new request did **not** hit the R25 timeout condition: it received a complete provider response within the unchanged 30-second boundary, with one attempt and no retry. This does not retroactively identify the R25 timeout phase, provider receipt, completion or billing.

The safe evidence identifies the fifth `field_bindings` item as the schema failure location and `value_error` as the Pydantic error category. It intentionally omits the raw model response and validator exception text, so the exact violated field-binding invariant cannot be determined from retained evidence. It would be incorrect to label this as a literal-oracle mismatch: extraction never reached `SUCCEEDED`, and `oracleStatus=NOT_RUN`.

Validated usage was input `5161`, output `4340`, total `9501` tokens. At the documented weekday peak Flash rates of USD `0.30`/M cache-miss input and USD `1.20`/M output, treating all input as cache miss gives a conservative arithmetic upper estimate of USD `0.0067563` before tax/account adjustments. The retained usage does not include the cache-hit breakdown, so actual billing remains unknown. Market cost is zero because market calls were zero.

## Bounded execution evidence

| ID | Observed result |
|---|---|
| R27-E01 | AI physical starts `1/1`: `LITERAL=1`; retries `0`; denied-before-network `0`; operation ID `0fb05b25-3d4d-4fc7-ac11-50a7ddf0e9be`. |
| R27-E02 | Market calls `0/0`, including `trade_cal=0`; market/reference lifecycle was not started. |
| R27-E03 | v2 sidecar recorded `INVALID_OUTPUT / schema / SCHEMA / field_bindings[4] / value_error`, `finishReason=stop`, model match `true`, usage available, and no timeout metadata. |
| R27-E04 | Cleanup is `COMPLETE`; the one-shot claim and allowance are consumed; the run directory is retained and must not be reused. |
| R27-E05 | Every isolated business table has zero rows, including `plan_extraction_review`, all plan/activation/holding/market/evaluation/alert/delivery tables and `trading_calendar`. Review-sink receipts are `0`, and the review artifact result is `null`. |
| R27-E06 | Real `config/app.yaml` SHA-256 remains `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`, unchanged from R25. |

## Evidence integrity

- `audit.json`: `0d738f4242f20a20c209b1129b188f0dd4ffe591cdaf95993546f37c986bf555`.
- `physical-attempts.json`: `41566ac3e2def5aa8c68762729bda61d341498356db92dd2d56949d113bf93f0`.
- `monitor.ai-extraction-diagnostics.jsonl`: `7cf5cd52295bbbd419464a8c823f11c691be059437c3b1122e2bbaae4007602c`.
- `validated-review-result.json`: `c60cc3755c251fc1edaae678d02f2bbeb0a41ec2fe35338cd4e20e8eff4133c2`.
- `monitor.sqlite3`: `6a843beb818d6f1e52f05947eb094fe47630ce743d0e1010895e1c2b9992f283`.

The ignored evidence directory is `data/r27-ai-timeout-diagnostic/r27-20260916-a/`. No credential, authorization header, source text, prompt text, raw provider content, raw response, exception text or direct IP is included in this report.

## Offline verification

Before the live run, the R27 focused suite passed **15/15**, and the R27/R25/R26 plus provider, extraction and diagnostic regression group passed **108/108**, with one pre-existing Starlette/httpx deprecation warning. Ruff and `git diff --check` passed. No code changed during the live run.

## Conclusion boundary

R27 fulfilled the one-POST/zero-market diagnostic: the result was a real, non-timeout provider completion rejected by the local schema at `field_bindings[4]`. It did not produce a validated literal extraction, oracle result, human review, semantic-case evidence, monitor startup, realtime evaluation, IN_APP delivery, plan save/activation or trading evidence. The claim and allowance are consumed. Do not replay R27 or open R28 automatically; any future real request requires a new bounded candidate and authority.
