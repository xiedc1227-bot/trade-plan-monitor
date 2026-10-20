# Reviewed plan library identity, 2026-10-19

## PLV01. Scope

The user authorized read-only investigation of eight visible library entries and clearer chain/predecessor/version presentation. Add only an optional `identity` projection to the existing library item, a pure display model and the existing library UI. No schema migration, data deletion/deduplication, selection substitution, new execution path or historical-result changes. Keep exact preparation IDs and manifest hashes in all existing commands.

## PLV02. Verified local evidence

The preparation database was opened using SQLite `mode=ro` and `query_only=ON`. Eight reviewed `SINGLE` records form two separate four-source chains, not duplicate rendering of the same preparation ID. Both chains use identical original text for dates 2026-09-24, 2026-09-28, 2026-09-30 and 2026-10-09; all four corresponding frozen plan hashes differ.

| Chain | Exact predecessor sequence | Root review |
|---|---|---|
| Earlier review | `full-chain-20261017-1` → `full-chain-20261017-2-v2` → `full-chain-20261017-3-v2` → `full-chain-20261017-4-v2` | 2026-10-17 02:48:03 +08:00 |
| Later review | `generic-live-final-20261017-1` → `generic-chain-20261017-2` → `generic-reviewed-chain-20261017-3` → `cohort-plan-20261018-4-v6` | 2026-10-17 11:44:19 +08:00 |

Differences include alert/ordinary conditions, position-allocation evidence and risk branches. The earlier 2026-10-09 snapshot has no risk line/comparison or risk branch; the later snapshot has `risk_line_fen=2599`, `risk_comparison=LT` and one risk branch. These are materially different approved snapshots. This inspection does not re-approve either version or select a preferred chain. Initial-account canonical values are identical across these eight entries. Retain every original record and historical reference.

## PLV03. Read-only display contract

`ReviewedPlanLibraryItem.identity` is optional/nullable for compatibility. When supplied, its four required fields are `sourceHash` (exact UTF-8 original-text hash), `planHash` (existing frozen plan hash), `planVersionId` (existing approved frozen version ID) and `reviewedVersionHash` (SHA-256 of `plan-library-reviewed-version-v1` + NUL + the canonical complete frozen version, including review time/evidence). The server computes the projection only from the already loaded/frozen record; no additional database reads or stored fields. Existing item fields, page order, pagination and mutation routes are unchanged.

The dropdown and checkbox library resolve each exact preparation-ID/manifest-hash predecessor to its root; unresolved roots remain separate. Content-based plan version IDs alone cannot identify an approval or a chain. Each entry shows review time, a distinguishable version label and the exact predecessor version. Same-source alternatives are labelled as identical complete reviewed snapshot/repeated preparation, same plan content/different approval, or different plan content, using complete hashes/IDs rather than names or dates. Older payloads without identity remain usable and explicitly lack comparable version metadata. Missing/stale predecessors remain visible as unresolved, never silently rebound. Full IDs/hashes and a link to the existing reviewed preparation appear in expandable details. Checkboxes and dropdown retain original preparation-ID values, selected state and existing emits; branches and records remain selectable under the unchanged server composition checks.

## PLV04. Verification

The following checks passed without relaxing any test gate:

- Frontend unit suite: `npm --prefix web test -- --run --maxWorkers=2` — 75 files, 1126 tests. The focused library suite includes five added cases covering two chains/eight entries, exact original selection events, missing/stale predecessors, independent approvals sharing a content version ID, repeated complete reviewed snapshots, legacy payloads and invalid metadata.
- Final affected backend/contract suite: `.venv/Scripts/python.exe -m pytest tests/integration/test_single_plan_library.py tests/integration/test_backtest_service_contract.py tests/integration/test_openapi_snapshot.py -q --tb=short` — 30 passed. Earlier compatibility/preservation checks passed 223 tests across preparation, stored loop inputs, results/export, plan switching, workbench reuse and contracts; after the final read-only identity refinement, the 30 affected checks were rerun. One existing Starlette/httpx deprecation warning remains.
- Ruff on both changed backend modules and both changed Python tests; `scripts/generate_frontend_types.py --check`; `npm --prefix web run type-check`; `npm --prefix web run build` — passed. Both generated API profiles match U28 snapshot hashes.
- The actual eight read-only metadata projections rendered as two chains/eight selectable entries, all labelled different plan content. Real Chrome checks passed at 1440px and 320px with 200% root text and expanded identity details: no horizontal overflow, failed requests, console/page errors or business write requests. The synthetic browser regression additionally covers 320/768/1024/1440px, keyboard selection and exact dropdown values.
- Independent read-only code review closed the content-version-ID collision issue: use a complete reviewed-version fingerprint for approval comparison, and exact preparation-ID/manifest-hash links for chain grouping. No remaining blocking findings.

Browser preservation suite: `npm --prefix web run test:e2e -- tests/e2e/backtests.spec.ts tests/e2e/monitor-loop-backtest.spec.ts tests/e2e/streamCompletion.spec.ts tests/e2e/plan-library-versions.spec.ts` — 20 passed in 6.0 minutes. Original request/DOM/polling bounds, cancellation audits, history/result behavior and narrow-layout gates remain intact. The real four-plan regression still submits one run with four frozen versions and one continuous account: two fills, final cash `1019000` fen, zero remaining quantity, fees `1000` fen, realized P&L `19000` fen and the exact seven-point equity sequence. No original browser test or test threshold was changed.

SHA-256 checks confirm the preparation database (`e710de8d995e88832ee9591b36ff07268c4266219261516ba651ff5a47d62f59`) and historical result database (`ffab0b51ff6c61342a56bebd6a14afd61a5f27e4d849a195ffe07afca8fcf012`) are byte-for-byte unchanged. All eight reviewed document hashes also match their pre-change values. Comparing all tracked files with the task-start snapshot limits this task to 13 existing files plus four new presentation/test/verification files. Existing unrelated edits remain unchanged; U28 alone is appended to the previously edited specification pair. No changes to execution, composition checks, stored hashes/codecs or historical-result handling.
