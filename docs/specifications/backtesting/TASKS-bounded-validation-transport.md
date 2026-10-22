# Bounded validation transport tasks

[Chinese review copy](TASKS-bounded-validation-transport.zh-CN.md). [Specification](SPEC-bounded-validation-transport.md).

- [x] BVT-T01: Freeze bilingual protocol, budget, ownership and fixed measurement schedule; preserve existing work.
- [x] BVT-T02: Prove lossless codec, framing and complete-stream verification against unchanged pure validation.
- [x] BVT-T03: Exercise aggregate admission, overlap, oversized fallback and synchronized memory observations.
- [x] BVT-T04: Verify observer cancellation, physical drain, child faults and cleanup fences.
- [x] BVT-T05: Run fixed comparisons and related regression/mutations; record all failures and decide P1.
- [x] BVT-T06: Publish bilingual evidence and decision; advance production integration only if every prerequisite passes.

P0 is complete. P1 is deferred: the concurrent SQL-batch envelope exceeds the unchanged budget. See the [verification report](../../verification/bounded-validation-transport-2026-10-22.md).
