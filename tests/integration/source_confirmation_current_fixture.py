"""Recorded-byte pins and explicitly synthetic current-review prerequisites."""

import sqlite3
from contextlib import closing, contextmanager
from datetime import date
from hashlib import sha256
from pathlib import Path

from tests.integration.test_source_coverage_preparation_commit import _initial_loop_case

from trade_plan_monitor.backtest.preparation_models import PreparationSource

FIXTURES = Path(__file__).parents[1] / "fixtures"
DATES = ("2026-09-24", "2026-09-28", "2026-09-30", "2026-10-09")
SOURCE_HASHES = {
    "01-20260924-104506.txt": "3d9199a69ddc65044b3f23c5bc35d4bb7a07978d79f28ef14bfdedc590e48fad",
    "02-20260928-092555.txt": "51182b5535e0b743e765eeed0a4f21d98aa6291633df1f7f278ffcc3efdc55d6",
    "03-20260930-095728.txt": "ed0addcd166735798111a6a22e9951270a2e4a8b1fc4448d0f49443baf8eb6bc",
    "04-20261009-091956.txt": "e71ab6dbfda744c92358b14ffd1ef8c09b2af13d6a12f6bc2d0e3255ea4f7d2b",
}
RESPONSE_HASHES = {
    ("", 1): "9cd9ea8aacf045c7e778d335e0feef382b6c6d0f93bb82ee7d25a3ce9be3439b",
    ("", 2): "a035583bd515e116d063142e2bc64797ade4f68b155a2a0f7ae9ad58ab270d9d",
    ("", 3): "28eb6cc6ff86fece9993be7493906ac50c165977485e2f472f10ee27e50e0213",
    ("", 4): "f1d5e0bc37e0dcc91af9809a720ff41ffdc54093ae04633ea67afbd3973b8ec2",
    ("live-check-", 1): "87fb25f43c6ba50a2fff65f387d903ac9dbb0f3242921992ab4cbd8e254e326b",
    ("live-check-", 2): "b5f634b54ed306c6276d34cbf6898b00a5ba3e4480e1459762569ef0a5273bf9",
    ("live-check-", 3): "1a14ff3a62006ac644b2277a9f27a737ac555e97014af3350ad44778bd537167",
    ("live-check-", 4): "13b179a6c7107ed7d2c3314cd582babc3ff0310ccc0933c5be036979b3e4bf9d",
}


def recorded_case(number, round_name):
    """Read original bytes unchanged; these are not current-complete candidates."""
    original = sorted((FIXTURES / "shengxin_sources").glob("*.txt"))[number - 1]
    response = FIXTURES / f"ai/shengxin-source-resolution-{round_name}{number:02d}.json"
    assert sha256(original.read_bytes()).hexdigest() == SOURCE_HASHES[original.name]
    assert sha256(response.read_bytes()).hexdigest() == RESPONSE_HASHES[round_name, number]
    source = PreparationSource(
        source_id=original.stem,
        text=original.read_text("utf-8-sig"),
        effective_trade_date=date.fromisoformat(DATES[number - 1]),
    )
    return source, response.read_text("utf-8")


def synthetic_current_case(identity):
    """Reuse the admitted full-loop engineering fixture, never a real-AI outcome."""
    source, _, result, _ = _initial_loop_case(identity)
    assert result.model == "synthetic-no-provider-call"
    assert result.coverage.coverage_complete
    assert result.normalization_trace.changes == ()
    return source, result


@contextmanager
def read_only_preparation(store):
    with closing(
        sqlite3.connect(store.database_path.resolve().as_uri() + "?mode=ro", uri=True)
    ) as connection:
        yield connection
        assert connection.total_changes == 0


def preparation_checkpoint(store):
    """Snapshot real record, INPUT, REVIEW and idempotency rows without a write."""
    with read_only_preparation(store) as connection:
        tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        )
        return tuple(
            (
                table,
                connection.execute(
                    'SELECT * FROM "' + table.replace('"', '""') + '" ORDER BY rowid',
                ).fetchall(),
            )
            for table in tables
        )
