# R29 one-POST plan-extract-v6 acceptance proposal

Canonical English; `R29-v6-extraction-proposal-20260916.zh-CN.md` is the equivalent Chinese review copy. Proposal `R29-20260917-V6-LITERAL-ACCEPTANCE-1`; run `r29-20260917-a`. Status **OFFLINE_CANDIDATE / EXACT_EGRESS_REVIEW_READY / LIVE_NOT_AUTHORIZED / CLAIM_UNCONSUMED / ZERO_EXTERNAL_CALLS**.

## Objective and evidence boundary

R29 answers one narrow question: can the unchanged synthetic `LITERAL` source, sent with the newly reviewed `plan-extract-v6` prompt through the production DeepSeek provider, extraction, strict schema, mapping validation and literal-oracle path, reach `SUCCEEDED / completed / NONE` and produce a review-only artifact?

This is not full workflow acceptance. It does not cover the two semantic cases, market data, monitor startup, real-time evaluation, IN_APP delivery, human review, plan save/activation, holdings, orders, fills or trading. A successful result still means `humanReviewStatus=REQUIRED_NOT_PERFORMED` and `activationAllowed=false`.

## Fixed candidate contract

| ID | Fixed value |
|---|---|
| R29-C01 | One fresh atomic claim under `data/r29-v6-extraction-acceptance/`; it is not created during preparation or dry run. |
| R29-C02 | Start window `2026-09-17 09:00:00` through `18:00:00` Asia/Shanghai. Extraction does not depend on an exchange session. Missing this window stops the candidate; no background wait or schedule is created. |
| R29-C03 | `LITERAL` only; physical AI POST cap `1`; retry/resubmission `0`; every market cap `0`, including `trade_cal=0`. |
| R29-C04 | Existing provider/HTTPX timeout `30` seconds; terminal observation allowance `31` seconds; hard total `45` seconds including at most `15` seconds of cooperative cleanup. |
| R29-C05 | Model alias `deepseek-v4-pro`; `plan-extract-v6`; `max_tokens=8192`; `temperature=0`; `thinking={"type":"disabled"}`; `response_format={"type":"json_object"}`; `stream=false`; exactly one user message. |
| R29-C06 | Destination `POST https://api.deepseek.com/chat/completions`; no balance, model-list or other account/API probe. |
| R29-C07 | Source SHA-256 `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`; v6 prompt SHA-256 `7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba`; prompt size `19,359` UTF-8 bytes. |

The former `19,000`-byte transport ceiling would reject the complete v6 prompt before network. The shared transport therefore accepts a configurable ceiling while retaining `19,000` as its default. R29 alone supplies exactly `19,359`, and the transport still requires the frozen prompt hash plus the exact endpoint, body fields and one-attempt budget. This does not admit arbitrary longer prompts and does not change R25/R27 frozen prompts, hashes, claims or evidence.

## Exact egress and changed approval scope

The complete source, complete sole v6 user prompt, all fixed request fields, omitted-credential header scope, destination, purpose, v5/v6 hash comparison, current price snapshot and package hashes are in:

- `data/r29-v6-extraction-review/egress-review.md`;
- `data/r29-v6-extraction-review/egress-review.zh-CN.md`;
- `data/r29-v6-extraction-review/egress-material.json`;
- `data/r29-v6-extraction-review/manifest.json`.

The package SHA-256 over `egress-material.json`, `egress-review.md`, and `egress-review.zh-CN.md` in that order is `328620ea1d51a7b5b15128ca5f1741825478e46ec1fd6eef0f4abd271c8579f9`. Component hashes are frozen in the script and manifest. Credentials, the complete local configuration, response content, exception text, headers returned by the provider and direct IP addresses are excluded.

The source bytes are unchanged from R25/R27, but the sole prompt changes from v5 hash `660945f63c48c66c6b115e8bb29a0ccc76fde1df60aca17ba7c74bba2a06ef89` to the v6 hash above. v6 adds rules 12–14 for the exact origin/reference matrix, unique binding identities, scalar type/value/unit rules, `ALL|ANY` structure bindings and reciprocal SOURCE mapping. Therefore the prior v5 approvals do not authorize R29. One explicit approval of this exact package and destination is required before execution.

## Production path, configuration and isolation

R29 uses `ConfiguredAIWebLifecycle`, `extract_plan`, `OpenAICompatibleProvider`, strict `PlanExtractionOutputV4`, server mapping validation and the existing literal oracle. It adds no success-only provider or schema bypass.

The isolated worktree intentionally has no ignored `config/app.yaml`. Preparation does not copy credentials, configuration or databases. A future approved execution must receive an explicit read-only `--config-path`; preflight requires that file to match SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`, select the configured DeepSeek profile and alias, and point only to `https://api.deepseek.com`. The path and configuration contents are not written to evidence.

A fresh isolated SQLite database and v2 sidecar are created only after every gate passes and the execute command is authorized. Success is retained in an ignored local review artifact and in-memory review receipt only. Every business table must remain empty, including plan/extraction-review, activation, holdings, market, evaluation, alert, delivery and trading-calendar tables.

## Success and stop rules

Success requires all of the following: terminal `SUCCEEDED`; diagnostic `completed / NONE`; `finishReason=stop`; returned-model match `true`; exact source, prompt version and operation receipt; validated usage when present; literal oracle acceptance; exactly one review-only result; full cleanup; one AI start maximum; zero market starts; and zero rows in every isolated business table.

Any provider error, timeout, non-stop finish, model mismatch, JSON/schema/mapping failure, literal-oracle mismatch, missing/invalid sidecar, receipt/query uncertainty, isolation failure or cleanup failure stops without another POST. Safe schema diagnostics may expose only fixed allowlisted codes, including the six R28 field-binding codes; raw response and exception content remain excluded. No outcome may be used to infer the omitted R27 response.

## Official contract and conservative cost snapshot

At `2026-09-16T11:09:28+08:00`, the official Chat Completions reference documented `POST /chat/completions`, `deepseek-v4-pro`, non-thinking mode, JSON object output and the fixed fields used here. The current official pricing page documented the alias as `DeepSeek-V4-Pro-0813`, with peak cache-miss input USD `1.32`/M and output USD `3.96`/M; this differs from R27's earlier temporary Flash-routing snapshot. Sources: https://api-docs.deepseek.com/api/create-chat-completion/ and https://api-docs.deepseek.com/quick_start/pricing/.

Using a deliberately conservative rounded-up `20,000` input-token bound and the full `8,192` output tokens, one request is at most USD `0.05884032` at the documented peak rates before taxes or account adjustments. Off-peak arithmetic would be USD `0.02942016`. Actual tokenization, cache split, output length, billing and taxes are unknown. Market cost is zero because market calls are forbidden. The official route, contract and price pages must be checked again immediately before any approved dispatch; a change that alters the approved payload blocks execution.

## Execution gate

Default invocation and review generation are offline-only. Live execution additionally requires: the exact authorization token and run ID; explicit `--config-path`; matching source/prompt/body/package/config hashes; committed clean R29 code; unused claim; eligible window; official route/price recheck; and the user's explicit approval of the exact review package. Preparation has consumed none of these one-shot resources.
