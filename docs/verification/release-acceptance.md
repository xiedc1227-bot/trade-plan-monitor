# T059 Release Acceptance Evidence

**Status:** `PENDING FINAL USER ACCEPTANCE` on 2026-08-31. Every approved internal offline gate is
green after the separately authorized production-performance remediation. Optional AI connectivity
is `NOT_RUN_UNAUTHORIZED`, and the user has not yet performed final release acceptance.

## 1. Decision and evidence boundary

This report evaluates `T059`, `P18`, `BT008`, `BC01`, and checkpoint `C24` against baseline
`d8b28b20e59b91b261ce46003effdb01288d832a`. The repository candidate contains exactly 12 formal
files: the original five T059 files plus seven separately authorized export/capacity implementation
and regression files. They are the bilingual README pair, this bilingual report pair,
`tests/contract/test_ai_live.py`, four production modules under `src/trade_plan_monitor/`, and three
focused regression files. No dependency, migration, database schema, API path, generated contract,
provider configuration, or approved performance threshold changed.

The release decision is `PENDING_FINAL_USER_ACCEPTANCE`. The earlier
`BLOCKED_OFFLINE_PERFORMANCE_GATE` decision was valid for the failed fresh gate and is superseded only
by the RED-first remediation and new complete passing gate recorded below. Business time remains
`Asia/Shanghai` with explicit `+08:00` semantics. `C24` is therefore 3 of 4, and T059 remains in
progress until the user explicitly accepts the release.

## 2. RED and optional AI live gate

The original documentation RED was:

```text
python -m pytest tests/contract/test_ai_live.py -q
1 failed, 1 passed, 1 skipped in 0.14s
T059_RELEASE_REPORT_MISSING
```

After the offline performance gate failed, export profiling identified avoidable repeated JSON
decoding and per-row CSV construction. The fixed `>= 5 MiB/s` threshold remained unchanged. Capacity
profiling then identified repeated materialization of unchanged daily indicator points and expensive
Windows working-set trimming. RED tests first proved missing prefix reuse, same-identity/different-OHLC
rejection, forged prefix rejection, and optimized-versus-reference report-byte equivalence. The
minimal implementation uses a private issued DailyBar prefix, exact immutable bar identity checks,
and ordinary garbage collection. Public interfaces and canonical result bytes remain unchanged.

The live AI test is optional and self-gated. Ordinary collection checks the exact marker expression
before reading target configuration and never constructs an HTTP client. A real connection needs all
four non-persistent process values: `TRADE_PLAN_MONITOR_AI_LIVE_BASE_URL`,
`TRADE_PLAN_MONITOR_AI_LIVE_MODEL`, `TRADE_PLAN_MONITOR_AI_LIVE_AUTHORIZATION_SHA256`, and
`AI_API_KEY`. Authorization is the lowercase SHA-256 of the operation context, normalized HTTPS
endpoint, exact model, and final newline. The exact selector is
`python -m pytest tests/contract/test_ai_live.py -q -m live`; it may run only after a separate
operation-specific network authorization.

No such authorization was given for this T059 run, so the canonical result is
`NOT_RUN_UNAUTHORIZED`. This does not fail deterministic monitoring. A future pass would prove only
bounded Chat Completions envelope connectivity, not model identity, plan quality, safe activation,
or trading correctness.

## 3. Fresh offline results

All formal Python inputs were constructed from Git-tracked paths, with the new T059 contract test
named explicitly. The five protected validation-only files were excluded from every formal test,
lint, format, and compile input.

| Gate | Fresh result |
|---|---|
| Complete protected-file-excluded backend suite | `1949 passed, 4 skipped, 1 warning in 2512.36s` |
| Daily-prefix focused runner/indicator suite | `30 passed in 48.34s` |
| Affected capacity regression | `106 passed in 53.08s` |
| Exact ten-symbol/252-day capacity node | `1 passed in 1509.95s` |
| Exact 252-day traced-heap node | `1 passed in 722.73s` |
| Offline AI provider/drafting contracts | `106 passed` |
| Tracked SQLite backup/restore contracts | `9 passed` |
| Frontend unit suite | `26 files, 484 tests passed` |
| Protected-file-excluded Vue type-check | PASS |
| Production build | PASS |
| Allowed `Chromium-only` E2E | `6 passed` |
| Ruff check / format | PASS on tracked Python plus `tests/contract/test_ai_live.py` |
| `compileall` / `pip check` | PASS / `No broken requirements found` |
| OpenAPI/TypeScript generator `--check` | PASS; current |

