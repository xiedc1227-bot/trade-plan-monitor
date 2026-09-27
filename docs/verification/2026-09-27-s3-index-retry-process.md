# S3-05 index retry across a clean OS-process restart

> Canonical English verification report. The paired Chinese review copy is `2026-09-27-s3-index-retry-process.zh-CN.md`.

## IRP-01 Scope and status

Status: writer verification and independent root review passed; three-file local commit approved, with no P1/P2 findings. No complete S3-05 or release acceptance is claimed.

Only `tests/integration/test_s3_index_retry_process.py` and this paired report belong to this slice. No production source, scheduler policy, database schema or existing test is changed. Authority is the existing S3-05 gate in `tasks/runtime-recovery-todo.md`.

## IRP-02 Test boundary

The fixture seeds a real Schema v2 plan requiring `INDEX_CLOSE_GTE_MA` and an independent Schema v3 plan with a legally deliverable rule. Both use complete persisted activation, calendar, inventory and manual-risk facts. A seed control verifies that no evaluation, alert, delivery, index snapshot or retry is prebuilt.

Two separate `spawn` processes create the real composition and start the real scheduler. An injected clock only releases the exact sleep selected by that scheduler. No direct `run_deadline`, retry-service call, forced lifecycle status, timer-policy override or admission bypass is used. A fake channel replaces only transport; the installed current-delivery admission remains active.

P1 starts at 09:59:30 and wakes at the legal 10:00:12 market deadline. Only the required index fails. Its dependent plan must record missing index evidence and no signal; the independent plan must actually deliver once, with the other four display indexes LIVE. P1 must stop its composition and exit normally before P2 exists.

P2 starts at 10:00:20 with the same temporary database and no provider failure. It must restore the original retry/cutoff and failed persisted head. Its first scheduler wake must recover that index head to LIVE at the original cutoff, without stock SDK requests, evaluations, alerts, delivery attempts or sends in that index-only segment. Subsequent ordinary scheduler wakes reach 10:05:12; the dependent plan must evaluate with LIVE index evidence, while the independent sibling must not send again.

The startup business tables must equal P1's clean-stop state, excluding unrelated liveness records. The original sibling event, first DELIVERED receipt and explicit evaluation remain unchanged at the final cutoff; per-target evaluation identities remain unique. Four negative oracle controls inject a stock call, evaluation row, alert row or send into independent copies of the real observations. Each must fail the same index-only assertion used by the main path; they never modify the database or production state.

## IRP-03 Commands and evidence

Run from `trade-plan-monitor/`:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_s3_index_retry_process.py -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_s3_index_retry_process.py --output-format concise
```

- Seed-only increment: **1 passed, 1 warning in 1.28s**.
- First real-process run: **1 failed, 1 passed in 7.20s**. The failure was a fixture comparing canonical JSON `10:00:00.000000+08:00` with an equivalent second-precision timestamp. The recovered index was already LIVE. Parsing the timestamp before comparison fixes the assertion without changing its cutoff requirement; this is not a product RED.
- Corrected process baseline: **2 passed, 1 warning in 6.99s**.
- Final strengthened file, including startup equality, original event/receipt preservation, identity uniqueness and four negative oracle controls: **2 passed, 1 warning in 6.87s**. Focused Ruff passed. The warning is the existing Starlette/httpx deprecation. Runs overlap and are not additive.

The first process run used a coordinated source freeze. The final run followed test-only changes; all four concurrent F2 source hashes were also unchanged before/after that run. The checkout was `7c178184b84b835aa93b40e7120185c95fccaccf` plus another writer's uncommitted F2 source changes, not an isolated committed release. This test writer changed no production source and does not approve those F2 changes. Recorded source fingerprints:

| Path under `src/trade_plan_monitor/` | SHA256 |
| --- | --- |
| `runtime/production.py` | `7D5FA3724CE7CC0243535B2A7FDCD54E78EB7A4A703FAEFC41F56AF553CEBBB7` |
| `web/monitor_composition.py` | `DBB3381DC4D29F80AAAF755F9340317D3A655D85C8C85649883A059C3404901E` |
| `runtime/recovery.py` | `C090C838BF61F5DA7EB89184C2153AC9D83C00490A9AB49D97BA6F0CC7E5378F` |
| `runtime/recovery_targets.py` | `C19139108C4C7B2192AF10B7391F0A4899E821685B40705FE0A6FBB9A32618BD` |
| `runtime/service.py` | `DF3EE4DF221D7FB40088B3CDAD66F263C8AB1D529C2A5774F213AFE41E9FAD43` |
| `runtime/scheduler.py` | `956887081F421DA68CAE222195CD35C3D946785513639C686976C278A542CC30` |
| `runtime/market_indexes.py` | `DBC989CA3DEE64A393F097BE669832B1DBAC25A3E6351E58A318E87D79310F36` |

Final test SHA256: `A6760C523D39A3E35E2B5EB3F4481A66DEDB8F39120AB3E38191DD4FF9D7D3F5`.

Independent root review reran the same focused command: **2 passed, 1 warning in 6.97s**. Focused Ruff passed; the four F2 source fingerprints and final test hash above were unchanged before/after this run. Test/code-oracle and paired-report review found no P1/P2. This is separate working-tree candidate evidence, not an additional aggregate count or approval of F2.

## IRP-04 Limits and handoff

Every child blocks requests/httpx network access and uses fake SDK/channel boundaries, controlled clocks and a temporary SQLite database. Normal completion requires clean OS exit; forced termination is failure cleanup for the exact fixture-owned process only. No real provider, real notification, user database, push or deployment is involved.

This adds the clean-process index-retry evidence missing from the older same-process/direct-deadline test; it does not replace the broader A06 matrix or close S3-02/S3-04 prerequisites. S3-05 remains OPEN pending integrated prerequisite acceptance. Concurrent A07 F2 work is outside this slice. Full-suite, release-revision and production-readiness claims are not made.
