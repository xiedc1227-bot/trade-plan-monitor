# R11 Explicit Plan Review Verification

## Scope

This report verifies the R11 explicit-plan review boundary with a fixed, independently classified semantic corpus. The verification is deterministic and offline: no live AI provider, market-data provider, notification channel, trade endpoint, production database, or secret was used.

R11 accepts partial Schema 3 drafts, preserves exact source clauses and bidirectional source mappings, derives required review issues on the server, binds review confirmations to the exact content and source hashes, and keeps public activation unavailable until the R12 ordinary-plan forms gate is implemented.

## Fixed Corpus Result

The oracle was recorded in `tests/fixtures/ai/explicit-plan-semantic-corpus-v1.json` before the implementation was accepted. `NONE` means that the server produced no semantic blocker.

| ID | Category | Expected semantic codes | Actual semantic codes | Status |
|---|---|---|---|---|
| EXP-01 | EXPLICIT | NONE | NONE | PASS |
| EXP-02 | EXPLICIT | NONE | NONE | PASS |
| EXP-03 | EXPLICIT | NONE | NONE | PASS |
| EXP-04 | EXPLICIT | NONE | NONE | PASS |
| EXP-05 | EXPLICIT | NONE | NONE | PASS |
| EXP-06 | EXPLICIT | NONE | NONE | PASS |
| EXP-07 | EXPLICIT | NONE | NONE | PASS |
| EXP-08 | EXPLICIT | NONE | NONE | PASS |
| AMB-01 | AMBIGUOUS | `UNRESOLVED_SEMANTICS` | `UNRESOLVED_SEMANTICS` | PASS |
| AMB-02 | AMBIGUOUS | `UNRESOLVED_SEMANTICS` | `UNRESOLVED_SEMANTICS` | PASS |
| AMB-03 | AMBIGUOUS | `UNRESOLVED_SEMANTICS` | `UNRESOLVED_SEMANTICS` | PASS |
| AMB-04 | AMBIGUOUS | `UNRESOLVED_SEMANTICS` | `UNRESOLVED_SEMANTICS` | PASS |
| AMB-05 | AMBIGUOUS | `UNRESOLVED_SEMANTICS` | `UNRESOLVED_SEMANTICS` | PASS |
| AMB-06 | AMBIGUOUS | `UNRESOLVED_SEMANTICS` | `UNRESOLVED_SEMANTICS` | PASS |
| UNS-01 | UNSUPPORTED | `UNSUPPORTED_SEMANTICS` | `UNSUPPORTED_SEMANTICS` | PASS |
| UNS-02 | UNSUPPORTED | `UNRESOLVED_SEMANTICS`, `UNSUPPORTED_SEMANTICS` | `UNRESOLVED_SEMANTICS`, `UNSUPPORTED_SEMANTICS` | PASS |
| UNS-03 | UNSUPPORTED | `UNSUPPORTED_SEMANTICS` | `UNSUPPORTED_SEMANTICS` | PASS |
| UNS-04 | UNSUPPORTED | `UNSUPPORTED_SEMANTICS` | `UNSUPPORTED_SEMANTICS` | PASS |
| UNS-05 | UNSUPPORTED | `UNSUPPORTED_SEMANTICS` | `UNSUPPORTED_SEMANTICS` | PASS |
| UNS-06 | UNSUPPORTED | `UNSUPPORTED_SEMANTICS` | `UNSUPPORTED_SEMANTICS` | PASS |

Result: **20/20 cases passed**: 8 explicit, 6 ambiguous, and 6 unsupported.

## Automated Evidence

- R11 focused review and security checks: 49 passed.
- AI, web, OpenAPI, repository, and R11 integration release gate: 433 passed after the final hardening pass.
- Legacy explicit runtime and transport regression group: 29 passed.
- Remaining plan, decision, outbox, risk, position, notification, and production regression group: 684 passed.
- Configuration regression group: 22 passed.
- Generated frontend API types match the OpenAPI snapshot.

The frontend type-check still reports pre-existing R10 alert-union errors in `AlertTable.vue` and `AlertsView.vue`. R11 does not modify those files or weaken that check.

## Release Boundary

The public capability remains `publicActivationAvailable=false`. A valid current review confirmation is necessary but deliberately insufficient for public activation: the API still returns the R12 ordinary-plan forms gate. Import, notification delivery, trade execution, and production deployment remain out of scope.