The only warning is the existing Starlette `TestClient`/httpx2 deprecation warning. The four skips
include the unauthorized optional live AI probe; no real AI, Tushare, Webhook, broker, notification,
or other network operation ran.

## 4. Fixed performance and resource evidence

No acceptance ceiling or floor was relaxed.

| Measurement | Fresh observation | Fixed limit |
|---|---:|---:|
| 100k export throughput, minimum of 30 | `7.435517829658122 MiB/s` | `>= 5 MiB/s` |
| Export first byte, maximum of 30 | `4.365700006019324 ms` | `<= 250 ms` |
| Export working-memory delta | `2,084,864 B` | `<= 256 MiB` |
| Slowest query p95 (`equity`) | `103.6420000018552 ms` | `<= 250 ms` |
| Query database plus WAL | `298,213,376 B` | `<= 384 MiB` |
| Query working-memory delta | `0 B` | `<= 256 MiB` |
| Ten-symbol replay elapsed range | `93.17825320002157–107.31649890000699 s` | each `<= 120 s` |
| Capacity working-set delta | `88,616,960 B` | `<= 768 MiB` |
| Capacity market database plus WAL | `519,028,736 B` | `<= 512 MiB` |
| Capacity result database plus WAL | `184,909,824 B` | `<= 192 MiB` |
| Capacity traced-heap delta | `122,690,533 B` | `<= 384 MiB` |

All 30 export samples exceeded the fixed floor. The daily-prefix integration test recomputes every
provisional and official context through the original full path, then compares every decision JSON,
the complete canonical report, and `report_hash` byte-for-byte. A fresh-context review found no P0–P2
issue after the issued-instance anti-forgery fix. Its remaining P3 observation concerns only an
unpromised no-GIL/alternate-interpreter concurrency contract.

## 5. Accessibility, security, soak, and restore evidence

- **Accessibility:** the two allowed tracked Playwright files pass all 6 Chromium tests, including
  axe, keyboard/focus, reduced motion, responsive layouts, and 200-percent text. The Windows NVDA
  four-route checklist remains accepted evidence from `cb81cf4`. This is a `Chromium-only` claim and
  makes no Firefox/Gecko claim.
- **Security:** the AI gate is selector-first, target-bound, secret-reference-only, TLS-verified,
  proxy-independent, redirect-free, resource-bounded, and redacts provider failures to stable codes.
  All formal security assertions pass. A diagnostic search accidentally scanned three protected
  backend validation files and displayed two matching lines from the restore file. It was disclosed,
  the user allowed continuation, and that search is excluded from evidence. No protected file was
  modified, run, staged, or committed.
- **Soak/capacity:** all ten 252-day replays, fixed storage ceilings, working-set ceiling, traced-heap
  ceiling, query latency, and 100k export throughput pass with the measurements above.
- **Restore:** all 9 tracked SQLite backup/restore tests pass. Accepted BT050 evidence additionally
  covers migration-backup fingerprint binding, `PRAGMA integrity_check = ok`, WAL sentinels, replay
  recovery, lease fencing, and rollback by verified file restore rather than guessed reverse SQL.

## 6. Approved evidence mapping

