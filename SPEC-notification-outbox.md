# Spec: notification-outbox (Notification Outbox)

> Canonical agent-facing English version. The human-review Chinese version is `SPEC-notification-outbox.zh-CN.md`; both documents must remain semantically equivalent.

## Objective

Persist and render deterministic textual reminders for actionable decisions, deliver them reliably to the local Web application, optionally dispatch them to console/generic webhook channels, and prevent duplicates across retries and restarts.

The module does not decide whether a trade condition is true. It receives an already validated `SignalIntent` and renders a fixed template from evidence. AI never writes live alert text.

## Tech Stack

- Python 3.14.x (`>=3.14,<3.15`)
- SQLite transactional outbox through `strategy-state`
- Pydantic 2 event payloads
- Jinja-free typed Python renderers to avoid template injection
- `httpx` for an optional generic HTTPS webhook
- FastAPI WebSocket publisher supplied by `local-web`

## Commands

```powershell
python -m pytest tests/unit/test_notification_outbox.py -q
python -m pytest tests/integration/test_notification_delivery.py -q
python -m ruff check src/trade_plan_monitor/notifications tests/unit/test_notification_outbox.py tests/integration/test_notification_delivery.py
```

## Project Structure

```text
src/trade_plan_monitor/notifications/
├── models.py       # Alert/event/channel contracts
├── identity.py     # Stable deduplication keys
├── render.py       # Deterministic Chinese text rendering
├── outbox.py       # Repository/service contract
├── dispatcher.py   # Bounded retry dispatch
└── channels.py     # In-app, console, optional webhook adapters
tests/unit/
└── test_notification_outbox.py
tests/integration/
└── test_notification_delivery.py
```

## Event Contract

```python
class AlertPayload(BaseModel):
    event_id: UUID
    dedup_key: str
    plan_id: str
    plan_version: int
    plan_hash: str
    symbol: str
    name: str
    signal_type: ActionableSignalType
    severity: Literal["INFO", "ACTION", "RISK", "CRITICAL"]
    trading_date: date
    cause_id: str
    evaluated_at: datetime
    market_data_at: datetime | None
    data_age_seconds: int | None
    price_fen: int | None
    quantity: int | None
    bucket: PositionBucket | None
    target_lot_id: str | None
    matched_conditions: tuple[ConditionEvidence, ...]
    satisfied_conditions: tuple[EvaluationEvidence, ...]
    unmet_conditions: tuple[EvaluationEvidence, ...]
    blockers: tuple[EvaluationEvidence, ...]
    zone: DecisionZone
    relevant_zone: AlertPriceZone | None
    risk_line_fen: int | None
    next_step: NextStep

class AlertEvent(AlertPayload):
    sequence: int
    message_text: str
    created_at: datetime
    acknowledged_at: datetime | None
```

The payload is strict, frozen, and copy-revalidated. `BUY_CORE_READY` and
`BUY_TACTICAL_READY` map to `ACTION`; `PRESSURE_REDUCE_READY` and `RISK_BREACH`
map to `RISK`; `RISK_EXIT_READY` and `RISK_EXIT_PENDING_SETTLEMENT` map to
`CRITICAL`. `RISK_BREACH` has no quantity, bucket, or target lot. The other five
actionable signal types preserve the exact quantity/bucket/target-lot shape
already validated by `SignalIntent`.

The deduplication preimage is exactly five pipe-separated fields, with no
surrounding whitespace:

```text
plan_hash|trading_date.isoformat()|signal_type.value|cause_id|quantity_text
```

`quantity_text` is the base-10 integer or the empty string when quantity is
`None`. SHA-256 hashes the UTF-8 bytes of that exact preimage and returns
lowercase hexadecimal. The validated field domains exclude `|`, so the encoding
is unambiguous.

The unique database constraint atomically claims the event. The signal's state transitions, audit entry, and event enqueue use the same transaction.

