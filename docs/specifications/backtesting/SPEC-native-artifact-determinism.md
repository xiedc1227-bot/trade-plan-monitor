# Native artifact determinism P0

## NAD-S01. Contract

Implement NAD01–NAD09 in the paired proposal. Preserve all existing authority, evidence, cancellation/drain and budget gates. Production integration stays disabled. Exclude AI extraction, daily inventory and README changes.

## NAD-S02. Native gate

Pin source and tool identities, non-PGO flags, source-derived `SOURCE_DATE_EPOCH`, `/Brepro` and path mappings. Build R in 3 clean roots including spaces/non-ASCII paths and altered mtimes. Compare complete native bytes; record effective commands and every failure. Unexplained differences stop dependent SBOM qualification and allocator work. No byte masks or copied artifacts.

## NAD-S03. Packaging gate

Only after NAD-S02 passes, implement reviewed SBOM identity mapping before wheel serialization. Preserve dependency provenance and graph equivalence. Validate unique safe ZIP members and exact `RECORD` hashes/sizes; compare full SBOM, native binary and wheel hashes. Reject malformed packages, duplicate members and tampering. Validate source/dependency mutations and path-only controls.

## NAD-S04. Downstream gate

Only qualified R and I configurations permit native instrumentation experiments. Require complete Rust/Python/actual-SQLite allocation coverage and physical ownership before changing legal-row reservations. Existing BIR08 thresholds remain binding. Failed prerequisites are reported as failed or unperformed, never as passing native bounds or browser acceptance. P1 stays NO-GO until all gates pass.

## NAD-S05. Diagnostic implementation boundaries

The isolated maturin patch invokes the pinned Python SBOM transform before its wheel writer. Preserve raw/generated SBOMs and prove inverse mapping restores the complete original JSON graph. The preliminary Rust `GlobalAlloc` observer counts requested live/peak bytes and calls, charging possible old/new reallocation overlap. It is not a three-domain upper bound or a per-proof ownership ledger. Missing Python/SQLite/backing-heap coverage blocks budget reduction even if all R/I wheels match. Run 3 diagnostic rounds of full valid/tampered rows and unchanged SQL admission in isolated child imports; never install experiment wheels into the service.

## NAD-S06. Review hardening

Before extraction, reject noncanonical ZIP paths, Windows reserved names, case-insensitive collisions, file/parent conflicts and nonregular members. Artifact admission requires 3 consistent native and wheel hashes in addition to the reported equality flags and an independent audit of the selected wheel. Atomically checkpoint attempts before child execution; retain command, variant/round and partial output on timeout without marking completion. Build timeouts also retain partial diagnostics. These experiment controls do not alter service cancellation/drain or budget ownership.
