"""Read-only migration preflight coverage for legacy backtest databases."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import trade_plan_monitor.backtest.migration as migration_module
from trade_plan_monitor.backtest.dataset import DatasetScope
from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
from trade_plan_monitor.backtest.market_store import BacktestMarketStore
from trade_plan_monitor.backtest.migration import (
    DatabaseState,
    MigrationPreflightError,
    VerifiedBackupFacts,
    authorize_migration,
    inspect_market_database,
    inspect_result_database,
    migrate_result_database,
)
from trade_plan_monitor.backtest.results import BacktestResultStore
from trade_plan_monitor.market_data.historical_provider import (
    HistoricalMinuteBatch,
    HistoricalMinuteProfile,
    HistoricalOpeningSpecial,
)
from trade_plan_monitor.market_data.models import DailyBar, DailyLimit, MinuteBar, TradingDay
from trade_plan_monitor.market_data.sessions import expected_minute_ends

_FIXTURE_DIRECTORY = Path(__file__).parents[1] / "fixtures" / "backtest"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SYMBOL = "600000.SH"
_TRADE_DATE = date(2026, 8, 24)
_PROFILE = HistoricalMinuteProfile.TUSHARE_STK_MINS_241_END_V1


def _seed_frozen_market_dataset(store: BacktestMarketStore) -> tuple[DatasetScope, str]:
    bars = tuple(
        MinuteBar(
            symbol=_SYMBOL,
            bar_end=bar_end,
            open_fen=1_000,
            high_fen=1_001,
            low_fen=999,
            close_fen=1_000,
            volume_shares=1_000 + index,
            amount_yuan=Decimal(10_000 + index),
            received_at=bar_end + timedelta(seconds=12),
        )
        for index, bar_end in enumerate(expected_minute_ends(_TRADE_DATE, is_open=True))
    )
    store.record_minute_batch(
        HistoricalMinuteBatch(
            symbol=_SYMBOL,
            trade_date=_TRADE_DATE,
            contract_version=_PROFILE,
            bars=bars,
            opening_special=HistoricalOpeningSpecial(
                symbol=_SYMBOL,
                source_time=datetime.combine(_TRADE_DATE, time(9, 30), _SHANGHAI),
                open_fen=1_000,
                high_fen=1_001,
                low_fen=999,
                close_fen=1_000,
                volume_shares=500,
                amount_yuan=Decimal("5000"),
            ),
        )
    )
    store.record_trading_days(
        (
            TradingDay(
                exchange="SSE",
                cal_date=_TRADE_DATE,
                is_open=True,
                previous_trade_date=date(2026, 8, 21),
            ),
        )
    )
    store.record_daily_limits(
        (
            DailyLimit(
                symbol=_SYMBOL,
                trade_date=_TRADE_DATE,
                up_limit_fen=1_100,
                down_limit_fen=900,
                received_at=datetime.combine(_TRADE_DATE, time(9, 30), _SHANGHAI),
            ),
        )
    )
    store.record_daily_bars(
        (
            DailyBar(
                symbol=_SYMBOL,
                trade_date=_TRADE_DATE,
                open_fen=1_000,
                high_fen=1_050,
                low_fen=950,
                close_fen=1_020,
                volume_shares=2_000_000,
                amount_yuan=Decimal("20000000"),
                is_official=True,
                received_at=datetime.combine(_TRADE_DATE, time(15, 20), _SHANGHAI),
            ),
        )
    )
    scope = DatasetScope(
        symbols=(_SYMBOL,),
        start=_TRADE_DATE,
        end=_TRADE_DATE,
        warmup_start=_TRADE_DATE,
        historical_profile=_PROFILE,
    )
    frozen = store.freeze_dataset(scope)
    assert frozen.dataset_hash is not None
    return scope, frozen.dataset_hash


def _market_identity_snapshot(path: Path) -> tuple[tuple[object, ...], ...]:
    queries = (
        "SELECT artifact_hash, kind, provider, contract_version, natural_key, content_json "
        "FROM market_artifact ORDER BY artifact_hash",
        "SELECT natural_key, artifact_hash, revision, kind, symbol, trade_date "
        "FROM market_head ORDER BY natural_key",
        "SELECT artifact_hash, symbol, bar_end, content_json "
        "FROM market_minute_artifact ORDER BY artifact_hash",
        "SELECT symbol, bar_end, artifact_hash, revision "
        "FROM market_minute_head ORDER BY symbol, bar_end",
        "SELECT dataset_hash, manifest_json FROM market_dataset ORDER BY dataset_hash",
        "SELECT dataset_hash, natural_key, artifact_hash, kind, symbol, trade_date "
        "FROM market_dataset_item ORDER BY dataset_hash, natural_key",
    )
    with closing(sqlite3.connect(path)) as connection:
        return tuple(tuple(connection.execute(query)) for query in queries)


def _remove_market_index_extension(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            DROP TABLE market_dataset_index_item;
            DROP TABLE market_index_head;
            DROP TABLE market_index_artifact;
            """
        )
        connection.commit()


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


