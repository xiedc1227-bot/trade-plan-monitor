# Backtest workspace implementation tasks

Contract: [SPEC-backtest-workspace-ux](../docs/specifications/backtesting/SPEC-backtest-workspace-ux.md). User approved P0 and existing-interface P1 on 2026-10-21. Preserve the existing proposal pair and business records.

- [x] BW-T01 Record paired scope, component boundaries, commands, acceptance criteria and this ordered implementation plan.
- [x] BW-T02 Measure result API/store costs, add a regression test for repeated work, optimize the verified read path and verify integrity/retention behavior. Files: result store/publication reader and focused backend tests. Verify: targeted pytest and identical before/after measurements. Depends on BW-T01.
- [x] BW-T03 Implement read-only slow/timeout feedback and previous-data refresh with race protection. Files: shared read feedback and relevant read composables/tests. Verify: fake-time and stale-request tests. Depends on BW-T01.
- [x] BW-T04 Compact run history, meaningful metrics, collapsed filters, clear conditions and visited pagination/return focus. Files: run filters/table/view/composable and focused tests. Verify: run discovery unit tests. Depends on BW-T03.
- [x] BW-T05 Clarify dataset scope, native dates, compact expandable catalog and visited pagination. Files: data form/panel/view/composable and tests. Verify: dataset read/no-match/pagination tests. Depends on BW-T03.
- [x] BW-T06 Add accepted-task discovery and task selection using existing APIs. Files: task composable/workspace, job presentation, run view and tests. Verify: identity, filter, pagination and read-only navigation tests. Depends on BW-T03.
- [x] BW-T07 Put stop in advanced management with confirmation and clarify service/task actions. Files: service component and tests. Verify: cancel confirmation causes zero stop calls; confirmed stop uses existing command. Depends on BW-T01.
- [x] BW-T08 Compact audit/provenance and add existing-data equity controls/exact table disclosure; clarify supported retention/export actions and index navigation. Files: result components/view and related tests, split by surface. Verify: exact cause links, version selection, chart controls and result-action tests. Depends on BW-T03.
- [x] BW-T09 Run focused and full frontend checks, relevant backend integrity checks and browser interaction/accessibility/responsive checks; record paired verification and measured limitations. Depends on BW-T02–BW-T08.

Checkpoints: verify BW-T02 before accepting any performance claim; verify BW-T03–BW-T05 before adding task discovery; verify all criteria in BW-T09 before completion. No unrelated incomplete task file is replaced. New bounded inventory/filter APIs and P2 remain deferred.
