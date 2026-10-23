# Reproducible native qualification and failure-recovery CPU

## BIR01. Decision and scope

Continue P0 with two concrete deliverables: a provisioned, reproducible Windows qualification target with allocation coverage, and an equal-lifetime failure-release experiment that avoids unnecessary full collections where proven safe. Only then change large-row admission. P1 remains NO-GO.

This analysis follows `5cb920b` and the [submitted report](../../verification/native-build-error-budget-p0-2026-10-23.md). It adds paired proposal documents and [sanitized evidence](../../verification/evidence/2026-10-23-native-build-instrumentation-next/analysis.json). Production and experimental implementations, prior evidence, README and parallel AI extraction/daily-inventory work are preserved. No toolchain installation, dependency replacement, commit or push. Complete paired specifications/tasks before implementation.

## BIR02. Correct the interpretation of the PGO flag

The matching release's [build.rs](https://github.com/pydantic/pydantic/blob/cf67d4b3193c3fe43ede18612ed62785eee11382/pydantic-core/build.rs) sets its PGO reporting flag by reading `RUSTFLAGS` and looking for `-Cprofile-use=`. However, Cargo documents that since Rust `1.55`, build scripts receive `CARGO_ENCODED_RUSTFLAGS` and `RUSTFLAGS` is removed. See [Cargo's build-script environment contract](https://doc.rust-lang.org/cargo/reference/environment-variables.html).

Therefore `profile=release pgo=false` cannot establish that the installed wheel was built without PGO. The reporting code has a concrete false-negative route under the documented Cargo environment. This is a source/documentation inference, not a rebuilt-wheel experiment; actual original flags and profiling inputs remain unknown. Stop treating the flag/workflow difference as an unexplained binary mismatch or a performance cause. Validate the reporting mechanism with a minimal build-script canary once tools exist; record effective compiler commands and encoded flags instead of trusting this string.

Binary identity and source identity remain established by the prior wheel/archive hashes. Original job-log/artifact recovery remains incomplete. Reconstructing the historical official wheel bit for bit is a separate objective from producing a new, reproducible, auditable qualification binary. Do not block every experiment on unavailable historical logs, and do not certify the old wheel from a new build.

## BIR03. Concrete build route

Prefer a dedicated Windows x64 build environment. Python is currently `3.14.7`, release with the GIL, built with `MSC v.1944`; the installed core is `2.46.4`. The current Docker context is `desktop-linux`: it can support exploratory Linux experiments, but does not qualify Windows allocator/CRT behavior. No Docker daemon or container was started in this analysis.

| Route | Use | Decision |
|---|---|---|
| Local Windows Build Tools, Rust and isolated Python environment | Repeatable native build and instrumented tests on the target ABI | Preferred when provisioning is available |
| Dedicated Windows VM/runner with pinned image and tools | Same target when local installation is unsuitable | Valid alternative; capture actual image/tool versions, not just a moving runner label |
| Existing Linux container | Parser-source exploration and early hook tests | Supplemental only; cannot close Windows gates |

Use Microsoft's standalone C++ Build Tools and Windows SDK, not a required full IDE. Discover the installed toolset with supported developer-environment scripts and record exact versions. A `14.44` toolset family aligns with the observed interpreter compiler but does not identify the original core compiler. Pin its actual patch and SDK before building; do not use a floating default. See [Microsoft's build-environment instructions](https://learn.microsoft.com/en-us/cpp/build/building-on-the-command-line?view=msvc-170).

Proposed isolated layout: `tools/native-qualification/` for build/probe recipes and manifests, with downloaded archives, vendor cache, wheels and temporary environments under `.pytest_cache/native-qualification/`. No imports from these wheels in the service environment. Preflight reports installer locations, disk needs, target ABI, actual tool versions and missing prerequisites. A missing compiler must lead to a concrete provisioning result or an explicit unperformed build, not a fabricated pass.

Build sequence:

1. Freeze the verified release archive, `Cargo.lock`, dependency checksums/features and `maturin 1.13.1`; obtain locked dependencies into a dedicated cache. Pick and pin an explicit Rust release meeting the source minimum; record `rustc -Vv`, Cargo, MSVC, linker, SDK, CRT, Python DLL/import-library identities, environment and source patch hashes. A newly selected compiler is not claimed to be the historical compiler.
2. Build an unmodified release target R in a separate Python environment using `maturin build --release --locked --offline --target x86_64-pc-windows-msvc --interpreter PATH`. Explicitly declare PGO policy. Start with a non-PGO qualification target; if PGO is later introduced, freeze the training corpus and profile digest and requalify. Record complete effective compiler/linker invocations. [Maturin documents the locked/offline build options](https://www.maturin.rs/distribution.html).
3. Repeat R in a second clean build directory. Compare wheel members and native binary hashes; investigate paths, timestamps, signing and compiler nondeterminism separately. A functional match is not byte reproducibility, and unexplained differences fail that claim. Keep the original official wheel as the behavioral reference, not as an expected identical hash.
4. Build I with a small reviewed allocation-observer patch from the same toolchain/configuration. Record the exact R/I patch. Prove complete valid output, canonical bytes and failure-category equivalence before interpreting allocations. Instrumentation changes allocation/performance behavior; qualify that difference, never benchmark I as if it were the production candidate.

Bind any reduced admission budget to an exact qualified runtime manifest, including the uninstrumented binary and dependency identities. If R becomes a deployment candidate, separately validate its real service behavior and CPU against the currently installed wheel; this proposal does not authorize replacing that wheel. A different or unverified runtime keeps conservative admission. I measurements alone cannot justify lower reservations for either R or the installed wheel without accounting for the observer patch's effect on allocation behavior.

## BIR04. Allocation instrumentation needs three domains

| Domain | Entry points and initialization | Coverage limit |
|---|---|---|
| Rust core/parser dependencies | A build-time `GlobalAlloc` wrapper around the selected backing allocator; cover allocation, zeroed allocation, reallocation and free | Does not automatically capture Python, SQLite, direct `System` calls or all CRT allocations |
| Python objects/writers/driver objects | Native wrappers for RAW/MEM/OBJ domains, plus arena observation, installed in an isolated launcher | Nested domain forwarding must not be summed as separate physical memory; arena retention differs from live objects |
| SQLite query/cast/cache buffers | Wrap the actual loaded library through `SQLITE_CONFIG_GETMALLOC` / `SQLITE_CONFIG_MALLOC` before initialization | A hook on a different SQLite DLL proves nothing; do not reconfigure a running service |

Use a fixed-capacity native event buffer and preallocated pointer/owner table; charge their memory separately. Record requested/usable bytes where available, live/high-water bytes, allocation counts, phase, physical owner and outstanding allocations at drain. Keep owner identity across thread handoff and phase changes; a thread-local phase alone cannot identify later frees. Prevent overflow, recursive allocation and dropped events: any accounting loss invalidates the run. Avoid Python callbacks, formatting, logging and allocating locks inside allocation hooks. [Rust's allocator contract](https://doc.rust-lang.org/std/alloc/trait.GlobalAlloc.html) explicitly constrains unwinding and reentrancy.

For reallocation, reserve the possible old/new overlap before calling the backing allocator, retain old ownership on failure, and transfer only on success. A net-size delta does not bound the backing allocator's transient copy. Track logical domain totals and deduplicated backing allocations separately; do not add Python arena capacity, object requests and OS heap bytes as though they were independent copies. Include metadata rounding, retained arenas, fragmentation and observer overhead in the process envelope.

The version-matched [CPython memory API](https://github.com/python/cpython/blob/v3.14.7/Doc/c-api/memory.rst) requires thread-safe wrappers and wrapping existing allocators after initialization. `PyTraceMalloc_Track` is an optional diagnostic export, not a budget gate; do not call allocation-producing tracing APIs recursively from the hooks. SQLite's [configuration](https://www.sqlite.org/c3ref/config.html) and [memory-method interface](https://www.sqlite.org/c3ref/mem_methods.html) require initialization-aware setup. Current SQLite is `3.50.4` with `SYSTEM_MALLOC`; record the actual DLL hash, source ID and options, then test coverage with a known query allocation before any proof benchmark.

Begin with allocation-count/byte canaries for every domain, reallocation growth/failure, cross-thread free and event overflow. Then exercise long Decimals, dense models, dense errors and malformed JSON. Native failure injection belongs in disposable supervised children: Rust allocation failure can terminate the process rather than become Python `MemoryError`. Never inject it into the service, rely on a Python catch to contain it, or unwind through an allocator callback. An aborted child yields no proof; retain parent ownership until exit, transport closure and actual drain, with cleanup failure debt fencing. Normal observer cancellation still does not kill synchronous physical work.

Observed high-water bytes alone are not an all-input upper bound. Combine source-derived shape bounds, maximum concurrent owners, allocator growth contracts, instrumentation coverage and process totals. Missing CRT/arena/driver coverage keeps reservations conservative. A runtime allocator failure fence is not a replacement for preallocation admission or a guarantee that legal inputs succeed.

## BIR05. New failure CPU and retention evidence

The previous traced benchmark timed the candidate's full collection inside the call but retained the baseline error until afterwards. That did not compare equal release endpoints. The new probe runs a fresh process per case, disables automatic GC only in that process, excludes tracing from CPU runs and times validation, reference drop and full collection for both variants. There are `3` alternating rounds per group, `18` calls total. All reported full collections return `0` collected objects.

| Invalid fixture | Fused total CPU seconds | Boundary total CPU seconds | Boundary full-collection CPU seconds |
|---|---:|---:|---:|
| Long Decimal | 0.250000 | 0.250000 | 0.078125 |
| Dense | 0.578125 | 0.562500 | 0.093750 |
| Dense with 100000 retained dictionaries/list pairs | 0.562500 | 0.562500 | 0.109375 |

These are diagnostic medians with coarse CPU resolution, not acceptance or evidence of a precise speedup. Ballast is allocated/promoted before timing; the small difference is not a proven scaling curve. Unlike the earlier numbers, totals include physical release on both sides. Do not compare their absolute times with traced runs.

A separate traced check calls the existing failure capture without the wrapper's full collection:

| Invalid fixture | Live before full GC, bytes | Live after full GC, bytes | Construction peak, bytes |
|---|---:|---:|---:|
| Long Decimal | 54680 | 18104 | 25113000 |
| Dense | 147072 | 25488 | 156796064 |

Both collections again report `0`. Most failure graph storage is already released by scope exit/reference counting in these fixtures; remaining traced-byte changes can include free-list cleanup and bookkeeping, not collected cycles. The [exact Python GC documentation](https://github.com/python/cpython/blob/v3.14.7/Doc/library/gc.rst) distinguishes cycle collection from free-list clearing. Prebuilt input is excluded; no native-memory ceiling is established.

The synthetic test deliberately creates `payload.cycle = payload`. It proves the existing generic cycle-cleanup behavior, not that every persisted JSON error creates cycles or requires a process-wide collection. Preserve that adversarial case as a drain/ownership requirement; do not delete it just to make an optimized branch pass.

## BIR06. Proposed failure-release optimization

First experiment with the existing bounded failure scope and no unconditional full GC on schema-qualified ordinary failure paths. Prove release using exact-model/source ownership analysis, weak references where possible, phase counters and allocation-ledger drain. Cover field/model errors, domain/literal failures after model construction, mixed valid/invalid items, late errors, nested exceptions and repeated calls with automatic GC enabled. The current two fixtures are evidence for the hypothesis, not sufficient qualification.

Keep exceptions local and descriptions immutable; each observer gets a fresh local exception. If a failure path can retain cycles or its ownership is unproven, retain its debt and use an explicit physical cleanup path. Compare at most one serialized collection per physical failed proof against a fully drained isolated worker where that worker architecture is already qualified. Neither option permits early refund or hiding pending cleanup behind observer completion. Account for unrelated heap pause and the collection coordinator's own memory. Do not hold a scan permit while waiting for another cleanup owner.

Do not globally disable/freeze GC, tune thresholds, replace every full collection with generation `0/1`, or infer acyclicity from `gc.is_tracked`. Production objects can have survived earlier collections. If the known failure categories cannot be separated safely, retain the current experiment's conservative behavior and leave production disabled. No parser fail-fast, truncated error traversal, relaxed model checks or omitted hashes are permitted.

## BIR07. Large-row admission after qualification

Current failures still occur before payload: reservations are `197697036 B` and `145472808 B` against `67108864 B`. These are not measured OOMs. Removing explicit whole-input decoded text hypothetically leaves a long-Decimal progress bundle of `69195268 B` at the current encoder target, still over budget. The next change must prove eliminated allocations and owner overlap, not merely subtract a coefficient.

Create a phase/owner budget from the qualified R/I evidence: metadata, SQL step/cast/driver, immutable raw aliases, previous/current generation, parser/model/error peak, normalized/encoder scratch, selected results, follower comparisons and physical cleanup. Keep the original input category and aggregate process limits; no reclassification to manufacture fit. Count immutable aliases once only with demonstrated identity and lifetime. Models/errors remain in the aggregate envelope even when they are not input copies.

Reserve a complete progress bundle atomically before payload. Use funded subleases through parsing/encoding/cleanup; no partial raw lease followed by a blocking encoder upgrade. Fund the single physical proof owner first, then only follower comparison workspaces that fit. Each follower independently reads and exactly compares all raw evidence to a still-running proof. Weighted scheduling may reduce simultaneous materialization, not authority checks or the eight-reader contract. Preserve small-row `1` proof plus `7` joins, fairness, original deadlines/attempts and query counts. A fully validating streaming fallback must first prove single-row fit. If it cannot, legal-large-row availability remains failed.

## BIR08. Stages and unchanged gates

| Stage | Required deliverable | Stop condition |
|---|---|---|
| P0-A | Paired specs/tasks; actual provisioned Windows toolchain; compiler-command canary; two clean R builds and I manifest | Missing tools, unexplained reproducibility differences or unclear target identity |
| P0-B | Three-domain coverage canaries, source ownership envelope and supervised allocation-failure tests | Lost events, unknown allocator overlap, early refund or unbounded telemetry |
| P0-C | Equal-lifetime CPU/retention comparison; qualified failure branch without unnecessary full GC | Cycles or caller-owned graphs released outside debt accounting, changed failure semantics |
| P0-D | Fully funded legal-row SQL path and concurrency experiment | Oversize row, deadlock, worse refusal/timeout or any integrity/authority omission |
| P1 | Conditional integration and real-owner/browser acceptance | Any preceding gate unresolved |

Maintain independent authority before/after and activation reread for every request; all history, `19` raw fields/types, missing dependencies, strict models, canonical UTF-8/EOF, bar/request/root/formula and per-fact validation. No completed-proof cache or trust in stored hashes. Cancellation only detaches observers or prevents unstarted work; physical work, retained outputs and transport remain owned through actual release. Cleanup failure retains debt and fences subsequent generations.

Keep `64 MiB` input, `768 MiB` aggregate working set, `2560 MiB` private commit, `1` physical proof, `1` queued owner, `15-second` waits, `90-second` eligibility and `2` attempts. Test `1/2/8` readers, both sides of time boundaries, late/rehashed tampering, cancelled leaders/followers, final-observer departure, storage failure and large/small progress. Failed gates allow `3` labeled diagnostic rounds; qualified candidates require `10` A/A pairs, `20` ABBA/BAAB blocks, `20%` mixed-process gain, at most `5%` result and `10%` monitor/total-CPU regression, and no worse rejection/timeout. Browser acceptance requires `100` attempts per variant, `100` successes before p95 claims and the existing `20%` mixed-p95 target.

Evidence embeds both scratch probes and every result. CPU/retention input fingerprints and inspected source fingerprints identify this analysis. No application code or test policy changed, and no new native build, allocator interception, lower-budget admission or browser pass is claimed.
