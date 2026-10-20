"""Optional, disposable lookup metadata; canonical result bytes remain unchanged."""

REVIEW_TABLE_SQL = """CREATE TABLE backtest_review_event (
    detail_id TEXT PRIMARY KEY REFERENCES backtest_detail (detail_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    cause_event_id TEXT,
    content_hash TEXT NOT NULL
)
"""

REVIEW_INDEXES = {
    "ix_backtest_review_identity": ("run_id", "event_id"),
    "ix_backtest_review_sequence": ("run_id", "sequence"),
    "ix_backtest_review_cause": ("run_id", "cause_event_id", "sequence"),
}

REVIEW_SCHEMA = REVIEW_TABLE_SQL.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ") + ";\n"
for _name, _columns in REVIEW_INDEXES.items():
    REVIEW_SCHEMA += (
        f"CREATE INDEX IF NOT EXISTS {_name} ON backtest_review_event "
        f"({', '.join(_columns)});\n"
    )


def index_review_event(connection, record, content_hash):
    """Index only a typed, self-verifying loop event already staged by its owner."""
    if record.payload.get("schema_version") not in {
        "monitor-loop-event-v1", "monitor-loop-event-v2",
    }:
        return
    import json

    from trade_plan_monitor.backtest.loop_report import decode_loop_event

    event = decode_loop_event(json.dumps(record.payload))
    if (event.run_id != record.run_id or record.event_at != event.at
            or record.detail_id != f"loop-{event.sequence:06d}-{record.run_id[:16]}"):
        raise ValueError("review event identity mismatch")
    connection.execute(
        "INSERT OR REPLACE INTO backtest_review_event "
        "(detail_id, run_id, event_id, sequence, cause_event_id, content_hash) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (record.detail_id, record.run_id, event.event_id, event.sequence,
         event.cause_event_id, content_hash),
    )