`AlertOutbox` is session-bound and exposed as `UnitOfWork.alerts`. `enqueue`
locks the shared `MonitorEventLog` before its deduplication read, appends an
`alert.created` event whose UUID and global sequence are also used by the alert
row, stores canonical strict JSON, and flushes without committing. Deleting
retained alert history or monitor-event rows cannot move the sole
`monitor_sequence` high-water mark backwards. A
retry with the same deduplication
identity and otherwise identical semantics returns the original event ID,
sequence, text, and creation time even if the caller generated a replacement
event ID; Decimal scale and signed zero do not create false conflicts, while
other conflicting semantics fail with `ALERT_IDENTITY_CONFLICT`. Reads
revalidate the payload and require its event ID and deduplication key to match
the owning row. `has_dedup_key` validates the lowercase SHA-256 identity and the
complete stored event before reporting it present. T032 uses that query inside
the evaluation write transaction so a later bucket with the same durable signal
cause still commits its evaluation/state but neither reenqueues nor republishes
the original alert; direct conflicting `enqueue` calls remain fail-closed.

## Textual Reminder

Every actionable message includes:

- signal label/severity, stock name, and symbol;
- evaluation time, market-data time, and age;
- current price and suggested quantity where applicable;
- signal-matched conditions plus the complete satisfied, unmet, and blocker
  partitions copied from `EvaluationResult`;
- relevant zone, risk line, plan version, and event ID;
- next step;
- `仅提醒，不会自动下单`.

Example shape:

```text
【低吸底仓买点成立｜ACTION】华亚智能（003043.SZ）
时间：2026-08-07 10:25  行情：2026-08-07 10:25（延迟18秒）
价格：64.20元  建议：低吸底仓100股
区间：低吸区63.00～64.50元（含下界、含上界）
信号成立：价格位于低吸区【成立】（当前价=64.20元）
结果成立：价格位于低吸区【成立】（当前价=64.20元）
结果未成立：无
阻断：无
风险线：60.80元  计划：huaya-smart-v1
下一步：人工确认后自行决定是否下单
原因：episode-001
事件：00000000-0000-0000-0000-000000000001
仅提醒，不会自动下单。
```

Routine `WAIT` state is visible in dashboard snapshots but does not create an alert event unless a health transition is configured as alertable.

Evidence rendering retains composite `ALL`/`ANY` grouping, each node's
three-valued outcome, parent facts, child order, missing-input codes, and every
supplemental `RuleEvidence`. Decimal text is context-independent and normalizes
scale and signed zero, so canonically equivalent decision facts render
identically. `data_age_seconds` is derived from the displayed `market_data_at`,
not from a potentially newer health-summary fact.

## Delivery Semantics

- `IN_APP` is mandatory: committed events are queryable in the alert center and published as sequenced WebSocket updates.
- `CONSOLE` is enabled for local diagnostics and renders the same event ID.
- `WEBHOOK` is implemented as a generic JSON channel but disabled by default. Only HTTPS allowlisted hosts are accepted; redirects are rejected.
- Delivery is at-least-once per channel with idempotent event IDs. Channel status is tracked separately.
- Failures remain pending with bounded retry/backoff. One failed channel does not hide the in-app event.
- Acknowledgement means “the user has seen this event”; it is not delivery success, a fill, or a position update.

For T027, `IN_APP` delivery success means that the dispatcher recovered a
committed outbox row and the alert remains queryable in the local alert center;
it does not claim that a browser received a WebSocket frame. T039 owns actual
WebSocket publication and replay. The dispatcher always adds `IN_APP`, defaults
to `CONSOLE`, skips a disabled `WEBHOOK` without creating an attempt, and orders
due work by event sequence and then `IN_APP`, `CONSOLE`, `WEBHOOK`.

