# R30 execution record: authorization interpretation corrected after prior zero-call stop

Canonical English; `R30-ai-timeout-budget-execution-20260917.zh-CN.md` is the equivalent Chinese review copy. Status **PRIOR_ATTEMPT_NOT_RUN / AUTHORIZATION_SCOPE_CORRECTED / ZERO_EXTERNAL_CALLS_TO_DATE / CLAIM_UNCONSUMED / PACKAGE_UNCHANGED**.

## Authorized scope

The user explicitly approved the exact R30 review package, one non-streaming `LITERAL` POST to `https://api.deepseek.com/chat/completions`, zero retry, zero market calls and the possible charge. The approval question described approximately USD `0.01583` as an estimate and explicitly said it was not a billing guarantee. The user's answer was `批准并且接受` (approved and accepted). No user-set dollar ceiling was stated. The bound package SHA-256 was `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`; the canonical request-body SHA-256 was `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`.

## Local gates

At `2026-09-17T10:03:59+08:00`, before any claim or network dispatch:

- branch `codex/r30-ai-timeout-budget` was clean at `99ff581246f95b97ec44abcb4d5b3ae9e923c27a` and retained R29 commit `d7279155b8965423d55fc71adfe6d50b4079fa06` as an ancestor;
- the explicit read-only original configuration matched SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428` and selected `api.deepseek.com` plus `deepseek-v4-pro`;
- the package digest recomputed to the authorized value;
- actual R29/R30 source, prompt and request-body bytes were equal;
- source SHA-256 was `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191` and prompt SHA-256 was `7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba`;
- the date window was eligible and the claim was absent;
- the offline preflight returned `ready=true` while still requiring an immediate official route/price recheck.

## Official-price recheck and prior interpretation error

Search extraction returned two conflicting snapshots for the same DeepSeek official pricing page. The canonical result used by the approved package showed `DeepSeek-V4-Pro`, cache-miss input USD `0.435`/M and output USD `0.87`/M. A second official snapshot showed the older, higher peak/off-peak schedule.

Because that conflict could change the approved cost boundary, the canonical official page was opened directly in a read-only browser. At approximately `2026-09-17T10:04+08:00`, the live page displayed:

- model alias `deepseek-v4-pro` and model version `DeepSeek-V4-Pro-0813`;
- peak cache-miss input USD `1.32`/M and peak output USD `3.96`/M;
- off-peak cache-miss input USD `0.66`/M and off-peak output USD `1.98`/M;
- peak hours `01:00-04:00` and `06:00-10:00` UTC, Monday through Friday;
- OpenAI-format base URL `https://api.deepseek.com`.

Source: https://api-docs.deepseek.com/quick_start/pricing/.

At the fixed `20,000` input-token arithmetic bound and unchanged `8,192` output-token cap, the current official peak estimate is USD `0.05884032`; the off-peak estimate is USD `0.02942016`. Both exceed the frozen package estimate of USD `0.01582704`. Actual tokenization, cache split, output length, billing, taxes and account adjustments remain unknown.

The request route and model alias remained compatible. The first attempt nevertheless treated the frozen estimate as a user-set cost ceiling and stopped before claim creation. That was a conservative agent interpretation, not a program gate or an accurate reading of the user's approval. The pricing conflict and zero-call stop remain recorded, while the invalid conclusion that prior approval had expired is withdrawn. The reviewed package bytes, request body, window, configuration, call limits and authorization scope remain unchanged.

## Prior stop result and accounting

Prior dispatch decision: `NOT_RUN_AGENT_AUTHORIZATION_INTERPRETATION`; this records the historical stop and is not a current program or user-authorization failure.

- DeepSeek physical POST starts: `0`;
- retries/resubmissions: `0`;
- market calls, including `trade_cal`: `0`;
- balance/model-list/account probes: `0`;
- real claim created or consumed: `0`;
- isolated run database or business rows created: `0`;
- provider response, finish reason, returned model and usage: unavailable because no request was sent;
- strict schema, mapping oracle and review artifact: not run;
- lifecycle cleanup: not required because no execution lifecycle started;
- package, R29 evidence, real configuration, holdings and main worktree: unchanged.

The existing approval remains applicable to the exact one-request package after disclosure of the higher estimate because the disclosed USD `0.01582704` figure was explicitly an estimate rather than a hard limit. Any execution must still pass the unchanged positive program gates immediately before launch and must permanently consume the one-shot claim before network I/O. R31 is not opened automatically.
