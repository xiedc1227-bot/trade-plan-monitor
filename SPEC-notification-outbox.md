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
class AlertEvent(BaseModel):
    event_id: UUID
    sequence: int
    dedup_key: str
    plan_id: str
    plan_hash: str
    symbol: str
    name: str
    signal_type: SignalType
    severity: Literal["INFO", "ACTION", "RISK", "CRITICAL"]
    evaluated_at: datetime
    market_data_at: datetime | None
    data_age_seconds: int | None
    price_fen: int | None
    quantity: int
    matched_conditions: list[ConditionEvidence]
    blockers: list[ConditionEvidence]
    risk_line_fen: int | None
    next_step: str
    message_text: str
```

Deduplication key:

```text
sha256(plan_hash | trading_date | signal_type | episode_or_risk_transition_id | quantity)
```

The unique database constraint atomically claims the event. The signal's state transitions, audit entry, and event enqueue use the same transaction.

## Textual Reminder

Every actionable message includes:

- signal label/severity, stock name, and symbol;
- evaluation time, market-data time, and age;
- current price and suggested quantity where applicable;
- matched conditions and blockers;
- relevant zone, risk line, plan version, and event ID;
- next step;
- `仅提醒，不会自动下单`.

Example shape:

```text
【低吸买点成立】华亚智能（003043.SZ）
时间：2026-08-07 10:25  行情：10:25（延迟18秒）
价格：64.20元  建议：低吸100股
成立：位于低吸区；两根5分钟K线未创新低；成交量收缩；MACD负柱改善
风险线：60.80元  计划：huaya-smart-v1
下一步：人工确认后自行决定是否下单
事件：<event-id>
仅提醒，不会自动下单。
```

Routine `WAIT` state is visible in dashboard snapshots but does not create an alert event unless a health transition is configured as alertable.

## Delivery Semantics

- `IN_APP` is mandatory: committed events are queryable in the alert center and published as sequenced WebSocket updates.
- `CONSOLE` is enabled for local diagnostics and renders the same event ID.
- `WEBHOOK` is implemented as a generic JSON channel but disabled by default. Only HTTPS allowlisted hosts are accepted; redirects are rejected.
- Delivery is at-least-once per channel with idempotent event IDs. Channel status is tracked separately.
- Failures remain pending with bounded retry/backoff. One failed channel does not hide the in-app event.
- Acknowledgement means “the user has seen this event”; it is not delivery success, a fill, or a position update.

Logical tables:

```text
alert_event(id, sequence UNIQUE, dedup_key UNIQUE, payload_json, message_text, created_at, acknowledged_at)
delivery_attempt(id, event_id, channel, attempt, status, response_code, next_retry_at, delivered_at, error_code)
```

WebSocket replay retention is seven days; alert history retention defaults to one year and is configurable.

## Code Style

```python
def render_alert(event: AlertPayload) -> str:
    lines = [render_heading(event), render_market_time(event)]
    lines.extend(render_evidence(event))
    lines.append("仅提醒，不会自动下单。")
    return "\n".join(lines)
```

Render user/AI-derived text as escaped plain text with length limits. Do not render arbitrary HTML.

## Testing Strategy

- Golden text tests for every actionable signal and missing optional fields.
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
