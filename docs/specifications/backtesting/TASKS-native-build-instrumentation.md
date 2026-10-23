# Native qualification implementation tasks

- [x] BIR-T01: Restore paired proposal/specification/task parity before implementation.
- [ ] BIR-T02: Provision fixed Windows tools, capture actual identity, build twice and compare.
- [ ] BIR-T03: Implement and qualify three-domain native hooks; reject lost events and unaccounted overlap.
- [x] BIR-T04: Run automatic-GC failure lifecycle comparison and cycle counterexample; preserve debt.
- [x] BIR-T05: Re-run legal large-row SQL and all safety regressions; lower budgets only after qualification.
- [x] BIR-T06: Publish paired report/evidence and decide P1 from measurements.

Dependencies: BIR-T03 requires BIR-T02; reduced admission in BIR-T05 requires BIR-T03. Diagnostic BIR-T04 and conservative regressions can run independently. Unmet prerequisites remain unchecked with the exact reason recorded. No automatic P1 rollout.

Execution: BIR-T02 produced two release builds but byte reproducibility failed (PE/debug metadata and SBOM differences). BIR-T03 is blocked and not implemented. BIR-T04 is diagnostic only; generic cycle drain remains unqualified. BIR-T05 completed conservative regression/admission measurements, not reduced-budget availability. P1 remains NO-GO. See [report](../../verification/native-build-instrumentation-p0-2026-10-23.md).