def _seed_partial_market_schema(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE market_artifact (artifact_hash TEXT PRIMARY KEY);
            CREATE TABLE market_head (natural_key TEXT PRIMARY KEY);
            CREATE TABLE market_minute_artifact (artifact_hash TEXT PRIMARY KEY);
            CREATE TABLE market_minute_head (
                symbol TEXT,
                bar_end TEXT,
                PRIMARY KEY (symbol, bar_end)
            );
            CREATE TABLE market_dataset (dataset_hash TEXT PRIMARY KEY);
            CREATE TABLE market_dataset_item (
                dataset_hash TEXT,
                natural_key TEXT,
                PRIMARY KEY (dataset_hash, natural_key)
            );
            """
        )
        connection.commit()


def _seed_partial_result_schema(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE backtest_run (
                run_id TEXT PRIMARY KEY,
                plan_sha256 TEXT,
                dataset_hash TEXT,
                status TEXT,
                completed_at TEXT,
                pinned INTEGER,
                materialized INTEGER,
                publication_fill_count INTEGER,
                publication_detail_count INTEGER,
                publication_fill_set_hash TEXT,
                publication_detail_set_hash TEXT,
                summary_hash TEXT,
                summary_json TEXT,
                created_at TEXT
            );
            CREATE TABLE backtest_fill (dummy TEXT PRIMARY KEY);
            CREATE TABLE backtest_detail (dummy TEXT PRIMARY KEY);
            """
        )
        connection.commit()


def _seed_structurally_complete_result_schema(
    path: Path,
    *,
    run_id_declaration: str = "TEXT PRIMARY KEY",
    plan_sha256_declaration: str = "TEXT NOT NULL",
    status_declaration: str = "TEXT NOT NULL",
    pinned_declaration: str = "INTEGER NOT NULL DEFAULT 0",
    extra_run_column: str = "",
    extra_schema_sql: str = "",
    include_contract_constraints: bool = False,
    constraints_as_comments: bool = False,
    include_foreign_keys: bool = False,
    deferred_foreign_keys: bool = False,
) -> None:
    check_clauses = {
        "status": "CHECK (status IN ('COMPLETED', 'FAILED', 'CANCELLED'))",
        "pinned": "CHECK (pinned IN (0, 1))",
        "materialized": "CHECK (materialized IN (0, 1))",
        "fill_count": ("CHECK (publication_fill_count IS NULL OR publication_fill_count >= 0)"),
        "detail_count": (
            "CHECK (publication_detail_count IS NULL OR publication_detail_count >= 0)"
        ),
        "kind": (
            "CHECK (kind IN ('DECISION', 'SIGNAL', 'EXECUTION_OUTCOME', "
            "'DAILY_EQUITY', 'DIAGNOSTIC', 'DEBUG_TRACE'))"
        ),
    }
    if constraints_as_comments:
        check_clauses = {name: f"/* {clause} */" for name, clause in check_clauses.items()}
    elif not include_contract_constraints:
        check_clauses = dict.fromkeys(check_clauses, "")
    check_clauses = {name: f" {clause}" if clause else "" for name, clause in check_clauses.items()}
    foreign_key_suffix = ""
    if include_foreign_keys:
        foreign_key_suffix = " REFERENCES backtest_run (run_id) ON DELETE RESTRICT"
        if deferred_foreign_keys:
            foreign_key_suffix += " DEFERRABLE INITIALLY DEFERRED"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            f"""
            CREATE TABLE backtest_run (
                run_id {run_id_declaration},
                plan_sha256 {plan_sha256_declaration},
                dataset_hash TEXT NOT NULL,
                status {status_declaration}{check_clauses["status"]},
                completed_at TEXT NOT NULL,
                pinned {pinned_declaration}{check_clauses["pinned"]},
                materialized INTEGER NOT NULL DEFAULT 1{check_clauses["materialized"]},
                publication_fill_count INTEGER{check_clauses["fill_count"]},
                publication_detail_count INTEGER{check_clauses["detail_count"]},
                publication_fill_set_hash TEXT,
                publication_detail_set_hash TEXT,
                summary_hash TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                created_at TEXT NOT NULL
                {extra_run_column}
            );
            CREATE TABLE backtest_fill (
                fill_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL{foreign_key_suffix},
                filled_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE backtest_detail (
                detail_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL{foreign_key_suffix},
                kind TEXT NOT NULL{check_clauses["kind"]},
                event_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            {extra_schema_sql}
            """
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


def _legacy_result_content(path: Path) -> tuple[tuple[object, ...], ...]:
    with closing(sqlite3.connect(path)) as connection:
        return tuple(
            tuple(connection.execute(query))
            for query in (
                "SELECT run_id, plan_sha256, dataset_hash, status, completed_at, pinned, "
                "summary_hash, summary_json, created_at FROM backtest_run ORDER BY run_id",
                "SELECT fill_id, run_id, filled_at, content_hash, payload_json, created_at "
                "FROM backtest_fill ORDER BY fill_id",
                "SELECT detail_id, run_id, kind, event_at, content_hash, payload_json, "
                "created_at FROM backtest_detail ORDER BY detail_id",
            )
        )


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


def test_partial_market_schema_fails_before_any_sqlite_mutation(tmp_path: Path) -> None:
    path = tmp_path / "partial-market.sqlite3"
    _seed_partial_market_schema(path)
    before = _database_state(path)

    error: Exception | None = None
    try:
        BacktestMarketStore(path)
    except Exception as caught:  # noqa: BLE001 - preserve state after the failed boundary
        error = caught

    assert _database_state(path) == before
    assert isinstance(error, MigrationPreflightError)
    assert error.code == "LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION"


