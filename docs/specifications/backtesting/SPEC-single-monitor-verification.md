# Single-monitor canonical verification

Status: implementation authorized, 2026-10-21. Baseline: `ba4156e`. [Chinese review copy](SPEC-single-monitor-verification.zh-CN.md). [Analysis](PROPOSAL-single-monitor-verification.md). The existing [sharing contract](SPEC-monitor-evidence-sharing.md) remains in force.

## SMV01. Availability prerequisite

Locate the current version-2 dashboard 503 before treating any response as a performance baseline. Record bounded failure stages/categories, never credentials or evidence bodies. Unknown authority must still fail closed. A restart alone is not a root-cause fix. Reproduce the diagnosed boundary in a deterministic test; restore successful real reads using the actual owner and establish their baseline before changing canonical verification.

## SMV02. P0 representation and equivalence

After `MarketIndexSnapshot.model_validate_json`, normalize one canonical primitive tree per row. One verification core checks exact snapshot/bar/tuple boundaries, typed bar ordering, canonical request sorting, all domain-separated bar/request/root hashes, formula definition and every fact formula. Reuse that tree to produce the full canonical string. Preserve public hash helpers and the `validate_market_index_snapshot_integrity` return value `None`. Preserve Decimal limits, float rejection, enum/subclass boundaries, timezone/microsecond/Unicode spelling and literal JSON equality. Release the tree per row; do not retain normalized history.

The repository calls `verified_market_index_snapshot_json(snapshot) -> str`. Both that helper and the existing integrity-only function use `_verified_market_index_value`; the latter avoids encoding a final string that its caller does not need. There is one integrity algorithm, with no new HTTP interface.

The repository still checks every metadata column, schema version, provider revision, missing payload, head identity and verified ranking for every historical candidate, including unselected candidates. No completed-proof cache, digest-only shortcut, latest-only query, retention reduction, API/schema/timeout/worker change or unvalidated model construction is permitted.

## SMV03. Independent ownership

Every read retains its own observed time, explicit `BEGIN` transaction, authority before/after (token, generation, configuration, lifecycle, block/standby/absence, plans, dependencies, progress), activation reread and at most 2 attempts. Inventory, risk, calendar, completion proof and current eligibility checks remain independent. Socket cursors/replay/cadence stay unchanged. Keep 8 owned reads, 1 physical validator, 1 queued distinct owner, 64 MiB retained raw input, 128-row batches and the original 15-second deadline. Observer cancellation never abandons physical ownership; storage cleanup must drain physical work. Unknown ownership and expired progress remain fail closed.

## SMV04. Acceptance evidence

Compare all 2,008 frozen candidates and entire outputs with `ba4156e`; separately cover active plans, nonempty requests/facts, reordered requests, small and larger/near-limit payloads. Test damaged unselected evidence, same-size/restored-time tamper, missing/BLOB payload, changed hash/domain/formula/provider/head, canonical spellings, numeric/type boundaries and a mutation removing an integrity gate. Repeat independent authority, 90-second/target/date/clock boundaries, cancellation/drain, retention, completion races and concurrency bounds.

Use at least 10 alternating uninstrumented rounds on the same frozen 2,008-candidate sample: median wall and CPU improvement >=30%, median wall <=2.5 seconds. In 2/8 monitor-plus-result and staggered scenarios, median CPU/wall regression must be <=10%. Measure fresh-process transient allocations and process peak memory; single-read peak memory regression must be <=10%, with raw input bounds unchanged. Profile runs are excluded from latency statistics; no small-sample p95 claim. Capture successful real browser monitor/result/heartbeat journeys, failures and business writes, alongside the deterministic browser suite.

## SMV05. Conditional P1 and delivery

Profile production P0 first. Consider bounded, physical-validation-local immutable representation reuse only if measured remaining cost justifies it, with key/equality/memory and lifecycle checks. Do not add cross-request completed reuse. If P0 passes and P1 adds unjustified complexity, record deferral with measurements. Produce paired implementation tasks and final verification reports with raw observations and limitations. Preserve existing changes and real data. This request does not authorize commit/push.
