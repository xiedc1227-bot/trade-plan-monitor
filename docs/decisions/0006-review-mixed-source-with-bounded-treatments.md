# ADR 0006: Review Mixed Source with Bounded Server Treatments

Canonical English; the matching `.zh-CN.md` is the Chinese review copy.

- Status: Accepted implementation guidance under the R11 corrective authorization
- Date: 2026-09-12
- Supersedes: ADR 0005 only for new server review mapping/evidence versions

## Context

R11 v2 simulated-provider tests prove typed source mappings and blocking, but the derived three-rule shorthand cannot complete review: existing inventory and alert-isolation prose are not executable plan fields. R08 C02/C09 explicitly place them at independent inventory and product boundaries. Mapping a whole mixed clause only to symbol loses meaning; leaving every such clause unresolved makes a supported source permanently unreviewable.

## Decision

Use the finite contract in [SPEC-source-treatment-review](../specifications/monitoring/SPEC-source-treatment-review.md). Keep every v1/v2/v3/v4 prompt/output schema and golden digest frozen. Extend only the server-owned mapping to `plan-mapping-v2`, with `source-processing-v1` and evidence domain `plan-review-evidence-v2`. Model v4 output remains v1; new save derives v2 treatments from exact full clauses. Stored v1 snapshots retain the existing review path.

Treatments cover only independently registered inventory assertions and implemented `alert-position-isolation-v1` guarantees. Exact source spans and parameter values are validated by re-derivation; every treatment needs an explicit current-snapshot review. No general ignore/acknowledge classifier, AI-selected product contract or inventory side effect exists. Content approval and live inventory readiness remain separate under E07.

Reuse mapping JSON and resolution storage; no database migration or new external dependency. Reject unknown versions and tampered treatment records on ordinary read/review. Older binaries cannot read new v2 mappings; use forward recovery or a compatible backup, never strip processing records.

## Alternatives and acceptance

Rejected: mapping all mixed prose to symbol; deleting/rephrasing source; generic non-trading exemptions; holding content approval permanently false; requiring live inventory to keep semantic approval valid.

Acceptance requires the literal provided source (only `测试股票` → `003043.SZ` substitution), a real completed reviewId, public R12 activation denial, independent idempotent inventory registration, verified reminder/ack isolation, adversarial omission/injection/tamper tests, frozen prompt checks and bilingual evidence. The previous shorthand and v1/v2 semantic corpora remain historical fixtures with accurate labels.
