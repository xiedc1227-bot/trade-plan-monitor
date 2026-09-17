# R30 execution record: one-shot attempt ended in a transient provider error

Canonical English; `R30-ai-timeout-budget-execution-20260917.zh-CN.md` is the equivalent Chinese review copy. Status **EXECUTED_ONCE / AI_ACCEPTANCE_FAILED / PROVIDER_ERROR_TRANSIENT / CLAIM_CONSUMED / NO_RETRY / CLEANUP_COMPLETE**.

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

## Authorized one-shot execution

After the authorization correction was committed as `71bd09cd757b4cf78788ec3d086f5a2462e5650d`, the official pages were opened directly again. They still showed `POST https://api.deepseek.com/chat/completions`, alias `deepseek-v4-pro`, model version `DeepSeek-V4-Pro-0813`, and the higher peak/off-peak pricing. At `2026-09-17T10:22:27.399234+08:00`, the candidate preflight returned `ready=true` with:

- clean committed R30 branch and eligible local date;
- original read-only configuration SHA-256 match and configured key/model/host readiness;
- package SHA-256 `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`;
- source, prompt and canonical request-body hashes unchanged, including request SHA-256 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`;
- fresh claim and absent prior run directory;
- one AI physical-attempt cap, zero retry, zero market cap, 65-second provider deadline and 81-second hard total.

The authorized launcher started at `2026-09-17T10:23:06.465672+08:00`, atomically consumed the claim before the provider path, and started the sole physical AI attempt. It finished at `2026-09-17T10:23:06.726004+08:00` after `261` bounded-work milliseconds with `AI_ACCEPTANCE_FAILED`.

The safe diagnostic reported `PROVIDER_ERROR` at the provider stage with `providerErrorCode=TRANSIENT`, `attempts=1`, no timeout classification, unknown finish reason, unavailable usage and no returned-model match determination. No provider response was available. Strict schema validation, mapping validation and the literal oracle therefore did not run; `oracleStatus=NOT_RUN`, review result was null, and review-sink receipts were zero. The evidence does not establish whether DeepSeek received or billed the attempt. No retry or resubmission is permitted.

## Final accounting and safety verification

- AI physical attempts: `1`; retries/resubmissions: `0`; denied-before-network attempts: `0`;
- market calls, including `trade_cal`: `0`; market lifecycle started: `false`;
- balance/model-list/account probes: `0`;
- real claim: consumed and retained; run directory: retained;
- cleanup: `COMPLETE`; no candidate process remained after launcher exit;
- activation allowed: `false`; human review status: `REQUIRED_NOT_PERFORMED`;
- all `38` independently queried business tables were empty; only local schema metadata rows existed;
- audit and physical-attempt journal agreed on status and counts; the journal recorded `normalAuditPresent=true`;
- real configuration was read only and not copied; package, request bytes, holdings and original main worktree remained unchanged.

## Evidence integrity

- `audit.json`: `9e5fb96e316fbef9b8b11c811f2a11b78e16941080718e5a459948a871a2e048`;
- `physical-attempts.json`: `9d4cef6722a70d690c06a1240b2ff30631719f244dc35e512361ac5094d2fa7d`;
- `monitor.ai-extraction-diagnostics.jsonl`: `b96aa8f4607315f57fbf00496bf03521c024bb3822d37b33ce98735b508fab40`;
- `validated-review-result.json`: `d64c4b1b55899621b50240fc3c961366e3393931705b80fa859f5a20b989338e`;
- `monitor.sqlite3`: `237a0911e2f6b6adfafcf6d1b4a5430af1d224936ce0b52b053407843310c255`;
- `monitor.sqlite3-shm`: `fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb`;
- `monitor.sqlite3-wal`: empty-file SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

The retained ignored evidence directory is `data/r30-ai-timeout-budget-acceptance/r30-20260917-a/`. The report excludes credentials, authorization headers, source/prompt text, raw provider content, exception text and direct IP addresses.

R30 did not validate the timeout-budget hypothesis because no terminal model response was obtained. The consumed claim forbids another R30 attempt. R31 was not opened.
