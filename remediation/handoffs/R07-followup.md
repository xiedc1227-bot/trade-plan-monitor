# R07 follow-up handoff: OpenAPI contract gate

Date: 2026-09-12 (Asia/Shanghai). Canonical English; `R07-followup.zh-CN.md` is the semantically equivalent Chinese review copy.

## Completion

This follow-up closes the two R07 residual OpenAPI contract-gate failures without changing runtime behavior. The R07-approved manual event-risk routes were already implemented, snapshotted, generated, and documented in the WEBF14 boundary; the gate's allowlist and current-contract summary were not synchronized after commit `beff041`.

## Root cause and implementation

- `tests/integration/test_openapi_snapshot.py` omitted `GET /api/v1/manual-event-risk` and `POST /api/v1/manual-event-risk-confirmations` from `APPROVED_PATHS`.
- The bilingual `SPEC-local-web` T041 snapshot digest and current-contract descriptions still stated the pre-R07 values: 42 paths, 27 live paths, and SHA-256 `a742c64992ba80183ecf68b61c0f64d0dc93a1b073b5e79952dab795b2d579a9`.
- Implementation commit `de6d62066db6e20b825816c3ca55196387290b30` adds only the two approved paths to the allowlist and updates only descriptions of the current contract to 44 paths (29 live, 15 backtest) and SHA-256 `fe3305aaf31db3eb8314675ab74790b40fc6e3ea08f44f69679127434bb001e3`. Historical WEBF statements that accurately describe the earlier 42-path boundary remain unchanged.

## Contract recheck

- GET requires one symbol and returns the three-state `ManualEventRiskView`. POST requires `symbol`, `CLEAR|RISK_PRESENT`, inclusive `expiresOn`, `expectedRevision`, and `Idempotency-Key`, then returns the same authoritative view.
- Both routes expose the standard `ErrorResponse` at 400, 401, 403, 404, 405, 409, 413, 422, 429, 500, and 503. The persistent service alone binds a write to the current active-plan hash, rejects past expiry, guards revision, writes audit evidence, and replays an identical idempotent command.
- The router, service, `openapi.json`, generated TypeScript, R07 handoff, and bilingual WEBF14 specification agree. The current generated outputs already matched the implementation, so no regeneration write was needed.

## Verification

- RED before repair: `.venv\\Scripts\\python.exe -m pytest tests\\integration\\test_openapi_snapshot.py -q -p no:cacheprovider` returned `2 failed, 12 passed`: old bilingual SHA-256 and the two missing approved paths.
- GREEN after repair: `.venv\\Scripts\\python.exe -m pytest tests\\integration\\test_openapi_snapshot.py tests\\integration\\test_manual_event_risk.py -q -p no:cacheprovider` returned `17 passed` with one existing Starlette deprecation warning.
- GREEN: `.venv\\Scripts\\python.exe scripts\\generate_frontend_types.py --check`, `.venv\\Scripts\\ruff.exe check tests\\integration\\test_openapi_snapshot.py`, and `git diff --check` passed.
- No full replay/capacity suite was rerun. The prior full-suite record remains `2390 passed, 1 skipped, 4 deselected, 2 failed`; this step repairs those two OpenAPI gate failures and does not claim an unrun full-suite result.

## Scope, provenance, and next step

- Baseline parent was `979a3ef2011d69c7c7da5adc84b52fd459f9279d`; owned implementation files are the snapshot gate test and both `SPEC-local-web` copies. This bilingual handoff pair is the sole documentation addition.
- The 12 user-owned modified files and four R00 untracked artifacts remained unstaged and were not included. Their pre-step SHA-256 manifest was captured before the repair and is rechecked after the handoff commit.
- No dependency, external call, real plan, holding, database, credential, provider, notification, or trading action was used. No remaining R07 OpenAPI-contract blocker is known.
- The coordinator should verify this pair and the commits, then start the already approved R09 task with `gpt-5.6-sol/high`.
