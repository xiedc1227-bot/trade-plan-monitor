# Monitor change delivery: 2026-10-10

Chinese review copy: [2026-10-10-monitor-change-delivery.zh-CN.md](2026-10-10-monitor-change-delivery.zh-CN.md).

## MCD01 Authorization and boundary

On 2026-10-10 the user requested organizing the completed changes and pushing them to GitHub. This delivery covers the earlier overview retry investigation, requested page presentation changes, and the authorized index-close-display repair. The target is `origin/main` in `xiedc1227-bot/trade-plan-monitor`; the initial local and remote heads matched. The operation uses ordinary commits and a fast-forward push. It does not restart the service or add provider permissions, dependencies or acquisition frequency changes.

## MCD02 Commit groups

| ID | Content |
|---|---|
| C01 | Correct elapsed scheduler wakes, stopped-owner health timestamps and explicit quota-message classification; include regression tests and paired investigation records. |
| C02 | Remove numbered English page captions and the overview management button; move the connection banner above backtest navigation while retaining headings, descriptions and accessible focus. |
| C03 | Preserve effective index data, store latest acquisition separately, add migration `0025_index_close_display`, run idempotent startup repair and persist the bounded final-bucket recovery budget. |
| C04 | Add `GET /api/v1/market-indexes/overview`, coherent readonly session/data assembly, strict bounded DTOs, compatible history, generated contracts and API acceptance. |
| C05 | Connect the overview UI to atomic envelopes; default to SSE, separate closed-session/data/acquisition status, preserve cached data and test actual chart endpoints and accessibility. |
| C06 | Synchronize English/Chinese specifications, completed implementation tasks, rollout evidence, known regression limits and this delivery record. |

Shared files are staged by logical content without rewriting their working-tree contents. Commit messages use a Conventional Commit prefix, a Chinese subject, one blank line and Chinese change bullets.

## MCD03 Pre-push verification

- Fresh targeted backend regression: 183 passed, including scheduler, quota handling, composition, persistence, recovery, session, overview and OpenAPI checks.
- Fresh complete frontend unit suite: 942 passed in 63 files with file parallelism disabled.
- Fresh browser acceptance: 9 passed for `dashboard.spec.ts`, `index-close-display.spec.ts` and `interface-design.spec.ts`.
- Type checking, canonical v2/compatibility v1 generated-contract checks, scoped Python lint and isolated production build passed.
- Mutation review inverted the LIVE-retention condition only inside an isolated test process: both A01/A02 persistence cases rejected it. Product source files and the running service were unchanged.
- Candidate-file review checked credentials/artifacts, paired-document structure and stable IDs. Existing translated comments in otherwise unchanged code blocks were preserved. Database files, backups, credentials, staged assets and temporary review helpers are excluded from Git.

## MCD04 Existing regression limits

The earlier complete integration run and final-code rechecks are documented in [index-close-display-repair verification](2026-10-09-index-close-display-repair.md). Two existing backtest lifecycle assertions still expect eager startup although the unchanged implementation uses `LazyBacktestLifecycle`. They remain recorded failures, with no weakened assertions or unrelated lifecycle modification. This delivery does not claim that the complete backend suite is entirely green.

## MCD05 Independent work retained

The following five independent research files stay uncommitted locally:

- `docs/verification/2026-10-03-shengxin-backtest.md`
- `docs/verification/2026-10-03-shengxin-backtest.zh-CN.md`
- `scripts/replay_shengxin_research.py`
- `tasks/shengxin-backtest-plan.md`
- `tasks/shengxin-backtest-plan.zh-CN.md`

The existing source, configuration, production data and research contents are preserved during commit organization. Remote delivery is verified against the resulting local commit after the push; no force push is used.
