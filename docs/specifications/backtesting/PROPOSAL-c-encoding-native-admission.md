# C encoding cost, native ownership and large-row admission

## CNA01. Decision and scope

Continue isolated P0 work; P1 remains NO-GO. Prioritize normalization/planning cost, a version-qualified native ownership envelope, then end-to-end large-row admission. Increasing chunk size or lowering a coefficient without proof is not the next step. Preserve independent authority, complete integrity and physical drain.

This proposal follows the [P0 report](../../verification/bounded-c-p0-2026-10-23.md) at `d0ba977`. This change adds paired analysis/proposal documents and [sanitized diagnostic evidence](../../verification/evidence/2026-10-23-c-encoding-next/analysis.json) only. No production/experimental implementation change, live-data write, service restart, commit or push. Parallel AI extraction and daily-inventory work remain outside scope. Restore paired specification/task parity before the next implementation.

## CNA02. What failed and what the new evidence establishes

| Gate | Recorded P0 result | Interpretation |
|---|---|---|
| CPU | Original `2.406250 s`; C256 `2.953125 s`; `+22.73%` | Exceeds `10%`; beating the Python token variant is insufficient |
| Native memory | Encoder reservation `12 * target + 4096`; traced long-Decimal full proof `23.88 MiB`, dense full proof `137.50 MiB` | Diagnostic reservation and traced peaks are not a native upper bound |
| Availability | Long-Decimal work `197697036 B`; dense work `145472808 B`; limit `67108864 B` | Both rejected before payload; pure-validator success is insufficient |

Fresh read-only attribution uses the unchanged frozen database: `2008` historical rows, `5` indexes, maximum raw JSON `35587 B`. Three current-C256 phase runs, two separate profiled reference/candidate runs and one producer-counter run all match complete reference outputs. The database fingerprint is unchanged. These are attribution runs, not a new before/after acceptance benchmark; do not compare their absolute timings against earlier sessions.

The counter run records `8032` traversals, `8032` C calls, `8032` chunks, maximum emitted chunk `35587 B`, and `0` roots exceeding the target. Each of the four domain/literal traversals fits one C call in this sample. Large-array fragmentation therefore does not explain this sample's regression. Batch fusion remains a separate large-input experiment.

Normalization occupies approximately `47%` of candidate elapsed time in the three phase runs. In the instrumented profiles, original normalization has cumulative `2.7181 s`, candidate normalization `4.9037 s`; candidate `bound()` executes `2177305` times, cumulative `1.6728 s`. C encoder cumulative time is `0.3758 s` versus `0.4047 s`. These nested/profiled values are not additive and cannot quantify an uninstrumented causal percentage. Per-row thread-CPU counters are too coarse for precise phase attribution; use elapsed phase sums and whole-pass CPU separately.

## CNA03. CPU and representation diagnosis

`normalize()` first constructs a `SizedDict`/`SizedList`, then creates `dict(result)`/`tuple(result)` and traverses children for sizing. Cached container totals eliminate repeated whole-tree maps, but not this extra per-container pass, shallow copies, generator overhead or repeated scalar sizing. `DecimalText` also adds a string-subclass allocation after canonical Decimal expansion. Model dump and normalized containers still coexist during construction.

The sorted bar vector, sorted requests and snapshot-without-hash mapping are ordinary containers. Their bounds are recalculated at encoder entry. The counter evidence says the common rows receive planning work even though every encode fits the target. Four separately acquired traversal leases also remain; measure their contribution rather than assume it dominates.

