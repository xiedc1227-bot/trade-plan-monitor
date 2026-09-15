# R18 same-morning restart proposal — authorized

Canonical English; `R18-restart-proposal-20260915.zh-CN.md` is the equivalent Chinese review copy. Proposal ID `R18-20260915-RESTART-105`; run ID `r18-20260915-b`. Status **AUTHORIZED / NOT_RUN**.

At 2026-09-15 09:36 Asia/Shanghai, after candidate `r18-20260915-a` made zero external calls because its exact time gate had closed, the user explicitly requested that R18 be restarted. This is treated as fresh authorization for one replacement candidate with the same accepted physical limits and possible charges: at most three `deepseek-v4-pro` POST starts, at most 105 market-data starts, and a 2,280-second call deadline with 20 seconds of cooperative cleanup.

Admission is limited to **09:40:00–09:45:00 inclusive** on 2026-09-15. The latest start stops new calls by 10:23, within the morning continuous auction. All isolation, input hashes, endpoint restrictions, zero-retry rules, thresholds, human review requirements, failure stops and evidence rules in `R18-execution-proposal.md` remain unchanged. Candidate `a` and its NOT_RUN record remain immutable; no claim or authorization is reused. A missed gate or failed prerequisite ends candidate `b` without another restart.
