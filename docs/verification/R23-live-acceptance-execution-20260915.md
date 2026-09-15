# R23 bounded live-acceptance execution and closeout

Canonical English; `R23-live-acceptance-execution-20260915.zh-CN.md` is the equivalent Chinese review copy. Proposal `R23-20260915-PM-105`; run `r23-20260915-a`. Status **REFERENCE_FAILED / AUTHORIZATION_CONSUMED / CLOSED / FULL_WORKFLOW_NOT_PROVEN**.

## 1. Outcome and completion boundary

R23 ran from `2026-09-15T12:51:26.061589+08:00` through `2026-09-15T12:51:26.553170+08:00`, using candidate commit `b9b45344fe52cf53b79a7e581670148db716274d`. The first `trade_cal` failed with `TIMEOUT`, failure kind `TRANSPORT_TIMEOUT`, and no HTTP status family. The reference boundary reported `REFERENCE_TIMEOUT` and the final audit recorded `REFERENCE_FAILED`.

The session interval is 491.581 milliseconds (approximately 492 milliseconds), not a separately measured HTTP request duration. The preserved categories do not identify the exact network, upstream, or local timeout cause. R22's success approximately 80 minutes earlier proves only its own invocation; it does not establish R23 availability or root cause.

The execution and evidence closeout are complete. The business acceptance did not pass: reference failure prevented any AI submission, human review, save, activation, evaluation, or visible alert validation. R19's real `plan-extract-v5`/8192 extraction remains unverified.

## 2. Calls and cleanup

| Item | Observed |
| --- | --- |
| AI physical starts | 0/3; each of `LITERAL`, `SEM-AMB-01`, `SEM-UNS-01` was not submitted |
| Market physical starts | 1/105; only `trade_cal=1`, all other endpoints zero |
| Retries | 0 |
| Denied before network | AI 0; market 0 |
| Final audit stop state | AI `stopped=true`; market `stopped=true` |
| Reference result | `REFERENCE_TIMEOUT` |
| Normal audit | Present; journal `normalAuditPresent=true` |
| Isolated plan cleanup | `INACTIVE` |
| Activation recovery | `NOT_RUN_NO_ACTIVE_PLAN` |
| Claim | `data/r23-acceptance/_session_claimed` remains present |
| Port 18768 at closeout | No listener |

Read-only SQLite inspection with `mode=ro` and `PRAGMA query_only=ON` found zero rows in all business tables, including calendar, sources, versions, reviews, activation, holdings, market data, evaluations, alerts, and delivery attempts. Only `alembic_version` and `monitor_sequence` contain one row each. The AI extraction diagnostic log is empty. The original execution task records deletion of its one-shot automation after failure; this closeout creates no automation or background wait.

The journal contains `ai.stopped=false` while the final audit contains `ai.stopped=true`. In `scripts/r14_bounded_acceptance.py`, AI and market budgets share one stop event, but journal updates replace only the budget snapshot that triggered the update. The market stop therefore leaves the journal's initial AI snapshot unchanged; `PhysicalAttemptJournal.complete` updates only status and normal-audit presence. The final audit freshly snapshots both budgets. The journal field is stale, not evidence of an admitted AI request; both records agree on zero AI attempts. This limitation is documented without rewriting historical artifacts or claiming that every journal field is a final snapshot.

## 3. Evidence integrity

Artifacts are under `data/r23-acceptance/r23-20260915-a/`. Closeout SHA-256 values:

- `audit.json`: `84109C3E26E1051D7D7428D058F6ED358EC7E86B837F4BE79CA88AE209425B5C`.
- `physical-attempts.json`: `642354D97B947507EB61F247B39FE2323E2BF2459F015C9C0346324335463CBA`.
- `monitor.sqlite3`: `541C241DE35D1E3CCDA2CD53E415D2E469838B5E9821507D0388270A31099159`.
- `monitor.ai-extraction-diagnostics.jsonl`: `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`.

The real `config/app.yaml` SHA-256 is `89923EA019712573B0F8118164EDA1EE2A8371C4EE57FAF2A2AD48FD6B8AB428`, matching the R22 recorded configuration hash. Raw configuration, direct-IP address, credentials, source content, provider content, and exception text are excluded from this report.

## 4. Closeout verification

The closeout began on clean `main` at the candidate commit. Checks cover the persisted audit and journal, read-only database counts, evidence/configuration hashes, claim presence, absence of a listener, the launcher and shared stop/journal code, and English/Chinese documentation consistency. Only documentation is changed. No application tests, dry-run launcher, or live calls are rerun; this documentation verification adds no runtime-success claim. Evidence and configuration hashes are checked again after documentation changes.

## 5. Remaining work and authorization

The consumed R23 claim, run ID, date window, and unused nominal allowance cannot be reused. Any new real run requires a concrete new candidate and its own authorization, with a fresh claim/database/port, a current time window, valid certificate evidence, and verified official model route/pricing. The local certificate files report stock expiry `2026-09-16T14:48:40.405317+08:00` and five-index expiry `2026-09-18T10:20:44.522358+08:00`; their validity must be evaluated at the future candidate time. Do not silently recertify. The original Flash route/cost assumption is disputed, and AI starts were zero; R23 cannot verify the actual returned model or AI bill. Market fees remain unknown.

The pending business proof remains faithful real extraction, ambiguity/unsupported-content blocking, current-content user review and explicit activation, deterministic live evaluation, and traceable IN_APP delivery. This run never reached evaluation. In a future eligible run, an absent natural BUY/SELL/RISK signal remains `NOT_OBSERVED`; it cannot be fabricated. Reading or acknowledging an alert does not change holdings. No new live candidate, budget, or R24 execution is authorized by this closeout.
