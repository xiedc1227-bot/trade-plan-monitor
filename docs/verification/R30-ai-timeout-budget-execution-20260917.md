# R30 execution gate record: dispatch blocked by current official pricing

Canonical English; `R30-ai-timeout-budget-execution-20260917.zh-CN.md` is the equivalent Chinese review copy. Status **NOT_RUN_OFFICIAL_PRICE_GATE_FAILED / ZERO_EXTERNAL_CALLS / CLAIM_UNCONSUMED / PACKAGE_UNCHANGED**.

## Authorized scope

The user explicitly approved the exact R30 review package and accepted its disclosed possible charge. The bound package SHA-256 was `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`; the canonical request-body SHA-256 was `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`. Authorization covered one non-streaming `LITERAL` POST to `https://api.deepseek.com/chat/completions`, zero retry and zero market calls, with a conservative disclosed estimate of USD `0.01582704` before unknown taxes and account adjustments.

## Local gates

At `2026-09-17T10:03:59+08:00`, before any claim or network dispatch:

- branch `codex/r30-ai-timeout-budget` was clean at `99ff581246f95b97ec44abcb4d5b3ae9e923c27a` and retained R29 commit `d7279155b8965423d55fc71adfe6d50b4079fa06` as an ancestor;
- the explicit read-only original configuration matched SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428` and selected `api.deepseek.com` plus `deepseek-v4-pro`;
- the package digest recomputed to the authorized value;
- actual R29/R30 source, prompt and request-body bytes were equal;
- source SHA-256 was `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191` and prompt SHA-256 was `7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba`;
- the date window was eligible and the claim was absent;
- the offline preflight returned `ready=true` while still requiring an immediate official route/price recheck.

## Official-price gate failure

Search extraction returned two conflicting snapshots for the same DeepSeek official pricing page. The canonical result used by the approved package showed `DeepSeek-V4-Pro`, cache-miss input USD `0.435`/M and output USD `0.87`/M. A second official snapshot showed the older, higher peak/off-peak schedule.

Because that conflict could change the approved cost boundary, the canonical official page was opened directly in a read-only browser. At approximately `2026-09-17T10:04+08:00`, the live page displayed:

- model alias `deepseek-v4-pro` and model version `DeepSeek-V4-Pro-0813`;
- peak cache-miss input USD `1.32`/M and peak output USD `3.96`/M;
- off-peak cache-miss input USD `0.66`/M and off-peak output USD `1.98`/M;
- peak hours `01:00-04:00` and `06:00-10:00` UTC, Monday through Friday;
- OpenAI-format base URL `https://api.deepseek.com`.

Source: https://api-docs.deepseek.com/quick_start/pricing/.

At the fixed `20,000` input-token arithmetic bound and unchanged `8,192` output-token cap, the current official peak estimate is USD `0.05884032`; the off-peak estimate is USD `0.02942016`. Both exceed the approved package estimate of USD `0.01582704`. Actual tokenization, cache split, output length, billing, taxes and account adjustments remain unknown.

The request route and model alias remained compatible, but the reviewed price/model-version metadata and conservative cost ceiling did not. This failed a mandatory pre-dispatch gate. No attempt was made to change the window, configuration, request body or authorization scope.

## Stop result and accounting

Dispatch decision: `NOT_RUN_OFFICIAL_PRICE_GATE_FAILED`.

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

The prior approval does not cover a request presented with the newly observed cost boundary. A future attempt would require a newly reviewed cost statement and explicit user authority. R31 is not opened automatically.
