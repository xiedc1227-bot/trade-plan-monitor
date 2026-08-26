"""Read-only migration preflight coverage for legacy backtest databases."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.migration import (
    DatabaseState,
    MigrationPreflightError,
    VerifiedBackupFacts,
    authorize_migration,
    inspect_market_database,
    inspect_result_database,
)
from trade_plan_monitor.backtest.results import BacktestResultStore

_FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "backtest"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _seed_legacy_results(path: Path, *, status: str = "COMPLETED") -> None:
    sql = (_FIXTURE_DIRECTORY / "legacy_results_v1.sql").read_text(encoding="utf-8")
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(sql)
        if status != "COMPLETED":
            connection.execute(
                "UPDATE backtest_run SET status = ? WHERE run_id = 'legacy-completed-v1'",
                (status,),
            )
        connection.commit()


def _file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _database_state(path: Path) -> dict[str, object]:
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)) as connection:
        schema = tuple(
            connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_schema ORDER BY type, name"
            )
        )
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    sidecars = {}
    for suffix in ("-wal", "-shm", "-journal"):
        candidate = Path(f"{path}{suffix}")
        if candidate.exists():
            sidecars[suffix] = (candidate.stat().st_size, _file_hash(candidate))
    return {
        "file_hash": _file_hash(path),
        "schema": schema,
        "journal_mode": journal_mode,
        "sidecars": sidecars,
    }


def test_legacy_terminal_rows_fail_before_any_sqlite_mutation(tmp_path: Path) -> None:
    path = tmp_path / "legacy-terminal.sqlite3"
    _seed_legacy_results(path, status="CANCELLED")
    before = _database_state(path)

    with pytest.raises(
        MigrationPreflightError,
        match="LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION",
    ):
        BacktestResultStore(path)

    after = _database_state(path)
    assert after == before


def test_fresh_inventory_precedes_store_initialization(tmp_path: Path) -> None:
    market_path = tmp_path / "fresh-market.sqlite3"
    result_path = tmp_path / "fresh-results.sqlite3"

    market_inventory = inspect_market_database(market_path)
    result_inventory = inspect_result_database(result_path)

    assert market_inventory.database_state == DatabaseState.FRESH
    assert result_inventory.database_state == DatabaseState.FRESH
    assert not market_path.exists()
    assert not result_path.exists()
    assert BacktestMarketStore(market_path).migration_inventory == market_inventory
    assert BacktestResultStore(result_path).migration_inventory == result_inventory


def test_sidecar_blocker_preserves_main_schema_journal_and_sidecar_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sidecar-blocked.sqlite3"
    BacktestMarketStore(path)
    Path(f"{path}-wal").write_bytes(b"uncheckpointed-sidecar-evidence")
    before = _database_state(path)

    with pytest.raises(
        MigrationPreflightError,
        match="SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT",
    ):
        BacktestMarketStore(path)

    assert _database_state(path) == before


def test_legacy_completed_rows_are_inventory_only_without_guessed_inputs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-completed.sqlite3"
    _seed_legacy_results(path)
    before = _database_state(path)

    inventory = inspect_result_database(path)

    assert inventory.database_state == DatabaseState.LEGACY
    assert inventory.terminal_run_count == 0
    assert inventory.compatibility_only_run_ids == ("legacy-completed-v1",)
    assert inventory.migration_reasons == (
        "LEGACY_COMPLETED_RESULTS_COMPATIBILITY_ONLY",
        "LEGACY_SCHEMA",
    )
    assert not hasattr(inventory, "guessed_run_input")
    assert not hasattr(inventory, "guessed_plan_snapshot")
    with pytest.raises(
        MigrationPreflightError,
        match="LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION",
    ):
        BacktestResultStore(path)
    assert _database_state(path) == before


def test_market_inventory_locks_utc_metadata_and_dataset_hash_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "backtest-market.sqlite3"
    BacktestMarketStore(path)
    expected_hashes = (
        "1111111111111111111111111111111111111111111111111111111111111111",
        "2222222222222222222222222222222222222222222222222222222222222222",
        "3333333333333333333333333333333333333333333333333333333333333333",
    )
    with closing(sqlite3.connect(path)) as connection:
        connection.executemany(
            "INSERT INTO market_dataset (dataset_hash, manifest_json, created_at) "
            "VALUES (?, '{}', '2026-08-24T07:20:00.000000+00:00')",
            ((value,) for value in reversed(expected_hashes)),
        )
        connection.commit()
    before = _database_state(path)

    inventory = inspect_market_database(path)

    assert inventory.database_state == DatabaseState.CURRENT
    assert inventory.dataset_hash_goldens == tuple(
        value.encode("ascii") for value in expected_hashes
    )
    dataset_times = next(
        item
        for item in inventory.utc_metadata
        if item.table == "market_dataset" and item.column == "created_at"
    )
    assert dataset_times.value_count == 3
    assert dataset_times.utc_value_count == 3
    assert len(dataset_times.ordered_values_sha256) == 64
    assert inventory.migration_reasons == ("UTC_MARKET_METADATA",)
    assert _database_state(path) == before


def test_migration_decision_is_bound_to_source_and_verified_backup_facts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-completed.sqlite3"
    _seed_legacy_results(path)
    inventory = inspect_result_database(path)
    verified_at = datetime(2026, 8, 26, 15, 30, tzinfo=_SHANGHAI)
    facts = VerifiedBackupFacts(
        source_fingerprint=inventory.source_fingerprint.digest,
        backup_sha256="d" * 64,
        backup_size_bytes=path.stat().st_size,
        verified_at=verified_at,
        coordinator_stopped=True,
    )

    decision = authorize_migration(inventory, facts)

    assert decision.authorized is True
    assert decision.source_fingerprint == inventory.source_fingerprint.digest
    assert decision.verified_backup == facts
    with pytest.raises(
        MigrationPreflightError,
        match="BACKUP_SOURCE_FINGERPRINT_MISMATCH",
    ):
        authorize_migration(
            inventory,
            VerifiedBackupFacts(
                source_fingerprint="e" * 64,
                backup_sha256="d" * 64,
                backup_size_bytes=path.stat().st_size,
                verified_at=verified_at,
                coordinator_stopped=True,
            ),
        )

    terminal_path = tmp_path / "legacy-terminal.sqlite3"
    _seed_legacy_results(terminal_path, status="FAILED")
    terminal = inspect_result_database(terminal_path)
    with pytest.raises(
        MigrationPreflightError,
        match="LEGACY_TERMINAL_RUNS_REQUIRE_MIGRATION",
    ):
        authorize_migration(
            terminal,
            VerifiedBackupFacts(
                source_fingerprint=terminal.source_fingerprint.digest,
                backup_sha256="f" * 64,
                backup_size_bytes=terminal_path.stat().st_size,
                verified_at=verified_at,
                coordinator_stopped=True,
            ),
        )
