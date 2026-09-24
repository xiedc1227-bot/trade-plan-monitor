# A05 Index Permission Scope Migration (Offline)

## Scope

Revision `0023_index_permission_scopes` is an additive data migration from `0022_runtime_liveness`; it does not change the checkpoint table. It replaces a persisted `index_minutes` permission reservation with separate `idx_mins` and `rt_idx_min_daily` reservations. The migration accepts legacy and mixed key sets only while upgrading. Runtime repository reads and writes accept only the new canonical scopes, with a 75-row limit and a 76-row over-limit read.

The existing index adapter and offline live-certification probe now pass the corresponding endpoint operation to request control. This mapping change adds no permission recheck probe. Existing work-key strings and their SHA-256 storage identities remain unchanged.

## Verified behavior

- A full legacy 74-row set becomes a canonical 75-row set. The two valid mixed sets, legacy plus one new scope at 75 rows and legacy plus both new scopes at 76 rows, also become 75 rows. Each shape rejects its one-row excess. Existing endpoint retry times are merged with the legacy retry time using the later value.
- Other permission rows, shared cooldown, backoff keys, retry strings, failure counts, reason codes, and provider identity remain byte-for-byte unchanged. A second provider's invalid row prevents any provider rewrite. Unknown scopes, corrupt reason codes or timestamps, and excess backoff rows fail closed without changing data or advancing the Alembic version. Repeated upgrade is idempotent.
- A migrated legacy block remains `BLOCKED_PERMISSION` even when its retry time has passed. Both ordinary index adapter paths stop before any SDK call. An old hashed work key retains its `TRANSIENT` backoff deadline after the new controller binds the recovered repository. The controller admits no physical request before binding. Clearing only the realtime permission leaves the historical permission blocked and permits a fresh realtime key independently. Runtime loading or saving of the legacy scope fails closed; no new checkpoint writes use it.
- Downgrade to `0022_runtime_liveness` refuses when either new scope is present and leaves both data and revision unchanged.

The focused migration file passed **14 tests**. The adjacent storage, request-control, index adapter, probe, migration, and repository checks passed **269 tests**. Installed production certification, A06 index, semantic-gate, and live-pipeline checks passed **79 tests**, with one existing Starlette/httpx deprecation warning. Ruff checks passed. These are bounded offline migration and admission results, not complete A05 acceptance. Cold-start positive permission probes, frontend health expansion, process-interruption coverage, and work-key stability changes remain separate work. No real provider, external notification, user database migration, deployment, or push was used.
