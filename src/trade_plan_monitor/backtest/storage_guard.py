"""Fail-closed SQLite domain separation for backtest stores."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

LIVE_MONITOR_TABLES = frozenset(
    {
        "active_plan",
        "alert_event",
        "audit_log",
        "ai_provider_configuration",
        "daily_bar",
        "daily_price_limit",
        "delivery_attempt",
        "evaluation_ledger",
        "five_minute_bar",
        "latest_quote",
        "minute_bar",
        "monitor_event",
        "monitor_sequence",
        "plan_source",
        "plan_version",
        "position_lot",
        "provider_health",
        "request_idempotency",
        "risk_state",
        "symbol_health",
        "trading_calendar",
        "zone_episode",
    }
)


def reject_incompatible_database(
    path: Path,
    *,
    store_name: str,
    forbidden_prefixes: tuple[str, ...],
) -> None:
    """Reject an existing SQLite file owned by another storage domain."""

    if not path.exists() or path.stat().st_size == 0:
        return
    try:
        with closing(
            sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)
        ) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type = 'table'"
                ).fetchall()
            }
    except sqlite3.Error as error:
        raise ValueError(f"{store_name} database_path must be a readable SQLite file") from error
    conflicting = sorted(
        table
        for table in tables
        if table in LIVE_MONITOR_TABLES
        or any(table.startswith(prefix) for prefix in forbidden_prefixes)
    )
    if conflicting:
        raise ValueError(
            f"{store_name} database_path belongs to another storage domain: {conflicting[0]}"
        )


__all__ = ["LIVE_MONITOR_TABLES", "reject_incompatible_database"]