`dispatch_pending(limit=100)` accepts a bound from 1 through 100 and attempts at
most that many due event/channel pairs. It reconstructs only committed events in
a short read transaction, closes that transaction before channel I/O, and saves
the result in a new short transaction. A restart can therefore scan a committed
event that has no delivery attempt. If a process stops after an external send
but before saving the result, the later attempt may send the same stable event
ID again, which is the intentional at-least-once boundary.

Each logical attempt first enters `CLAIMED` in a short transaction with a fixed
60-second lease. Only the successful claimant performs channel I/O; competing
dispatchers skip that event/channel pair. A restart reclaims an expired lease
with the same attempt row and number, so a stop before send does not consume a
retry. A stop after send but before finalization may repeat the same stable event
ID, as required by at-least-once delivery. Final statuses are `DELIVERED`,
`RETRY_PENDING`, or `FAILED`. The first attempt is immediate. The default
persistent retry delays are exactly 30, 60, and 300 seconds, for at most four
logical attempts; an attempt is eligible at its exact `next_retry_at`. Retry
tuples are injectable for tests or later runtime configuration but contain at
most 10 positive delays, each no longer than one day. A terminal delivery or
failure is never selected again.

`WebhookConfig` is strict, frozen, and disabled by default. An enabled endpoint
uses HTTPS, is at most 2,048 characters, contains no embedded credentials,
query, or fragment, and its exact case-insensitive host appears in a unique
allowlist of at most 64 entries; wildcard hosts and redirects are forbidden.
Timeout is 5 seconds by default and bounded from 1 through 30 seconds. The JSON
body contains only `createdAt`, `eventId`, `messageText`, `sequence`, `severity`,
`signalType`, and `symbol`.

Configuration copies revalidate all fields, exact configuration instances are
revalidated again when a channel is constructed, and channel enablement is a
read-only view of the validated frozen configuration. These boundaries prevent
copy/update or post-construction toggles from bypassing HTTPS and the allowlist.

Any 2xx Webhook result is `DELIVERED`. HTTP 408, 429, 5xx, timeouts, and transport
failures are retryable; other 4xx responses and every 3xx redirect are terminal.
The adapter never reads or retains a response body. Public configuration and
storage errors remove validation input, SQL parameters, exception context, and
exception cause; channel results retain only a stable error code and optional
HTTP status. Console, Webhook, or unexpected adapter failure is isolated from
the other channels.

Logical tables:

```text
alert_event(id, sequence UNIQUE, dedup_key UNIQUE, payload_json, message_text, created_at, acknowledged_at)
monitor_event(id, sequence UNIQUE, event_type, schema_version, aggregate_id, payload_json, occurred_at)
monitor_sequence(singleton_id PRIMARY KEY CHECK(singleton_id = 1), last_sequence CHECK(last_sequence >= 0))
delivery_attempt(id, event_id, channel, attempt, status, response_code, next_retry_at, delivered_at, error_code)
```

Historical migration `0004_alert_sequence` first created the alert singleton.
Append-only `0006_monitor_event` replaces it with the only global
`monitor_sequence` and backfills every historical alert as `alert.created` with
the same UUID and sequence. Later non-alert events make alert rows sparse in the
global sequence without changing alert delivery order. Before DDL, its
self-contained frozen v1 validator rechecks the complete historical alert
contract, including closed evidence, partitions and budgets, exact timestamp
arithmetic, next-step semantics, and deterministic rendering. It imports no
evolving application model or renderer; normal outbox reads independently
revalidate the current canonical `AlertEvent`.

Global `monitor_event` WebSocket replay retention is seven days; alert history retention defaults to one year and is configurable.

