# R27 one-POST AI timeout diagnostic proposal

Canonical English; `R27-ai-timeout-diagnostic-proposal-20260916.zh-CN.md` is the equivalent Chinese review copy. Status **OFFLINE_CANDIDATE / LIVE_NOT_RUN / ONE_AI_POST_MAXIMUM / ZERO_MARKET**.

## Objective and boundary

R27 answers one narrow question: can the unchanged, previously approved `LITERAL` `plan-extract-v5` / 8192 request reach a terminal result through the production DeepSeek provider and extraction path; if not, which R26 v2 timeout category is recorded? It is an extraction diagnostic, not complete monitor, market, semantic, human-review or trading acceptance.

R27 permits exactly one physical AI POST, zero retries and zero resubmission. It permits zero market calls, including `trade_cal=0`, and does not start the production monitor/reference lifecycle, a Web listener, a broker action, a webhook or a trading action. It never saves or activates a plan and never changes a holding.

## Candidate identity and fixed limits

| ID | Fixed value |
|---|---|
| R27-C01 | Proposal `R27-20260916-AI-TIMEOUT-DIAGNOSTIC-1`; run `r27-20260916-a`; fresh one-shot claim under `data/r27-ai-timeout-diagnostic/`. |
| R27-C02 | Start window `2026-09-16 10:00:00` through `12:00:00` Asia/Shanghai. This extraction-only diagnostic does not depend on an exchange session or a market certificate. |
| R27-C03 | `LITERAL` only; `AI_TOTAL=1`; per-input cap `LITERAL=1`; all market endpoint caps and `MARKET_TOTAL` are `0`. |
| R27-C04 | Existing provider/HTTPX timeout `30` seconds; terminal observation allowance `31` seconds; hard bounded work deadline `45` seconds including no more than `15` seconds of cooperative cleanup. |
| R27-C05 | `deepseek-v4-pro`, `plan-extract-v5`, `max_tokens=8192`, `temperature=0`, `thinking={"type":"disabled"}`, `response_format={"type":"json_object"}`, `stream=false`, one user message and transport retries `0`. |
| R27-C06 | Destination `POST https://api.deepseek.com/chat/completions`; no balance, model-list or extra probe call. |

## Exact egress and authority

The source and sole user prompt are byte-identical to the `LITERAL` subset of the already approved R25 package. Their frozen SHA-256 values remain:

- source: `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`;
- prompt: `660945f63c48c66c6b115e8bb29a0ccc76fde1df60aca17ba7c74bba2a06ef89`.

The prior R25 exact package hashes are `6b0d300b0404a24b690281f9336a013f430b72ec9371be069b82c66aab92833d` and `4d689c24721901e3de8ee38d1accdfdc6f3f54433c36c446a5dff11ce04a32d0`. The user expressly approved those three exact sources and prompts for at most three DeepSeek sends; R25 physically started only `LITERAL` once, and the user then instructed this one-call/zero-market next step to continue. R27 is a fresh claim and operation, while its content, destination and request fields remain inside that exact approval scope. Any byte, field or destination change invalidates this gate and stops execution.

The fresh local review copies are `data/r27-ai-timeout-review/egress-review.md` and `egress-review.zh-CN.md`, with SHA-256 `cb0217addc5efde66f5f1a50d6b1eceac2c6b09121a422d92bfe1e0712e23554` and `4f282bd6cd384ca24e351c3fd3eae03db23d678ffd349ddff1d386a1a249250b`. They display the exact source and prompt, explain the diagnostic purpose and possible new charge, and omit the credential.

## Production path and isolation

The candidate uses `ConfiguredAIWebLifecycle`, `extract_plan` and `OpenAICompatibleProvider` with the existing `AIBudgetTransport`. It does not create a success-only provider bypass. A fresh isolated SQLite database is initialized only to prove business-state isolation. Successful validated extraction is received by an in-memory review sink and written only to the ignored run directory's review artifact; it is not persisted to `plan_extraction_review` or any plan, activation, holding, market, alert or delivery table.

The v2 diagnostic sidecar is colocated with the isolated database. It retains only the fixed diagnostic schema, including `timeoutKind`, `timeoutElapsedMs`, returned-model match, finish reason, attempt count and optional validated usage. It never retains credentials, headers, source, prompt, raw provider content, raw response, exception text or direct IP.

## Stop rules and result interpretation

R27 stops after the first terminal success or failure. It also stops without another POST on missing/invalid v2 diagnostics, receipt/query uncertainty, model mismatch, `finishReason=length`, invalid output, literal-oracle mismatch or cleanup/isolation failure. A later same-run attempt is rejected before network by the physical-attempt budget, and the atomic claim prevents reopening the candidate.

A recorded `CONNECT`, `READ`, `WRITE`, `POOL`, `OVERALL_DEADLINE` or `UNKNOWN` identifies only the local boundary observed by R26 instrumentation. It does not prove DeepSeek receipt, remote computation state, completion or billing. In particular, `READ` cannot distinguish provider computation, upstream queueing or a receive stall, while `OVERALL_DEADLINE` may mask a nearly simultaneous HTTPX boundary.

If extraction succeeds, R27 still requires human review and proves only this one `LITERAL` extraction and oracle result. It does not prove `SEM-AMB-01`, `SEM-UNS-01`, realtime evaluation, IN_APP delivery, market data, monitor startup, plan activation or trading.

## Cost and pre-execution source check

At `2026-09-16 10:25` Asia/Shanghai, the official Chat Completions reference still documented `POST /chat/completions`, the `deepseek-v4-pro` request alias, non-thinking mode, JSON output and the 8,192-token request value used by this candidate. The official pricing page also stated that from `2026-09-14 12:00` Beijing time, requests using the unchanged `deepseek-v4-pro` alias are routed server-side to `DeepSeek-V4.1-Flash` and billed at the Flash rate until V4.1 Pro is available. This route change requires no request-field or destination change, so the exact approved payload remains intact. Sources: https://api-docs.deepseek.com/api/create-chat-completion/ and https://api-docs.deepseek.com/quick_start/pricing/.

The current Flash prices are peak USD `0.30`/M cache-miss input and USD `1.20`/M output, with off-peak rates USD `0.15`/M and USD `0.60`/M. Under the conservative 19,000-input-token arithmetic bound and full 8,192 output tokens, one request is estimated at peak USD `0.0155304` or off-peak USD `0.0077652`, before taxes and account adjustments. The planned 10:00–12:00 Asia/Shanghai window falls within the documented weekday peak interval of 01:00–04:00 UTC. Actual tokenization, caching, output length, billing and taxes are unknown. Market fee is zero because no market call is permitted. No balance or model-list API was called.

The operator must re-read those official pages at the final execution gate. Any further route, request-contract or price change is recorded and blocks execution if it would require altering the approved payload.

## Offline verification and execution gate

Focused tests must cover simulated success, all six timeout kinds, one-call accounting, second-call denial, byte/hash/body tamper rejection, atomic second-claim refusal and cleanup. The R25/R26 extraction and diagnostic regression group, Ruff and `git diff --check` must pass. The exact review package must match its frozen hashes, the repository must be clean on a committed candidate, the new claim must be available, and the time window must be eligible.

Dry run and review generation make no network call:

```text
python -m scripts.r27_ai_timeout_diagnostic --prepare-egress-review
```

The live form is intentionally gated by the exact authorization token and run ID. It may be invoked once only after all gates above are green. No automatic R28 or retry follows any result.
