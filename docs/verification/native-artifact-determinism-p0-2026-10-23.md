# Native artifact determinism P0 results

## NAD-V01. Decision

Native, SBOM and whole-wheel reproducibility pass for the measured R configuration. The instrumented I configuration also reproduces, separately. Rust-domain observation and conservative legal-row diagnostics ran, but native memory upper bounds and legal-large-row availability remain unqualified. P1 is NO-GO. Production dependencies, independent authority checks, complete evidence validation and cancellation/drain paths are unchanged.

See the paired [specification](../specifications/backtesting/SPEC-native-artifact-determinism.md), [tasks](../specifications/backtesting/TASKS-native-artifact-determinism.md) and [summary evidence](evidence/2026-10-23-native-artifact-determinism-p0/summary.json). This work excludes AI extraction, daily inventory and README. Implementation measurements and submission review did not restart services or install production wheels.

## NAD-V02. Before/after artifacts

| Gate | Previous result | Current measured result |
|---|---|---|
| Complete native binary | 19 differing bytes | 3 clean R builds identical |
| SBOM | Time, serial and source-path differences | 3 generated SBOMs identical after explicit identity mapping |
| Whole wheel | Different; old checker only compared members | 3 complete R wheels identical; members/RECORD independently audited |
| Instrumented target | Not built | 3 clean I wheels identical within I; distinct from R |
| Native allocation ceiling | Unproven | Still unproven; actual Rust observations now available |
| Legal-row admission | Safe refusal | Same safe refusal |

R native SHA-256: `9dd446e5a9bb8dfde009c4c156df02f523146fb4560ef0aa4ff59875b03c629a`. R complete wheel SHA-256: `ccc1c0cc22ef3552a08b2dcad34a595c2d5a04110ad3e3f202b16a74b22c9e98`. I native SHA-256: `26fefa0aef62c79f92ff46945caf472eeda698cce6532d2cd5e067e606cff24a`.

There were 9 full-core builds: 3 native-phase builds with the original backend, 3 final R builds and 3 I builds. Each phase used independent fresh targets; the third root included spaces/non-ASCII characters and altered source file mtimes. No existing wheel was copied to manufacture a rebuild. Dependencies came from the locked offline cache. No cross-machine or changed-time-zone reproducibility is claimed.

The fixed epoch `1153704088` is the maximum member timestamp of the verified source archive; this is an archive-derived packaging clock, not a claim about the actual release/build date. `/Brepro` stabilizes native metadata. The fixed backend patch calls the pinned Python mapper before wheel serialization. Inverse mapping must restore the entire original SBOM; raw and normalized JSON are retained in the evidence. Native source is unchanged in R. I additionally binds the observer content and module-inclusion recipe into its SBOM source identity.

Full build logs, backend build recipe/log, executable hashes and raw SBOMs are retained. The runner evolved between phases to add packaging status and instrumentation support; each measurement retains its start-time runner hash, and final source hashes are recorded separately. The final CLI requires wheel equality when the SBOM transform is enabled. The earlier final-R log labels its native success separately and records `wheelEqual=true`; the artifact hashes independently establish the wheel result.

## NAD-V03. Actual allocation and admission experiment

Six isolated children ran 3 alternating rounds per R/I configuration. Every child loaded the exact expected native binary from an unpacked experimental wheel, with no service installation. Both large valid rows passed full validation and equaled the independent reference result; output fingerprints matched across R/I. Every tampered row was rejected. Collection and retained-state observations ran after physical validation returned.

| Fixture | R validation CPU median, seconds | I validation CPU median, seconds | Observer overhead | Rust requested lifetime peak, bytes |
|---|---:|---:|---:|---:|
| Long Decimal | 0.359375 | 0.359375 | 0.00% | 62108326 |
| Dense | 1.593750 | 1.703125 | 6.86% | 139943398 |

These are diagnostic validation CPU measurements, not mixed-load acceptance or production speedups. The peaks include the process's Rust lifetime history, not a reset per request, and do not include all native memory. The observer tracks allocation/zeroed allocation/reallocation/free with possible old/new overlap, fixed atomic counters and no callbacks or event allocation. Its accounting-loss flag remained zero. Aggregate live bytes after release include retained runtime/schema state; they are not a zero-debt proof for individual physical owners.

A Python-only `8388608 B` allocation left Rust counters unchanged: before/during were both `[44357288, 44357288, 351167, 0]`. This directly demonstrates missing Python coverage. Actual SQLite allocator interception, backing-heap overhead/fragmentation, per-owner attribution, complete failure injection and cross-domain deduplication are also unqualified. Rust peaks cannot reduce the existing progress bundle.

SQL still reserves `197697036 B` / `145472808 B` against `67108864 B`. Both fixtures make 1 metadata query, 0 payload queries, finish with 0 charged bytes and report `availability_failed`. This is unchanged conservative admission, not an OOM result or successful large-row availability. No memory category or coefficient was reduced.

## NAD-V04. Verification and limits

The focused suite passes 19 tests; related authority/evidence/scan/disconnect/drain/recovery regression suites pass 166 tests, disjoint from the focused selection. Negative controls cover changed bytes, duplicate/unsafe members, RECORD hash/size/coverage, bad source identity, dangling/duplicate/local SBOM references, path relocation, dependency-version changes and failed prerequisite reporting. The I source mutation changes its native bytes. The earlier factorial canary retains controls for missing epoch and reproducible-linker settings. One intentional duplicate-ZIP warning and one existing FastAPI dependency warning were observed in their respective selections.

Ruff, bilingual stable IDs/literals and evidence consistency checks pass. Installed runtime SHA-256 remains `5ba0685a9153952ce1b5e1e8e5939685a675c0ca5786e720cfef255cb1b62a3e`. No browser/performance acceptance is claimed because no service candidate is integrated. Existing BIR08 requirements for independent pre/post authority and activation reread, full historical evidence, observer cancellation, physical drain, cleanup debt, time boundaries and concurrency remain binding.

Next prerequisite: add qualified Python and actual SQLite coverage plus per-owner/backing-allocation reconciliation, then repeat valid/dense-error/failure-injection and cleanup experiments before revising admission. The preliminary Rust observer must not be deployed as a budget allocator.

## NAD-V05. Submission review

Review fixed unsafe extraction aliases/nonregular members, inconsistent reproducibility manifests and missing timeout-attempt diagnostics. Experiment checkpoints now use atomic replacement. The initial negative run reproduced 12 failures; after fixes, 34 focused tests and 166 disjoint regressions pass, totaling 200. Disabling the reserved-name condition in an isolated in-memory mutation caused 4 expected failures; repository source was not mutated. Source-epoch boundary controls also pass.

The first restricted regression attempt stalled during asynchronous drain and was interrupted. The same selection passed with normal local process permissions in 32.84 seconds; no test was skipped or relaxed. Ruff and bilingual parity checks pass. All 9 existing wheel files were independently re-audited with the hardened checker; their complete hashes, members and RECORDs match the original evidence. All 6 retained SBOM mappings and allocation-output fingerprints/medians remain consistent. The installed native hash is unchanged.

Original measurements and their source hashes remain historical evidence. [Submission review evidence](evidence/2026-10-23-native-artifact-determinism-p0/submission-review.json) records the reviewed source hashes separately. This review did not rebuild native artifacts or repeat performance measurements; the changes affect experiment validation/reporting only. P1 remains NO-GO, native upper bounds and successful legal-large-row admission remain unqualified, and no service/browser acceptance is claimed.