def test_exact_pre_index_market_schema_expands_without_rewriting_v1_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pre-index-market.sqlite3"
    store = BacktestMarketStore(path)
    _, dataset_hash = _seed_frozen_market_dataset(store)
    before = _market_identity_snapshot(path)
    _remove_market_index_extension(path)

    inventory = inspect_market_database(path)
    assert inventory.database_state is DatabaseState.CURRENT
    assert inventory.migration_reasons == ("MISSING_MARKET_INDEX_SCHEMA",)
    assert inventory.requires_schema_migration is False

    reopened = BacktestMarketStore(path)

    assert _market_identity_snapshot(path) == before
    assert reopened.dataset_manifest(dataset_hash).dataset_hash == dataset_hash
    assert reopened.migration_inventory.migration_reasons == ()
    migrated = inspect_market_database(path)
    assert migrated.database_state is DatabaseState.CURRENT
    assert migrated.migration_reasons == ()
    with closing(sqlite3.connect(path)) as connection:
        for table in (
            "market_index_artifact",
            "market_index_head",
            "market_dataset_index_item",
        ):
            assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone() == (0,)


def test_partial_market_index_extension_still_fails_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "partial-index-extension.sqlite3"
    BacktestMarketStore(path)
    _remove_market_index_extension(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE market_index_artifact (
                artifact_hash TEXT PRIMARY KEY,
                natural_key TEXT NOT NULL,
                index_code TEXT NOT NULL,
                interval TEXT NOT NULL CHECK (interval IN ('FIVE_MINUTE', 'OFFICIAL_DAILY')),
                bar_at TEXT NOT NULL,
                provider_revision INTEGER NOT NULL CHECK (provider_revision >= 1),
                content_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
    before = _database_state(path)

    with pytest.raises(
        MigrationPreflightError,
        match="LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION",
    ):
        BacktestMarketStore(path)

    assert _database_state(path) == before


def test_partial_result_schema_fails_before_any_sqlite_mutation(tmp_path: Path) -> None:
    path = tmp_path / "partial-results.sqlite3"
    _seed_partial_result_schema(path)
    before = _database_state(path)

    error: Exception | None = None
    try:
        BacktestResultStore(path)
    except Exception as caught:  # noqa: BLE001 - preserve state after the failed boundary
        error = caught

    assert _database_state(path) == before
    assert isinstance(error, MigrationPreflightError)
    assert error.code == "LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION"


def test_unknown_sqlite_schema_is_not_claimed_by_a_backtest_store(tmp_path: Path) -> None:
    path = tmp_path / "unknown.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE unrelated_state (identity TEXT PRIMARY KEY)")
        connection.commit()
    before = _database_state(path)

    error: Exception | None = None
    try:
        BacktestMarketStore(path)
    except Exception as caught:  # noqa: BLE001 - preserve state after the failed boundary
        error = caught

    assert _database_state(path) == before
    assert isinstance(error, MigrationPreflightError)
    assert error.code == "LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION"


@pytest.mark.parametrize(
    (
        "run_id_declaration",
        "plan_sha256_declaration",
        "pinned_declaration",
        "extra_run_column",
    ),
    (
        ("TEXT PRIMARY KEY", "TEXT NOT NULL", "INTEGER NOT NULL DEFAULT 0", ""),
        ("INTEGER PRIMARY KEY", "TEXT NOT NULL", "INTEGER NOT NULL DEFAULT 0", ""),
        (
            "TEXT PRIMARY KEY COLLATE NOCASE",
            "TEXT NOT NULL",
            "INTEGER NOT NULL DEFAULT 0",
            "",
        ),
        ("TEXT PRIMARY KEY", "TEXT NOT NULL", "INTEGER NOT NULL DEFAULT 2", ""),
        (
            "TEXT PRIMARY KEY",
            "TEXT NOT NULL",
            "INTEGER NOT NULL DEFAULT 0",
            ", must_supply TEXT NOT NULL",
        ),
        ("TEXT PRIMARY KEY", "TEXT NOT NULL UNIQUE", "INTEGER NOT NULL DEFAULT 0", ""),
    ),
)
def test_incompatible_writable_result_schema_fails_before_any_sqlite_mutation(
    tmp_path: Path,
    run_id_declaration: str,
    plan_sha256_declaration: str,
    pinned_declaration: str,
    extra_run_column: str,
) -> None:
    path = tmp_path / "incompatible-writable-results.sqlite3"
    _seed_structurally_complete_result_schema(
        path,
        run_id_declaration=run_id_declaration,
        plan_sha256_declaration=plan_sha256_declaration,
        pinned_declaration=pinned_declaration,
        extra_run_column=extra_run_column,
    )
    before = _database_state(path)

    error: Exception | None = None
    try:
        BacktestResultStore(path)
    except Exception as caught:  # noqa: BLE001 - preserve state after the failed boundary
        error = caught

    assert _database_state(path) == before
    assert isinstance(error, MigrationPreflightError)
    assert error.code == "LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION"


def test_schema_object_name_collision_fails_before_any_sqlite_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "colliding-schema-object.sqlite3"
    _seed_structurally_complete_result_schema(
        path,
        extra_schema_sql="CREATE TABLE ix_backtest_run_retention (dummy TEXT);",
    )
    before = _database_state(path)

    error: Exception | None = None
    try:
        BacktestResultStore(path)
    except Exception as caught:  # noqa: BLE001 - preserve state after the failed boundary
        error = caught

    assert _database_state(path) == before
    assert isinstance(error, MigrationPreflightError)
    assert error.code == "LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION"


@pytest.mark.parametrize(
    ("schema_variant", "schema_options"),
    (
        (
            "commented-checks",
            {"constraints_as_comments": True, "include_foreign_keys": True},
        ),
        (
            "missing-index-nocase",
            {
                "status_declaration": "TEXT NOT NULL COLLATE NOCASE",
                "include_contract_constraints": True,
                "include_foreign_keys": True,
            },
        ),
        (
            "replace-primary-key",
            {
                "run_id_declaration": "TEXT PRIMARY KEY ON CONFLICT REPLACE",
                "include_contract_constraints": True,
                "include_foreign_keys": True,
            },
        ),
        (
            "descending-primary-key",
            {
                "run_id_declaration": "TEXT PRIMARY KEY DESC",
                "include_contract_constraints": True,
                "include_foreign_keys": True,
            },
        ),
        (
            "deferred-foreign-key",
            {
                "include_contract_constraints": True,
                "include_foreign_keys": True,
                "deferred_foreign_keys": True,
            },
        ),
    ),
)
def test_deceptive_result_schema_fails_before_any_sqlite_mutation(
    tmp_path: Path,
    schema_variant: str,
    schema_options: dict[str, object],
) -> None:
    path = tmp_path / f"{schema_variant}.sqlite3"
    _seed_structurally_complete_result_schema(path, **schema_options)
    before = _database_state(path)

    error: Exception | None = None
    try:
        BacktestResultStore(path)
    except Exception as caught:  # noqa: BLE001 - preserve state after the failed boundary
        error = caught

    assert _database_state(path) == before
    assert isinstance(error, MigrationPreflightError)
    assert error.code == "LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION"


def test_generated_column_fails_before_any_sqlite_mutation(tmp_path: Path) -> None:
    path = tmp_path / "generated-column.sqlite3"
    BacktestResultStore(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "ALTER TABLE backtest_run ADD COLUMN derived_status TEXT "
            "GENERATED ALWAYS AS (json_extract(summary_json, '$.status')) STORED"
        )
        connection.commit()
    before = _database_state(path)

    error: Exception | None = None
    try:
        BacktestResultStore(path)
    except Exception as caught:  # noqa: BLE001 - preserve state after the failed boundary
        error = caught

    assert _database_state(path) == before
    assert isinstance(error, MigrationPreflightError)
    assert error.code == "LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION"


def test_partial_replacement_index_fails_before_any_sqlite_mutation(tmp_path: Path) -> None:
    path = tmp_path / "partial-index.sqlite3"
    BacktestResultStore(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            DROP INDEX ix_backtest_run_retention;
            CREATE INDEX ix_backtest_run_retention
                ON backtest_run (status, pinned, completed_at DESC, run_id DESC)
                WHERE status = 'COMPLETED';
            """
        )
        connection.commit()
    before = _database_state(path)

    error: Exception | None = None
    try:
        BacktestResultStore(path)
    except Exception as caught:  # noqa: BLE001 - preserve state after the failed boundary
        error = caught

    assert _database_state(path) == before
    assert isinstance(error, MigrationPreflightError)
    assert error.code == "LEGACY_SCHEMA_REQUIRES_VERIFIED_MIGRATION"


def test_wal_domain_conflict_fails_without_reopening_or_mutating_source(tmp_path: Path) -> None:
    path = tmp_path / "market-domain.sqlite3"
    BacktestMarketStore(path)
    before = _database_state(path)

    with pytest.raises(ValueError, match="another storage domain"):
        BacktestResultStore(path)

    assert _database_state(path) == before


def test_unknown_schema_cannot_receive_migration_authorization(tmp_path: Path) -> None:
    path = tmp_path / "unknown-authorization.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE unrelated_state (identity TEXT PRIMARY KEY)")
        connection.commit()
    inventory = inspect_result_database(path)

    assert inventory.database_state == DatabaseState.UNKNOWN
    with pytest.raises(
        MigrationPreflightError,
        match="UNRECOGNIZED_SCHEMA_CANNOT_BE_MIGRATED",
    ):
        authorize_migration(
            inventory,
            VerifiedBackupFacts(
                source_fingerprint=inventory.source_fingerprint.digest,
                backup_sha256="a" * 64,
                backup_size_bytes=path.stat().st_size,
                verified_at=datetime(2026, 8, 26, 18, 0, tzinfo=_SHANGHAI),
                coordinator_stopped=True,
            ),
        )


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


@pytest.mark.parametrize("store_factory", [BacktestMarketStore, BacktestJobRepository])
def test_current_store_reopens_after_empty_wal_and_shm_are_left_behind(
    tmp_path: Path,
    store_factory,
) -> None:
    path = tmp_path / "empty-wal.sqlite3"
    store = store_factory(path)
    if store_factory is BacktestMarketStore:
        _seed_frozen_market_dataset(store)
    before = _database_state(path)
    Path(f"{path}-wal").write_bytes(b"")
    Path(f"{path}-shm").write_bytes(bytes(32_768))

    store_factory(path)

    assert _database_state(path) == before
    assert not Path(f"{path}-wal").exists()
    assert not Path(f"{path}-shm").exists()


def test_result_store_reopens_after_empty_wal_is_left_behind(tmp_path: Path) -> None:
    path = tmp_path / "result-empty-wal.sqlite3"
    BacktestJobRepository(path)
    before = _database_state(path)
    Path(f"{path}-wal").write_bytes(b"")

    BacktestResultStore(path)

    assert _database_state(path) == before


def test_empty_wal_does_not_relax_read_only_migration_inventory(tmp_path: Path) -> None:
    path = tmp_path / "inventory-empty-wal.sqlite3"
    BacktestMarketStore(path)
    Path(f"{path}-wal").write_bytes(b"")
    before = _database_state(path)

    with pytest.raises(MigrationPreflightError, match="SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT"):
        inspect_market_database(path)

    assert _database_state(path) == before


@pytest.mark.parametrize("seed", [_seed_partial_market_schema, _seed_legacy_results])
def test_empty_wal_on_legacy_store_is_preserved_without_recovery(tmp_path: Path, seed) -> None:
    path = tmp_path / "legacy-empty-wal.sqlite3"
    seed(path)
    Path(f"{path}-wal").write_bytes(b"")
    before = _database_state(path)
    factory = BacktestMarketStore if seed is _seed_partial_market_schema else BacktestResultStore

    with pytest.raises(MigrationPreflightError, match="SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT"):
        factory(path)

    assert _database_state(path) == before


@pytest.mark.parametrize("begin", ["BEGIN", "BEGIN IMMEDIATE"])
def test_empty_wal_recovery_refuses_a_database_with_another_connection(
    tmp_path: Path,
    begin: str,
) -> None:
    path = tmp_path / "busy-empty-wal.sqlite3"
    BacktestMarketStore(path)
    before = _database_state(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(begin)
        connection.execute("SELECT COUNT(*) FROM market_artifact").fetchone()
        assert Path(f"{path}-wal").stat().st_size == 0

        with pytest.raises(
            MigrationPreflightError,
            match="SQLITE_(EMPTY_WAL_RECOVERY_BUSY|SIDECARS_REQUIRE_STOPPED_CHECKPOINT|"
            "SOURCE_BUSY_OR_UNREADABLE)",
        ):
            BacktestMarketStore(path, busy_timeout_ms=50)

        assert Path(f"{path}-wal").exists()
        assert Path(f"{path}-shm").exists()

    assert _database_state(path) == before


@pytest.mark.parametrize("extra_sidecar", ["-journal", "-shm"])
def test_empty_wal_recovery_preserves_unsafe_sidecar_combinations(
    tmp_path: Path,
    extra_sidecar: str,
) -> None:
    path = tmp_path / "unsafe-sidecars.sqlite3"
    BacktestMarketStore(path)
    if extra_sidecar == "-journal":
        Path(f"{path}-wal").write_bytes(b"")
    Path(f"{path}{extra_sidecar}").write_bytes(b"preserve-this-evidence")
    before = _database_state(path)

    with pytest.raises(MigrationPreflightError, match="SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT"):
        BacktestMarketStore(path)

    assert _database_state(path) == before


@pytest.mark.parametrize("kind", ["unknown", "pending_extension", "utc_metadata"])
def test_empty_wal_recovery_preserves_sources_needing_maintenance(
    tmp_path: Path,
    kind: str,
) -> None:
    path = tmp_path / "maintenance-empty-wal.sqlite3"
    if kind == "unknown":
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
    elif kind == "pending_extension":
        BacktestResultStore(path)
    else:
        BacktestMarketStore(path)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "INSERT INTO market_dataset (dataset_hash, manifest_json, created_at) "
                "VALUES (?, '{}', '2026-08-24T07:20:00.000000+00:00')",
                ("1" * 64,),
            )
            connection.commit()
    Path(f"{path}-wal").write_bytes(b"")
    before = _database_state(path)
    factory = BacktestResultStore if kind == "pending_extension" else BacktestMarketStore

    with pytest.raises(MigrationPreflightError, match="SQLITE_SIDECARS_REQUIRE_STOPPED_CHECKPOINT"):
        factory(path)

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


def test_completed_only_result_migration_preserves_legacy_v1_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-completed-v1.sqlite3"
    _seed_legacy_results(path)
    before = _legacy_result_content(path)
    inventory = inspect_result_database(path)
    decision = authorize_migration(
        inventory,
        VerifiedBackupFacts(
            source_fingerprint=inventory.source_fingerprint.digest,
            backup_sha256="a" * 64,
            backup_size_bytes=path.stat().st_size,
            verified_at=datetime(2026, 8, 27, 18, 0, tzinfo=_SHANGHAI),
            coordinator_stopped=True,
        ),
    )

    migrated = migrate_result_database(inventory, decision)

    assert migrated.database_state is DatabaseState.CURRENT
    assert migrated.compatibility_only_run_ids == ("legacy-completed-v1",)
    assert _legacy_result_content(path) == before
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT summary_domain FROM backtest_run").fetchone() == (
            "backtest-run-summary-v1",
        )
        with pytest.raises(sqlite3.IntegrityError, match="COMPLETED_ONLY"):
            connection.execute("UPDATE backtest_run SET status = 'FAILED'")


def test_bt016_completed_only_schema_adds_revision_fence_without_row_changes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bt016-completed-only.sqlite3"
    run_id = "a" * 64
    with closing(sqlite3.connect(path)) as connection:
        for statement in migration_module._BT016_RESULT_TABLE_SQL_CONTRACTS.values():
            connection.execute(statement)
        for statement in (
            "CREATE INDEX ix_backtest_run_retention "
            "ON backtest_run (status, pinned, completed_at DESC, run_id DESC)",
            "CREATE INDEX ix_backtest_run_retention_v2 "
            "ON backtest_run (status, pinned, materialized, created_at DESC, run_id DESC)",
            "CREATE INDEX ix_backtest_fill_run ON backtest_fill (run_id, filled_at, fill_id)",
            "CREATE INDEX ix_backtest_detail_retention "
            "ON backtest_detail (kind, run_id, detail_id)",
            "CREATE INDEX ix_backtest_detail_run_event "
            "ON backtest_detail (run_id, event_at, detail_id)",
            *migration_module._BT016_RESULT_TRIGGER_SQL_CONTRACTS.values(),
        ):
            connection.execute(statement)
        connection.execute(
            """
            INSERT INTO backtest_run (
                run_id, plan_sha256, dataset_hash, status, completed_at,
                pinned, materialized, summary_domain, summary_hash,
                summary_json, created_at
            ) VALUES (?, ?, ?, 'COMPLETED', ?, 0, 0, ?, ?, ?, ?)
            """,
            (
                run_id,
                "b" * 64,
                "c" * 64,
                "2026-08-24T15:00:00.000000+08:00",
                "backtest-run-summary-v2",
                "d" * 64,
                '{"runId":"preserved"}',
                "2026-08-27T18:00:00.000000+08:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO backtest_fill (
                fill_id, run_id, filled_at, content_domain,
                content_hash, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "e" * 64,
                run_id,
                "2026-08-24T14:30:00.000000+08:00",
                "backtest-fill-record-v2",
                "f" * 64,
                '{"fillId":"preserved"}',
                "2026-08-27T18:00:00.000000+08:00",
            ),
        )
        connection.commit()
    with closing(sqlite3.connect(path)) as connection:
        before = migration_module._result_completed_only_content_hash(connection)
    inventory = inspect_result_database(path)
    decision = authorize_migration(
        inventory,
        VerifiedBackupFacts(
            source_fingerprint=inventory.source_fingerprint.digest,
            backup_sha256="1" * 64,
            backup_size_bytes=path.stat().st_size,
            verified_at=datetime(2026, 8, 27, 18, 0, tzinfo=_SHANGHAI),
            coordinator_stopped=True,
        ),
    )

    migrated = migrate_result_database(inventory, decision)

    assert migrated.database_state is DatabaseState.CURRENT
    with closing(sqlite3.connect(path)) as connection:
        assert migration_module._result_completed_only_content_hash(connection) == before
        assert connection.execute(
            "SELECT stage_revision FROM backtest_run WHERE run_id = ?", (run_id,)
        ).fetchone() == (1,)
        connection.execute(
            """
            INSERT INTO backtest_detail (
                detail_id, run_id, kind, event_at, content_domain,
                content_hash, payload_json, created_at
            ) VALUES (?, ?, 'DECISION', ?, ?, ?, ?, ?)
            """,
            (
                "2" * 64,
                run_id,
                "2026-08-24T14:35:00.000000+08:00",
                "backtest-detail-record-v2",
                "3" * 64,
                '{"detailId":"new"}',
                "2026-08-27T18:01:00.000000+08:00",
            ),
        )
        assert connection.execute(
            "SELECT stage_revision FROM backtest_run WHERE run_id = ?", (run_id,)
        ).fetchone() == (2,)


def test_bt017_result_schema_adds_query_metadata_without_changing_result_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bt017-results.sqlite3"
    run_id = "4" * 64
    with closing(sqlite3.connect(path)) as connection:
        for statement in migration_module._BT017_RESULT_TABLE_SQL_CONTRACTS.values():
            connection.execute(statement)
        for statement in (
            "CREATE INDEX ix_backtest_run_retention "
            "ON backtest_run (status, pinned, completed_at DESC, run_id DESC)",
            "CREATE INDEX ix_backtest_run_retention_v2 "
            "ON backtest_run (status, pinned, materialized, created_at DESC, run_id DESC)",
            "CREATE INDEX ix_backtest_fill_run ON backtest_fill (run_id, filled_at, fill_id)",
            "CREATE INDEX ix_backtest_detail_retention "
            "ON backtest_detail (kind, run_id, detail_id)",
            "CREATE INDEX ix_backtest_detail_run_event "
            "ON backtest_detail (run_id, event_at, detail_id)",
            *migration_module._BT017_RESULT_TRIGGER_SQL_CONTRACTS.values(),
        ):
            connection.execute(statement)
        connection.execute(
            "INSERT INTO backtest_plan_snapshot VALUES (?, '{}', ?)",
            ("5" * 64, "2026-08-27T18:00:00.000000+08:00"),
        )
        connection.execute(
            "INSERT INTO backtest_run_input VALUES (?, ?, ?, '{}', ?)",
            (
                run_id,
                "5" * 64,
                "6" * 64,
                "2026-08-27T18:00:00.000000+08:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO backtest_run (
                run_id, plan_sha256, dataset_hash, status, completed_at, pinned,
                materialized, publication_fill_count, publication_detail_count,
                publication_fill_set_hash, publication_detail_set_hash,
                summary_domain, publication_fill_set_domain,
                publication_detail_set_domain, summary_hash, summary_json,
                created_at, stage_revision
            ) VALUES (?, ?, ?, 'COMPLETED', ?, 0, 1, 0, 3, ?, ?, ?, ?, ?, ?, ?, ?, 4)
            """,
            (
                run_id,
                "5" * 64,
                "7" * 64,
                "2026-08-24T15:00:00.000000+08:00",
                "8" * 64,
                "9" * 64,
                "backtest-run-summary-v2",
                "backtest-fill-set-v2",
                "backtest-detail-set-v2",
                "a" * 64,
                '{"coverage":{"dailyEquityCount":1,"decisionCount":2,'
                '"detailCount":3,"fillCount":0,"outcomeCount":0,'
                '"signalCount":0}}',
                "2026-08-27T18:00:00.000000+08:00",
            ),
        )
        for index, kind in enumerate(("DECISION", "DECISION", "DAILY_EQUITY")):
            connection.execute(
                """
                INSERT INTO backtest_detail (
                    detail_id, run_id, kind, event_at, content_domain,
                    content_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, 'backtest-detail-record-v2', ?, '{}', ?)
                """,
                (
                    f"detail-{index}",
                    run_id,
                    kind,
                    f"2026-08-24T14:0{index}:00.000000+08:00",
                    str(index) * 64,
                    "2026-08-27T18:00:00.000000+08:00",
                ),
            )
        connection.commit()
        before = migration_module._result_completed_only_content_hash(connection)

    inventory = inspect_result_database(path)
    decision = authorize_migration(
        inventory,
        VerifiedBackupFacts(
            source_fingerprint=inventory.source_fingerprint.digest,
            backup_sha256="b" * 64,
            backup_size_bytes=path.stat().st_size,
            verified_at=datetime(2026, 8, 27, 18, 0, tzinfo=_SHANGHAI),
            coordinator_stopped=True,
        ),
    )
    migrated = migrate_result_database(inventory, decision)

    assert migrated.database_state is DatabaseState.CURRENT
    with closing(sqlite3.connect(path)) as connection:
        assert migration_module._result_completed_only_content_hash(connection) == before
        assert connection.execute(
            "SELECT pin_revision, catalog_revision FROM backtest_run WHERE run_id = ?",
            (run_id,),
        ).fetchone() == (0, 1)
        assert connection.execute(
            """
            SELECT decision_original_count, decision_expired_at,
                   signal_original_count, signal_expired_at,
                   outcome_original_count, outcome_expired_at,
                   daily_equity_original_count, daily_equity_expired_at,
                   pin_idempotency_json
            FROM backtest_run WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone() == (2, None, 0, None, 0, None, 1, None, "{}")


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
    assert dataset_times.invalid_value_count == 0
    assert len(dataset_times.ordered_values_sha256) == 64
    assert inventory.migration_reasons == ("UTC_MARKET_METADATA",)
    assert _database_state(path) == before


@pytest.mark.parametrize(
    "invalid_timestamp",
    (
        "2026-08-24T16:20:00.000000+09:00",
        "2026-08-24T15:20:00.000000",
        "2026-08-24T15:20:00.0000001+08:00",
    ),
)
def test_current_market_store_rejects_noncanonical_metadata_on_initialization(
    tmp_path: Path,
    invalid_timestamp: str,
) -> None:
    path = tmp_path / "noncanonical-current-market.sqlite3"
    store = BacktestMarketStore(path)
    store.record_trading_days(
        (
            TradingDay(
                exchange="SSE",
                cal_date=_TRADE_DATE,
                is_open=True,
                previous_trade_date=date(2026, 8, 21),
            ),
        )
    )
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE market_artifact SET created_at = ?",
            (invalid_timestamp,),
        )
        connection.execute(
            "UPDATE market_head SET updated_at = ?",
            (invalid_timestamp,),
        )
        connection.commit()
    before = _database_state(path)

    inventory = inspect_market_database(path)

    assert inventory.migration_reasons == ("INVALID_MARKET_METADATA_TIMESTAMP",)
    assert sum(item.invalid_value_count for item in inventory.utc_metadata) == 2
    with pytest.raises(
        MigrationPreflightError,
        match="INVALID_MARKET_METADATA_TIMESTAMP",
    ):
        BacktestMarketStore(path)
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


def test_market_metadata_new_writes_and_parser_use_fixed_shanghai_time(
    tmp_path: Path,
) -> None:
    time_module = import_module("trade_plan_monitor.backtest.time")
    parsed = time_module.parse_shanghai_datetime("2026-08-27T10:03:04+08:00")

    assert time_module.format_shanghai_datetime(parsed) == "2026-08-27T10:03:04.000000+08:00"
    for invalid in (
        "2026-08-27T02:03:04.000000Z",
        "2026-08-27T10:03:04",
        "2026-08-27T11:03:04.000000+09:00",
        "2026-08-27T10:03:04.0000001+08:00",
    ):
        with pytest.raises(ValueError, match="Shanghai datetime"):
            time_module.parse_shanghai_datetime(invalid)

    path = tmp_path / "new-market.sqlite3"
    store = BacktestMarketStore(path)
    store.record_trading_days(
        (
            TradingDay(
                exchange="SSE",
                cal_date=_TRADE_DATE,
                is_open=True,
                previous_trade_date=date(2026, 8, 21),
            ),
        )
    )
    with closing(sqlite3.connect(path)) as connection:
        values = connection.execute(
            "SELECT created_at FROM market_artifact UNION ALL SELECT updated_at FROM market_head"
        ).fetchall()
    assert len(values) == 2
    assert all(
        time_module.format_shanghai_datetime(time_module.parse_shanghai_datetime(str(row[0])))
        == row[0]
        for row in values
    )


def test_market_metadata_migration_preserves_all_identity_bearing_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-utc-market.sqlite3"
    store = BacktestMarketStore(path)
    _, dataset_hash = _seed_frozen_market_dataset(store)
    legacy_utc = "2026-08-24T07:20:00.000000+00:00"
    with closing(sqlite3.connect(path)) as connection:
        for table, column in (
            ("market_artifact", "created_at"),
            ("market_head", "updated_at"),
            ("market_minute_artifact", "created_at"),
            ("market_minute_head", "updated_at"),
            ("market_dataset", "created_at"),
        ):
            connection.execute(f'UPDATE "{table}" SET "{column}" = ?', (legacy_utc,))
        connection.commit()
    before_identity = _market_identity_snapshot(path)
    inventory = inspect_market_database(path)
    decision = authorize_migration(
        inventory,
        VerifiedBackupFacts(
            source_fingerprint=inventory.source_fingerprint.digest,
            backup_sha256="a" * 64,
            backup_size_bytes=path.stat().st_size,
            verified_at=datetime(2026, 8, 27, 16, 0, tzinfo=_SHANGHAI),
            coordinator_stopped=True,
        ),
    )

    migrated = migration_module.migrate_market_metadata(inventory, decision)

    assert migrated.database_state is DatabaseState.CURRENT
    assert migrated.migration_reasons == ()
    assert migrated.dataset_hash_goldens == inventory.dataset_hash_goldens
    assert _market_identity_snapshot(path) == before_identity
    with closing(sqlite3.connect(path)) as connection:
        for table, column in (
            ("market_artifact", "created_at"),
            ("market_head", "updated_at"),
            ("market_minute_artifact", "created_at"),
            ("market_minute_head", "updated_at"),
            ("market_dataset", "created_at"),
        ):
            values = tuple(connection.execute(f'SELECT "{column}" FROM "{table}"'))
            assert values
            assert {row[0] for row in values} == {"2026-08-24T15:20:00.000000+08:00"}
    assert BacktestMarketStore(path).dataset_manifest(dataset_hash).dataset_hash == dataset_hash


def test_market_metadata_migration_rejects_ambiguous_time_before_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ambiguous-market-time.sqlite3"
    store = BacktestMarketStore(path)
    store.record_trading_days(
        (
            TradingDay(
                exchange="SSE",
                cal_date=_TRADE_DATE,
                is_open=True,
                previous_trade_date=date(2026, 8, 21),
            ),
        )
    )
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("UPDATE market_artifact SET created_at = '2026-08-24T07:20:00+00:00'")
        connection.execute("UPDATE market_head SET updated_at = '2026-08-24T16:20:00+09:00'")
        connection.commit()
    inventory = inspect_market_database(path)
    assert inventory.migration_reasons == (
        "UTC_MARKET_METADATA",
        "INVALID_MARKET_METADATA_TIMESTAMP",
    )
    before = _database_state(path)

    with pytest.raises(
        MigrationPreflightError,
        match="INVALID_MARKET_METADATA_TIMESTAMP",
    ):
        authorize_migration(
            inventory,
            VerifiedBackupFacts(
                source_fingerprint=inventory.source_fingerprint.digest,
                backup_sha256="b" * 64,
                backup_size_bytes=path.stat().st_size,
                verified_at=datetime(2026, 8, 27, 16, 0, tzinfo=_SHANGHAI),
                coordinator_stopped=True,
            ),
        )

    assert _database_state(path) == before


def test_frozen_reader_streams_one_verified_symbol_day_without_manifest_projection(
    tmp_path: Path,
) -> None:
    store = BacktestMarketStore(tmp_path / "frozen-reader.sqlite3")
    scope, dataset_hash = _seed_frozen_market_dataset(store)

    with store.open_frozen_dataset(dataset_hash) as reader:
        assert reader.dataset_hash == dataset_hash
        assert reader.scope == scope
        assert not hasattr(reader, "manifest")
        assert not hasattr(reader, "items")
        iterator = iter(reader)
        symbol_day = next(iterator)
        assert symbol_day.symbol == _SYMBOL
        assert symbol_day.trade_date == _TRADE_DATE
        assert symbol_day.trading_day.is_open is True
        assert symbol_day.daily_bar is not None
        assert symbol_day.daily_limit is not None
        assert len(symbol_day.minutes) == 240
        with pytest.raises(StopIteration):
            next(iterator)
        with pytest.raises(RuntimeError, match="one-shot"):
            iter(reader)

    with pytest.raises(RuntimeError, match="closed"):
        iter(reader)
