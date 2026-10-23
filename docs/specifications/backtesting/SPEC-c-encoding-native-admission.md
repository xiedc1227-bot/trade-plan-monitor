# Native admission P0 specification

## CNA-S01. Scope

Implement isolated experiments from the paired CNA proposal. Preserve all existing files and parallel work. No production registration, live-data writes, commit or push. P1 remains conditional.

## CNA-S02. Representation

Trial fused normalization and conservative bound accumulation without per-container shallow copies or a second child traversal. Preserve model_dump/round_trip, exact scalar semantics and all canonical bytes. Keep the previous producer as the differential control. Do not remove native allocations from accounting because a Python traversal disappeared.

## CNA-S03. Ownership and admission

Record installed binary/source/schema fingerprints and an explicit allocation/ownership matrix. Successful measurement is not a native allocation proof. Keep `64 MiB`, `768 MiB`, `2560 MiB`, `8` readers, `1` proof, `1` queued owner, `15-second` waits, `90-second` eligibility and `2` attempts. Native provenance or allocation bounds failing prevents reservation reductions and funded-bundle integration. Still run legal-large-row SQL admission diagnostics and report rejection as failed availability.

## CNA-S04. Validation and gates

Compare original, previous C producer and fused candidate over identical frozen inputs in `3` diagnostic rounds, separately from tests and memory instrumentation. Validate long Decimals, dense objects/errors, all `19` fields, rehashed-domain tampering, concurrent isolation/deadlock, time boundaries, cancellation and cleanup debt. Preserve independent authority and complete historical proof. P1 requires native and availability gates plus `10` A/A pairs, `20` ABBA/BAAB blocks, `20%` mixed gain, at most `5%` result and `10%` monitor/CPU regression. No browser claims for an unintegrated experiment.
