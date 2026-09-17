# R30 AI timeout-budget preparation record

Canonical English; `R30-ai-timeout-budget-preparation-20260917.zh-CN.md` is the equivalent Chinese review copy. Status **OFFLINE_COMPLETE / EXECUTION_BLOCKED_OFFICIAL_PRICE_MISMATCH / CLAIM_UNCONSUMED / ZERO_EXTERNAL_CALLS**.

Post-approval update: all local gates passed, but the direct official price page displayed a higher schedule than the approved review package. The dispatch stopped before claim creation or network execution. See `R30-ai-timeout-budget-execution-20260917.md`.

## Completed offline work

- Created isolated worktree `D:\Workspace\Projects\ai-quant-pilot\trade-plan-monitor-r30` and branch `codex/r30-ai-timeout-budget` from R29 commit `d7279155b8965423d55fc71adfe6d50b4079fa06`.
- Preserved the original main worktree's eight unrelated uncommitted files without staging, changing, cleaning, stashing or committing them.
- Added optional `transport_timeout_seconds` and `read_timeout_seconds` to `AIProviderConfig`. Defaults are `None`, so existing production behavior still applies `timeout_seconds` to connect/read/write/pool and the outer deadline.
- Prepared one R30 candidate with connect/write/pool `30` seconds, read `60` seconds, provider overall `65` seconds, terminal observation `66` seconds, cleanup up to `15` seconds and hard total `81` seconds.
- Kept model, source, prompt, `max_tokens=8192`, temperature, thinking mode, JSON response format, streaming flag, endpoint and one-message body unchanged from R29. Direct comparison of the actual local R29 and R30 material files returned `sourceBytesEqual=true`, `promptBytesEqual=true`, `bodyEqual=true`, and the same canonical body SHA-256 `c2a60f45fc41784ada733d6f6e7267435597d59897f1333b31ff1f242048c10c`.
- Generated the exact ignored review package under `data/r30-ai-timeout-budget-review/`; package SHA-256 is `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`.
- Rechecked the official DeepSeek route/model/price pages and the HTTPX/Python timeout semantics without uploading plan data. The current route remains `POST https://api.deepseek.com/chat/completions`; the current pricing snapshot yields a conservative one-request estimate of USD `0.01582704` at the fixed request bounds.

## Offline evidence

The RED phase failed because the provider model did not yet admit independent transport/read budgets. After the minimal implementation:

- R30 and R29 focused acceptance plus R30 timeout unit tests: **27/27 passed**.
- Wider provider/extraction/configured lifecycle/R26/R27/R28/R29/R30 regression group: **188/189 passed**. The sole failure was `test_production_app_defaults_to_direct_ai_configuration`, which stopped at `ProductionAssetError: Installed Web assets are unavailable` because this isolated worktree intentionally lacks built frontend assets. No AI timeout or candidate path was reached by that failure.
- The same wider group with that known asset-dependent test explicitly deselected: **188 passed, 1 deselected**.
- Ruff on changed Python files and `git diff --check`: passed before the candidate commit.
- The scaled delayed-response test used `40 ms` as the analogue of a response after the former `30 ms` boundary and before the new `65 ms` overall boundary. It exercised the production provider, extraction, strict schema, mapping validation and literal oracle. The result was accepted, one physical AI start was counted, market starts were zero, all isolated business tables were zero, cleanup completed, and the audit/journal/review-only artifacts agreed.
- A separate scaled hard-deadline test proved cancellation propagation, `OVERALL_DEADLINE`, one start and safe error metadata. Other focused tests retained observable CONNECT/READ/WRITE/POOL categories, denied a second request before network, stopped an unknown receipt without resubmission, and excluded secrets from evidence.

The time scaling and fake transport prove local control flow, not real DeepSeek performance. HTTPX `MockTransport` does not emulate network timing. No mock result is reported as live success.

## External-call and state accounting

During R30 preparation:

- DeepSeek POSTs: `0`;
- market calls, including `trade_cal`: `0`;
- balance/model-list/account probes: `0`;
- real claims consumed: `0`;
- real isolated run databases created: `0`;
- plan save/activation, holdings, orders, fills, webhooks: `0`.

The ignored review package is the only R30 local data artifact. No real configuration, credential, provider response or account data was copied into the worktree.

## Exact approval item

Before a live run, the reviewer must inspect:

- `data/r30-ai-timeout-budget-review/egress-review.zh-CN.md`;
- `data/r30-ai-timeout-budget-review/egress-material.json`;
- `data/r30-ai-timeout-budget-review/manifest.json`.

Approval means exactly one non-streaming `LITERAL` POST to `https://api.deepseek.com/chat/completions`, with zero retry and zero market call, using package SHA-256 `282fcb7198c54e861bb41c9822907a7841e17fdaa16cd46190c9b5a0f96acc10`, and accepting a conservative possible charge up to USD `0.01582704` before unknown taxes/account adjustments. It does not authorize any second POST, account probe, market call, plan save/activation or trading action.

At execution time, preflight must use the explicit read-only original config path, verify config SHA-256 `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`, confirm a clean committed branch and unused claim, and recheck the official route and price. The current local date gate is `2026-09-17` Asia/Shanghai; missing it requires a disclosed local gate update and a new dry run, not a silent send.
