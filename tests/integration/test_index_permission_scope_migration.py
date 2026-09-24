"""Migrate legacy index-minute permission facts without weakening admission."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from trade_plan_monitor.market_index.identity import MarketIndexCode
from trade_plan_monitor.market_index.tushare import (
    TushareMarketIndexCapabilityStatus,
    TushareMarketIndexProvider,
    TushareMarketIndexProviderError,
    TushareMarketIndexSourceTimeLabel,
    certified_tushare_market_index_profile,
)
from trade_plan_monitor.runtime.clock import SHANGHAI
from trade_plan_monitor.runtime.request_control import (
    RequestControlErrorCode,
    TushareOperation,
    create_live_tushare_request_controller,
)
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.runtime_recovery import (
    ProviderRecoveryRepository,
    RecoveryCheckpoint,
    RecoveryCheckpointError,
)

NOW = datetime(2026, 9, 24, 10, tzinfo=SHANGHAI)
IDENTITY = "a" * 64
OLD_PERMISSIONS = (
    "probe_capabilities",
    "realtime_minutes",
    "current_day_minutes",
    "historical_minutes",
    "trading_calendar",
    "daily_limits",
    "daily_bars",
    "index_minutes",
    "index_daily",
)
NEW_PERMISSIONS = ("idx_mins", "rt_idx_min_daily")


def _migrate(engine, revision: str, *, downgrade: bool = False) -> None:
    import trade_plan_monitor.state.database as database

    config = Config()
    config.set_main_option("script_location", str(Path(database.__file__).with_name("migrations")))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        if downgrade:
            command.downgrade(config, revision)
        else:
            command.upgrade(config, revision)


def _seed(engine, *, new_scopes: tuple[str, ...], legacy: bool = True, extra_backoff=False):
    rows = [
        ("cooldown", "shared", NOW + timedelta(seconds=300), 0, "RATE_LIMITED"),
        *(
            ("permission", scope, NOW + timedelta(seconds=300), 0, "BLOCKED_PERMISSION")
            for scope in OLD_PERMISSIONS
            if legacy or scope != "index_minutes"
        ),
        *(
            (
                "permission",
                scope,
                NOW + timedelta(seconds=120 if scope == "idx_mins" else 600),
                0,
                "BLOCKED_PERMISSION",
            )
            for scope in new_scopes
        ),
        *(
            ("backoff", f"{index:064x}", NOW + timedelta(seconds=30), 1, "TRANSIENT")
            for index in range(64 + int(extra_backoff))
        ),
    ]
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO provider_recovery_checkpoint "
                "(provider_identity, kind, scope_key, schema_version, retry_at, failures, "
                "reason_code) VALUES (:identity, :kind, :scope, 1, :retry, :failures, :reason)"
            ),
            [
                {
                    "identity": IDENTITY,
                    "kind": kind,
                    "scope": scope,
                    "retry": retry.isoformat(),
                    "failures": failures,
                    "reason": reason,
                }
                for kind, scope, retry, failures, reason in rows
            ],
        )
    return len(rows)


def _snapshot(engine):
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT provider_identity, kind, scope_key, retry_at, failures, reason_code "
                "FROM provider_recovery_checkpoint ORDER BY provider_identity, kind, scope_key"
            )
        ).all()
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    return rows, version


@pytest.mark.parametrize("new_scopes", ((), ("idx_mins",), NEW_PERMISSIONS))
def test_legacy_74_75_76_rows_migrate_by_key_set_and_keep_later_retry(
    tmp_path,
    new_scopes,
):
    engine = create_sqlite_engine(tmp_path / "state.db")
    try:
        _migrate(engine, "0022_runtime_liveness")
        assert _seed(engine, new_scopes=new_scopes) == 74 + len(new_scopes)
        original, _ = _snapshot(engine)
        original_unchanged = [
            row
            for row in original
            if row.kind != "permission" or row.scope_key not in {"index_minutes", *NEW_PERMISSIONS}
        ]
        upgrade_database(engine)
        migrated, _ = _snapshot(engine)
        assert [
            row
            for row in migrated
            if row.kind != "permission" or row.scope_key not in {"index_minutes", *NEW_PERMISSIONS}
        ] == original_unchanged
        rows = ProviderRecoveryRepository(
            create_session_factory(engine), provider_identity=IDENTITY
        ).load()
        assert len(rows) == 75
        assert all(row.scope_key != "index_minutes" for row in rows if row.kind == "permission")
        expected = {
            "idx_mins": NOW + timedelta(seconds=300),
            "rt_idx_min_daily": NOW
            + timedelta(seconds=600 if "rt_idx_min_daily" in new_scopes else 300),
        }
        assert {
            row.scope_key: row.retry_at
            for row in rows
            if row.kind == "permission" and row.scope_key in NEW_PERMISSIONS
        } == expected
        before = _snapshot(engine)
        upgrade_database(engine)
        assert _snapshot(engine) == before
    finally:
        engine.dispose()


def test_new_canonical_75_rows_need_no_rewrite(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    try:
        _migrate(engine, "0022_runtime_liveness")
        assert _seed(engine, new_scopes=NEW_PERMISSIONS, legacy=False) == 75
        before, _ = _snapshot(engine)
        upgrade_database(engine)
        assert _snapshot(engine)[0] == before
        assert (
            len(
                ProviderRecoveryRepository(
                    create_session_factory(engine), provider_identity=IDENTITY
                ).load()
            )
            == 75
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("legacy", "new_scopes", "expected_count"),
    (
        (False, NEW_PERMISSIONS, 76),
        (True, ("idx_mins",), 76),
        (True, NEW_PERMISSIONS, 77),
    ),
)
def test_migration_reads_one_past_each_key_set_bound_and_preserves_rows_on_failure(
    tmp_path,
    legacy,
    new_scopes,
    expected_count,
):
    engine = create_sqlite_engine(tmp_path / "state.db")
    try:
        _migrate(engine, "0022_runtime_liveness")
        assert (
            _seed(engine, new_scopes=new_scopes, legacy=legacy, extra_backoff=True)
            == expected_count
        )
        before = _snapshot(engine)
        with pytest.raises(RuntimeError, match="provider recovery"):
            upgrade_database(engine)
        assert _snapshot(engine) == before
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("scope", "reason", "retry"),
    (
        ("unexpected_scope", "BLOCKED_PERMISSION", NOW.isoformat()),
        ("index_minutes", "TRANSIENT", NOW.isoformat()),
        ("index_minutes", "BLOCKED_PERMISSION", "corrupt"),
    ),
)
def test_migration_rejects_unknown_or_corrupt_legacy_rows_without_mutation(
    tmp_path,
    scope,
    reason,
    retry,
):
    engine = create_sqlite_engine(tmp_path / "state.db")
    try:
        _migrate(engine, "0022_runtime_liveness")
        _seed(engine, new_scopes=())
        with engine.begin() as connection:
            if scope == "unexpected_scope":
                connection.execute(
                    text(
                        "INSERT INTO provider_recovery_checkpoint VALUES "
                        "(:identity, 'permission', :scope, 1, :retry, 0, :reason)"
                    ),
                    {"identity": IDENTITY, "scope": scope, "retry": retry, "reason": reason},
                )
            else:
                connection.execute(
                    text(
                        "UPDATE provider_recovery_checkpoint SET reason_code=:reason, "
                        "retry_at=:retry WHERE scope_key='index_minutes'"
                    ),
                    {"reason": reason, "retry": retry},
                )
        before = _snapshot(engine)
        with pytest.raises(RuntimeError, match="provider recovery"):
            upgrade_database(engine)
        assert _snapshot(engine) == before
    finally:
        engine.dispose()


def test_invalid_second_provider_prevents_first_provider_rewrite(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    try:
        _migrate(engine, "0022_runtime_liveness")
        _seed(engine, new_scopes=())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO provider_recovery_checkpoint VALUES "
                    "(:identity, 'permission', 'unknown', 1, :retry, 0, 'BLOCKED_PERMISSION')"
                ),
                {"identity": "b" * 64, "retry": NOW.isoformat()},
            )
        before = _snapshot(engine)
        with pytest.raises(RuntimeError, match="provider recovery"):
            upgrade_database(engine)
        assert _snapshot(engine) == before
    finally:
        engine.dispose()


def test_migrated_legacy_block_fences_both_index_paths_and_keeps_work_backoff(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    work_key = "index:399001.SZ:20260924T1000:realtime-minutes"
    backoff_key = sha256(work_key.encode("utf-8")).hexdigest()
    old_retry = NOW - timedelta(seconds=1)
    backoff_retry = NOW + timedelta(seconds=120)
    try:
        _migrate(engine, "0022_runtime_liveness")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO provider_recovery_checkpoint "
                    "(provider_identity, kind, scope_key, schema_version, retry_at, failures, "
                    "reason_code) VALUES (:identity, :kind, :scope, 1, :retry, :failures, :reason)"
                ),
                (
                    {
                        "identity": IDENTITY,
                        "kind": "permission",
                        "scope": "index_minutes",
                        "retry": old_retry.isoformat(),
                        "failures": 0,
                        "reason": "BLOCKED_PERMISSION",
                    },
                    {
                        "identity": IDENTITY,
                        "kind": "backoff",
                        "scope": backoff_key,
                        "retry": backoff_retry.isoformat(),
                        "failures": 2,
                        "reason": "TRANSIENT",
                    },
                ),
            )
        old_rows, _ = _snapshot(engine)
        old_backoff = [row for row in old_rows if row.kind == "backoff"]
        upgrade_database(engine)
        new_rows, _ = _snapshot(engine)
        assert [row for row in new_rows if row.kind == "backoff"] == old_backoff
        repository = ProviderRecoveryRepository(
            create_session_factory(engine), provider_identity=IDENTITY
        )
        permissions = {
            row.scope_key: row.retry_at for row in repository.load() if row.kind == "permission"
        }
        assert permissions == {scope: old_retry for scope in NEW_PERMISSIONS}

        class Clock:
            def now(self):
                return NOW

            async def sleep_until(self, _deadline):
                raise AssertionError("request control must not call scheduler sleep")

        class SDK:
            def __init__(self):
                self.calls = []

            def __getattr__(self, name):
                def call(**_kwargs):
                    self.calls.append(name)
                    return pd.DataFrame()

                return call

        async def scenario():
            elapsed = 0.0

            def monotonic():
                return elapsed

            async def pace_sleep(seconds):
                nonlocal elapsed
                elapsed += seconds
                await asyncio.sleep(0)

            controller = create_live_tushare_request_controller(
                clock=Clock(),
                monotonic=monotonic,
                pace_sleep=pace_sleep,
                require_repository_binding=True,
            )
            sdk = SDK()
            profile = certified_tushare_market_index_profile(
                capabilities={
                    code: (
                        TushareMarketIndexCapabilityStatus.DEFERRED
                        if code is MarketIndexCode.BSE_50
                        else TushareMarketIndexCapabilityStatus.READY
                    )
                    for code in MarketIndexCode
                },
                source_time_label=TushareMarketIndexSourceTimeLabel.END,
            )
            provider = TushareMarketIndexProvider(
                client=sdk,
                profile=profile,
                request_controller=controller,
                now=lambda: NOW,
            )
            index_code = MarketIndexCode.SHENZHEN_COMPONENT

            async def acquire():
                return await provider.acquire_index_data(
                    index_code=index_code,
                    decision_cutoff=NOW,
                    five_minute_bar_count=1,
                    official_daily_bar_count=1,
                )

            try:
                with pytest.raises(RecoveryCheckpointError):
                    await controller.execute(
                        TushareOperation.INDEX_DAILY,
                        lambda: sdk.index_daily(),
                        work_key="unbound",
                    )
                assert sdk.calls == []
                controller.bind_recovery_repository(repository)
                assert controller.repository_bound
                assert controller.backoff_until(work_key) == backoff_retry
                for operation in (
                    TushareOperation.INDEX_HISTORICAL_MINUTES,
                    TushareOperation.INDEX_REALTIME_MINUTES,
                ):
                    assert controller.is_permission_blocked(operation)
                    assert controller.permission_retry_at(operation) == old_retry
                with pytest.raises(TushareMarketIndexProviderError) as historical:
                    await acquire()
                assert historical.value.stage == "HISTORICAL_MINUTES"
                assert historical.value.reason is RequestControlErrorCode.BLOCKED_PERMISSION
                provider._historical_minute_cache[(index_code, NOW.date())] = pd.DataFrame()
                with pytest.raises(TushareMarketIndexProviderError) as realtime:
                    await acquire()
                assert realtime.value.stage == "REALTIME_MINUTES"
                assert realtime.value.reason is RequestControlErrorCode.BLOCKED_PERMISSION
                assert sdk.calls == []

                controller.reset_permission_block(TushareOperation.INDEX_REALTIME_MINUTES)
                with pytest.raises(TushareMarketIndexProviderError) as backed_off:
                    await acquire()
                assert backed_off.value.reason is RequestControlErrorCode.TRANSIENT
                assert backed_off.value.next_retry_at == backoff_retry
                assert sdk.calls == []
                assert controller.is_permission_blocked(TushareOperation.INDEX_HISTORICAL_MINUTES)
                assert not controller.is_permission_blocked(TushareOperation.INDEX_REALTIME_MINUTES)
                assert (
                    await controller.execute(
                        TushareOperation.INDEX_REALTIME_MINUTES,
                        lambda: "realtime-allowed",
                        work_key="new-realtime-key",
                    )
                    == "realtime-allowed"
                )
                assert (
                    await controller.execute(
                        TushareOperation.INDEX_DAILY,
                        lambda: "allowed",
                        work_key="fresh-index-daily",
                    )
                    == "allowed"
                )
                assert all(row.scope_key != "index_minutes" for row in repository.load())
            finally:
                await controller.aclose()

        asyncio.run(scenario())
    finally:
        engine.dispose()


def test_downgrade_refuses_new_permission_state_without_changing_data(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    try:
        upgrade_database(engine)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine), provider_identity=IDENTITY
        )
        repository.save(
            (RecoveryCheckpoint("permission", "idx_mins", NOW - timedelta(seconds=1), 0),)
        )
        before = _snapshot(engine)
        with pytest.raises(RuntimeError, match="refuses to discard"):
            _migrate(engine, "0022_runtime_liveness", downgrade=True)
        assert _snapshot(engine) == before
        assert repository.load()[0].retry_at < NOW  # Expiry does not lift a permission block.
        with pytest.raises(RecoveryCheckpointError):
            repository.save((RecoveryCheckpoint("permission", "index_minutes", NOW, 0),))
    finally:
        engine.dispose()


def test_runtime_load_rejects_legacy_scope_even_after_upgrade(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    try:
        upgrade_database(engine)
        repository = ProviderRecoveryRepository(
            create_session_factory(engine), provider_identity=IDENTITY
        )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO provider_recovery_checkpoint VALUES "
                    "(:identity, 'permission', 'index_minutes', 1, :retry, 0, "
                    "'BLOCKED_PERMISSION')"
                ),
                {"identity": IDENTITY, "retry": NOW.isoformat()},
            )
        before = _snapshot(engine)
        with pytest.raises(RecoveryCheckpointError):
            repository.load()
        assert _snapshot(engine) == before
    finally:
        engine.dispose()
