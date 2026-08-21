# Capability Map: Local AI-Assisted Trade Plan Monitor

> Canonical agent-facing English version. The human-review Chinese version is `CAPABILITY-MAP.zh-CN.md`; both documents must remain semantically equivalent.

## Product Boundary

- A standalone local Web application for one user, listening only on `127.0.0.1`.
- Enable and monitor at most 10 A-share stocks at the same time.
- Accept pasted natural-language trade plans and use a user-configured AI service to create structured drafts.
- An AI draft must pass deterministic validation and explicit user activation before entering monitoring.
- Provide textual and visual reminders only; do not submit, cancel, or simulate broker orders.
- Use one SQLite WAL database with local online backups; do not build a cluster, primary/replica topology, or high-availability system.

## Capability Modules

| Module ID | Responsibility | Depends on |
|---|---|---|
| `plan-domain` | Versioned plan model, price zones, monitoring conditions, activation policy, validation, and immutable active versions | None |
| `ai-plan-drafting` | AI service configuration, prompt versions, natural-language extraction, evidence, uncertainty, and connectivity tests | `plan-domain` |
| `market-data` | Tushare APIs, trading calendar, daily price limits, 1-minute/5-minute/daily bars, freshness, request control, and indicators | None |
| `strategy-state` | Manual position lots, T+1, low-zone episodes, risk state, plan activation state, market history, and audit records | `plan-domain` |
| `decision-engine` | Pure deterministic evaluation from an active plan, complete market data, indicators, blockers, and strategy state | `plan-domain`, `market-data`, `strategy-state` |
| `notification-outbox` | Signal deduplication, textual alert rendering, acknowledgement, retries, in-app alerts, console, and generic webhook | `decision-engine` |
| `monitor-runtime` | Trading-session scheduling for at most 10 stocks, bounded concurrency, recovery, health, replay, and graceful shutdown | `market-data`, `strategy-state`, `decision-engine`, `notification-outbox` |
| `local-web` | Local REST/WebSocket API and Vue UI for overview, plan/AI review, stock detail, alerts, positions, settings, and health | All modules |

## Build Order

```text
plan-domain ──→ ai-plan-drafting
     │
     └──→ strategy-state ───────────────┐
                                        ▼
market-data ───────────────────→ decision-engine
                                        │
                                        ▼
                              notification-outbox
                                        │
                                        ▼
                                 monitor-runtime
                                        │
                                        ▼
                                    local-web
```

After `plan-domain` is approved, `ai-plan-drafting`, `market-data`, and `strategy-state` can be specified and implemented independently. The live decision path never calls AI.

## AI Trust Boundary

1. The user pastes or edits a natural-language trade plan.
2. AI returns JSON conforming to the published draft schema, together with source evidence, uncertainty, and unmapped text.
3. The backend treats AI output as untrusted input and validates types, numeric ranges, dates, overlapping zones, position limits, and allowlisted conditions.
4. The Web UI shows source text, extracted fields, omissions, warnings, and version differences together.
5. The user edits as needed and explicitly activates one immutable plan version.
6. During market hours, only `decision-engine` reads the active plan and produces decisions.

AI output cannot directly activate a plan, write SQL, execute code, call a broker, or bypass validation. If AI is unavailable, structured forms and YAML/JSON import remain available.

## Textual Alert Contract

A “textual alert” is a complete, readable, traceable message generated when a buy, reduction, or risk event occurs. It is more than a chart color change or sound. The first release stores messages in the Web alert center and displays an in-app notification; console output is diagnostic, and external webhook delivery is disabled by default.

Every actionable alert must include:

- signal type and severity;
- stock name and symbol;
- evaluation time, market-data time, and data delay;
- current price and suggested quantity;
- satisfied conditions and remaining blockers;
- relevant price zone, risk line, plan version, and event ID;
- next-step guidance;
- `Reminder only; no order will be placed automatically.`

The Chinese renderer uses the equivalent disclaimer `仅提醒，不会自动下单`.

## Confirmed Assumptions

1. “Text required” means both natural-language plan input and complete readable textual alerts.
2. The first AI integration uses an OpenAI-compatible HTTP contract. The user can configure service name, base URL, model, timeout, retries, token limit, and secret reference.
3. AI secrets are never written into plans, logs, or ordinary API responses; the UI displays masked status only.
4. Tushare is the only first-release market-data source. Token reference, symbol batching, pacing, capability probes, and limits for 1–10 symbols are configurable.
5. The service listens only on the local loopback interface, so the first release has no login system. Origin/CORS restrictions, CSP, input validation, and secret protection still apply.
6. The user records actual fills manually. Neither an alert nor its acknowledgement represents a fill.

## Documentation Language and Parity

- Unsuffixed documents are canonical English inputs for agents and implementation workflows.
- Matching `.zh-CN.md` documents are Chinese review copies for the user.
- Every user-facing project document created or materially changed must update both language versions in the same change.
- Both versions must preserve the same section structure, stable IDs, numeric thresholds, API paths, JSON fields, commands, boundaries, and acceptance criteria.
- Module IDs, filenames, API paths, JSON fields, code identifiers, commands, and third-party interface names remain unchanged in both versions.
- If the two versions conflict or a counterpart is missing, specification approval and downstream implementation are blocked until parity is restored.

## Review Status

The capability map was approved by the user on 2026-08-18. Module specifications are now at the human review gate. Create `tasks/plan.md` and `tasks/todo.md` only after the specifications are approved; begin application implementation only after the task plan is approved.
