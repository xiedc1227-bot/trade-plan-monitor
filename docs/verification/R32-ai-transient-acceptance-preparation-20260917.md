# R32 AI transient-classification acceptance preparation record

Canonical English; `R32-ai-transient-acceptance-preparation-20260917.zh-CN.md` is the equivalent Chinese review copy. Status **AI_ACCEPTANCE_FAILED / TERMINAL / ONE_AI_POST / ZERO_RETRY / ZERO_MARKET_ACCOUNT / CLAIM_CONSUMED**.

## Scope completed

R32 was prepared in the isolated worktree `D:\Workspace\Projects\ai-quant-pilot\trade-plan-monitor-r32` on branch `codex/r32-ai-transient-acceptance`, based on R31 commit `ca7e878fea27f1a9a602915a9a48cbfd80a83cf6`. The main worktree remained at `e947397d373aa6ed79c5e88f16145eedf14053f0` with its eight unrelated modified files preserved.

The offline candidate uses proposal `R32-20260917-V6-LITERAL-TRANSIENT-ACCEPTANCE-1` and run `r32-20260917-a`. It has a new R32 claim root, run directory, operation and idempotency identities, audit, physical-attempt journal, sidecar, isolated database, and review artifact. It does not reuse the consumed R30 claim or `r30-20260917-a` identity.

The default command is `DRY_RUN_NO_NETWORK`. Exact review-package generation is also local only. The user supplied fresh explicit approval for this exact package and possible fee on 2026-09-17. Live execution additionally requires `--execute`, an explicit configuration path, exact authorization token `R32_20260917_LITERAL_ONE_AI_ZERO_MARKET_TRANSIENT_ACCEPTANCE`, exact run ID, all positive immutable gates, the hash-bound approval attestation, current official route and price review, and an unconsumed R32 claim.

## Post-approval adversarial review and remediation

Independent reviews, including `gpt-6-astra` at `xhigh` reasoning, blocked the initial candidate before any network or claim action. They identified complete-body admission, shared cleanup timing, total-process timing, exact branch/commit binding, atomic claim behavior, and invalid-host disclosure gaps. The remediated candidate now:

- reconstructs and verifies the complete outbound canonical body at the final transport boundary and rejects any added field before network I/O;
- requires an exact clean branch and commit plus a hash-bound approval attestation at preflight, then rechecks the configuration, package, approval, branch, commit, material, and date after lifecycle startup and before submission;
- atomically creates the run directory as the one-shot claim and rejects an existing directory without consuming another marker;
- shares one `15s` cleanup deadline and uses an external parent watchdog for the complete `81s` execution bound;
- reports no rejected direct host and emits no captured child output or exception text when the watchdog fires.

The approved source, prompt, destination, request fields, package files, component hashes, ordered package hash, attempt limits, and possible-fee scope did not change.

The final `gpt-6-astra` / `xhigh` read-only review reproduced the repaired watchdog and timeout-evidence paths and reported no remaining reproducible P1/P2 blocker. The hardened focused suite passed **24/24** and the adjacent diagnostic/acceptance regression group passed **70/70**, with only the existing Starlette/httpx deprecation warning.

The first authorized launcher invocation stopped before claim creation or network I/O because the elevated execution identity could not read Git state under Git's safe-directory policy. The read-only Git checks now apply a command-scoped safe-directory value for this exact worktree; no global Git configuration is changed. This local preflight stop consumed no physical POST and is not a retry or resubmission.

## Recomputed frozen request

The real R30 `egress-material.json` in `D:\Workspace\Projects\ai-quant-pilot\trade-plan-monitor-r30\data\r30-ai-timeout-budget-review\` and the generated R32 material were parsed and compared without displaying their source or prompt text. The results were:

- `sourceBytesEqual=true` and source SHA-256 `0b8b389b9b083adff268186c2d6ac8a2589b4ad02e0b4d3b5b8ca37ce1452191`;
- `promptBytesEqual=true`, prompt SHA-256 `7ea200c89eb3357659aa9ab96aa3cd97e9c685474bf2f996592f1460219d86ba`, and UTF-8 length `19,359` bytes;
- `bodyEqual=true` and canonical request-body SHA-256 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`;
- historical R30 package SHA-256 `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`.

The candidate remains one non-streaming `POST https://api.deepseek.com/chat/completions` request with model `deepseek-v4-pro`, prompt version `plan-extract-v6`, `max_tokens=8192`, `temperature=0`, `thinking={"type":"disabled"}`, `response_format={"type":"json_object"}`, and one user message. There are no sent-field differences from R30.

