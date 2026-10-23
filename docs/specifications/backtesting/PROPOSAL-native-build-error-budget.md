# Native build evidence, dense-error lifetime and funded large-row admission

## NBB01. Decision and scope

Continue isolated P0; P1 remains NO-GO. The next work should establish the actual native build and allocation contracts, separate error construction from retained error state, and replace obsolete reservations only after ownership is proven. Further encoder tuning is not the first dependency.

This proposal follows the [submitted P0 report](../../verification/c-native-p0-2026-10-23.md) at `487f517`. The [new analysis evidence](../../verification/evidence/2026-10-23-native-build-error-budget/analysis.json) contains source/package fingerprints, read-only acquisition diagnostics, one error-lifetime probe per variant and admission arithmetic. This change adds this paired proposal and evidence only. Production code, experiment implementations, live data, services and parallel AI extraction/daily-inventory work are unchanged. No commit, push or browser-performance claim is made. Complete paired specifications/tasks before implementation.

## NBB02. Source availability is no longer the same blocker

The previous attempt at a standalone pydantic-core source tag and the installed distribution's absence of Rust sources did not establish that matching release source was unavailable. Follow the installed package's metadata: its source is now the `pydantic/pydantic` monorepo under `pydantic-core`.

| Evidence layer | Newly established | Remaining gap |
|---|---|---|
| Installed binary | The official `cp314-cp314-win_amd64` wheel's native binary exactly matches the installed SHA256 | This identifies bytes, not their allocation bound |
| Release source | Official source archive contains `124` Rust source files; both archive digests match PyPI metadata | Source archive identity alone does not bind compiler/options to the wheel |
| Repository | `Cargo.toml`, `Cargo.lock` and `src/errors/validation_exception.rs` match commit `cf67d4b3193c3fe43ede18612ed62785eee11382`, reached through `v2.13.4` | Only these files were compared; no whole-tree or reproducible-build claim |
| Dependencies | Lockfile and bundled SBOM agree on `jiter 0.14.0`, `pyo3 0.28.3`, `serde_json 1.0.149`, `smallvec 1.15.1` | Matching dependency sources, active features and allocator paths still need auditing |
| Build | Wheel declares `maturin 1.13.1`; native module reports `profile=release pgo=false` | Exact compiler, linker/CRT, flags, allocator and artifact binding are not qualified |

