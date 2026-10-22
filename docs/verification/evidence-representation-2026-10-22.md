# Evidence representation and funded sharing P0 verification

[Measurements](evidence/2026-10-22-evidence-representation/measurements.json)

## ERS-V01. Decision

P0 stages A/B/C/D are implemented as isolated experiments. P1 is NO-GO: valid large input still fails admission, final concurrent CPU/latency exceed the frozen regression gates, and native allocation bounds remain unproven. No production hook, validator change or service restart. Implementation did not commit or push; submission review is separately authorized. All 1825 pre-existing tracked/untracked file fingerprints remain unchanged, including the previous proposal and parallel work.

## ERS-V02. Stage findings

A: bounded events distinguish preflight, workspace admission, publication, exact comparison, physical validation and queue rejection. Across the 3 eight-reader rounds, each of the eager P0 and byte variants has 21 comparisons with equal=True, completed=True, joined=False. The funded and ordered variants instead have 21 equal comparisons joining before completion. This directly identifies completion-fence loss for the observed failed joins; it is not data corruption. Native SQL substage CPU and every individual allocation lifetime are not fully profiled.

B: conditional JSON byte projection preserves storage type and avoids the driver text-to-bytes round trip. Full decoded validation and conservative two-generation ownership remain. For the supported 16,472,833-byte input, the work bound falls from 296,534,034 bytes (282.80 MiB) to 197,697,036 bytes (188.54 MiB), still above 64 MiB. The unchanged validator accepts it; both new scans reject before payload query. One tracemalloc probe of the original validator peaks at 156,326,294 bytes (149.08 MiB), excluding prebuilt input and native memory. This is a Python allocation observation, not RSS or an input-budget violation measurement. Canonical/model lifetime needs separate design; merely shrinking capture cannot certify the complete memory contract.

C: the leader funds a closed set of collection-time comparators from available budget without waiting under budget/coordinator locks. Unfunded waiters do not delay physical validation. The deterministic fast-proof test recovers 1 proof and 7 joins. Late arrivals still face the completion fence; no completed-proof cache, grace period or deadline refresh was introduced.

D: one complete metadata preflight reserves maximum row workspace before the ordered payload cursor executes. Metadata/payload query counts become 1/1 rather than 2/666. Byte capture alone reduces grouped payload queries to 416. Read count, complete successful outputs, original ordering and failure behavior are checked; native driver lookahead/sort/cache bounds are not certified. No claim of a deployable memory cap follows from these experiments.

## ERS-V03. Same-run comparison

3 alternating diagnostic rounds per case: 60 batches, 195 attempts, 165 successes and 30 retained failures. Each variant attempts 39 requests. Frozen read-only full monitor/result reads use synthetic authority. Every successful monitor/result output hash matches. Every successful monitor executes independent before/after authority checks; failed monitors retain their before check. No failure is replaced. No p95 or formal performance-acceptance claim.

| Variant | Successes | 8-reader batch median (s) | 8-reader CPU median (s) | Proofs / joins across 3 rounds | Mixed batch median (s) |
|---|---:|---:|---:|---:|---:|
| Original | 39/39 | 2.540 | 3.984 | 3 / 21 | 4.074 |
| Previous P0 with tracing | 24/39 | 8.342 | 15.797 | 9 / 0 | 4.204 |
| Byte capture | 24/39 | 8.063 | 14.828 | 9 / 0 | 4.106 |
| Byte capture + funded cohort | 39/39 | 4.020 | 10.906 | 3 / 21 | 4.079 |
| Ordered cursor + funded cohort | 39/39 | 3.165 | 7.875 | 3 / 21 | 4.060 |

The final variant improves materially over the failed previous P0, but remains about 24.60% slower than original for eight-reader completion and uses about 1.98 times its CPU. Mixed batch completion is effectively unchanged. Earlier result-only completion is not a whole-workload speedup. All 30 failures occur in the eager P0/byte variants. All new-ledger samples drain to zero; its maximum is 48,621,249 bytes. Original samples do not use that ledger: zero is not zero original memory. Process execution was not reintroduced after hard-gate failure; its previous evidence is not substituted into this table.

## ERS-V04. Verification and reproduction

Related regression: 156 passed in 72.15 s, with 1 existing Starlette warning, before the final invalid UTF-8 case. Final new suite: 37 passed in 6.36 s. Injected ordered/cohort adapter: 5 authority/time/disconnect tests passed in 5.20 s, with 1 existing warning. These are separate overlapping runs, not an additive unique total. Coverage includes literal TEXT/BLOB/NUL/Unicode, invalid UTF-8 TEXT, old/head/missing/canonical tamper, real changed SQLite snapshots, valid large rejection, full fallback, funded sharing, large workspaces, cancellation, deadlines, cursor cleanup failure and child cleanup debt. Production authority/retention tests remain unchanged. Both process-local negative controls are detected: removing funding causes repeated proofs; losing TEXT provenance fails exact comparison. Ruff passes.

Run `.venv/Scripts/python.exe -m pytest tests/integration/test_evidence_representation.py -q`. Use `.venv/Scripts/python.exe -m scripts.experiments.evidence_benchmark --help` for the frozen-input diagnostics; pass `--monitor`, `--results`, `--run`, `--output`. The existing immutable-result ownership directory is required. Diagnostic memory counters remain observations, not native allocation proofs. Evidence records all batches, bounded reason timelines, memory samples, logs, source/input fingerprints and the P1 decision.

## ERS-V05. Boundaries and next step

Preserve independent authority, original full historical/canonical/domain verification, transaction boundaries, 15-second waiting, 90-second validity and cancellation/physical drain. No production module changed. Hard-gate failure stopped fixed performance acceptance, fresh process/native-memory acceptance, changed-snapshot performance and real-owner/browser validation. Correctness under changed snapshots and injected authority is covered separately.

Next investigate complete-validator/model/canonical representation lifetimes and independent preflight/comparison CPU. Do not raise the budget, weaken checks or infer production readiness from restored sharing. The current results justify retaining an experimental reference, not enabling P1.

## ERS-V06. Submission review

No blocking defect was found for retaining this isolated P0 experiment. Added 2 deterministic races after comparison prepayment: cancellation and expired deadline. Both reject the follower before payload SQL, release prepaid credit and leave the leader progressing; no experiment implementation changed. The review regression passed 159 tests in 72.88 s with 1 existing Starlette warning. Ruff passed; removing funded coordination was again detected by the mutation test.

Rechecked all 60 batches / 195 attempts, successful output hashes, independent authority counts, zero ending leases, source/input fingerprints and all 1825 pre-existing files. The 16-file submission excludes AI extraction and daily-inventory work. Measured implementation fingerprints remain unchanged; evidence updates only the expanded test fingerprint and adds review logs. The benchmark retains an idle child inherited from its harness in every variant; reported parent counters exclude that idle child. These observations are not aggregate process-memory acceptance. P1 remains NO-GO.
