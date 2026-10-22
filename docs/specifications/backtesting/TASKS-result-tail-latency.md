# Result tail latency implementation tasks

[Chinese review copy](TASKS-result-tail-latency.zh-CN.md). [Contract](SPEC-result-tail-latency.md). User authorized execution, 2026-10-22; preserve existing changes. Dependency order: RLT-T01 → RLT-T02 → RLT-T03 → RLT-T04 → RLT-T05.

- [x] RLT-T01: Restore paired specification/task parity. Acceptance: equivalent IDs, numbers, boundaries and commands. Verify counterpart/link/token checks before source edits.
- [x] RLT-T02: Add bounded opt-in tracing and HTTP correlation. Acceptance: no business effect on disabled/overflow/failure paths; fixed fields, bounded storage, explicit response residual. Verify failing tests followed by focused success.
- [x] RLT-T03: Propagate physical ownership across threads and shared observers; annotate existing verification boundaries. Acceptance: same-key callers reference one physical trace, cancellation cannot erase or release ongoing work, every authority/evidence gate remains called. Verify cross-thread, failure, cancellation and drain tests plus existing regressions.
- [x] RLT-T04: Capture real-owner successful baseline/after scenarios and browser timelines; measure instrumentation overhead separately. Acceptance: RLT-S04 counts/bounds or explicit failed/not-reproduced scope; no synthetic delay counted as real latency. Verify raw samples, trace reconciliation, clean console and read-only browser interactions.
- [x] RLT-T05: Decide P1 from measured attribution and unchanged gate. Acceptance: keep only fully verified gains; otherwise record deferral. Publish bilingual comparison/test report with limitations and inspect final diff. Verify integrity/retention/mutation/ownership suites and documentation parity.
