# S3 certification fixture alignment

## CFA-01 — Scope and reviewed diagnosis

Test-only follow-up after F3-C `a1f217b`, during S2 owner work. The three owned paths are `tests/integration/test_production_certification_gate.py` and this report pair. Only four existing cases, one local clock helper and one exception import change. No production code, thresholds, public APIs, real services, user databases, push or deployment are involved.

The original three-case run produced **3 failed, 41 deselected in 10.32s**. Two failures were fixed sleep-count assumptions: new stock maintenance used the available wake before the expected realtime request, so a second request or a first 429 never occurred. The adjacent five-minute backoff negative control still passed but likewise had not reached its second market duty. Astra classified these premises read-only and Sol approved the limited alignment before editing.

The third failure was the direct internal `state.run_deadline` call after an already permitted decision committed and a worker revoked configuration authority. F3-C's subsequent demand synchronization correctly rejects the revoked owner with `RecoveryAdmissionChangedError`. The real lifecycle already catches failures only when configuration restart is required, marks `NEEDS_RESTART`, and waits for explicit stop; otherwise it propagates. No production catch or authority weakening is needed. The independent reviewer approved requiring the exact typed exit in this direct-call test, not a broad exception or a claim that this test executes the full runner path.

## CFA-02 — Preserved acceptance

The local clock helper releases at most eight real scheduler waits through `10:02:12` for transport recovery/backoff, or `10:01:12` for 429. It records each actual due time, advances only to that due time and waits without advancing after the cutoff. The first two tests require the next wait beyond the cutoff, proving the target duty returned rather than merely entered `sleep_calls`.

- Recovery still requires at least two physical `rt_min` calls, the same runtime/controller and RUNNING, and normal controller close after stop.
- The five-minute backoff control now proves the next market duty completed with exactly one physical call; no next-minute bypass is permitted.
- The 429 control still requires exactly 300 seconds from the controlled observation, durable repository binding, actual clean stop/reopen, restored cooldown and zero provider calls before that floor despite the new token.
- The final-permit control catches only `RecoveryAdmissionChangedError` around that one internal call. Real worker revocation, exactly one legally committed result, `NEEDS_RESTART` and closed decision admission remain mandatory.

No test, original business assertion or retry threshold was removed, skipped or weakened. The actual same-generation scheduled revocation path remains covered separately by the committed authority test.

## CFA-03 — Verification

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_certification_gate.py -k 'resumes_after_one_runtime_transport_failure or next_minute_cannot_bypass or 429_cooldown_restores or revocation_after_final_permit' -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_production_certification_gate.py
```

Author result: **4 passed, 40 deselected in 4.86s**. Ruff initially requested import ordering; after that formatting-only correction it passed. Final test SHA256: `D79C4E4C90F241374D3338297A900C91CA7AECA0ECE245043085DC40D267C010`; observed S2 candidate `production.py`: `522560DDFB708A0DA31B6C5321611E96E0D700B5DF7AF9AB6B391ACED27658A7`.

Independent Sol verification used this exact command:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_production_certification_gate.py -k "production_composition_resumes_after_one_runtime_transport_failure or next_minute_cannot_bypass_realtime_transport_backoff or production_429_cooldown_restores_before_provider_work_after_restart or revocation_after_final_permit_finishes_one_inflight_decision" -q --tb=short
```

Result: **4 passed, 40 deselected in 4.85s**, without warnings. Six source and the test hashes were unchanged before/after, including the two hashes above. Ruff, targeted diff check, static review and bilingual parity passed; all three paths were approved with no P1/P2. The runs overlap and are not additive. This is a source-frozen S2 working-candidate compatibility window, not S2 approval or fixed-commit aggregate acceptance. C1/C3 and the final full offline suite remain OPEN.
