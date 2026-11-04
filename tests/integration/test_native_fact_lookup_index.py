"""The native FACT seek index is identical in metadata and the additive migration."""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateIndex
from tests.integration.test_lot_history_indexes import _migrate
from tests.integration.test_native_fact_reads import facts as facts
from tests.integration.test_source_coverage_authority_save import state as state

from trade_plan_monitor.state import database
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.database import create_sqlite_engine

INDEX_NAME = "ix_daily_fact_trade_date_lookup"


def definition(engine):
    with engine.connect() as connection:
        return connection.scalar(
            text("SELECT sql FROM sqlite_master WHERE type='index' AND name=:name"),
            {"name": INDEX_NAME},
        )


def snapshot(engine):
    with engine.connect() as connection:
        return {
            table: sorted(
                (tuple(row) for row in connection.exec_driver_sql(f'SELECT * FROM "{table}"')),
                key=repr,
            )
            for table in inspect(connection).get_table_names()
            if table != "alembic_version"
        }


def test_metadata_installs_the_native_fact_lookup_index(tmp_path):
    engine = create_sqlite_engine(tmp_path / "metadata.sqlite")
    try:
        DailyRecord.__table__.create(engine)
        with engine.connect() as connection:
            definition = connection.scalar(
                text("SELECT sql FROM sqlite_master WHERE type='index' AND name=:name"),
                {"name": INDEX_NAME},
            )
        assert definition is not None
        assert "available_at" in definition and "verified_at" in definition
    finally:
        engine.dispose()


def test_migration_has_one_head_and_only_adds_or_removes_the_identical_index(facts):
    facts.add("retained-fact")
    config = Config()
    config.set_main_option("script_location", str(Path(database.__file__).with_name("migrations")))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0029_native_fact_lookup"]
    assert scripts.get_revision("0029_native_fact_lookup").down_revision == "0028_source_coverage"
    before = snapshot(facts.engine)
    assert before["source_coverage_assessment"] and before["source_coverage_review"]
    original_definition = definition(facts.engine)
    index = next(value for value in DailyRecord.__table__.indexes if value.name == INDEX_NAME)
    expected = str(CreateIndex(index).compile(dialect=facts.engine.dialect))
    assert re.sub(r"\s+", " ", original_definition).strip() == re.sub(r"\s+", " ", expected).strip()
    _migrate(facts.engine, "0028_source_coverage", downgrade=True)
    assert definition(facts.engine) is None and snapshot(facts.engine) == before
    _migrate(facts.engine, "0029_native_fact_lookup")
    assert definition(facts.engine) == original_definition and snapshot(facts.engine) == before
    _migrate(facts.engine, "0029_native_fact_lookup")
    assert snapshot(facts.engine) == before
    _migrate(facts.engine, "0028_source_coverage", downgrade=True)
    assert snapshot(facts.engine) == before and definition(facts.engine) is None
