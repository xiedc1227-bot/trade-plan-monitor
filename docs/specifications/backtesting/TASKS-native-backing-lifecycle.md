# Native backing lifecycle proposed tasks

Status update — 2026-10-23: PAUSED at the user's request. Unchecked tasks remain unperformed and must not resume automatically. Existing work is retained; current production read measurements take priority.

## NBL-T00. Status and order

Planning only. Follow the paired [proposal](PROPOSAL-native-backing-lifecycle.md). The prior P0 remains `NOT_QUALIFIED`; P1 remains `NO_GO`. Each task below is a separate checkpoint; stop dependent qualification when its prerequisite fails. Keep existing plans, production checks and parallel AI extraction, daily inventory and README work intact.

- [x] Inspect reviewed source and evidence, recalculate row/domain deltas, and check version-matched primary sources.
- [ ] Complete the implementation tasks below after paired specification parity is restored.

## NBL-T01. Specify accounting boundaries

Dependency: NBL-T00. Scope: medium, paired specification and task/proposal updates.

Acceptance:

- [ ] Update both versions of `SPEC-native-owner-accounting.md` for logical views, backing identity, pending operations, epochs and conservative unresolved debt; retain previous experimental evidence.
- [ ] Specify capacities, owner/operation handoff, disjoint charging, lock order, loss behavior and exact release/transfer boundaries.
- [ ] Identify the unchanged production validation, limits and qualification gates; do not authorize a service allocator replacement.

Verification: compare bilingual stable IDs, numeric limits, code literals, links and acceptance semantics. Review the state transitions against the existing generation tests and independent authority/drain implementation.

## NBL-T02. Prove nested-domain bookkeeping

Dependency: NBL-T01. Scope: medium; `scripts/experiments/owner_observer.c`, `tests/native/test_owner_ledger.c`, and an isolated native backing-oracle fixture.

Acceptance:

- [ ] Known fallback aliases charge one backing block while distinct nested metadata and real copies retain separate charges.
- [ ] Saved owner/generation survives cross-thread release and address reuse; bounds include operation stack and all bookkeeping.
- [ ] Duplicate/missing backing charges fail an independent oracle, not merely equality of two aggregations of the same ledger.

Verification: deterministic native tests plus deduplication/generation mutation controls; record new binary/source hashes and memory overhead. Table/depth/ID exhaustion must invalidate observation without changing delegation. Passing this checkpoint permits startup and lifecycle experiments, not lower admission reservations.

## NBL-T03. Qualify early startup provenance

Dependency: NBL-T02. Scope: medium; isolated launcher, build helper and canary files.

Acceptance:

- [ ] Inert launcher preserves full outputs and configuration; after-preinitialization control and compatible before-preinitialization candidate retain verified hooks throughout startup.
- [ ] Provenance separates known earlier, known later and unresolved allocations; phase changes preserve outstanding storage and saved owners.
- [ ] Inventory bootstrap/default/direct paths; record a source-supported envelope or an explicit unresolved gate, never relabel all unknown frees as baseline.

Verification: cold/warm startup, compatible/incompatible allocator settings, overwritten-hook negative control, early block released late, late cross-thread free and realloc. Compare allocator identities at each stage; record build reproducibility and output equivalence. No runtime replacement or environment-policy substitution.

## NBL-T04. Account for shared arenas and release completion

Dependency: NBL-T03. Scope: medium; observer, native lifecycle fixtures and canary report. If a source-level runtime probe is required, specify its exact build/equivalence scope before starting that separate slice.

Acceptance:

- [ ] Arena registry and logical occupants reconcile without double charging, including metadata, slack and retained shared capacity.
- [ ] Blocked free retains the old generation's charge while new allocations may reuse addresses; unconfirmed native release remains debt.
- [ ] Native release success/failure is observed at a justified boundary or explicitly remains unqualified; pool transfer is funded.

Verification: shared owners, final logical release, warm reuse, arena/address reuse, blocked callback and release-failure barriers. Check observer/pool/process categories without subtracting one measurement from another to invent an upper bound.

## NBL-T05. Prove pending allocation and realloc bounds

Dependency: NBL-T04. Scope: medium; observer and native operation fixtures.

Acceptance:

- [ ] Pending malloc/calloc/arena/realloc records retain old backing and fund destination/scratch before delegation without duplicate nested reservations.
- [ ] Failure, in-place result, movement, zero-size and null-pointer cases preserve the underlying contract and saved ownership; materialization replaces reservation atomically.
- [ ] Hooks never wait for application admission or hold locks across allocation; exhausted metadata preserves conservative failure reporting.

Verification: barrier-controlled intermediate snapshots, nested realloc, small/large transitions, multi-thread address reuse, allocation failure, cancellation during blocked operations and final drain. Mutations that refund early or omit the pending destination must fail. Actual allocator/CRT scratch still needs source support; mock success alone cannot pass that gate.

## NBL-T06. Measure complete candidate lifetimes

Dependency: NBL-T05. Scope: medium; oracle/setup helper, `scripts/experiments/native_allocation_child.py`, `scripts/experiments/owner_probe_child.py`, paired evidence report.

Acceptance:

- [ ] Fixture creation/reference validation is outside the measured candidate; complete outputs and canonical streams are compared externally.
- [ ] Cold imports/schema creation, warm pools, actual file-backed SQL, dense errors, selected outputs and cleanup have distinct funded owners/phases.
- [ ] Report coverage/loss first, then CPU/wall, observer overhead, pending peaks, retained pool/debt and process memory; no sampled peak is presented as an all-input bound.

Verification: actual SQLite identity/late-install controls, TEXT-to-BLOB row retention, dense valid/invalid graphs, large Decimal rows, repeated failure, result retention, tampering and cleanup failure. Preserve all original evidence. At most `3` labeled diagnostic rounds when qualification fails; record the exact unresolved source or ownership edge.

## NBL-T07. Conditionally test funded legal-row admission

Dependency: NBL-T06 and all coverage/backing gates passing. Scope: medium; isolated admission/scan experiment and focused tests. Do not start this task merely because logical deduplication passed.

Acceptance:

- [ ] Source-derived simultaneous bounds cover existing input/aggregate categories without halving old reservations or moving copies into another category.
- [ ] Complete progress bundles fit before payload; legal large rows finish full validation, or availability failure is reported with P1 disabled.
- [ ] Independent authority, exact follower evidence comparison, unchanged deadlines, cancellation/drain and cleanup-debt fencing all remain intact.

Verification: memory boundaries, `1/2/8` readers, small/large fairness, deadlock, both sides of eligibility boundaries, rehashed/late tampering, leaders/followers leaving, last observer leaving and storage cleanup failure. Run the related existing integrity, representation, transport and monitor-ownership suites. Retain all proposal budget limits.

## NBL-T08. Decide P1 from qualified evidence

Dependency: NBL-T07. Scope: small, paired report and task status.

Acceptance:

- [ ] Apply the existing A/A, ABBA/BAAB, CPU, latency, availability and browser thresholds from the proposal unchanged.
- [ ] Distinguish accounting corrections from actual reduced allocations and speedups, and observer cost from the uninstrumented candidate.
- [ ] Keep P1 disabled for any unresolved native remainder, loss, early refund, integrity/authority regression or incomplete drain.

Verification: review full evidence manifests and bilingual parity; record all unperformed checks. Only a qualified service candidate proceeds to real browser acceptance. This planning change runs no native/browser acceptance and claims no new performance improvement.