Version-matched CPython source identifies another temporary: the C list encoder calls `PySequence_Fast`; its implementation copies non-exact lists such as `SizedList`. This is a reference-vector copy, not a deep copy of every item. Sorted dictionaries also allocate item lists; `sort_keys=True` requires that work for ordinary dictionaries too, so do not attribute it solely to subclassing. See the [C encoder](https://raw.githubusercontent.com/python/cpython/v3.14.7/Modules/_json.c) and [sequence conversion](https://raw.githubusercontent.com/python/cpython/v3.14.7/Objects/abstract.c).

Recommended independent experiments:

1. Fuse normalization and conservative size accumulation in one pass. Avoid `dict(result)`/`tuple(result)` solely for sizing, and reuse validated scalar bounds without relaxing canonical Decimal/datetime rules. Compare container subclass overhead against exact containers with a bounded, row-local plan; do not replace it with an unbounded global size map.
2. Trial an ordinary-container small-row path only when a schema-derived preallocation envelope proves every call fits. Raw JSON length alone is not an encoded-size certificate; exponent expansion, defaults, escaping and invalid input must remain covered. Unknown schema/builds cannot use the fast path until requalified.
3. Evaluate size-bounded exact-list batches on large arrays separately. Precharge reference vectors, writer/UTF-8 overlap and preceding chunks. Avoid uncharged slicing/concatenation. Keep `64 KiB` and `256 KiB` diagnostic targets until measurements justify a change.
4. Consider snapshot-hash/literal dual consumption only after those measurements. The hash omits `snapshot_hash`; literal comparison includes it and EOF. Explicitly test member/comma routing and keep bar/request/formula checks independent. Do not assume one traversal will be faster for small rows.

## CNA04. Close native bounds before reducing admission

Distinguish three obligations: a logical output bound, allocation/ownership bounds for input workspaces, and aggregate process working-set/private-commit bounds. One does not establish the others. Python's [tracemalloc documentation](https://docs.python.org/3.14/library/tracemalloc.html) covers traced Python allocations; the [Pydantic JSON API](https://pydantic.dev/docs/validation/latest/concepts/json/) does not provide a bounded-workspace contract for complete byte parsing.

Freeze Python, parser, SQLite, driver, schema and build fingerprints. Obtain matching native source/build provenance; the attempted public `pydantic-core v2.46.4` source tag remains unavailable in this analysis. Do not substitute a nearby version and claim qualification. First close this provenance gate; if it cannot be closed, retain NO-GO instead of repeatedly tuning coefficients.

Produce an allocation table covering: SQL execute/step/cast and driver buffers; immutable bytes; previous/current row overlap; parser scratch and string caches; successful and failed models; model dump; normalized plan; sorted reference vectors; Unicode writer growth/reallocation and width changes; UTF-8 conversion; comparison views/copies; all selected outputs and replacements; exception chains and cleanup. Record allocator, maximum simultaneous count, preallocation owner, transfer and physical release for each entry. Count a reference alias once only after proving it shares the same immutable owner.

Use source-derived bounds plus isolated instrumentation of the actual native allocators, process working set and private commit. SQLite counters are supplemental and version-dependent, not a complete process cap. Repeated sampling can falsify a bound; it cannot prove no transient peak exists. No synthetic multiplier becomes certified because samples fall below it. Native failure injection must cover allocation failure, writer growth, invalid UTF-8, deep/duplicate/extra JSON, and error-heavy model validation before eventual error sanitization.

The dense invalid-OHLC probe retained approximately `149.53 MiB` of traced allocations with `40000` errors. Shortening the final error message cannot remove that earlier peak. Include arbitrary malformed persisted input within the current read envelope, not just valid schema shapes. Do not change accepted inputs or failure semantics through partial parsing, `model_construct()`, truncated validation or new cardinality limits. A structural prepass, if required, needs a separately bounded bootstrap allocation, full cost accounting and strict separation from evidence certification.

## CNA05. Why valid large rows are still refused

The old shape formula reserves two overlapping generations of source, raw capture and decoded text. `ByteScan` subtracts only the driver's Unicode-to-bytes saving. The remaining JSON term is approximately `12 * N`, including an obsolete decoded-text allowance for the new parser. The actual experiment still calls `scan.acquire(work)` before invoking the new validator. Thus the rejection is deterministic admission arithmetic, not measured parser OOM or a new hash failure.

Do not immediately replace that term with `2 * N`, move charged input copies into the model category, or raise the `64 MiB` limit. First prove which buffers disappeared and which generations cannot coexist. With a near-`16 MiB` row, four full-size copies already consume almost the entire input budget before metadata and encoding. Reduced representation overlap and weighted scheduling are both needed; fewer readers alone cannot make an oversized single workspace fit.

After CNA04, define separate **proof** and **comparison** progress envelopes. Each request still performs its own SQL metadata/raw comparison and authority checks. A follower may omit model parsing only after exact equality of every field/type/row with a still-running physical proof; a digest match alone is insufficient. Lease plan must include all currently pinned leader/follower rows, transfer overlap, output consumption and draining generations.

Reserve a complete progress bundle atomically before payload execution. Do not hold a partial scan/raw lease while blocking for an encoder upgrade; nested acquisition can starve progress when several scans consume the remaining capacity. Prefer subleases within a funded bundle. If a shape-dependent upgrade is unavoidable, it must be nonblocking with an explicit release/retry protocol preserving the original clock and attempts; a structural prepass cannot justify circular funding.

Fund the leader first, then only followers whose full comparison workspace fits. Keep admission for `8` readers, but limit concurrently materialized large workspaces by bytes. Preserve fairness and deadlines, release scan permits before proof/cohort waits, and keep the small-input `1` proof plus `7` joins acceptance. Do not promise that many simultaneous large-row joins. When a complete collection cannot fit, choose fully validating streaming before worker submission, releasing incompatible retained prefixes; do not duplicate an in-flight proof. Prove single-row fit before calling this an available fallback.

## CNA06. Ordered implementation and stop conditions

| Stage | Deliverable | Exit/stop condition |
|---|---|---|
| P0-A | Paired specifications/tasks; source/build provenance; phase ownership table; frozen attribution baseline | Unresolved parser/native provenance blocks reservation changes |
| P0-B | One-pass normalization/planning; separate small-path and large-batch ablations | Complete byte/output/error equivalence; no weaker bounds; measure CPU against original |
| P0-C | Encoder/parser/driver success and failure native envelopes; repeated full-process memory measurement | Unproved native overlap or ceiling violation keeps P1 blocked |
| P0-D | Funded proof/comparison bundles and weighted large-row SQL path | Legal large rows pass metadata, payload, full validation, ranking and drain; no deadlock/early refund |
| P1 | Conditional integration and real-owner/browser comparison | All correctness, availability, memory and performance gates pass first |

Keep `64 MiB` input, `768 MiB` aggregate working set, `2560 MiB` private commit, `1` physical proof, `1` queued owner, `15-second` waits, `90-second` eligibility and `2` attempts. Retain the earlier `2-slot` independent-scan candidate as a separate variable. Failed gates permit only `3` labeled diagnostic rounds. Qualified candidates require `10` A/A pairs and `20` ABBA/BAAB blocks, at least `20%` mixed-process gain, at most `5%` result and `10%` monitor/total-CPU regression, and no worse rejection/timeout. Real-owner/browser acceptance requires `100` attempts per variant and no p95 claim below `100` successes, with the existing `20%` mixed-p95 target. This proposal claims no browser or tail-latency improvement.

## CNA07. Non-negotiable semantics and validation matrix

Every request retains independent before/after authority checks, activation reread, its original transaction/observation clock and attempt budget. No shared authority certificate, completed-proof cache, latest-only validation or trust in stored hashes. Validate all historical rows, all `19` raw fields and SQL types, head/missing dependencies, strict models, canonical UTF-8 and EOF, sorted bar/request domains, root hash, formula definition and every fact's formula hash.

Test valid long Decimals, dense arrays and all selected indexes; exact chunk/scalar boundaries; control/supplementary Unicode; sorting; late corrupted rows; fully rehashed domain tampering; malformed/error-heavy inputs; model replacement; old/new row overlap. Test `1/2/8` readers, equal/changed/late cohorts, large/small fairness, metadata/query count and full-budget progress. Allocation mutations must detect unleased buffers and early refund. Integrity mutations must detect omitted domain/literal/authority checks.

Cancellation only detaches an observer or prevents unstarted work. It does not interrupt a synchronous native call or release its memory. Keep ownership through actual return, chunk consumption, cursor close and physical worker/bridge drain. A follower cannot cancel another observer's proof. Verify cancellation before admission, during parse/encoding/comparison, last-observer departure, both sides of time boundaries and stop. Cleanup failure retains debt and fences future generations even when a CPU permit is free. Never return a partial proof.

## CNA08. Reproduction and limits

Evidence embeds the successful diagnostic source, source/input fingerprints, phase results, profile call counts and full-output equality assertions. Save its source as `.pytest_cache/bep-next-analysis-probe.py` and run `.venv/Scripts/python.exe .pytest_cache/bep-next-analysis-probe.py` from the repository with the existing frozen database. The script only reads that database and writes its scratch analysis. Two earlier report-writing attempts failed on an encoding-name typo after measurement; they produced no saved performance evidence. The corrected completed run is the only new reported dataset.

No new admission implementation or native-memory proof was produced in this analysis. The proposed optimization order follows measured common-row planning cost and the unresolved allocation contracts. It must not be presented as a guaranteed performance improvement or as a relaxation of the current gates.