`replay_after(sequence, limit=1000)` uses an exclusive non-negative sequence
cursor, returns ascending events, and includes an event created exactly at the
configured retention cutoff. `acknowledge(event_id)` records only the first
acknowledgement time and appends one `ALERT_ACKNOWLEDGED` audit in the same
transaction plus one `alert.acknowledged` monitor event with a deterministic
UUID; repeated acknowledgement is idempotent and creates neither duplicate.
Neither operation creates
a delivery attempt or modifies strategy state or position lots. T026 supplies
these alert persistence queries only; channel dispatch is owned by T027. T039
owns the global business-event ledger, replay, and WebSocket wake-up transport.
Every public `MonitorEventLog` database operation maps SQLAlchemy/DBAPI failure
to a sanitized monitor-event error. `AlertOutbox` maps those failures back into
its own stable error domain. Stored-data and acknowledgement-integrity failures
therefore expose neither raw SQL, parameters, payloads, context, nor cause.

T038 exposes the committed alert center through a separately injected application service. Bounded pages may filter by symbol, actionable signal type, acknowledgement state, and a paired inclusive Shanghai-time range; the returned page echoes the exact filters, rejects duplicate event IDs or sequences, and revalidates the complete canonical `AlertEvent`, including dedup identity, relevant zone, next step, deterministic reminder text, and all evidence/display budgets. A buy/reduction alert may supply an identity-matched form prefill, but the alert query and acknowledgement routes never invoke the position service. Every acknowledgement requires idempotency and an expected revision. Unacknowledged and acknowledged rows have revisions `0` and `1`; the first acknowledgement advances `0` to `1`, while an already acknowledged command at revision `1` is a no-op that remains `1`. Acknowledgement still cannot represent a fill. T039 publishes the resulting committed `alert.created` and `alert.acknowledged` types through the shared monitor-event replay stream rather than a parallel alert-only sequence.

## Code Style

```python
def render_alert(event: AlertPayload) -> str:
    lines = [render_heading(event), render_market_time(event)]
    lines.extend(render_evidence(event))
    lines.append("仅提醒，不会自动下单。")
    return "\n".join(lines)
```

Render user/AI-derived text as escaped plain text with length limits. Do not
render arbitrary HTML. The final message is limited to 16,384 characters and is
built under an incremental remaining-character budget. Each evidence partition
has at most 50 top-level items; one payload has at most 250 rendered evidence
nodes, 512 facts, and 256 digits in any displayed numeric coefficient or
integer. Reject control/format/surrogate/line-separator/paragraph-separator
characters (`Cc`, `Cf`, `Cs`, `Zl`, and `Zp`) in interpolated names; only the
renderer-owned newline is allowed in final text.

## Testing Strategy

- Complete golden text tests for every actionable signal and missing optional fields.
- Composite evidence tests preserve three-valued child outcomes, grouping,
  parent facts, and supplemental rule evidence.
- Decimal scale, signed-zero, and ambient-context invariance tests.
- Deduplication tests across duplicate evaluations, retries, restarts, and concurrent enqueue attempts.
- Transaction tests proving state and alert either commit together or both roll back.
- WebSocket sequence/replay tests and seven-day retention boundaries.
- Webhook tests for timeouts, 2xx, 4xx, 5xx, bounded retry, host allowlist, redirect rejection, and secret redaction.
- Acknowledgement tests proving it cannot modify positions.
- XSS/control-character/oversized evidence tests.

## Boundaries

- Always: persist before publish; publish only committed events.
- Always: preserve stable event IDs and sequence ordering.
- Always: separate delivery, acknowledgement, and fill semantics.
- Ask first: add SMS, email, WeChat, DingTalk, Feishu, or browser OS notification channels.
- Never: let a renderer change signal type, quantity, or rule evidence.
- Never: send secrets, raw provider errors, or hidden prompt content.
- Never: use AI to rewrite live alerts.

## Success Criteria

- One actionable event appears once in the Web alert center across retries/restarts.
- A WebSocket disconnect does not lose the event; reconnect/snapshot or replay restores it.
- Text contains the complete evidence contract and disclaimer.
- Console/webhook failure cannot suppress in-app persistence.
- Acknowledging an event cannot alter strategy state or position lots.
- User/AI content is displayed as safe plain text.

## Open Questions

- No external messaging product is selected; the generic webhook remains disabled by default.
