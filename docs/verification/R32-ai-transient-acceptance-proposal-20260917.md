# R32 isolated AI transient-classification acceptance proposal

Canonical English; `R32-ai-transient-acceptance-proposal-20260917.zh-CN.md` is the equivalent Chinese review copy. Proposal `R32-20260917-V6-LITERAL-TRANSIENT-ACCEPTANCE-1`; candidate run `r32-20260917-a`. Status **AI_ACCEPTANCE_FAILED / TERMINAL / ONE_AI_POST / ZERO_RETRY / ZERO_MARKET_ACCOUNT**.

## Scope

R32 prepares, but does not execute, one new isolated candidate that can verify whether the R31 `transientKind` contract reaches the existing real extraction chain. The candidate keeps the R30 v6 `LITERAL` request unchanged and adds no extraction behavior, schema relaxation, retry, market-data call, account probe, plan persistence, activation, monitoring, holding mutation, order, fill, or trade action.

R30 is historical evidence only. Its consumed claim and run identity must never be reused. R32 uses a new proposal, run, operation, idempotency key, claim root, run directory, audit, physical-attempt journal, diagnostic sidecar, database, and review artifact.

## Frozen request and local budgets

- destination: `POST https://api.deepseek.com/chat/completions`;
- source SHA-256: `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`;
- prompt SHA-256: `7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba` and UTF-8 length `19,359` bytes;
- canonical request-body SHA-256: `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`;
- model `deepseek-v4-pro`, prompt version `plan-extract-v6`, `max_tokens=8192`, `temperature=0`, `thinking={"type":"disabled"}`, `response_format={"type":"json_object"}`, `stream=false`, and one user message;
- connect/write/pool `30s`, read `60s`, provider overall `65s`, terminal observation `66s`, cleanup at most `15s`, and hard total `81s`;
- at most `1` physical AI POST, `0` retries/resubmissions, `0` market calls, and `0` account calls. Every terminal result, including `UNKNOWN`, stops the candidate.

These values must be recomputed from the real local source, prompt, and request material. They are not accepted merely because this document repeats them. Production defaults and the real configuration remain unchanged.

## Authorization and default behavior

`python -m scripts.r32_ai_transient_acceptance` is an offline dry run and cannot create or consume a claim. Exact review-package generation is local only. Live execution requires all positive gates, an explicit config path, the exact new R32 authorization token, the exact run ID, an unconsumed R32 claim, and fresh explicit user approval bound to the generated package hashes and stated destination.

R25, R30, historical default authorization, and the instruction to continue are not R32 live approval. The user approved this exact package, destination, one-POST limit, zero-retry/market/account limits, and possible fee on 2026-09-17. Execution remains blocked until that approval is represented by a hash-bound local attestation, current official route and price facts are recorded, all immutable gates pass at an exact clean branch and commit, and an independent post-remediation review finds no substantive blocker.

## Post-approval safety gates

- The complete canonical outbound body must match `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`; extra top-level or message fields are denied before network I/O. The transport rebuilds the configured numeric zero as the reviewed JSON integer `0` before final hash verification.
- Preflight binds the clean branch `codex/r32-ai-transient-acceptance`, an explicitly supplied exact commit, the frozen package, the unchanged real configuration hash, the fresh run identity, and the approval-attestation hash.
- The same immutable snapshot is checked again after local lifecycle startup and before submission. Any change consumes no additional request and terminates locally.
- The claim is the atomic creation of `data/r32-ai-transient-acceptance/r32-20260917-a/`; an existing run directory is rejected without creating another marker.
- Both lifecycles share one cleanup deadline of at most `15s`. A parent-process watchdog bounds the entire child execution to `81s` and emits only a content-free status on timeout or unavailable child output.

## Acceptance criteria

| ID | Criterion |
|---|---|
| R32-A01 | Default and review-package commands make zero network calls and create or consume zero execution claims. |
| R32-A02 | A fresh R32 claim permits exactly one physical POST and a second admission is denied before network I/O; R30 identities and claims are never reused. |
| R32-A03 | The generated package contains the exact complete local source and prompt, fixed request fields, destination, limits, cost uncertainty, and comparison showing no sent-field difference from R30; credentials are absent. |
| R32-A04 | Source, prompt, prompt byte length, and canonical body hashes are recomputed and match the frozen values; component and package hashes are recorded in a manifest and tampering blocks preflight. |
| R32-A05 | Offline fake transport failures traverse the real provider/extraction/sidecar/assessment path, emit sidecar v3, retain only a closed `transientKind`, and do not retain injected exception text, response text, headers, credentials, prompts, URLs, or IP addresses. |
| R32-A06 | Offline fake success traverses the production provider, extraction, strict schema, mapping, literal oracle, and review-receipt checks; failure and `UNKNOWN` terminate without retry or resubmission. |
| R32-A07 | Cancellation respects the hard deadline; cleanup, audit, physical-attempt journal, and diagnostic evidence agree; every independently queried business table remains empty. |
| R32-A08 | Focused regressions and Ruff pass. Known installed-Web-asset baseline exclusions are named rather than disabled or weakened. |
| R32-A09 | English and Chinese proposal, preparation report, exact review copies, manifest metadata, and handoff preserve the same IDs, hashes, limits, boundaries, and acceptance result. |
| R32-A10 | Before live execution, actual external calls remain `0`, retries `0`, market/account calls `0`, and real R32 claims created or consumed `0`; execution requires the hash-bound approval attestation and current official review record. |

## Stop conditions

Preparation stops on any hash, package, bilingual, schema, mapping, oracle, cleanup, audit, journal, business-table, config, branch, or claim inconsistency. A future live candidate must stop after its first terminal result. A `TRANSIENT / UNKNOWN` result is terminal and must not trigger another paid request.
