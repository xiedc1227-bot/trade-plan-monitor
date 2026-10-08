"""Single-source preparation persists independently from live/market/job state."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_store import (
    PreparationConflictError,
    PreparationStore,
)

NOW = datetime(2026, 10, 8, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def source(text="Explicit 100 CORE shares at 40.105/share; cash unknown."):
    return PreparationSource(source_id="source-1", text=text)


def create(store, *, key="create-1"):
    return store.create(
        SinglePlanPreparationInput(preparation_id="preparation-1", sources=(source(),)),
        idempotency_key=key,
    )


def test_source_and_creation_receipt_survive_restart(tmp_path):
    path = tmp_path / "preparations.sqlite"
    store = PreparationStore(path, clock=lambda: NOW)
    record = create(store)
    assert record.revision == record.source_revision == 1
    assert record.source.text == source().text
    assert record.source.source_hash == sha256(source().text.encode()).hexdigest()
    assert record.source.authored_at is record.source.available_at is None
    assert record.candidate is record.review is None
    assert record.attempts == ()
    reopened = PreparationStore(path, clock=lambda: NOW)
    assert reopened.get(record.preparation_id) == record
    assert create(reopened) == record
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "SELECT domain, schema_version FROM backtest_preparation_metadata"
        ).fetchone() == ("backtest-preparation-v1", 1)


@pytest.mark.parametrize("count", [0, 2])
def test_preparation_rejects_any_other_source_count(count):
    with pytest.raises(ValidationError):
        SinglePlanPreparationInput(
            preparation_id="preparation-1", sources=tuple(source() for _ in range(count))
        )


@pytest.mark.parametrize("table", ["active_plan", "market_head", "backtest_job", "unknown"])
def test_cross_domain_path_is_rejected_without_file_mutation(tmp_path, table):
    path = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"CREATE TABLE {table} (id TEXT)")
        connection.commit()
    original = path.read_bytes()
    with pytest.raises(ValueError):
        PreparationStore(path)
    assert path.read_bytes() == original


def test_concurrent_creation_retry_has_one_durable_receipt(tmp_path):
    store = PreparationStore(tmp_path / "preparations.sqlite", clock=lambda: NOW)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: create(store), range(6)))
    assert all(record == results[0] for record in results)
    with pytest.raises(PreparationConflictError, match="PREPARATION_EXISTS"):
        create(store, key="different-intent")