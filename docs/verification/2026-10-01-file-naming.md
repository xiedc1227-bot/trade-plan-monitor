# File naming verification — 2026-10-01

## Scope and result

Checked all 1,448 tracked filenames in `trade-plan-monitor`. Renamed 38 maintained Python scripts, test modules and browser tests from historical task identifiers to responsibility-based names. Updated references in 27 maintained files, including imports, child-process module arguments and paired operational documents. The complete [rename map](assets/file-naming/renames.json) records every old and new path.

| Former name | Current name |
|---|---|
| `r13-active-process-restart.spec.ts` | `active-plan-process-restart.spec.ts` |
| `r13-ai-faults.spec.ts` | `ai-faults.spec.ts` |
| `r14_bounded_acceptance.py` | `bounded_live_acceptance.py` |
| `test_r19_output_truncation.py` | `test_ai_output_truncation.py` |

The [naming guide](../guides/file-naming.md) defines language-specific conventions. Tool-owned filenames, migration revisions, document role prefixes, dated reports, ticker identifiers and semantic fixture versions remain valid. Historical task records and frozen evidence retain their original identities and recorded commands; the rename map supplies the current executable paths. No case-insensitive collisions or missing rename destinations were found. No former executable path remains in maintained source, scripts or tests.

## Verification

| Check | Result |
|---|---|
| Affected Python tests, offline | 224 passed in 141.69s; one existing Starlette deprecation warning |
| Browser test discovery | Unchanged: 47 tests in 19 files |
| Affected browser tests | 7 passed in 3.8m across the four renamed suites |
| Python test discovery | Unchanged: 224 selected tests |
| Python syntax tree comparison | 34 renamed files retain executable behavior; only module paths and import order differ |
| Ruff on renamed Python files | Passed |
| Frontend type check | Passed |
| Isolated browser fixture build | Passed |
| Whitespace check | Passed |

The browser suites cover active, replaced, disabled and expired plan process restarts, AI failure boundaries, review corrections and alert stream recovery. An initial run used an outdated isolated browser bundle containing the former button label. Rebuilding that bundle resolved the fixture mismatch; the final seven tests passed without weakening assertions. External paid providers and live trading were not exercised.

Discovery outputs, the migration audit and the Python test log are stored in [file-naming evidence](assets/file-naming/). Existing button-copy edits were preserved. This change does not alter business logic, requirement IDs, schema versions, execution budgets or live-provider authorization boundaries.
