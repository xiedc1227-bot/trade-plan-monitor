# ADR 0007: Separate Recovery Delivery Metadata from Alert Identity

Canonical English; the matching `.zh-CN.md` is the Chinese review copy.

- Status: Accepted; production composition uses current delivery admission
- Date: 2026-09-21
- Related: `SPEC-runtime-recovery`, RR011–RR013

## Context

Recovery may commit historical decisions whose original alerts must remain auditable but must not automatically be sent. Alert/result payloads and hashes are immutable; acknowledgement, channel attempts and current delivery applicability are different facts. An old successful classification cannot establish current activation, generation, target or inventory after restart.

## Decision

Migration `0019_alert_delivery_eligibility`, after `0018_provider_recovery`, adds a separate row keyed by event ID. Missing rows mean unclassified `HOLD`. A session-bound repository initializes on demand or in batches of at most 100. `AlertOutbox.enqueue_recoverable` is opt-in and creates the alert and initial HOLD in the caller-owned transaction; dedup never resets a classification or assigns current-activation provenance to an old event.

Classify by signal, not severity. Actionable intraday alerts expire at original source cutoff + 90 seconds, including equality. A missing source cutoff is not replaced with creation/evaluation time. State-risk alerts have no blanket age expiry. Persist classification, captured barrier/result identity, revision and audit atomically. Validate metadata against canonical alert facts; malformed evidence is a visible fault. Serialize writers before reading and use revision compare-and-set; the repository never commits independently.

`SUPPRESS` is terminal for the original event; `HOLD` is reversible. `ELIGIBLE` is only a historical receipt. Future dispatch must establish current authority after claim and before each channel call, avoid candidate-limit starvation, and preserve uncertain-send handling. No database transaction spans external I/O. The isolated explicit-risk path does not authorize legacy risk, and the separate pure legacy classifier does not itself persist or send anything.

## Alternatives and acceptance

Rejected: rewriting canonical payloads; reusing acknowledgement or channel failure as suppression; applying a blanket 90-second expiry to risk; backfilling all history inside schema upgrade; treating persisted ELIGIBLE as a permanent permit.

Acceptance for this increment is temporary-database migration/interruption/rollback, bounded initialization, immutable alert bytes, source expiry, corrupt-evidence rejection, concurrent revision fencing and atomic audit. Current integration and executed evidence are maintained in `SPEC-runtime-recovery.md` and the latest acceptance report. Nonempty downgrade refuses to discard metadata, including terminal audit state; use forward recovery or a compatible backup without overwriting newer business records. Live migration and deployment require separate approval.
