# Native owner accounting proposed tasks

Status: isolated logical-domain experiments executed; coverage gates failed; dependent admission work stopped. Follow the paired [proposal](PROPOSAL-native-owner-accounting.md). Restore paired specification parity before implementation; do not overwrite existing experiment plans.

- [x] NOA-T01: Inspect current ownership/admission and collect actual-runtime counter evidence.
- [ ] NOA-T02: Complete paired specifications, pinned manifests and an inert launcher; verify unchanged behavior before hooks.
- [ ] NOA-T03: Qualify native Python domain/arena observation and its bounded bookkeeping.
- [ ] NOA-T04: Qualify early configuration of the actual SQLite module and real-query coverage.
- [ ] NOA-T05: Separate oracle/setup lifetime; reconcile physical owners, backing storage and result/pool transfers.
- [ ] NOA-T06: Test cross-thread/reallocation/overflow/failure/cancellation/drain and cleanup fencing.
- [ ] NOA-T07: Only after coverage, derive and test funded legal-row admission with unchanged limits and complete validation.
- [ ] NOA-T08: Record qualified before/after measurements and decide P1 using all existing gates.

Each task is a separate review checkpoint. A failed prerequisite stops dependent work and is recorded as unqualified; artifact reproducibility is not native-memory qualification. Keep changes confined to paired docs and isolated experiments until a separately qualified service candidate exists.

Execution: paired specification added; native Python/SQLite, cross-thread, dense-error and overflow canaries executed. Qualification tasks remain unchecked because backing/ownership coverage failed. See the paired P0 report.
