# Single-monitor verification optimization proposal

Status: analysis only, 2026-10-21. Baseline: `ba4156e`. [Chinese review copy](PROPOSAL-single-monitor-verification.zh-CN.md). [Raw observations](../../verification/evidence/2026-10-21-single-monitor-analysis/measurements.json). The existing [sharing contract](SPEC-monitor-evidence-sharing.md) remains authoritative; this proposal does not authorize production implementation, completed-proof caching or a service restart.

## SMR01. Finding and measurement scope

Non-overlapping reads correctly miss in-flight sharing and verify all historical candidates again. The dominant cost is repeated model export/canonical normalization/encoding inside each individual verification, rather than SQL query count. Reduce repeated representations of the same fully checked snapshot first; retain the complete history traversal.

Windows / Python 3.14, the same frozen read-only monitor copy used previously: 2,008 candidates, 72,280 embedded bars, 27,588,993 raw JSON UTF-8 bytes. This sample has no active plans, fact requests or indicator facts. SQLite connections use explicit transactions, `mode=ro`, `query_only=ON` and the bounded pool. Fixed clock and synthetic absent-owner authority isolate the historical index cost; they do not certify actual runtime authority. Every sequential call uses a fresh owned read and completes before the next. There are no joins or completed cache hits.

Ten alternating uninstrumented rounds, with complete dashboard equality and two owner-loop authority calls per request:

| Whole single read | Current implementation | Process-local single canonical tree experiment |
|---|---:|---:|
| Median wall seconds | 3.4802 | 1.9768 |
| Median process CPU seconds | 3.4219 | 1.9688 |
| Wall range, seconds | 3.4237–3.5353 | 1.9559–2.0391 |
| Physical candidate validations per call | 2,008 | 2,008 |
| Authority calls per call | 2 | 2 |

Exploratory wall improvement is 43.2%, CPU improvement 42.5%. These are feasibility results, not deployed latency or production acceptance. Complete row results also match for all 2,008 stored candidates. Peak retained raw input stays 30,826,621 bytes, and retained bytes return to zero after drain. This is the existing sharing-input accounting, not a measurement of the additional transient normalized tree or total process memory.

Supplementary pure-row fixtures include 8 bars, 4 requests and 4 indicator facts covering SMA, SMA_LOOKBACK and RETURN. Five alternating rounds of 500 full validations have median wall 0.2769 → 0.1667 seconds. Both implementations accept the correctly rehashed snapshot with requests/facts reordered together, and reject malformed fact formula, request hash, Decimal spelling, JSON number and timestamp spelling. The main frozen sample must not be represented as coverage of fact-heavy or active-plan workload.

## SMR02. Where one read spends time

Separate one-run stage instrumentation from the uninstrumented benchmark above. The index path takes 3.5329 wall seconds; row verification takes 3.3770 seconds, approximately 95.6%. The following nested-independent stages are not added to their inclusive parents:

| Verification stage | Wall seconds |
|---|---:|
| Typed JSON parsing and model validators | 0.6346 |
| Bar-set canonicalization/encoding/hash | 0.9344 |
| Snapshot canonicalization/encoding/hash | 0.8213 |
| Final literal canonical JSON equality | 0.8573 |

The three canonical/hash stages above account for about 74.0% of the complete index path. Their times include model export, normalization and encoding, not just SHA-256. Ranking, metadata, input capture and SQL account for the remainder; changing the winning-snapshot query cannot remove the verification requirement.

Direct raw SQL scan/capture/accounting of all 2,008 candidates takes 0.2112 / 0.0682 / 0.0640 wall seconds in three supplementary observations. No cold-cache claim is made. The query plan already searches the head primary-key index for mapping/index and the payload primary-key index for snapshot hash, using one left join. There is no measured N+1 query or missing-index justification in this path.

