# S3 stock recovery owner — F3-A

## SRO-01 — Status and scope

Base: `1254761`, including accepted F2 `6bcf080`. F3-A design and the narrow pure-schedule interface extension were approved. Independent source/test review passed with no P1/P2; paired-report parity and root acceptance remain pending. This is an **unwired intermediate slice**, not completion of F3, A07 or S3-04.

The six candidate paths are `runtime/production.py`, `runtime/reconciliation.py`, `tests/integration/test_s3_stock_recovery_owner.py`, `tests/unit/test_runtime_reconciliation.py`, and this paired report. Runtime paths are under `src/trade_plan_monitor/`.

Only explicit `_synchronize_stock_recovery()` observes local facts. `next_stock_recovery_at()` returns cached memory without SQL, files, controller calls, clock reads or mutation. No default caller, request, background loop, scheduler/service/composition wiring, provider/controller change, business write, schema change or dependency change was added. Startup still uses the accepted F2 transition of at most 10 symbols; F3-B execution, maintenance-only 31.25-second reserve, F3-C startup-at-most-one and actual autonomous progress remain separate work. `MAX_RECOVERY_SCOPES = 32` is unchanged.

## SRO-02 — Implemented invariants

- A short owned read loads at most 10 ACTIVE records, rejects a larger total, checks exact F2 plan/activation identities, and derives the authoritative current-day target. Each legacy scope contains at most 240 exact session-minute identities, excluding lunch and future minutes. Missing identities come from committed facts, not row count or maximum timestamp.
- An independent `RecoverySchedule` uses `stock-prefix:{symbol}`. The latest desired capture/requirement, missing identities, authoritative permission observation, permission-readiness epoch and next wake are bounded owner caches. Revision includes exact plan dependencies, cutoff/date, source/Event identity, stable semantic revision, configuration, authority epoch and runtime generation; observation-time refresh alone does not change it.
- Exact committed coverage can become READY with zero fetch. Explicit plans retain only the existing bounded current-day prefetch: the cache is not explicit evaluation readiness and adds no cross-day recovery or legacy readiness gate.
- Existing RETRY deadlines survive target changes and late completion. Unknown targets/calendars produce zero requests and fixed local reobservation, only extended when due, using the existing 30-second interval.
- BLOCKED schedule revisions remain frozen while latest desired targets advance separately. Only an observed real controller blocked→cleared transition under the same non-revoked binding increments readiness epoch and deliberately synchronizes a new requirement. Business recovery neither probes nor clears permission. Index operation blocks remain independent.
- Source/client/inner-client/Event identity is exact; semantics use `semantic_revision`, not contract-object identity. Metadata-only refresh preserves pending, blocked and retry state. Revocation, changed binding or stale generation rejects synchronization without rearming and disables the cached wake. Deactivation removes the scope.

## SRO-03 — RED history and interface correction

TDD, incremental implementation, Git scope isolation and security-boundary checks were used. Initial fixture mistakes (wrong sample symbol, immutable instance monkeypatch, missing `work_key`, and future row `received_at`) were corrected separately; they are not product defects.

1. Minimal owner entry/getter tests: **3 failed, 1 warning, 1.74s**, all missing API after the symbol fixture correction; then **3 passed, 1 warning, 1.62s**.
2. Source/client-inner/authority-epoch rejection was initially missing. The initial semantic-copy rejection oracle was too strict and is **not** product-fix evidence. Root required stable semantic revision compatibility. Three real metadata-only refresh controls subsequently failed (**3 failed, 23 passed, 1 warning, 5.55s**) and passed after correcting the binding comparison.
3. Root identified that local classification via `claim/complete(PENDING)` consumed real round-robin turns. The deterministic A/PENDING, B/future-RETRY, C/PENDING owner control genuinely failed (**1 failed, 15 passed, 1 warning, 3.86s**).
4. Root and independent Sol approved the minimal `resolve_local(requirement, result, *, now) -> bool` extension before expanding source scope. Twelve new unit controls plus the fairness control were RED (**13 failed, 27 passed, 1 warning, 3.98s**), then **40 passed, 1 warning, 3.80s**.

`resolve_local` changes only `entry.result`, never `_order`, `_owned` or identity. It requires exact current requirement and PENDING or due RETRY; future RETRY, READY, BLOCKED and any owned ticket for the same stable scope (including old revision/removal-readdition) remain unchanged. It allows READY/BLOCKED/strictly future RETRY and rejects PENDING. Unrelated local classification cannot replace a physical ticket. The owner does not call it for known missing facts. Final coverage also checks late retry floors, bounded reads with zero business SQL writes, all session edges, reactivation/deactivation and authoritative clearance under changed binding.

