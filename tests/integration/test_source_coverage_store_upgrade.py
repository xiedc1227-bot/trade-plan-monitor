"""Missing assurance storage is read-only upgrade-required, never implicit migration."""

import pytest
from sqlalchemy import inspect
from tests.integration.test_live_monitor_projection_migration import _upgrade
from tests.integration.test_source_coverage_migration import (
    _PREVIOUS,
    _REVISION,
    _assert_legacy_readable,
    _old_snapshot,
    _revision,
    _seed_legacy,
)

import trade_plan_monitor.state.database as database
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import Base
from trade_plan_monitor.state.source_coverage_store import (
    SourceCoverageStore,
    SourceCoverageUpgradeRequired,
)


@pytest.mark.parametrize("partial_upgrade", [False, True])
@pytest.mark.parametrize("read", ["installation", "cutover", "latest"])
def test_missing_assurance_tables_are_upgrade_required_and_reads_never_auto_migrate(
    partial_upgrade, read, tmp_path, monkeypatch,
):
    engine = create_sqlite_engine(tmp_path / "missing-sidecar.sqlite3")
    try:
        _upgrade(engine, _PREVIOUS)
        legacy = _seed_legacy(engine)
        if partial_upgrade:
            _upgrade(engine, _REVISION)
            with engine.begin() as connection:
                connection.exec_driver_sql("DROP TABLE source_coverage_assessment")
        tables = set(inspect(engine).get_table_names())
        before, revision = _old_snapshot(engine), _revision(engine)

        def forbidden(*args, **kwargs):
            raise AssertionError("A read attempted automatic migration/schema creation")

        monkeypatch.setattr(database, "upgrade_database", forbidden)
        monkeypatch.setattr(Base.metadata, "create_all", forbidden)
        with create_session_factory(engine)() as session:
            with pytest.raises(SourceCoverageUpgradeRequired):
                store = SourceCoverageStore(session)
                if read == "installation":
                    store.installation()
                else:
                    getattr(store, read)(legacy.id)
        _assert_legacy_readable(engine, legacy)
        assert set(inspect(engine).get_table_names()) == tables
        assert _old_snapshot(engine) == before and _revision(engine) == revision
    finally:
        engine.dispose()
