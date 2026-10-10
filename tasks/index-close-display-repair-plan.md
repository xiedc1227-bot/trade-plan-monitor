# Implementation plan: index-close-display-repair

Chinese review copy: [index-close-display-repair-plan.zh-CN.md](index-close-display-repair-plan.zh-CN.md).
Authorized on 2026-10-09 against [the design](../docs/specifications/monitoring/SPEC-index-close-display-repair.md). This focused task record does not replace the active backtest plan or its task list.

## ICP01 Scope

Only effective index heads, acquisition diagnostics, the bounded overview read, final-session recovery, existing index components, their tests, generated contracts and paired documentation are in scope. Preserve all pre-existing changes. No new permissions, dependency, plan-evaluation authority or normal acquisition frequency.

## ICP02 Ordered tasks and acceptance

- [x] IC-T01: Reproduce durable head loss; share selection by capture order; persist latest attempt separately. Verify A01–A04 and A09 with real SQLite transactions and reopen.
- [x] IC-T02: Add an idempotent validated repair and additive migration. Verify A11; preserve immutable snapshots and decision evidence.
- [x] IC-T03: Add one coherent overview read with trusted session/calendar, four bounded cards and aligned turnover. Verify A07–A09, A12–A13, strict contracts and no read-side writes.
- [x] IC-T04: Persist final-bucket recovery at +72/+132/+252 seconds, at most 3 starts within 5 minutes. Verify A05–A06 using fake clocks, deferral, restart and reason changes.
- [x] IC-T05: Switch only the overview index strip to atomic reads; render session and data status separately; preserve selection, caching and missing-bar gaps. Verify A10/A12 plus responsive browser checks.
- [x] IC-T06: Run focused and full offline regression, build, type generation and browser acceptance; drain owner, backup SQLite, migrate/repair, restart and verify actual closed-session data. Record evidence and limitations in paired verification reports.

## ICP03 Checkpoints and boundaries

Check persistence before adding the read path; check the read contract before connecting Vue; complete offline regression before local rollout. Use the design's commands plus focused acceptance tests. Do not repair unrelated failures or commit concurrent work. Runtime rollout must use normal owner drain and a consistent backup. If a design gap affects contract or authority, consult the user before dependent changes.
