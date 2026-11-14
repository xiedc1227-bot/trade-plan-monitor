"""Assurance migration contracts use only disposable SQLite databases.

The cutover is a storage fact, never a caller-selected date or legacy flag. No
test opens an application/user database or contacts a provider.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import insert, inspect
from tests.integration.test_live_monitor_projection_migration import _downgrade, _upgrade
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_source_coverage_baseline import _baseline

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json, daily_draft_sha256
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    Base,
    PlanReviewProvenance,
    PlanSource,
    PlanVersion,
    PlanVersionReview,
    StoredPlanExtractionReview,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

_REVISION = "0028_source_coverage"
_PREVIOUS = "0027_simulation_capital"
_TABLES = frozenset({
    "source_coverage_installation", "source_coverage_cutover", "source_coverage_input",
    "source_coverage_assessment", "source_coverage_review",
})
_OLD_TABLES = ("plan_source", "plan_version", "plan_version_review", "plan_review_provenance")
_NOW = datetime(2026, 10, 27, 10, 0, tzinfo=UTC)


def _revision(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()


def _rows(engine, table):
    assert table in {*_TABLES, *_OLD_TABLES}
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(f"SELECT * FROM {table}")
        return tuple(sorted(tuple(row) for row in rows))


def _old_snapshot(engine):
    return {table: _rows(engine, table) for table in _OLD_TABLES}


def _seed_legacy(engine, *, number=1, confirmed=True, created_at="2000-01-01T00:00:00+00:00"):
    """Insert a real old-verifier-consistent row without invoking current save guards."""
    draft, _, _ = _baseline()
    draft = draft.model_copy(update={"plan_id": f"migration-plan-{number}", "version": number})
    source, mapping = source_mapping(draft)
    snapshot = build_daily_review(draft, mapping, source)
    assert snapshot.issues == () and draft.to_executable() is not None
    source_id, version_id, review_id = (str(UUID(int=number * 10 + offset)) for offset in (0, 1, 2))
    plan_hash = daily_draft_sha256(draft)
    with engine.begin() as connection:
        connection.execute(insert(PlanSource), dict(id=source_id, source_text=source,
            source_hash=snapshot.source_hash, created_at=created_at))
        connection.execute(insert(PlanVersion), dict(id=version_id, plan_id=draft.plan_id,
            version=draft.version, symbol=draft.symbol, plan_hash=plan_hash, status="DRAFT",
            payload_json=daily_draft_json(draft), source_id=source_id, revision=0,
            created_at=created_at))
        connection.execute(insert(PlanVersionReview), dict(plan_version_id=version_id,
            review_issues_json="[]"))
        connection.execute(insert(PlanReviewProvenance), dict(plan_version_id=version_id,
            origin="MANUAL", extraction_id=None, source_hash=snapshot.source_hash,
            draft_hash=plan_hash, confirmed_at=_NOW.isoformat() if confirmed else None,
            content_hash=snapshot.content_hash, review_evidence_hash=snapshot.evidence_hash,
            mapping_json=canonical(mapping.model_dump(mode="json")), required_issues_json="[]",
            resolutions_json="[]", review_id=review_id if confirmed else None,
            review_revision=int(confirmed)))
    return SimpleNamespace(id=version_id, source_id=source_id, draft=draft,
        source=source, mapping=mapping, snapshot=snapshot, plan_hash=plan_hash,
        source_hash=snapshot.source_hash, review_id=review_id if confirmed else None)


def _assert_legacy_readable(engine, legacy):
    with SqlAlchemyUnitOfWork(create_session_factory(engine), clock=lambda: _NOW) as work:
        details = work.plans.get_version_details(legacy.id)
        assert details is not None
        assert details.payload_json == daily_draft_json(legacy.draft)
        assert details.source_text == legacy.source
        assert details.review_id == legacy.review_id
        assert details.review_evidence_hash == legacy.snapshot.evidence_hash
        assert details.daily_mapping == legacy.mapping and details.daily_issues == ()


def test_new_empty_database_has_the_assurance_tables_and_singleton_cutover_marker(tmp_path):
    engine = create_sqlite_engine(tmp_path / "empty-assurance.sqlite3")
    try:
        _upgrade(engine, "head")

        assert _TABLES <= set(inspect(engine).get_table_names())
        assert _revision(engine) == "0029_native_fact_lookup"
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT id FROM source_coverage_installation"
            ).all() == [(1,)]
            count = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM source_coverage_cutover").scalar()
            assert count == 0
            marker = connection.exec_driver_sql(
                "SELECT installation_id, payload_json, evidence_hash "
                "FROM source_coverage_installation"
            ).one()
            payload = json.loads(marker.payload_json)
            assert payload["installation_id"] == marker.installation_id
            assert payload["member_count"] == 0
            assert len(payload["membership_hash"]) == len(marker.evidence_hash) == 64
            assert datetime.fromisoformat(payload["installed_at"]).utcoffset() is not None
        for name in _TABLES:
            assert name in Base.metadata.tables
            assert {column.name for column in Base.metadata.tables[name].columns} == {
                column["name"] for column in inspect(engine).get_columns(name)
            }
    finally:
        engine.dispose()


@pytest.mark.parametrize("confirmed", [False, True])
def test_upgrading_populated_old_database_preserves_all_old_rows_bytes_and_review(
    confirmed, tmp_path,
):
    engine = create_sqlite_engine(tmp_path / "populated-old.sqlite3")
    try:
        _upgrade(engine, _PREVIOUS)
        legacy = _seed_legacy(engine, confirmed=confirmed)
        before = _old_snapshot(engine)
        _assert_legacy_readable(engine, legacy)

        _upgrade(engine, _REVISION)

        assert _old_snapshot(engine) == before
        _assert_legacy_readable(engine, legacy)
        with engine.connect() as connection:
            member = connection.exec_driver_sql(
                "SELECT plan_version_id, installation_id, plan_hash, source_hash, payload_json "
                "FROM source_coverage_cutover"
            ).one()
            marker = connection.exec_driver_sql(
                "SELECT installation_id, payload_json FROM source_coverage_installation"
            ).one()
            assert member.plan_version_id == legacy.id
            assert member.plan_hash == legacy.plan_hash and member.source_hash == legacy.source_hash
            assert member.installation_id == marker.installation_id
            payload = json.loads(member.payload_json)
            assert payload["plan_version_id"] == legacy.id
            assert payload["plan_hash"] == legacy.plan_hash
            assert payload["source_hash"] == legacy.source_hash
            assert isinstance(payload["legacy_identity"], dict)
            assert json.loads(marker.payload_json)["member_count"] == 1
            for table in _TABLES - {"source_coverage_installation", "source_coverage_cutover"}:
                assert connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar() == 0
    finally:
        engine.dispose()


def test_reopening_or_repeating_upgrade_never_replaces_marker_or_recaptures_new_versions(tmp_path):
    path = tmp_path / "stable-marker.sqlite3"
    engine = create_sqlite_engine(path)
    try:
        _upgrade(engine, _PREVIOUS)
        legacy = _seed_legacy(engine)
        _upgrade(engine, _REVISION)
        marker, membership = _rows(engine, "source_coverage_installation"), _rows(
            engine, "source_coverage_cutover")
        new = _seed_legacy(engine, number=2, created_at="1990-01-01T00:00:00+00:00")
    finally:
        engine.dispose()
    engine = create_sqlite_engine(path)
    try:
        _upgrade(engine, "head")
        assert _rows(engine, "source_coverage_installation") == marker
        assert _rows(engine, "source_coverage_cutover") == membership
        _assert_legacy_readable(engine, legacy)
        _assert_legacy_readable(engine, new)
        with engine.connect() as connection:
            members = connection.exec_driver_sql(
                "SELECT plan_version_id FROM source_coverage_cutover")
            assert members.all() == [(legacy.id,)]
    finally:
        engine.dispose()


@pytest.mark.parametrize("populated", [False, True])
def test_pristine_safe_downgrade_preserves_preexisting_rows_and_removes_only_new_tables(
    populated, tmp_path,
):
    engine = create_sqlite_engine(tmp_path / "safe-downgrade.sqlite3")
    try:
        _upgrade(engine, _PREVIOUS)
        legacy = _seed_legacy(engine) if populated else None
        before = _old_snapshot(engine)
        _upgrade(engine, _REVISION)

        _downgrade(engine, _PREVIOUS)

        assert _revision(engine) == _PREVIOUS
        assert not _TABLES.intersection(inspect(engine).get_table_names())
        assert _old_snapshot(engine) == before
        if legacy is not None:
            _assert_legacy_readable(engine, legacy)
    finally:
        engine.dispose()


def test_downgrade_rejects_a_backdated_new_version_even_without_any_proof_rows(tmp_path):
    engine = create_sqlite_engine(tmp_path / "new-version-refuses-downgrade.sqlite3")
    try:
        _upgrade(engine, _PREVIOUS)
        _seed_legacy(engine)
        _upgrade(engine, _REVISION)
        _seed_legacy(engine, number=2, created_at="1990-01-01T00:00:00+00:00")
        before = _old_snapshot(engine)
        marker = _rows(engine, "source_coverage_installation")

        with pytest.raises(RuntimeError):
            _downgrade(engine, _PREVIOUS)

        assert _revision(engine) == _REVISION
        assert _TABLES <= set(inspect(engine).get_table_names())
        assert _old_snapshot(engine) == before
        assert _rows(engine, "source_coverage_installation") == marker
    finally:
        engine.dispose()


def test_downgrade_rejects_marker_hash_corruption_even_when_all_evidence_tables_are_empty(tmp_path):
    engine = create_sqlite_engine(tmp_path / "corrupt-marker-downgrade.sqlite3")
    try:
        _upgrade(engine, _REVISION)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER pma_seal_source_coverage_installation_update")
            connection.exec_driver_sql(
                "UPDATE source_coverage_installation SET evidence_hash = ?", ("0" * 64,))

        with pytest.raises(RuntimeError):
            _downgrade(engine, _PREVIOUS)

        assert _revision(engine) == _REVISION
        assert _TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _resign(value):
    unsigned = {key: item for key, item in value.items() if key != "evidence_hash"}
    return unsigned | {"evidence_hash": daily_hash(unsigned["version"], unsigned)}


def _tamper_cutover(engine, legacy, attack):
    new = _seed_legacy(engine, number=2) if attack == "added_member" else None
    with engine.begin() as connection:
        # Explicit storage-corruption injection bypasses the immutable SQL guards.
        for name in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'pma_seal_%'",
        ).scalars().all():
            connection.exec_driver_sql(f"DROP TRIGGER {name}")
        marker = connection.exec_driver_sql(
            "SELECT * FROM source_coverage_installation").mappings().one()
        member = connection.exec_driver_sql(
            "SELECT * FROM source_coverage_cutover").mappings().one()
        if attack == "added_member":
            payload = json.loads(member["payload_json"])
            payload.update(plan_version_id=new.id, plan_hash=new.plan_hash,
                           source_hash=new.source_hash)
            payload = _resign(payload)
            connection.exec_driver_sql(
                "INSERT INTO source_coverage_cutover "
                "(plan_version_id, installation_id, plan_hash, source_hash, payload_json, "
                "evidence_hash) VALUES (?, ?, ?, ?, ?, ?)",
                (new.id, member["installation_id"], new.plan_hash, new.source_hash,
                 canonical(payload), payload["evidence_hash"]))
        elif attack == "deleted_member":
            connection.exec_driver_sql(
                "DELETE FROM source_coverage_cutover WHERE plan_version_id = ?", (legacy.id,))
        elif attack == "member_projection":
            connection.exec_driver_sql(
                "UPDATE source_coverage_cutover SET installation_id = ?", (str(UUID(int=900)),))
        elif attack in {"member_payload_resigned", "member_payload_unsigned"}:
            payload = json.loads(member["payload_json"])
            payload["legacy_identity"]["status"] = "ACTIVE"
            if attack == "member_payload_resigned":
                payload = _resign(payload)
            connection.exec_driver_sql(
                "UPDATE source_coverage_cutover SET payload_json = ?, evidence_hash = ?",
                (canonical(payload), payload["evidence_hash"]))
        elif attack == "marker_projection":
            connection.exec_driver_sql(
                "UPDATE source_coverage_installation SET installation_id = ?",
                (str(UUID(int=900)),))
        else:
            payload = json.loads(marker["payload_json"])
            if attack == "marker_payload_unsigned":
                payload["installed_at"] = "2001-01-01T00:00:00+08:00"
            else:
                assert attack == "marker_count_resigned"
                payload["member_count"] += 1
                payload = _resign(payload)
            connection.exec_driver_sql(
                "UPDATE source_coverage_installation SET payload_json = ?, evidence_hash = ?",
                (canonical(payload), payload["evidence_hash"]))


@pytest.mark.parametrize("attack", [
    "added_member", "deleted_member", "member_projection", "member_payload_resigned",
    "member_payload_unsigned", "marker_projection", "marker_payload_unsigned",
    "marker_count_resigned",
])
def test_downgrade_validates_complete_cutover_root_payloads_and_scalar_projections(
    attack, tmp_path,
):
    engine = create_sqlite_engine(tmp_path / "invalid-cutover-downgrade.sqlite3")
    try:
        _upgrade(engine, _PREVIOUS)
        legacy = _seed_legacy(engine)
        _upgrade(engine, _REVISION)
        _tamper_cutover(engine, legacy, attack)
        before = {table: _rows(engine, table) for table in _TABLES}
        old_before = _old_snapshot(engine)

        with pytest.raises(RuntimeError):
            _downgrade(engine, _PREVIOUS)

        assert _revision(engine) == _REVISION
        assert {table: _rows(engine, table) for table in _TABLES} == before
        assert _old_snapshot(engine) == old_before
    finally:
        engine.dispose()


@pytest.mark.parametrize("table", [
    "source_coverage_input", "source_coverage_assessment", "source_coverage_review",
])
def test_downgrade_never_discards_new_input_assessment_or_receipt_evidence(table, tmp_path):
    engine = create_sqlite_engine(tmp_path / "evidence-refuses-downgrade.sqlite3")
    try:
        _upgrade(engine, _PREVIOUS)
        legacy = _seed_legacy(engine)
        _upgrade(engine, _REVISION)
        with engine.begin() as connection:
            if table == "source_coverage_input":
                extraction_id = str(UUID(int=100))
                connection.execute(insert(StoredPlanExtractionReview), dict(id=extraction_id,
                    provider_id=str(UUID(int=101)), model="offline-migration-fixture",
                    prompt_version="plan-extract-v12", source_hash=legacy.source_hash,
                    draft_hash=legacy.plan_hash, review_issues_json="[]", mapping_json=None,
                    content_hash=None, review_evidence_hash=None, required_issues_json=None,
                    completed_at=_NOW.isoformat()))
                connection.exec_driver_sql(
                    "INSERT INTO source_coverage_input "
                    "(extraction_id, source_hash, payload_json, evidence_hash) VALUES (?, ?, ?, ?)",
                    (extraction_id, legacy.source_hash, "{}", "a" * 64))
            elif table == "source_coverage_assessment":
                connection.exec_driver_sql(
                    "INSERT INTO source_coverage_assessment "
                    "(plan_version_id, revision, command_id, request_hash, payload_json, "
                    "evidence_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (legacy.id, 1, "migration-command", "a" * 64, "{}", "b" * 64, _NOW.isoformat()))
            else:
                connection.exec_driver_sql(
                    "INSERT INTO source_coverage_review "
                    "(review_id, plan_version_id, review_revision, payload_json, evidence_hash) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (legacy.review_id, legacy.id, 1, "{}", "a" * 64))
        before = _rows(engine, table)

        # Even corrupt/unreadable evidence must not be silently dropped by a
        # downgrade merely because its application-level signature is invalid.
        with pytest.raises(RuntimeError):
            _downgrade(engine, _PREVIOUS)

        assert _revision(engine) == _REVISION
        assert _rows(engine, table) == before
        assert _TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


