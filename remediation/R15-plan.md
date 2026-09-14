# R15 offline AI extraction diagnostics plan

Canonical English; `R15-plan.zh-CN.md` is the equivalent Chinese review copy. R15 follows the partial R14 real execution recorded in `docs/verification/R14-execution-20260914-supplement.md`. The original three provider responses were not retained; their precise causes remain unknown.

## Scope and boundary

- Work only on the AI extraction, Web lifecycle, and local diagnostic persistence path. Do not run paid AI, market, Webhook, or real `--execute`; do not reuse the R14 one-shot authorization or modify its claim, database, or completed evidence.
- Keep the original strict prompt/output contracts and all 3-AI, 60-market, byte, token, date, and single-session guards. Never turn unknown output into a successful or executable plan.
- Preserve all 16 protected files in `remediation/evidence/R14-preparation/protected-before.json` and commit only R15 files.

## Acceptance checklist

- [x] A failed real Web extraction with a writable diagnostic sink leaves a durable, bounded record tied to operation/request ID, source SHA-256, configured provider/model, prompt version, status, stage, safe error category, safe path, finish-reason category, and optional validated usage/attempt counts. Missing values are `unknown` or null; a write failure is reported as `WRITE_FAILED` without changing the extraction outcome.
- [x] Distinguish provider failures, non-stop/truncated finish, JSON syntax/duplicate/non-finite/budget, schema, and field-evidence/mapping failures. Do not persist model content, source, prompt, raw errors, headers, tokens/keys, or Pydantic input/context/message. Normalize all untrusted paths and values through closed categories and limits.
- [x] The public Web failure still exposes no draft or provider content. Invalid extraction cannot save or activate a plan or change holdings; existing valid plans survive. A faithful valid result still follows the ordinary review-only path.
- [x] Offline tests enter the real FastAPI lifespan and production provider adapter through controlled HTTP transport. Every synthetic response is labeled `SIMULATED`; results survive lifecycle restart and include malicious-string leak checks across stdout, Web response, and disk.
- [x] Run focused AI/Web/persistence/launcher and relevant contract tests with a unique `--basetemp`, plus applicable Ruff checks. Report exact commands and limits in paired R15 handoffs.

## Diagnostic retention and access

Store metadata only in a JSONL sidecar named from the configured SQLite path. Each record is at most 2,048 bytes; the file retains at most 512 records and 1 MiB, removing oldest records at the cap. It inherits local database-directory access controls and is not served through HTTP. There is no automatic time-based deletion: operators with local filesystem access inspect it and remove it with the isolated database after diagnostic review. The R14 historical database cannot be retroactively diagnosed. Normal Web startup and extraction continue if the sidecar is unavailable, reporting `WRITE_FAILED` on the operation; the dedicated R14 bounded launcher refuses to start its paid session if its sink is unwritable.
