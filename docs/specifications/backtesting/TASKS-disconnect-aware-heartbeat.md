# Disconnect-aware heartbeat implementation tasks

[Chinese review copy](TASKS-disconnect-aware-heartbeat.zh-CN.md). [Specification](SPEC-disconnect-aware-heartbeat.md). User authorized P0 execution, 2026-10-22; exclude parallel AI extraction work.

- [x] DHA-T01: Restore paired specification/task parity. Acceptance: equivalent IDs, numbers, tokens, commands and boundaries before implementation. Verify local links and counterpart checks.
- [x] DHA-T02: Capture successful real-owner baseline before source changes. Acceptance: read-only history, actual protocol/cadence, closure and connected controls; retain failures and diagnostic limitations. Verify sanitized browser/server correlations.
- [x] DHA-T03: Add current-source failing disconnect/admission tests. Acceptance: demonstrate unnecessary health read and missing cancellation; cover terminal/deadline/publication races. Verify meaningful red assertions.
- [x] DHA-T04: Implement supervised receive/send and guarded admission. Acceptance: connection-local terminal state, bounded children, no post-terminal health admission, joined cleanup and unchanged protocol. Verify focused green tests and default-disabled traces.
- [x] DHA-T05: Verify ownership, proof and storage races. Acceptance: surviving followers remain verified, abandoned work drains physically, cleanup failure retains its pause, stopped-health temporary cleanup remains awaited. Verify regression and mutation probes.
- [x] DHA-T06: Capture actual-owner browser/after and controlled overhead. Acceptance: DHA-S05 sample counts or explicit missing scope; same data/cadence, all failures retained, no synthetic delay reported as real speedup. Verify request/trace linkage and read-only interaction.
- [x] DHA-T07: Publish paired report and final review. Acceptance: comparisons and limitations, tests, preserved authority/integrity bodies and excluded changes. Verify lint/type/browser/document checks. The original implementation phase excluded commit/push; the subsequent user instruction authorizes review and scoped commit/push, excluding parallel AI extraction and daily-inventory work.
