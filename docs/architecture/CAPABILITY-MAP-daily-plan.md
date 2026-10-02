# Capability map: daily-plan

Canonical English; `CAPABILITY-MAP-daily-plan.zh-CN.md` is the Chinese review copy. Date:2026-10-02. Status: monitoring and explicit whole-lot simulation are implemented with current offline acceptance. An actual source plan still requires complete parameters, human review and explicit activation.

| Module ID | Responsibility and contract section | Depends on |
|---|---|---|
| `daily-plan-contract` | Unpublished Schema4 finite conditions, whole100-share simulation and compatibility boundaries; D01–D05 of [specification](../specifications/monitoring/SPEC-daily-plan.md). | Existing `plan-domain`, `market-data` |
| `daily-plan-monitor` | Durable confirmation/window, ordinary/severe technical risk, reminders and user-triggered atomic simulated trades; isolated minimal daily simulated position/T+1; D06–D10. | `daily-plan-contract`, existing `strategy-state`, `monitor-runtime`, `notification-outbox` |
| `daily-plan-review` | V7 faithful candidates, source mapping, human review/activation, technical/operational evidence and a separate explicit simulation action; D11–D13. | `daily-plan-contract`, `daily-plan-monitor`, existing `ai-plan-drafting`, `local-web` |

Dependency order is `daily-plan-contract` → `daily-plan-monitor` → `daily-plan-review`; stable module IDs are unchanged. Existing daily records and unit of work host isolated simulation state; trades never write shared real/legacy position tables. The [specification](../specifications/monitoring/SPEC-daily-plan.md) owns interfaces and behavior, [tasks](../../tasks/daily-plan-todo.md) consolidate completion, and [final verification](../verification/2026-10-02-daily-simulation-cleanup.md) records executed acceptance.

Reminders do not mutate holdings; an explicit eligible simulation is one complete100-share-multiple transaction. Broker reports, partial/unknown orders, reservations and client allocations have been removed. Deduplication, T+1, CORE protection, plan maximum holdings, independent risk causes, official-close recovery and QFQ/calendar safeguards remain.

Fundamentals/announcements are reviewed by the user only at plan generation and remain visible non-monitoring background, outside technical conditions and runtime blockers. Tradability/suspension remain operational inputs. New broad-market index logic is deferred; existing index behavior, Schema1/2/3, prompt v1–v6, ta-v1 and shared legacy inventory APIs remain. Obsolete development evidence is explicitly unsupported and never auto-converted into simulated success. The2026-10-01 verification proves only the former scope; the current implementation has no broker submission or automatic trading.
