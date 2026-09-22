# Position-lot Evidence Decoder Verification — 2026-09-22

> English canonical; paired Chinese review copy. Continuation from `7c46a6e`. Single-record RR009 evidence decoding, not historical reconstruction or restart acceptance.

## Scope and boundaries

The pure decoder reads one audit's versioned date and complete before/after snapshots, verifies strict structure, identity bindings, existing hashes and exact mutation invariants, then returns validated evidence or typed unknown. It does not read or mutate a database, certify committed publication, establish a complete chain/inventory, authenticate the effective date or grant replay/delivery permission. No writer, migration, provider, notification, API or production default changes are included.

The bound is 16384 UTF-8 bytes, checked before parsing and after a cheap character-length guard. Malformed Unicode, duplicate keys, excessive nesting, nonstandard constants, unknown/missing fields and coerced types cannot become valid evidence. Legacy records missing the envelope remain unknown. Existing hashes retain their original representation and timezone offsets; they do not cover the newly retained effective date.

## Design and review

Implementation uses `gpt-6-astra` / `high`; independent design and final review use `gpt-6-astra` / `xhigh`. These settings do not attest the parent model/effort. Additional cross-model review remains skipped per the user's earlier choice.

Design review identified an actionable identifier-compatibility ambiguity: SQLite does not enforce the declared 36-character column length, while committed custom-factory buy events can carry up to 128 characters. The decoder accepts bounded non-padding lot/entity IDs up to 128, keeps related alert IDs at 36, and does not change current mutation lookup limits. It also preserves custom board-lot quantities and distinguishes source dates from write times. The original permissive record DTO is not itself a validation boundary.

## Executed verification

Test-first RED initially failed collection because the decoder module did not exist. After implementation, additional malformed-legacy cases exposed that missing-envelope classification preceded shared detail validation (3 failed, 99 passed). Moving the shared checks before that classification made those cases green without weakening assertions. The integration test filename is distinct from the unit filename to avoid pytest's existing flat-module import collision; no test-runner configuration changed.

| Command | Observed result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_position_lot_evidence.py tests/integration/test_position_lot_evidence_roundtrip.py -q` | 107 passed (102 unit, 5 integration); 2.57 seconds |
| `.\.venv\Scripts\python.exe -m ruff check src tests scripts` | Passed on frozen source/tests |
| `.\.venv\Scripts\python.exe scripts/generate_frontend_types.py --check` | OpenAPI snapshot and frontend types remain current |
| `.\.venv\Scripts\python.exe -m pytest -m "not live" --ignore=tests/integration/test_backtest_acceptance.py -q --tb=short` | Frozen-source functional regression: 3448 passed, 4 pre-existing failures, 1 existing skip, 4 live deselected, 1 existing warning; 450.15 seconds |

The tests independently recompute the existing hash representation and exercise delayed buys, partial/full/repeated reductions, custom board lots, a committed 64-character custom ID, strict integer/date/timestamp inputs, offset-sensitive hashes, exact object fields, duplicate keys, payload limits before parsing, malformed Unicode and excessive nesting. Results and nested snapshots are immutable. The decoder does not mutate the committed audit records.

The fresh-context final reviewer found no blocking issue after checking the paired contract, permissive DTO, real writer and existing hash algorithm. The reviewer independently reran the 107 focused cases and performed 360 malformed-field/type probes without an uncaught exception. This approval covers only the single-record decoder, not complete restart recovery. All 107 new cases are included in the completed broad functional regression; no new failure was observed. The full acceptance gate is not green.

The 4 failures match the preceding writer report: canonical index-head update time (10:36 versus expected 10:38), pending-close index-error reference health (LIVE versus expected BLOCKED), provider TIMEOUT versus TRANSIENT, and the R14 mock request rejected by the temperature guard before its fake transport. The unchanged heavy backtest file was not rerun; earlier full-run evidence remains in the runtime-recovery increments report. The existing skip is the Windows/POSIX ownership boundary, and the existing warning is the Starlette/httpx deprecation.

Bilingual heading/technical-literal parity and whitespace checks passed. A scoped high-confidence secret-pattern scan across the 9 changed files found no matches; this is not a comprehensive credential audit. Tests use isolated local state, with no real providers or notification channels. No existing assertion was weakened or new skip introduced.

## Remaining work

A durable per-lot reader must prove a unique complete hash-linked chain, committed position publications and current-row agreement within one snapshot. Its row/payload limits do not by themselves bound database scan cost: the existing audit table lacks an entity-type/entity-ID index. Complete inventory coverage, opening balances/confirmation history, risk source-effective semantics, chronological execution and process-restart acceptance remain open. RR009/C2 and the broader initiative are incomplete. No push, merge, production migration or deployment is included; the preceding 4 baseline functional failures are not waived.