## Exact local review package

The complete source and prompt appear only in the controlled local review files under `data/r32-ai-transient-review/`; they are not reproduced in this report. Credentials, authorization values, provider responses, exception text, headers, and direct IP addresses are absent.

| File | SHA-256 | Bytes |
|---|---|---:|
| `egress-material.json` | `0d21ba5216c8ff5b70aea3bc50fdbb4f0a9ca43e55bf8890065f873c7bd0941f` | `25,613` |
| `egress-review.md` | `401cc23111147d3389b474e5e2211fd2cac9110ebee852d5ff7563602930f2c0` | `22,184` |
| `egress-review.zh-CN.md` | `3d196b44697168688510c1e5a851282e932e66431126c4a40e78e76838f7739d` | `22,080` |
| `manifest.json` | `5a60e76e4499a921d09351adb2d0e7b38e66a3525526354d176436ca8d0e3b13` | `570` |

The ordered package SHA-256 over `egress-material.json`, `egress-review.md`, and `egress-review.zh-CN.md` is `7832b7e80f791c6a9f58fb30e1bd1f18f1958c60e6d845557d9b4f5e0916bfda`. The manifest records the same order, component hashes, package hash, and proposal ID. Offline tests prove that modifying a component makes the package check fail.

The package discloses the R30 price observation time `2026-09-17T10:22:27.399234+08:00` and its historical peak/off-peak estimates, but labels them as a historical snapshot, not a current quote, billing guarantee, or hard cost gate. Actual tokenization, cache split, output length, billing, taxes, and account adjustments remain unknown. Provider receipt, processing, and billing may remain unconfirmable even after a future attempt.

## Candidate limits and terminal behavior

- AI physical POST cap `1`; retries/resubmissions `0`; market calls `0`; account calls `0`;
- connect/write/pool `30s`; read `60s`; provider overall `65s`; terminal observation `66s`; cleanup at most `15s`; hard total `81s`;
- every terminal result stops, including `TRANSIENT / UNKNOWN`;
- a valid response continues through the existing provider, extraction, strict schema, mapping, literal oracle, and review-receipt checks;
- a transient response uses sidecar v3 and the closed R31 `transientKind` contract without retaining exception/response content;
- production defaults, the real configuration, TLS verification, proxy behavior, holdings, plan state, and extraction schema were not changed.

The real configuration was not needed and was not opened during R32 preparation. The existing read-only execution gate still requires SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428` before any future live candidate.

## Offline verification

- R32 focused integration group: **11/11 passed** with one existing Starlette/httpx deprecation warning.
- R31 diagnostic surface plus R27, R29, R30, and R32 compatibility group: **132/132 passed** with the same existing warning.
- R15 non-asset cases: **2/2 passed**; the two parameterized `test_simulated_production_composition_selects_the_database_sidecar` cases were explicitly deselected because isolated worktrees do not contain installed Web assets. This known baseline was named, not weakened.
- Ruff passed for `scripts/r32_ai_transient_acceptance.py` and `tests/integration/test_r32_ai_transient_acceptance.py`.
- `git diff --check` passed.

Offline fakes verified default zero execution, one admission and second denial before network I/O, deterministic package and tamper detection, real provider/extraction/sidecar/assessment traversal, v3 `CONNECT` and `UNKNOWN` categories, content redaction, valid-response schema/mapping/oracle success, uncertain-receipt stop, overall-deadline cancellation, cleanup completion, audit/journal agreement, zero market starts, and zero rows in all 38 business tables. These fakes are not evidence about DeepSeek availability, processing, or billing.

## External-call and claim accounting

- real AI requests: `0`;
- real retries/resubmissions: `0`;
- real market-data and account requests: `0`;
- route, pricing, DNS, TCP, TLS, proxy, certificate, or other network probes: `0`;
- real R32 execution claims created or consumed: `0`;
- R30 replay: `0`;
- live acceptance: **not run**.

## Terminal execution disposition

All gates passed and the one allowed POST was consumed. The result was terminal `AI_ACCEPTANCE_FAILED` because the response failed strict schema validation at `draft.plan_id`. Cleanup completed, audit and journal agree, market/account calls remained zero, and all 38 business tables remained empty. See `R32-ai-transient-acceptance-execution-20260917.md`. No retry, resubmission, R30 replay, or R33 action is permitted.
