# R25 extraction-only acceptance execution

Canonical English; `R25-extraction-acceptance-execution-20260916.zh-CN.md` is the equivalent Chinese review copy. Proposal `R25-20260916-AM-EXTRACT-3`; run `r25-20260916-a`. Status **EXTRACTION_ACCEPTANCE_FAILED / ALLOWANCE_CONSUMED / CLOSED / FULL_WORKFLOW_NOT_PROVEN**.

## Outcome

At 09:30 Asia/Shanghai, the current official DeepSeek pages still identified `deepseek-v4-pro` as `DeepSeek-V4-Pro-0813`, documented `POST /chat/completions`, and retained peak prices per one million tokens of USD 0.044 cache-hit input, USD 1.32 cache-miss input, and USD 3.96 output. Sources: https://api-docs.deepseek.com/quick_start/pricing/ and https://api-docs.deepseek.com/api/create-chat-completion/.

After exact user approval of the immutable local review package, final offline preflight passed at `2026-09-16T09:41:23.794194+08:00` on clean HEAD `a67b76ca34c9dc1801c790ce45b23986eef12550`. The session ran from `09:41:54.211503+08:00` to `09:42:24.947266+08:00` (30.735763 seconds). The only `trade_cal` physical start succeeded, current-date reference validation passed, and 399 calendar rows were persisted.

The `LITERAL` case made one physical AI POST and received a content-free diagnostic with `status=PROVIDER_ERROR`, `stage=provider`, `providerErrorCode=TIMEOUT`, `path=unknown`, unknown finish reason, no usage values, and no returned-model match result. Its operation ID is `8c00d923-dc5d-484e-9175-7e53d0d552b0`. Because receipt/completion and billing cannot be established from the preserved metadata, the candidate classified the case as `EXTRACTION_OR_DIAGNOSTIC_REJECTED`, stopped immediately, and did not resubmit it. `SEM-AMB-01` and `SEM-UNS-01` were not sent.

AI starts were 1/3: `LITERAL=1`, `SEM-AMB-01=0`, `SEM-UNS-01=0`. Market starts were 1/1 with only `trade_cal=1`; every other market endpoint remained zero. Retries and denied-before-network counts were zero. AI cost is indeterminate because the request physically started but no usage was returned; market-data fee and tax also remain unknown.

Normal audit is present, final AI/market budget snapshots in `physical-attempts.json` match `audit.json`, cleanup is `COMPLETE`, and port 18770 has no listener. The fresh run directory remains as the consumed one-shot claim and must not be reused. `validated-review-results.json` contains only the rejected-case review record; no validated extraction was saved. `plan_version`, `plan_activation_state`, `active_plan`, and `plan_extraction_review` are all zero.

Read-only SQLite inspection used `mode=ro` and `PRAGMA query_only=ON`. `trading_calendar` has 399 rows; `alembic_version` and `monitor_sequence` each have one. Every other business table, including source, version, review, activation, holding, market bars/quotes, evaluation, alert, and delivery tables, has zero rows.

## Evidence integrity

- `audit.json`: `32a1da86d7f537a7144b255d5fadac153767339a0d157206ae05a951c9f7be6a`.
- `physical-attempts.json`: `662746e3ed56e0e18bad82c5229dfec216d4815f90ed4d1bc0b5027cb0040dc2`.
- `monitor.ai-extraction-diagnostics.jsonl`: `8bc1613700b7d5e352df4f1efb357f977f21f682e4cee697e3894d912aa3c869`.
- `validated-review-results.json`: `0415f10dfa5ff0dc7b003b28a1cf4d31245dc62628a45edcaad86ca916729e21`.
- `monitor.sqlite3`: `2dc2c988d34a1b1eed196bbc58bcdef8ab01e879aa83c4d92ccca772327612ec`.
- Real `config/app.yaml`: `89923ea019712573b0f8118164eda1ee2a8371c4ee57faf2a2ad48fd6b8ab428`, unchanged from the prior preflight record.

The cursor key is intentionally excluded from hashing/output because its filesystem permissions deny ordinary inspection. No credential, direct address, authorization header, source text, prompt text, raw provider content, or exception body is retained in this report.

## Conclusion boundary

R25 proves that the fixed candidate admitted exactly one successful calendar prerequisite, attempted only the first approved AI case, stopped on its first provider timeout, preserved a content-free diagnostic, and completed isolation cleanup without activating or saving a plan. It does not prove successful `plan-extract-v5` / 8192 extraction, literal fidelity, either semantic blocker, a provider model match, or human review.

The evidence cannot distinguish a connect, TLS, write, read, remote-processing, or local timeout cause, and it cannot prove whether the provider received or billed the timed-out request. The consumed claim, run ID, window, and allowance must not be reused. Do not activate a plan, open R26 automatically, or make another real request without a new bounded candidate and authority.