A separate worker-thread cProfile run locates 8,032 `canonical_json` calls, 3,701,644 recursive `canonical_value` calls and 1,328,368 `canonical_decimal` calls. Its profiled assembly time is 10.4385 seconds because profiling changes costs; never substitute that value for ordinary latency or sum nested cumulative times. See [Python profiling documentation](https://docs.python.org/3.14/library/profile.html). Windows per-call thread CPU accounting is coarse; tiny stage totals can quantize to zero, so wall stages and uninstrumented process CPU are reported separately.

The pure-validator prefix experiment gives current/prototype wall seconds of 0.1325 / 0.0729 at 128 candidates, 1.0773 / 0.5913 at 512, and 3.3768 / 1.8681 at 2,008. Prefix payload mixes differ; these are component observations, not valid shortened monitor reads or a forecast based only on candidate count. Work remains dependent on total evidence bytes and embedded bars.

## SMR03. P0: one canonical representation per fully verified snapshot

Keep typed JSON parsing and every model validator. Build one canonical primitive tree with the existing Python-mode export and canonical rules. Reuse that representation only within the current row verification to derive the ordered bar-set hash, sorted request-set hash, root snapshot hash excluding only the root snapshot hash field, and full canonical text for literal storage comparison.

Preserve exact tuple/type boundaries, typed ordering, domain prefixes, formula definition and fact-formula checks, row metadata/provider binding, missing-payload rejection, head identity and verified ranking. Typed bar timestamps/intervals determine the existing ordering; request sorting must produce exactly the current canonical sort keys. Never use hash equality as a substitute for canonical-byte equality. Release the tree after the row is processed; do not retain a second normalized representation of all 2,008 candidates.

Use one internal verification implementation that can return the verified canonical text to the repository reader. Retain existing public hash helpers and the `validate_market_index_snapshot_integrity` interface, including its existing return behavior; avoid maintaining a second independent integrity algorithm. The prototype duplicates logic only inside an ignored feasibility script and must not be copied into production as a parallel validator.

Do not replace the project codec with `model_dump_json()` or generic JSON mode without proving exact bytes. Decimal normalization, microsecond timestamp spelling, Unicode, enum/subclass behavior and float rejection are part of the evidence format. Pydantic documents recursive Python-mode export and different serialization modes; that supports reusing a representation, not changing this project's canonical policy. See [Pydantic serialization](https://docs.pydantic.dev/latest/concepts/serialization/). The previously reverted primitive-type fast-path experiment is not being proposed again.

Independent reads remain unchanged: own observed time and BEGIN snapshot, plan/inventory/risk/calendar/completion-proof checks, authority-before/after including progress state, activation-identity reread and at most two attempts. Preserve each socket's cursor, replay and cadence; cancellation ownership, original wait deadlines, shutdown/storage drain and current admission/byte limits remain intact. Retain full validation of unselected history. No financial, API, schema, retention, timeout or worker-pool change is needed.

## SMR04. Conditional P1 and alternatives

Re-profile the production P0 implementation before choosing P1. If repeated normalization still dominates, experiment with a small, explicitly bounded memo of common immutable bar/Decimal representations inside one physical validation only. Every snapshot must still pass typed parsing, all domain hashes, metadata binding and literal canonical-byte comparison. Measure the key-building cost, equality behavior and peak memory; discard the memo at physical completion. No gain is claimed yet.

If typed validation becomes dominant, preserve `model_validate_json()` and the complete validator chain while looking for measured duplication. Do not replace models with unvalidated dictionaries or `model_construct()`. Another serialization library, compiled validator or process split requires a separate equivalence and lifecycle assessment; more workers alone do not reduce single-read CPU.

Do not introduce completed-proof caching in this slice. An exact fresh-byte comparison against a bounded completed pure proof is theoretically a different design from caching authority, but it changes the accepted no-completed-reuse contract and adds memory, semantic-version and lifetime fences. A digest-only, event-sequence, mtime or SQLite data-version cache is insufficient. A materialized latest row, LIMIT or verify-on-write policy would omit corrupt unselected history under the current contract. Reducing retention to improve timing is also excluded. SQLite WAL snapshots are per read transaction and do not prove a later transaction unchanged; see [SQLite isolation](https://sqlite.org/isolation.html).

P0 reduces the constant cost of full verification, not its order of growth. If full-history work later outgrows the budget, bring a separately specified evidence-storage/trusted-proof design for review rather than quietly skipping old artifacts.

## SMR05. Real-service observation and prerequisite

Three sequential version-2 live dashboard requests return HTTPError rapidly; a follow-up confirms 503 `SERVICE_UNAVAILABLE`. A separate diagnostic without the required monitor version returns the expected 409 contract mismatch. Exclude these failures from successful-read performance measurements. The current production evidence also passes an independent read-only full assembly with zero active symbols under the synthetic absent-owner authority and fixed analysis clock. This does not establish actual live authority or explain the 503.

Before implementation acceptance, locate whether the real service rejects at admission, storage pause, authority capture/progress coverage or another fail-closed boundary, using bounded stage/error-category observations without credentials/evidence bodies. Preserve unknown-authority rejection. Do not switch the live service to synthetic owner absence, suppress authority errors or restart it merely to obtain a faster number. Establish a successful real baseline after the state is understood, then repeat the same journey after deployment. No service restart or production source change was performed during this analysis.

## SMR06. Implementation sequence and proposed gates

1. Record paired implementation specifications/tasks and a check-by-check equivalence map; resolve the live measurement prerequisite in SMR05.
2. Add deterministic canonical byte/hash/error goldens and differential cases, then implement the single-representation verifier through one canonical core.
3. Test every original candidate and output, damaged unselected history, same-size/same-time tamper, missing payload, changed domain/hash/formula/provider/head, fact-heavy/reordered requests, Decimal extremes, float/bool/enum/subclass boundaries and timezone/microsecond/Unicode spelling. Existing error shapes and ranking must match. A process-local mutation dropping an integrity gate must be rejected by tests.
4. Repeat independent authority/configuration/generation/activation, inventory/risk/calendar/proof, 90-second/target/date/clock, STOPPING/STALLED/unreadable owner and all-observer cancellation tests. Retain 8-read/1-validator/1-queued/64-MiB bounds, completion-race and budget fallbacks; verify actual storage cleanup drains physical reads.
5. At least 10 alternating uninstrumented rounds on the same 2,008-candidate sample: proposed single-read median CPU and wall improvement at least 30%, with median wall at most 2.5 seconds. The experiment meets these proposed targets, but production implementation must repeat them. Also cover an active current plan, nonempty requests/facts, small histories, larger/near-limit payloads and matching payload distributions for growth measurements. Profile overhead is excluded.
6. Re-run 2/8 monitor-plus-result scenarios and staggered arrivals; shorter validation can narrow sharing windows, so do not assume old join rates. Require no worse than 10% median CPU/wall regression against the current implementation and retain correctness when completion forces fresh validation. Measure peak transient allocations and process memory in fresh processes; propose at most 10% single-read peak memory regression, with the existing raw-input budget unchanged. Missed gates require reassessment, not weaker checks.
7. Complete relevant integrity/retention/runtime tests and real browser result/monitor/heartbeat journeys with no business writes or page errors. Record paired before/after verification. Consider P1 only if a remaining measured bottleneck justifies it. Commit/push only after a subsequent request.

## SMR07. Analysis delivery

Only this proposal pair and portable observations are added. Ignored scripts remain under `.pytest_cache/single-monitor-analysis-20261021/`; the frozen copy remains in the earlier ignored analysis directory. All prototype changes occur only in an independent measurement process. Production source, runtime configuration, real evidence, retention, service state and Git history are unchanged by this analysis. No implementation approval, deployed speedup or full production safety acceptance is claimed.
