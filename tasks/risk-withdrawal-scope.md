# Risk withdrawal scope correction

Historical task: the execution limitation below was completed by [CR-01–CR-03](cohort-risk-execution.md) on 2026-10-18, with a separately reviewed four-original continuous replay. Earlier findings remain audit history.

## RW-01 — Meaning

A restriction concerning new positions does not revoke an entire predecessor risk rule. Source 4 explicitly excludes applying 25.99 directly as a new-position stop; source 3's prior exit cannot be globally cancelled on that basis. Current zero holdings do not grant cancellation authority. No new stop price may be invented.

## RW-02 — Processing contract

Risk withdrawal proposals declare a source-backed `scope_assessment`: `ENTIRE_RULE`, `PARTIAL_RULE`, `CONTEXT_ONLY` or `UNCLEAR`. Only `ENTIRE_RULE` permits a whole-rule REVOKE. Missing assessment requires automatic re-extraction. Partial scope is a current representation limitation, not missing source information or a request for manual facts. Keep the predecessor branch and its price-line evidence in the non-executable candidate; do not apply it to newly opened holdings by silently approving the candidate. Remove the exact-sentence demotion exception and the biased verification feedback.

## RW-03 — Verification

Reproduce the actual fourth-source false approval, check different wording and explicit whole cancellation, rerun neutral real AI extraction against the reviewed third source, and preserve historical frozen reports. A failed scope check must block review/composition; do not publish a supposedly corrected replay while scoped execution is unsupported. Record that remaining execution limitation explicitly in both documentation languages.

Verified: false approval and lost context-scope metadata reproduced; neutral actual response and differently worded cases now remain correctly unresolved for partial scope. Historical-read/new-reuse boundaries, user-facing system-limit explanation and generated contracts pass. See [RW-V01–RW-V04](../docs/verification/2026-10-17-risk-scope-audit.md). Scoped execution remains outside this repair and no corrected replay is claimed.