## SRO-04 — Final author verification

All commands run from `trade-plan-monitor`, offline with temporary databases. No live service, real user database, push or deployment was used. Counts below are separate runs, not additive.

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest; original = builtins.__import__; builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError('A07 is not a committed dependency')) if name == 'test_s3_startup_minute_coverage' else original(name, *args, **kwargs); raise SystemExit(pytest.main(['tests/integration/test_s3_stock_recovery_owner.py', 'tests/unit/test_runtime_reconciliation.py', '-q', '--tb=short']))"
```

**59 passed, 1 warning, 6.69s**: 35 owner tests and 24 schedule tests (12 existing + 12 new). The A07 import blocker proves the candidate uses only committed helper dependencies.

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_frozen_startup_recovery.py tests/integration/test_runtime_recovery_coverage.py tests/integration/test_runtime_recovery_storage.py tests/integration/test_recovery_activation_fences.py tests/integration/test_production_semantic_gate.py tests/integration/test_runtime_lifecycle.py tests/integration/test_monitor_production_composition.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/unit/test_monitor_runtime.py -q --tb=short
```

The seven-file integration batch: **182 passed, 1 warning, 44.71s**. The scheduler/runtime unit batch: **88 passed, 2.36s**. An earlier command named nonexistent `tests/unit/test_runtime_scheduler.py`, collected no tests and is not passing evidence.

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
```

**11 passed, 2 failed, 11.98s**. Only the unchanged A-empty/B-missing-0931 autonomous progress cases remain RED; the F2 cutoff and original oracle controls pass. Original A07 files are untouched. No runner replacement, suppressed assertion, skip or xfail closes this gap.

```powershell
.venv/Scripts/python.exe -m ruff check src/trade_plan_monitor/runtime/production.py src/trade_plan_monitor/runtime/reconciliation.py tests/unit/test_runtime_reconciliation.py tests/integration/test_s3_stock_recovery_owner.py
git diff --check
```

Both pass (Ruff is scoped, not full-project). The known Starlette/httpx deprecation warning is unchanged. Earlier 3/11/40/50/59 development runs are pre-final windows, not independent acceptance.

## SRO-05 — Frozen candidate and independent review

Independent Sol source/test review passed with no P1/P2; no commit by the implementation writer. Independent commands and results:

```powershell
.venv/Scripts/python.exe -c "import builtins, pytest; original = builtins.__import__; builtins.__import__ = lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError('A07 is not a committed dependency')) if name == 'test_s3_startup_minute_coverage' else original(name, *args, **kwargs); raise SystemExit(pytest.main(['tests/integration/test_s3_stock_recovery_owner.py', 'tests/unit/test_runtime_reconciliation.py', 'tests/unit/test_recovery_coordinator.py', 'tests/unit/test_recovery_targets.py', '-q', '--tb=short']))"
.venv/Scripts/python.exe -m pytest tests/integration/test_production_semantic_gate.py tests/integration/test_s3_installed_runtime_read_liveness.py -q --tb=short
```

Respectively **107 passed, 1 warning, 6.88s** and **13 passed, 1 warning, 5.22s**. The reviewer confirmed the four-path Ruff command, diff check and unchanged four source/test hashes. The reviewer did not rerun original A07; SRO-04's 11/2 result is author-only, not independent evidence. Source/test SHA256:

| Path | SHA256 |
| --- | --- |
| `src/trade_plan_monitor/runtime/production.py` | `8DE77DBC7982E51EE5D64214B0E730144AC7CD6A9540F2886A2F124F73C4887E` |
| `src/trade_plan_monitor/runtime/reconciliation.py` | `6992DABFFA617B0C1B467363A7753F720C451FAC874837095EB9E387547E1A19` |
| `tests/unit/test_runtime_reconciliation.py` | `E2D37F1267BCBE72E046401D81F963E502FE6F0C9CEEDA285D8626A8F5E6B604` |
| `tests/integration/test_s3_stock_recovery_owner.py` | `BFEB26492D211B17B2F74F67D56C4F2B805EB85B4E31A1E85515DD998490EB8D` |

Residual boundary: this cache is not fetch/commit authority. F3-B must recapture and apply F2 fences, the closed F3-09 outcome matrix and maintenance-only reserve. F3-C must supply real scheduler/lifecycle ownership and prove same-generation 10:05:12 evaluation and public non-actionable readiness before that evaluation. Existing official-close, manual admission and 120h policies are not changed.