| Approved boundary | Evidence and current decision |
|---|---|
| `P18` / `T058` live Tushare | `d8b28b2`: authorized visible-block branch; five capabilities mapped to visible `ERROR`, application remained `DEGRADED` and read-only |
| `BT008` / `BC01` | `eee65fd`: deterministic two-symbol journey, live-state zero-diff, zero provider/notification/WebSocket calls, recovery, retention, pin/unpin, and initial-lot evidence; `BC01` remains Complete |
| AI provider boundary | 106 offline contracts pass; optional live connection is `NOT_RUN_UNAUTHORIZED` |
| Browser/accessibility | 484 unit tests, 6 allowed Chromium E2E tests, and accepted NVDA evidence |
| Backup/restore | 9 fresh tracked tests plus accepted BT050 migration/restore evidence |
| Complete release gate | All approved internal gates pass; only explicit final user acceptance remains |

## 7. Backup, rollback, and operating boundary

The candidate has no migration or schema change. Before any database recovery, use a verified SQLite
online backup, require `PRAGMA integrity_check = ok`, validate schema and source fingerprint, stop the
local process, and restore the complete verified file set. Do not copy a live `.sqlite3` file or
invent reverse SQL.

Rollback is limited to the exact 12 repository candidate files; it does not authorize deletion of
user data or rollback of accepted BT050/T058 commits. The product remains `local-only` on exact
`127.0.0.1`, `reminder-only`, and unable to place orders. Historical fills are simulated research
records, never broker executions. No remote bind, tunnel, high-availability component, automatic
order path, or live AI decision path is accepted.

## 8. Known limitations and open decisions

- `PENDING_FINAL_USER_ACCEPTANCE`: all internal gates pass, but the user has not accepted the release.
- `NOT_RUN_UNAUTHORIZED`: optional AI connectivity was not called; a future call needs a new exact
  authorization and configured target/secret references.
- T058 accepted a visible-block result, not provider readiness; current real Tushare availability is
  not claimed.
- Browser evidence is `Chromium-only`; Firefox/Gecko compatibility is outside the approved profile.
- The existing Starlette `TestClient`/httpx2 deprecation warning remains the only suite warning.
- The five validation-only untracked files remain outside formal inputs and Git.

## 9. C24 release checklist

- [x] Complete offline backend/frontend/replay/browser/security/accessibility/soak/restore gates pass.
- [x] `BC01` remains complete with live-state isolation and bounded-retention evidence.
- [x] Authorized live-contract evidence is bilingual, and optional AI connectivity remains honestly
  `NOT_RUN_UNAUTHORIZED` without weakening deterministic monitoring.
- [ ] The user confirms final acceptance.

<!-- T059-CANONICAL-EVIDENCE-START -->
```json
{
  "aiLive": "NOT_RUN_UNAUTHORIZED",
  "backtestAcceptanceCommit": "eee65fd9ede37cee229c0147ba2ddb55a5f311d5",
  "baseline": "d8b28b20e59b91b261ce46003effdb01288d832a",
  "capacity": {
    "marketDatabaseAndWalBytes": 519028736,
    "maximumReplayElapsedSeconds": 107.31649890000699,
    "minimumReplayElapsedSeconds": 93.17825320002157,
    "resultDatabaseAndWalBytes": 184909824,
    "status": "PASSED",
    "tracedHeapDeltaBytes": 122690533,
    "workingSetDeltaBytes": 88616960
  },
  "chromiumE2E": {
    "passed": 6,
    "status": "PASSED"
  },
  "export": {
    "firstByteMaximumMilliseconds": 4.365700006019324,
    "minimumThroughputMiBPerSecond": 7.435517829658122,
    "requiredMinimumThroughputMiBPerSecond": 5,
    "status": "PASSED"
  },
  "frontendUnit": {
    "passed": 484,
    "status": "PASSED"
  },
  "offlineAI": {
    "passed": 106,
    "status": "PASSED"
  },
  "offlineBackend": {
    "durationSeconds": 2512.36,
    "passed": 1949,
    "skipped": 4,
    "status": "PASSED",
    "warnings": 1
  },
  "releaseDecision": "PENDING_FINAL_USER_ACCEPTANCE",
  "restore": {
    "passed": 9,
    "status": "PASSED"
  },
  "timezone": "Asia/Shanghai",
  "tushareLiveEvidenceCommit": "d8b28b20e59b91b261ce46003effdb01288d832a"
}
```
<!-- T059-CANONICAL-EVIDENCE-END -->
