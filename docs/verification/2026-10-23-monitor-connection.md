# Monitor connection banner verification — 2026-10-23

## Findings and scope

The draft page initially displayed “正在连接监控服务”. An indefinite stall was not reproduced: reloading the unmodified application eventually displayed “传输连接正常”. The confirmed presentation defect was that an open WebSocket remained `CONNECTING` until the first validated heartbeat. The server interval is 20 seconds; the read-only live probe received its first heartbeat after 24.80 seconds and its second after 47.32 seconds.

The original process served valid HTTP responses and heartbeat frames while reporting `STOPPED / BLOCKED / RUNTIME_STOPPED`. The retained evidence does not establish why that older runtime stopped. Restarting the local web service restored `RUNNING / STANDBY / NO_ACTIVE_PLANS`; subsequent checks confirmed that it remained running. A sandboxed process query did not see the process, but an unrestricted read-only check confirmed it was still listening. A duplicate launch failed to bind and shut itself down; it did not replace the running service.

## Change

- On WebSocket open, enter `AWAITING_HEARTBEAT` and show “连接已建立，等待监控状态”. Only a valid heartbeat establishes `LIVE`.
- When transport is live but runtime lifecycle is `STOPPED`, explicitly show “传输连接正常；监控已停止”.
- Treat the new waiting state as unknown in the index overview. Keep the existing 40-second silence timeout, retry behavior, protocol validation and strict runtime validation.
- No backend rules, review/activation requirements, source validation or inventory logic changed.

## Validation

- New component regressions: 2 failed and 2 passed before the fix; all 4 passed after it. They cover waiting versus live, stopped runtime, silent socket timeout and incompatible heartbeat rejection.
- Focused connection/startup/navigation suite: 4 files, 26 tests passed.
- Full frontend suite: 85 files, 1,229 tests passed. `npm run type-check`, `npm run build` and `git diff --check` passed.
- Actual dashboard/health/heartbeat payloads passed existing validators in a temporary diagnostic test; a real component accepted the captured heartbeat without normalization.
- Rebuilt local page: “连接已建立，等待监控状态” transitioned to “传输连接正常”; no warning/error console entries were returned. The final health response reports `RUNNING / STANDBY / NO_ACTIVE_PLANS`.

## Reminder impact and preservation

Draft `3c426adf-09d2-48ca-af3d-177caa4f8f65` remains `DRAFT`, review revision 0, with no review ID or confirmation timestamp. Both page and read-only database verification confirm exactly 1 technical alert, 0 ordinary rules and 0 risk branches. Its alert uses official daily close strictly below 26.59 yuan. It is not enabled and therefore correctly does not perform technical reminder monitoring.

The misleading connection label itself does not change rule evaluation. A genuinely stopped runtime would prevent monitoring of enabled plans; a healthy transport alone is not proof that monitoring is running. This task did not activate a plan to test alert delivery.

Before/after read-only snapshots match for all plan and review history, this draft and its provenance, activation tables, inventory tables, risk/manual event state, the symbol's daily records, storage constraint and configuration hash. All three historical drafts remain. No audit confirmation, activation, inventory initialization or simulated trade was performed.

Evidence is in [the scoped evidence directory](evidence/2026-10-23-monitor-connection/). It contains health responses, protected-state hashes, the final page accessibility snapshot and screenshot; no local database or configuration secrets are included. Unrelated README and prompt-verification changes were left untouched. No commit or push was performed during page verification. A separate commit preparation on 2026-10-24 reran the focused 4-file/26-test suite successfully and checked this change against origin/main; only this fix, its regression test and scoped verification evidence are included.