The [official release metadata](https://pypi.org/pypi/pydantic_core/2.46.4/json) points to the correct source. The [release workflow](https://github.com/pydantic/pydantic/blob/cf67d4b3193c3fe43ede18612ed62785eee11382/.github/workflows/ci.yml) uses a floating Rust `stable` toolchain; `rust-version = 1.88` is a minimum, not the actual compiler. Its Windows/Python job and [PGO action](https://github.com/pydantic/pydantic/blob/cf67d4b3193c3fe43ede18612ed62785eee11382/.github/actions/core-build-pgo-wheel/action.yml) declare profile generation/use. A successful job does not explain the installed binary's PGO flag or bind its bytes to that job. This is an unresolved provenance discrepancy, not evidence of tampering or proof that PGO caused the performance result.

The targeted job-log request returned `410`; the named artifact query returned no artifacts. Both source/wheel [PyPI Integrity API](https://docs.pypi.org/api/integrity/) requests returned `404`, including normalized project-name requests. These are observed retrieval limits, not a universal claim that no other provenance exists. Do not substitute a nearby version, assume a workflow ran with today's compiler, or infer an allocator contract from the wheel filename.

## NBB03. Dense errors retain much more than an outer traceback

Release-source inspection gives a concrete ownership route: tuple validation collects line errors; `ValidationError` owns a `Vec<PyLineError>`; each line error retains an input object. Conversion from internal errors can materialize Python input objects. Function-validation errors also retain the raised Python exception. Our OHLC after-validator raises after constructing a bar model, so error objects can retain input/model/frame state. Exact attribution among those owners still needs allocation instrumentation; the probe does not assign all bytes to one native vector.

`hide_input` and `errors(include_input=False)` control display/export, not construction of stored errors. Calling `str(error)`, `errors()` or `json()` can allocate additional output; shortening the eventual response cannot remove the construction peak. Fail-fast or truncating validation would change this task's required behavior and is not proposed.

The original wrapper raises `ProjectionError` after leaving its `except` block. The experiment raises it `from error` inside the handler. The new probe follows both `__cause__` and `__context__`, deduplicates identities and never formats or exports the errors. The original has neither link; the candidate retains one `ValidationError` with `40000` errors. The prior null error count was not zero errors.

| Traced memory, MiB | Original | Fused candidate |
|---|---:|---:|
| Construction/return peak | 184.2095 | 149.5323 |
| Failure held, after garbage collection | 34.7044 | 149.5291 |
| Outer cause/context tracebacks cleared, errors still held | 0.0247 | 149.5246 |
| Full outer chain released and collected | 0.0246 | 0.0252 |

This is one sequential diagnostic pass per variant on the existing synthetic dense fixture, not a throughput comparison. It excludes prebuilt raw input and untracked native allocations. Clearing outer tracebacks is a diagnostic only; it does not traverse Python exceptions hidden inside native line errors. It demonstrates that the candidate's retained error graph survives outer-frame clearing. The earlier traced peak comparison is valid as an observation of each implementation, but their post-failure ownership policies differ and cannot establish equivalent failure memory behavior.

Next experiment: measure parse/error construction, failure-boundary capture, cursor close, physical drain, observer delivery and last-observer release separately. After full validation returns, let the physical worker produce only a bounded immutable failure description and release owned graphs in a dedicated scope before publishing the outcome. Preserve failure category/meaning; inspect any cleanup failure separately. Observers receive fresh local exceptions, never one mutable shared traceback. Do not clear frames of running work or refund leases at observer cancellation. Removing retained chains may shorten high-memory duration; it does not solve the earlier construction peak.

## NBB04. The large-row rejection is still old arithmetic

For these two fixtures, `ByteScan` reserves `12 * N + 23040` bytes. Its adjustment removes only driver Unicode storage. The remaining JSON term is `2 * (N + N + 4 * N)`: driver bytes, raw capture and decoded text across two generations. Byte parsing avoids the explicit whole-input Python decode, but parser strings, native trees and error inputs are separate obligations and cannot disappear from accounting.

| Bytes | Long Decimal | Dense objects |
|---|---:|---:|
| Raw JSON | 16472833 | 12120814 |
| Current work reservation | 197697036 | 145472808 |
| Hypothetically remove only decoded-text term | 65914372 | 48506296 |
| Add metadata and current 256 KiB encoder reservation | 69195268 | 51787192 |
| Headroom against 67108864 | -2086404 | 15321672 |

The extra terms are `131072` metadata bytes and `12 * 262144 + 4096` encoder bytes. Thus removing the obsolete text term alone still leaves the long-Decimal row over budget by about `1.99 MiB`. At a `64 KiB` encoder target the hypothetical total becomes `66835972` bytes, leaving just `272892` bytes before other owners. This is not a qualified fit: the encoder multiplier is itself unproven, native ownership is incomplete, and concurrent/follower workspaces are absent from this arithmetic. A smaller target must also remeasure CPU.

Tuple slicing currently reuses immutable byte objects. This makes alias deduplication a candidate, not an automatic subtraction: prove identity and lifetime across driver values, raw rows, generators, previous/current generations, retained selected outputs and failure paths. SQLite execute/step/cast buffers are not proven aliases. Count physical allocations once while preserving their owners and transfer overlap. Do not silently move input costs to the model category, halve generation counts, raise the limit or shorten accepted data to obtain a pass.

## NBB05. Proposed experiments and stop conditions

| Stage | Concrete work | Gate |
|---|---|---|
| P0-A | Paired specifications/tasks; artifact-to-source/build manifest; dependency source checksums; compiler/CRT/allocator and schema identities | Resolve actual build evidence before certifying smaller reservations |
| P0-B | Error-lifetime phase measurements and bounded failure-outcome experiment, with unchanged full validation | Same accepted/rejected evidence and failure categories; prove actual graph release; do not label retained-memory savings as peak savings |
| P0-C | Source-derived allocation/lifetime table and native instrumentation for success, dense errors and cleanup failure | Close every temporary/reallocation/owner path and aggregate limits, or stop reduced-budget integration |
| P0-D | Phase-aware, fully funded proof/comparison bundles; legal-row SQL and concurrency experiment | Legal fixtures reach payload, full verification, ranking and physical drain under unchanged limits; no partial-lease deadlock |
| P1 | Conditional integration and mixed-load/browser measurements | All prior correctness, memory, availability and performance gates pass |

P0-A must have an explicit alternative to endless source searches. Prefer a recoverable official build manifest/artifact binding. If unavailable, evaluate an isolated reproducible build from pinned release source and dependencies, with declared compiler/options/allocator and an instrumented companion. That would be a distinct qualification target and binary hash, not certification of the installed wheel. Reconcile instrumentation overhead and behavior with the intended release binary; never replace production dependencies silently. If neither route closes the contract, report the specific unsupported allocator/build paths and retain NO-GO.

P0-C must cover SQLite/driver buffers, immutable raw ownership, parser scratch/tree/string cache, models, error vectors/input conversions/inner exception frames, dump/normalized containers, sorted vectors, C writer growth, UTF-8 copies, selected results, replacement overlap and retained failure outcomes. Include both a source-derived preallocation envelope and allocator/process observations. `tracemalloc`, working-set samples and successful stress tests can reveal violations; none alone proves a transient upper bound. Include all malformed persisted inputs within the current envelope. A structural sizing pass, if needed, requires its own bounded bootstrap budget and CPU accounting; it must not certify evidence, skip checks or introduce new acceptance limits.

P0-D reserves a complete progress bundle before payload execution. Suballocate encoder and transition work from that bundle; do not let scans hold raw leases while blocking for an unfunded encoder upgrade. Fund one proof owner first, then admit only comparison workspaces that fit. Keep eight-reader admission, with byte-weighted materialization and bounded fair waiting; do not promise eight simultaneous large buffers. A follower must independently read and compare every raw field/type/row against a still-running proof before sharing it. Keep the small-row `1` proof plus `7` joins case. No completed cache, digest-only equality or duplicated physical proof as fallback. Any nonblocking upgrade/retry retains the original clock and attempt budget. Fully validating streaming is a fallback only after its single-row progress bundle is proven to fit.

## NBB06. Invariants and targeted validation

Every request retains independent before/after authority checks, activation reread, its own transaction/observation clock and attempts. Keep every historical row, all `19` raw fields and SQL types, heads/missing dependencies, strict models, canonical UTF-8 and EOF, sorted bar/request domains, root hash, formula definition and each fact's formula hash. Do not trust stored hashes or validate only the latest row.

Test long Decimals, dense valid/invalid objects, mixed good/bad items, many field errors per item, late corruption, malformed UTF-8, deep/duplicate/extra JSON, Unicode widening and scalar/chunk boundaries. Distinguish initial error construction, error export and retained graph lifetime. Exercise unchanged full validation before/after failure sanitization; include coherent rehashed domain tampering and source-level mutations that remove domain/literal/authority checks.

Concurrency covers `1/2/8` readers, equal/changed/late cohorts, leader/follower cancellation, last-observer departure, large/small fairness and full-budget progress. Check before admission, during native parse/encode, during comparison and at both sides of eligibility/deadline boundaries. Cancellation detaches observers or prevents unstarted work; synchronous native work remains owned until it returns. Retain debt through cursor close, physical worker/bridge drain, outcome consumption and actual graph release. Storage cleanup failure keeps debt and fences subsequent generations; no early refund, partial proof or cancellation of another observer's work.

## NBB07. Unchanged quantitative gates

Retain `64 MiB` input, `768 MiB` aggregate working set, `2560 MiB` private commit, `1` physical proof, `1` queued owner, `15-second` waits, `90-second` eligibility and `2` attempts. Keep independent-scan concurrency as a separate variable. Do not hide native/input allocations in another category or omit retained results and error owners from process totals.

Failed gates allow `3` labeled diagnostic rounds only. Qualified candidates require `10` A/A pairs and `20` ABBA/BAAB blocks, at least `20%` mixed-process gain, at most `5%` result and `10%` monitor/total-CPU regression, and no worse rejection/timeout. Real-owner/browser acceptance requires `100` attempts per variant, no p95 claim below `100` successes, and the existing `20%` mixed-p95 target. Prior fused CPU improvement is retained historical evidence, not a new mixed-load pass.

## NBB08. Reproduction and limits

The evidence embeds the acquisition and error-probe sources, artifact/source fingerprints, observed retrieval failures, exact byte arithmetic and frozen fixture SHA256. Acquisition reads official archives without installing or executing their code. Run the embedded error probe from the project environment against `.pytest_cache/cna-measurements/dense.sqlite3`; it writes only scratch output and checks the input hash before/after. Its frame-clearing stage is diagnostic and is not proposed as a production callback. Repository source fingerprints identify the code inspected.

This analysis improves source provenance and explains retained dense-error memory and deterministic preflight rejection. It does not prove native allocator bounds, implement smaller SQL reservations, rerun performance acceptance or validate browser behavior. The next implementation should report each stage as passed, failed or explicitly deferred, rather than repeatedly describing source availability and actual-build qualification as the same missing evidence.
