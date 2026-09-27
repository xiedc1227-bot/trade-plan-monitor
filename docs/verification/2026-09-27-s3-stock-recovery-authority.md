# S3 scheduled stock-recovery authority fence

## SRA-01 — Scope and status

One connected S3-06 test uses the actual application composition, scheduler, certified provider wrapper, request controller and temporary SQLite. All SDK/channel boundaries are offline fakes; HTTP clients are forbidden by the A07 fixture. No source, schema, user database, real notification, push or deployment is changed by this test slice.

Base HEAD is `8d83f79`; the four F3-C source files and strengthened A07 fixture are working candidates, not a committed release. This test imports A07 and must be accepted/submitted with that fixture, not independently presented as a self-contained committed test. F3-C implementation and final integrated gates remain separate. Independent verification approved this authority test/report slice for that shared batch.

## SRA-02 — Connected scenario and hard assertions

After a partial startup, release only actual scheduler waits. Pause the physical `rt_min_daily` SDK call belonging to an observed `STOCK_RECOVERY` duty. Capture all existing minute/latest-quote fields and business rows after earlier legitimate market work. While that SDK worker remains blocked, edit only the temporary token and have a second worker execute the real `configuration_is_current` file comparison and authority publication. Neither admission results nor revocation Events are mocked.

Release the SDK with a valid response containing the originally missing `09:31` minute. Assert no late minute/latest-quote change, including `received_at`, and no change to evaluation, ledger, head, risk, pending-close, alert or delivery rows. The original lifecycle, runner and owner generation remain; the runner waits for explicit stop with `NEEDS_RESTART`, no future poll/retry and no additional SDK/channel entry. Restoring the old configuration and advancing observation time by five minutes cannot unlock the revoked baseline.

This proves rejection at the commit boundary after a read has already entered the SDK. It does not claim that the already-started request was prevented. The second worker performs a real validation call as a controlled fault interleaving; it is not a new automatic watcher.

## SRA-03 — Observation corrections, not product fixes

- The first run during incomplete C wiring failed before SDK entry (`1 failed, 2.10s`); this is not a stable baseline RED.
- The first complete candidate run reached all write/owner protections but failed a health-copy generation assertion (`1 failed, 2.17s`). `RuntimeHealthSnapshot.runtime_generation` is deliberately excluded from serialization, while the validated `model_copy(update=...)` recreates excluded defaults. Assert the actual lifecycle and its direct health generation instead of treating the copied hidden field as a public generation contract. No health implementation or Step 4 protocol is changed.
- An additional public-state assertion initially expected a populated dashboard (`1 failed, 2.14s`). Before the first evaluation the existing union is `UNAVAILABLE / AWAITING_FIRST_EVALUATION`. The corrected assertion requires that exact response, no current symbol health, and an actual heartbeat frame with `runtimeLive=false` and `runtimeGeneration=null`. It does not accept arbitrary unavailable reasons.

## SRA-04 — Author verification

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_authority.py -q --tb=short
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_stock_recovery_authority.py
```

The corrected target passed **1 test in 2.03s**. The target plus all 13 A07 controls passed **14 tests in 13.93s**. Ruff passed. These are separate overlapping runs, not additive. The following hashes were unchanged before/after the combined run:

| Path | SHA256 |
| --- | --- |
| `src/trade_plan_monitor/runtime/production.py` | `7A5DE1FE6ADF80587505A3E3156B6CDD6A3C25A93192B2A83046EA2C1806A275` |
| `src/trade_plan_monitor/runtime/scheduler.py` | `97FA4303B5833F4C9C28FB1BB1CEF6F9D98A4F59D1E1FC718622F03BE80426AD` |
| `src/trade_plan_monitor/runtime/service.py` | `1FBF2D7C6731F46A4104F0C55C1EC1CB89F3C961482E55D9D87FB7C83FAB84C5` |
| `src/trade_plan_monitor/web/monitor_composition.py` | `3030F227DE0DA8EF02C69BF04996FCE92AF10546C577B10D955CED51AA339C68` |
| `tests/integration/test_s3_startup_minute_coverage.py` | `93E459A2B2D85A975895F4A374CE59F52BA44EF44C0AC4A5CCA16D153B0387EF` |
| `tests/integration/test_s3_stock_recovery_authority.py` | `73A68A95AB130BDA25D40BA1FDAD6FBF53979C4798BCEF0323A85AB8E9D9D67B` |

## SRA-05 — Independent verification and remaining gates

Independent Sol verification passed **15 tests in 17.46s** with the following command:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_identity.py tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_startup_minute_coverage.py -q --tb=short
```

The six SRA-04 hashes and the identity test's `961410F55D498DB70CB8BD4CAE4DF2BA2B9D0235DC477355F65BF6802FBA2767` were unchanged before/after. Both new tests passed Ruff; bilingual review found no semantic mismatch. The reviewer approved the authority oracle corrections and its three files for inclusion with C/A07, not a standalone commit. This combined run precedes a separately requested identity-test strengthening: it does not close that test's missing explicit maintenance-owner assertion or approve all C source.

The final frozen F3-C candidate was independently rerun with the strengthened identity and delivery controls:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_stock_recovery_wiring.py tests/integration/test_s3_startup_minute_coverage.py tests/integration/test_s3_stock_recovery_delivery.py tests/integration/test_s3_stock_recovery_authority.py tests/integration/test_s3_stock_recovery_identity.py tests/unit/test_monitor_runtime.py tests/unit/test_runtime_reconciliation.py tests/integration/test_s3_missed_close_kill_restart.py -q --tb=short
```

Result: **159 passed, 1 warning, 52.75s**. All four source and seven changed/new test hashes matched the final freeze before and after this run. Final `production.py` SHA256 is `38608F351317BBA04E35D169FC471B0F9707884E83C61E816544073143E968F7`; this authority test and the other three source hashes remain as listed in SRA-04. The strengthened identity test is `9E47CBB6E5F69D5273647F71E1EA90D9096C2230B8B2098DD48CF59C9FA99ED1`. Full-project `ruff check .` and `git diff --check` passed. No remaining P1/P2 source/test findings were reported. These overlapping runs are not additive.

This closes the requested final-candidate rerun of this connected control, not C1 unified permission dispatch, C3 overall or fixed-committed-revision full-suite acceptance. Final bilingual report review passed, approving all 21 reviewed paths for the shared local commit.
