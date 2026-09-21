"""Recovery checkpoints are bounded, safe, atomic, and survive restarts."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from trade_plan_monitor.runtime.clock import SHANGHAI
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

NOW = datetime(2026, 9, 21, 10, tzinfo=SHANGHAI)
IDENTITY = "a" * 64


def test_checkpoint_roundtrip_is_idempotent_and_scoped(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    upgrade_database(engine)
    factory = create_session_factory(engine)
    repository = ProviderRecoveryRepository(factory, provider_identity=IDENTITY)
    rows = (
        RecoveryCheckpoint("cooldown", "shared", NOW + timedelta(seconds=300), 0),
        RecoveryCheckpoint("permission", "daily_bars", NOW + timedelta(seconds=300), 0),
        RecoveryCheckpoint("backoff", "b" * 64, NOW + timedelta(seconds=30), 1),
    )
    repository.save(rows)
    assert set(ProviderRecoveryRepository(factory, provider_identity=IDENTITY).load()) == set(rows)
    assert ProviderRecoveryRepository(factory, provider_identity="c" * 64).load() == ()
    repository.save(rows)
    assert len(repository.load()) == 3
    engine.dispose()


def test_invalid_checkpoint_fails_closed_without_replacing_prior_state(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    repository = ProviderRecoveryRepository(
        create_session_factory(engine), provider_identity=IDENTITY
    )
    old = (RecoveryCheckpoint("cooldown", "shared", NOW, 0),)
    repository.save(old)
    with pytest.raises(RecoveryCheckpointError):
        repository.save(
            tuple(RecoveryCheckpoint("backoff", f"{index:064x}", NOW, 1) for index in range(65))
        )
    assert repository.load() == old
    with engine.begin() as connection:
        connection.execute(text("UPDATE provider_recovery_checkpoint SET retry_at='corrupt'"))
    with pytest.raises(RecoveryCheckpointError, match="invalid provider recovery checkpoint"):
        repository.load()
    engine.dispose()


def test_checkpoint_migration_refuses_pending_downgrade_and_has_empty_down_path(tmp_path):
    engine = create_sqlite_engine(tmp_path / "state.db")
    upgrade_database(engine)
    repository = ProviderRecoveryRepository(
        create_session_factory(engine), provider_identity=IDENTITY
    )
    repository.save((RecoveryCheckpoint("cooldown", "shared", NOW, 0),))
    config = Config()
    import trade_plan_monitor.state.database as database

    config.set_main_option("script_location", str(Path(database.__file__).with_name("migrations")))
    with pytest.raises(RuntimeError, match="refuses to discard"):
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0017_market_index_recovery")
    repository.save(())
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0017_market_index_recovery")
    upgrade_database(engine)
    assert repository.load() == ()
    engine.dispose()


def test_ownership_canonicalizes_file_aliases_and_separates_memory_engines(tmp_path):
    engines = [
        create_engine(f"sqlite:///{tmp_path / 'state.db'}"),
        create_engine(f"sqlite:///{tmp_path / 'alias' / '..' / 'state.db'}"),
        create_engine("sqlite:///:memory:"),
        create_engine("sqlite:///:memory:"),
    ]
    repositories = [
        ProviderRecoveryRepository(
            create_session_factory(engine),
            provider_identity=IDENTITY,
        )
        for engine in engines
    ]
    owners = [object() for _ in engines]
    try:
        repositories[0].acquire_owner(owners[0])
        with pytest.raises(RecoveryCheckpointError, match="already owned"):
            repositories[1].acquire_owner(owners[1])
        repositories[2].acquire_owner(owners[2])
        repositories[3].acquire_owner(owners[3])
    finally:
        for repository, owner, engine in zip(repositories, owners, engines, strict=True):
            repository.release_owner(owner)
            engine.dispose()
