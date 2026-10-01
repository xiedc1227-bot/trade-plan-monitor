# File naming

## Scope

Use names that describe the file's responsibility. Apply this policy to maintained source, tests, scripts, configuration and new documentation in `trade-plan-monitor`. Do not use temporary task identifiers such as `r13` as the primary name of an executable file. Keep requirement IDs in comments and acceptance reports.

## Conventions

| File type | Convention | Example |
|---|---|---|
| Python module or script | `snake_case.py` | `bounded_live_acceptance.py` |
| Python test | `test_<behavior>.py` | `test_ai_timeout_budget.py` |
| Vue component or view | `PascalCase.vue` | `SourceTextEditor.vue` |
| TypeScript utility or composable | Existing `camelCase.ts`; composables start with `use` | `marketIndexChartOptions.ts`, `usePlans.ts` |
| Component unit test | Match the component, then `.spec.ts` | `PlanWorkbench.spec.ts` |
| Utility unit test | Match the utility, then `.spec.ts` | `transport.spec.ts` |
| Browser test | Behavior in `kebab-case.spec.ts` | `active-plan-process-restart.spec.ts` |
| Guide or task document | Topic in `kebab-case.md` | `file-naming.md` |
| Chinese document copy | Same stem plus `.zh-CN.md` | `file-naming.zh-CN.md` |

## Stable conventions and historical records

Preserve tool-owned names such as `README.md`, `pyproject.toml`, `package.json`, `__init__.py`, `__main__.py`, `conftest.py` and dotted Vite configuration filenames. Preserve established `SPEC-`, `CAPABILITY-MAP-` and `PROPOSAL-` document roles, numbered ADRs and migration revisions, date-based verification records, ticker identifiers and semantic fixture versions.

Historical task plans, acceptance reports, recorded commands and frozen evidence may retain `R13` and similar IDs. These are record identities, not templates for new executable names. Preserve `remediation/evidence/`, existing `docs/verification/assets/` and recorded runtime data byte-for-byte during naming migrations; do not rewrite historical executions as though they used a new command.

## Rename procedure

1. Check tracked and non-ignored project files; exclude dependencies, generated bundles, caches, secrets and local runtime data.
2. Use a descriptive name that is unique even on case-insensitive filesystems.
3. Move the existing file and update imports, subprocess module arguments, current operational commands and documentation in both languages. Preserve pending edits.
4. Record old-to-new paths in a migration map, including the new command for historical executable paths. Do not add duplicate compatibility test files that would run twice.
5. Compare test discovery, check imports and run affected offline tests. Preserve authorization IDs, budgets, schema versions and live-provider opt-in boundaries.

## Current migration

The 2026-10-01 audit checked all 1,448 tracked filenames and renamed 38 maintained executable files. See the complete [path map](../verification/assets/file-naming/renames.json) and [verification report](../verification/2026-10-01-file-naming.md). For example, run `python -m scripts.bounded_live_acceptance` instead of the former `scripts.r14_bounded_acceptance` entry. Default offline behavior and existing execution authorization requirements are unchanged.
