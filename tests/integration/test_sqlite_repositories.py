from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Barrier
from zoneinfo import ZoneInfo

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, event, inspect, select
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from trade_plan_monitor.domain.plan_codec import load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradePlan
from trade_plan_monitor.domain.plan_validation import (
    ALL_MARKET_EVIDENCE,
    PlanValidationResult,
    validate_trade_plan,
)
from trade_plan_monitor.state.database import (
    DEFAULT_BUSY_TIMEOUT_MS,
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import (
    ActivePlan,
    AlertEvent,
    AuditLog,
    Base,
    EvaluationLedger,
)
from trade_plan_monitor.state.repositories import (
    BoardLotViolationError,
    DuplicatePlanVersionError,
    EpisodeIdentityConflictError,
    EpisodeTransitionError,
    EvaluationIdentityConflictError,
    IdempotencyInProgressError,
    IdempotencyKeyReuseError,
    MaxPositionExceededError,
    PlanActivationBlockedError,
    PlanSaveBlockedError,
    PositionReductionError,
    PositionT1LockedError,
    ProviderHealthConflictError,
    RepositoryError,
    RevisionConflictError,
)
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

EXPECTED_APP_TABLES = frozenset(
    {
        "active_plan",
        "ai_provider_configuration",
        "alert_event",
        "audit_log",
        "daily_bar",
        "daily_price_limit",
        "delivery_attempt",
        "evaluation_ledger",
        "five_minute_bar",
        "latest_quote",
        "minute_bar",
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

_FIXED_NOW = datetime(2026, 8, 21, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
_SAMPLE_PLAN_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "plans" / "003043.SZ.sample.yaml"
)
_REQUEST_HASH = "a" * 64


def _sample_plan() -> tuple[TradePlan, str]:
    source_text = _SAMPLE_PLAN_PATH.read_text(encoding="utf-8")
    return load_plan_yaml(source_text), source_text


def _unit_of_work(engine: Engine) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(
        create_session_factory(engine),
        clock=lambda: _FIXED_NOW,
    )


def _pragma_value(engine: Engine, pragma: str) -> object:
    with engine.connect() as connection:
        return connection.exec_driver_sql(f"PRAGMA {pragma}").scalar_one()


def test_position_lots_enforce_bucket_board_lot_maximum_and_t_plus_one(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            core = work.positions.record_buy(
                symbol="003043.SZ",
                bucket="CORE",
                quantity=200,
                acquired_trade_date=date(2026, 8, 20),
                cost_fen=6400,
                board_lot=100,
                max_position_qty=300,
            )
            tactical = work.positions.record_buy(
                symbol="003043.SZ",
                bucket="TACTICAL",
                quantity=100,
                acquired_trade_date=date(2026, 8, 21),
                cost_fen=6500,
                board_lot=100,
                max_position_qty=300,
            )
            assert work.positions.sellable_quantity(
                "003043.SZ", trade_date=date(2026, 8, 21)
            ) == 200
            assert work.positions.sellable_quantity(
                "003043.SZ",
                trade_date=date(2026, 8, 21),
                bucket="TACTICAL",
            ) == 0
            work.commit()

        assert core.bucket == "CORE"
        assert tactical.bucket == "TACTICAL"
        with _unit_of_work(engine) as work:
            assert work.positions.list_open_lots("003043.SZ") == (core, tactical)
            with pytest.raises(BoardLotViolationError) as board_lot_error:
                work.positions.record_buy(
                    symbol="003043.SZ",
                    bucket="CORE",
                    quantity=50,
                    acquired_trade_date=date(2026, 8, 21),
                    cost_fen=6500,
                    board_lot=100,
                    max_position_qty=400,
                )
            assert board_lot_error.value.code == "BOARD_LOT_VIOLATION"

            with pytest.raises(MaxPositionExceededError) as maximum_error:
                work.positions.record_buy(
                    symbol="003043.SZ",
                    bucket="TACTICAL",
                    quantity=100,
                    acquired_trade_date=date(2026, 8, 21),
                    cost_fen=6500,
                    board_lot=100,
                    max_position_qty=300,
                )
            assert maximum_error.value.code == "MAX_POSITION_EXCEEDED"
    finally:
        engine.dispose()


def test_position_partial_reduction_is_t_plus_one_safe_and_audited(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            lot = work.positions.record_buy(
                symbol="003043.SZ",
                bucket="CORE",
                quantity=200,
                acquired_trade_date=date(2026, 8, 20),
                cost_fen=6400,
                board_lot=100,
                max_position_qty=200,
            )
            work.commit()

        with _unit_of_work(engine) as work:
            reduced = work.positions.reduce_lot(
                lot.id,
                quantity=100,
                trade_date=date(2026, 8, 21),
            )
            work.commit()
        assert reduced.remaining_qty == 100
        assert reduced.closed_at is None

        with _unit_of_work(engine) as work:
            with pytest.raises(PositionReductionError) as reduction_error:
                work.positions.reduce_lot(
                    lot.id,
                    quantity=200,
                    trade_date=date(2026, 8, 21),
                )
            assert reduction_error.value.code == "POSITION_REDUCTION_EXCEEDS_REMAINING"

        with _unit_of_work(engine) as work:
            same_day = work.positions.record_buy(
                symbol="003043.SZ",
                bucket="TACTICAL",
                quantity=100,
                acquired_trade_date=date(2026, 8, 21),
                cost_fen=6500,
                board_lot=100,
                max_position_qty=200,
            )
            with pytest.raises(PositionT1LockedError) as locked_error:
                work.positions.reduce_lot(
                    same_day.id,
                    quantity=100,
                    trade_date=date(2026, 8, 21),
                )
            assert locked_error.value.code == "POSITION_T1_LOCKED"
            assert work.positions.get_lot(same_day.id).remaining_qty == 100

        with create_session_factory(engine)() as session:
            position_audits = session.scalars(
                select(AuditLog).where(AuditLog.entity_type == "POSITION_LOT")
            ).all()
        assert [entry.action for entry in position_audits] == [
            "POSITION_BUY_RECORDED",
            "POSITION_REDUCTION_RECORDED",
        ]
        assert position_audits[1].before_hash != position_audits[1].after_hash
    finally:
        engine.dispose()


def test_alert_acknowledgement_cannot_modify_a_related_position_lot(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    alert_id = "00000000-0000-0000-0000-000000000001"

    try:
        upgrade_database(engine)
        with create_session_factory(engine)() as session:
            session.add(
                AlertEvent(
                    id=alert_id,
                    sequence=1,
                    dedup_key="a" * 64,
                    payload_json="{}",
                    message_text="test",
                    created_at=_FIXED_NOW.isoformat(),
                    acknowledged_at=None,
                )
            )
            session.commit()

        with _unit_of_work(engine) as work:
            lot = work.positions.record_buy(
                symbol="003043.SZ",
                bucket="CORE",
                quantity=100,
                acquired_trade_date=date(2026, 8, 20),
                cost_fen=6400,
                board_lot=100,
                max_position_qty=200,
                related_alert_id=alert_id,
            )
            work.commit()

        with create_session_factory(engine)() as session:
            alert = session.get(AlertEvent, alert_id)
            assert alert is not None
            alert.acknowledged_at = _FIXED_NOW.isoformat()
            session.commit()

        with _unit_of_work(engine) as work:
            after_acknowledgement = work.positions.get_lot(lot.id)
        assert after_acknowledgement == lot
        assert after_acknowledgement.remaining_qty == 100
    finally:
        engine.dispose()


def test_position_foreign_key_failure_is_sanitized(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    missing_alert_id = "00000000-0000-0000-0000-000000000099"

    try:
        upgrade_database(engine)
        with pytest.raises(RepositoryError) as captured:
            with _unit_of_work(engine) as work:
                work.positions.record_buy(
                    symbol="003043.SZ",
                    bucket="CORE",
                    quantity=100,
                    acquired_trade_date=date(2026, 8, 20),
                    cost_fen=6400,
                    board_lot=100,
                    max_position_qty=200,
                    related_alert_id=missing_alert_id,
                )
        assert captured.value.__cause__ is None
        assert missing_alert_id not in str(captured.value)
    finally:
        engine.dispose()


def test_low_zone_episode_identity_replays_and_revisions_are_deterministic(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    episode_id = "episode-1"

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            started = work.episodes.start(
                episode_id=episode_id,
                plan_hash="b" * 64,
                symbol="003043.SZ",
                zone="LOW_BUY",
                started_at=_FIXED_NOW,
                episode_low_fen=6400,
            )
            work.commit()

        with _unit_of_work(engine) as work:
            replayed = work.episodes.start(
                episode_id=episode_id,
                plan_hash="b" * 64,
                symbol="003043.SZ",
                zone="LOW_BUY",
                started_at=_FIXED_NOW,
                episode_low_fen=6400,
            )
            lower_low = work.episodes.revise(
                episode_id,
                episode_low_fen=6300,
                bars_since_low=0,
                status="ACTIVE",
                alerted_signal=None,
            )
            stable_bar = work.episodes.revise(
                episode_id,
                episode_low_fen=6300,
                bars_since_low=1,
                status="ACTIVE",
                alerted_signal=None,
            )
            work.commit()

        assert replayed == started
        assert lower_low.episode_low_fen == 6300
        assert stable_bar.bars_since_low == 1
        with _unit_of_work(engine) as work:
            with pytest.raises(EpisodeTransitionError) as increased_low:
                work.episodes.revise(
                    episode_id,
                    episode_low_fen=6350,
                    bars_since_low=2,
                    status="ACTIVE",
                    alerted_signal=None,
                )
            assert increased_low.value.code == "EPISODE_TRANSITION_INVALID"
            with pytest.raises(EpisodeTransitionError):
                work.episodes.revise(
                    episode_id,
                    episode_low_fen=6200,
                    bars_since_low=1,
                    status="ACTIVE",
                    alerted_signal=None,
                )
            with pytest.raises(EpisodeIdentityConflictError) as identity_conflict:
                work.episodes.start(
                    episode_id=episode_id,
                    plan_hash="b" * 64,
                    symbol="600000.SH",
                    zone="LOW_BUY",
                    started_at=_FIXED_NOW,
                    episode_low_fen=6400,
                )
            assert identity_conflict.value.code == "EPISODE_IDENTITY_CONFLICT"

        with create_session_factory(engine)() as session:
            episode_audits = session.scalars(
                select(AuditLog).where(AuditLog.entity_type == "ZONE_EPISODE")
            ).all()
        assert [entry.action for entry in episode_audits] == [
            "ZONE_EPISODE_STARTED",
            "ZONE_EPISODE_REVISED",
            "ZONE_EPISODE_REVISED",
        ]
    finally:
        engine.dispose()


def test_close_risk_state_uses_explicit_optimistic_revisions(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            breached = work.risk.upsert(
                symbol="003043.SZ",
                plan_hash="b" * 64,
                status="BREACHED_PENDING_CONFIRMATION",
                breach_trade_date=date(2026, 8, 21),
                prior_close_fen=6000,
                expected_revision=0,
            )
            work.commit()
        assert breached.revision == 1
        assert breached.updated_at == _FIXED_NOW

        with _unit_of_work(engine) as work:
            recovered = work.risk.upsert(
                symbol="003043.SZ",
                plan_hash="b" * 64,
                status="CLEAR",
                breach_trade_date=None,
                prior_close_fen=6100,
                expected_revision=1,
            )
            work.commit()
        assert recovered.revision == 2
        assert recovered.breach_trade_date is None

        with _unit_of_work(engine) as work:
            with pytest.raises(RevisionConflictError) as conflict:
                work.risk.upsert(
                    symbol="003043.SZ",
                    plan_hash="b" * 64,
                    status="BREACHED_PENDING_CONFIRMATION",
                    breach_trade_date=date(2026, 8, 21),
                    prior_close_fen=5990,
                    expected_revision=1,
                )
            assert conflict.value.current_revision == 2
            assert work.risk.get("003043.SZ") == recovered

        with create_session_factory(engine)() as session:
            risk_audits = session.scalars(
                select(AuditLog).where(AuditLog.entity_type == "RISK_STATE")
            ).all()
        assert [entry.action for entry in risk_audits] == [
            "RISK_STATE_UPDATED",
            "RISK_STATE_UPDATED",
        ]
    finally:
        engine.dispose()


def test_evaluation_identity_claim_is_idempotent_and_conflict_safe(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    bucket_end = datetime(2026, 8, 21, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai"))

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            first = work.evaluations.claim(
                plan_hash="b" * 64,
                symbol="003043.SZ",
                bucket_end=bucket_end,
                formula_version="ta-v1",
                result_hash="c" * 64,
                evaluated_at=_FIXED_NOW,
            )
            replay = work.evaluations.claim(
                plan_hash="b" * 64,
                symbol="003043.SZ",
                bucket_end=bucket_end.astimezone(UTC),
                formula_version="ta-v1",
                result_hash="c" * 64,
                evaluated_at=_FIXED_NOW.astimezone(UTC),
            )
            work.commit()

        assert first.created is True
        assert replay.created is False
        assert replay.record == first.record
        with _unit_of_work(engine) as work:
            with pytest.raises(EvaluationIdentityConflictError) as conflict:
                work.evaluations.claim(
                    plan_hash="b" * 64,
                    symbol="003043.SZ",
                    bucket_end=bucket_end,
                    formula_version="ta-v1",
                    result_hash="d" * 64,
                    evaluated_at=_FIXED_NOW,
                )
            assert conflict.value.code == "EVALUATION_IDENTITY_CONFLICT"

        with create_session_factory(engine)() as session:
            entries = session.scalars(select(EvaluationLedger)).all()
        assert len(entries) == 1
        assert entries[0].result_hash == "c" * 64
    finally:
        engine.dispose()


def test_provider_health_upsert_ignores_delayed_observations_and_detects_conflicts(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            ready = work.health.upsert_provider(
                capability="realtime_minutes",
                status="READY",
                checked_at=_FIXED_NOW,
                latency_ms=18,
                error_code=None,
                next_retry_at=None,
            )
            delayed = work.health.upsert_provider(
                capability="realtime_minutes",
                status="ERROR",
                checked_at=_FIXED_NOW - timedelta(minutes=1),
                latency_ms=900,
                error_code="TRANSIENT",
                next_retry_at=_FIXED_NOW + timedelta(minutes=1),
            )
            replay = work.health.upsert_provider(
                capability="realtime_minutes",
                status="READY",
                checked_at=_FIXED_NOW,
                latency_ms=18,
                error_code=None,
                next_retry_at=None,
            )
            work.commit()

        assert delayed == ready
        assert replay == ready
        with _unit_of_work(engine) as work:
            with pytest.raises(ProviderHealthConflictError) as conflict:
                work.health.upsert_provider(
                    capability="realtime_minutes",
                    status="ERROR",
                    checked_at=_FIXED_NOW,
                    latency_ms=19,
                    error_code="TRANSIENT",
                    next_retry_at=_FIXED_NOW + timedelta(minutes=1),
                )
            assert conflict.value.code == "PROVIDER_HEALTH_OBSERVATION_CONFLICT"
            assert work.health.get_provider("realtime_minutes") == ready
    finally:
        engine.dispose()


def test_symbol_health_revisions_are_isolated_per_symbol(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    latest_bar_end = datetime(
        2026,
        8,
        21,
        9,
        35,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            first = work.health.upsert_symbol(
                symbol="003043.SZ",
                status="LIVE",
                latest_bar_end=latest_bar_end,
                data_age_seconds=5,
                gaps={"missingBucketEnds": []},
                error_streak=0,
                expected_revision=0,
            )
            other = work.health.upsert_symbol(
                symbol="600000.SH",
                status="STALE",
                latest_bar_end=latest_bar_end,
                data_age_seconds=90,
                gaps={"missingBucketEnds": []},
                error_streak=1,
                expected_revision=0,
            )
            work.commit()

        assert first.revision == 1
        assert other.revision == 1
        with _unit_of_work(engine) as work:
            gapped = work.health.upsert_symbol(
                symbol="003043.SZ",
                status="GAPPED",
                latest_bar_end=latest_bar_end,
                data_age_seconds=10,
                gaps={"missingBucketEnds": ["2026-08-21T09:40:00+08:00"]},
                error_streak=1,
                expected_revision=1,
            )
            work.commit()
        assert gapped.revision == 2

        with _unit_of_work(engine) as work:
            assert work.health.get_symbol("600000.SH") == other
            with pytest.raises(RevisionConflictError) as conflict:
                work.health.upsert_symbol(
                    symbol="003043.SZ",
                    status="LIVE",
                    latest_bar_end=latest_bar_end,
                    data_age_seconds=1,
                    gaps={"missingBucketEnds": []},
                    error_streak=0,
                    expected_revision=1,
                )
            assert conflict.value.current_revision == 2
            assert work.health.get_symbol("600000.SH") == other
            with pytest.raises(ValueError, match="JSON-compatible"):
                work.health.upsert_symbol(
                    symbol="600000.SH",
                    status="STALE",
                    latest_bar_end=latest_bar_end,
                    data_age_seconds=90,
                    gaps={"invalid": float("nan")},
                    error_streak=1,
                    expected_revision=1,
                )
            assert work.health.get_symbol("600000.SH") == other
    finally:
        engine.dispose()


def test_plan_draft_is_durable_only_after_explicit_unit_of_work_commit(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan, source_text = _sample_plan()

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            work.plans.save_draft(plan, source_text=source_text)

        with _unit_of_work(engine) as work:
            assert work.plans.get_version(plan.plan_id, plan.version) is None

        with _unit_of_work(engine) as work:
            saved = work.plans.save_draft(plan, source_text=source_text)
            work.commit()

        with _unit_of_work(engine) as work:
            loaded = work.plans.get_version(plan.plan_id, plan.version)

        assert loaded == saved
        assert loaded is not None
        assert loaded.status == "DRAFT"
        assert loaded.plan_hash == plan_sha256(plan)
        assert loaded.created_at == _FIXED_NOW
        with create_session_factory(engine)() as session:
            draft_audits = session.scalars(
                select(AuditLog).where(AuditLog.action == "PLAN_DRAFT_SAVED")
            ).all()
        assert len(draft_audits) == 1
        assert draft_audits[0].before_hash is None
        assert draft_audits[0].after_hash == loaded.plan_hash
    finally:
        engine.dispose()


def test_plan_versions_are_immutable_and_duplicate_identity_is_sanitized(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan, source_text = _sample_plan()

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            original = work.plans.save_draft(plan, source_text=source_text)
            work.commit()

        changed = plan.model_copy(update={"name": "changed-name"})
        with pytest.raises(DuplicatePlanVersionError) as captured:
            with _unit_of_work(engine) as work:
                work.plans.save_draft(changed, source_text="changed source")

        assert captured.value.code == "PLAN_VERSION_EXISTS"
        assert "changed source" not in str(captured.value)
        with _unit_of_work(engine) as work:
            assert work.plans.get_version(plan.plan_id, plan.version) == original
    finally:
        engine.dispose()


def test_plan_draft_save_rejects_cross_field_validation_errors(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan, source_text = _sample_plan()
    wrong_exchange = plan.model_copy(update={"market": "SSE"})

    try:
        upgrade_database(engine)
        with pytest.raises(PlanSaveBlockedError) as captured:
            with _unit_of_work(engine) as work:
                work.plans.save_draft(wrong_exchange, source_text=source_text)
        assert captured.value.code == "PLAN_SAVE_BLOCKED"
        with _unit_of_work(engine) as work:
            assert work.plans.get_version(plan.plan_id, plan.version) is None
    finally:
        engine.dispose()


def test_unexpected_plan_integrity_error_drops_sensitive_sql_exception_chain(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan_v1, source_text = _sample_plan()
    plan_v2 = plan_v1.model_copy(update={"version": 2})
    colliding_id = "00000000-0000-0000-0000-000000000000"

    def colliding_unit_of_work() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(
            create_session_factory(engine),
            clock=lambda: _FIXED_NOW,
            id_factory=lambda: colliding_id,
        )

    try:
        upgrade_database(engine)
        with colliding_unit_of_work() as work:
            work.plans.save_draft(plan_v1, source_text=source_text)
            work.commit()

        sentinel = "SENSITIVE-SOURCE-MUST-NOT-LEAK"
        with pytest.raises(RepositoryError) as captured:
            with colliding_unit_of_work() as work:
                work.plans.save_draft(plan_v2, source_text=sentinel)

        assert captured.value.__cause__ is None
        assert sentinel not in str(captured.value)
        assert sentinel not in repr(captured.value)
    finally:
        engine.dispose()


def test_plan_activation_switches_one_active_version_with_revision_and_audit(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan_v1, source_text = _sample_plan()
    plan_v2 = plan_v1.model_copy(update={"version": 2})
    ready = validate_trade_plan(
        plan_v1,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )
    ready_v2 = validate_trade_plan(
        plan_v2,
        available_market_evidence=ALL_MARKET_EVIDENCE,
    )

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            work.plans.save_draft(plan_v1, source_text=source_text)
            work.plans.save_draft(plan_v2, source_text=source_text)
            work.commit()

        with pytest.raises(PlanActivationBlockedError):
            with _unit_of_work(engine) as work:
                work.plans.activate(
                    plan_v1,
                    expected_revision=0,
                    validation=PlanValidationResult.model_validate(
                        {
                            "issues": [
                                {
                                    "code": "UNRESOLVED_REVIEW",
                                    "path": "plan",
                                    "severity": "WARNING",
                                    "message": "Resolve before activation.",
                                    "activationBlocking": True,
                                }
                            ]
                        }
                    ),
                )

        with _unit_of_work(engine) as work:
            first = work.plans.activate(
                plan_v1,
                expected_revision=0,
                validation=ready,
            )
            work.commit()

        with pytest.raises(RevisionConflictError) as captured:
            with _unit_of_work(engine) as work:
                work.plans.activate(
                    plan_v2,
                    expected_revision=0,
                    validation=ready_v2,
                )
        assert captured.value.code == "CONFLICT"
        assert captured.value.current_revision == 1

        with _unit_of_work(engine) as work:
            second = work.plans.activate(
                plan_v2,
                expected_revision=1,
                validation=ready_v2,
            )
            work.commit()
        assert first.revision == 1
        assert second.revision == 2
        assert second.plan_version_id != first.plan_version_id

        with create_session_factory(engine)() as session:
            active_rows = session.scalars(select(ActivePlan)).all()
            audits = session.scalars(
                select(AuditLog).where(AuditLog.action == "PLAN_ACTIVATED")
            ).all()

        assert [(row.symbol, row.plan_version_id) for row in active_rows] == [
            (plan_v2.symbol, second.plan_version_id)
        ]
        assert len(audits) == 2
        initial_audit = next(audit for audit in audits if audit.before_hash is None)
        switch_audit = next(audit for audit in audits if audit.before_hash is not None)
        assert initial_audit.after_hash == switch_audit.before_hash
        assert switch_audit.after_hash != switch_audit.before_hash
        assert all(len(audit.after_hash or "") == 64 for audit in audits)
    finally:
        engine.dispose()


def test_request_idempotency_replays_completion_and_rejects_ambiguous_reuse(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            pending = work.idempotency.claim("activate-request-1", _REQUEST_HASH)
            completed = work.idempotency.complete(
                "activate-request-1",
                _REQUEST_HASH,
                response_code=200,
                response={"revision": 1, "status": "ACTIVE"},
            )
            work.commit()
        assert pending.status == "PENDING"
        assert completed.status == "COMPLETED"
        assert completed.response_json == '{"revision":1,"status":"ACTIVE"}'

        with _unit_of_work(engine) as work:
            replay = work.idempotency.claim("activate-request-1", _REQUEST_HASH)
        assert replay == completed

        with pytest.raises(IdempotencyKeyReuseError) as captured:
            with _unit_of_work(engine) as work:
                work.idempotency.claim("activate-request-1", "b" * 64)
        assert captured.value.code == "IDEMPOTENCY_KEY_REUSED"

        with _unit_of_work(engine) as work:
            work.idempotency.claim("activate-request-2", "c" * 64)
            work.commit()
        with pytest.raises(IdempotencyInProgressError) as in_progress:
            with _unit_of_work(engine) as work:
                work.idempotency.claim("activate-request-2", "c" * 64)
        assert in_progress.value.code == "IDEMPOTENCY_IN_PROGRESS"
    finally:
        engine.dispose()


def test_concurrent_plan_activation_has_one_winner_and_one_revision_conflict(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan_v1, source_text = _sample_plan()
    candidates = (
        plan_v1.model_copy(update={"version": 2}),
        plan_v1.model_copy(update={"version": 3}),
    )
    ready = tuple(
        validate_trade_plan(plan, available_market_evidence=ALL_MARKET_EVIDENCE)
        for plan in candidates
    )
    start = Barrier(2)

    def activate_candidate(plan: TradePlan, validation: PlanValidationResult) -> tuple[str, int]:
        start.wait(timeout=5)
        try:
            with _unit_of_work(engine) as work:
                active = work.plans.activate(
                    plan,
                    expected_revision=1,
                    validation=validation,
                )
                work.commit()
            return "activated", active.revision
        except RevisionConflictError as error:
            return "conflict", error.current_revision

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            work.plans.save_draft(plan_v1, source_text=source_text)
            for candidate in candidates:
                work.plans.save_draft(candidate, source_text=source_text)
            work.commit()
        with _unit_of_work(engine) as work:
            work.plans.activate(
                plan_v1,
                expected_revision=0,
                validation=validate_trade_plan(
                    plan_v1,
                    available_market_evidence=ALL_MARKET_EVIDENCE,
                ),
            )
            work.commit()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(
                future.result(timeout=10)
                for future in (
                    executor.submit(activate_candidate, candidates[0], ready[0]),
                    executor.submit(activate_candidate, candidates[1], ready[1]),
                )
            )

        assert sorted(outcome[0] for outcome in outcomes) == ["activated", "conflict"]
        assert {outcome[1] for outcome in outcomes} == {2}
        with _unit_of_work(engine) as work:
            active = work.plans.get_active(plan_v1.symbol)
        assert active is not None
        assert active.revision == 2
    finally:
        engine.dispose()


def test_plan_activation_acquires_sqlite_writer_turn_before_any_read(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan, source_text = _sample_plan()
    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.split())
        if normalized.startswith(("SELECT", "UPDATE", "INSERT", "DELETE")):
            statements.append(normalized)

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            work.plans.save_draft(plan, source_text=source_text)
            work.commit()
        event.listen(engine, "before_cursor_execute", record_statement)
        with _unit_of_work(engine) as work:
            work.plans.activate(
                plan,
                expected_revision=0,
                validation=validate_trade_plan(
                    plan,
                    available_market_evidence=ALL_MARKET_EVIDENCE,
                ),
            )
            work.commit()
        assert statements[0].startswith("UPDATE active_plan")
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)
        engine.dispose()


def test_unit_of_work_rolls_back_idempotency_activation_and_audit_together(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan, source_text = _sample_plan()
    ready = validate_trade_plan(plan, available_market_evidence=ALL_MARKET_EVIDENCE)

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            work.plans.save_draft(plan, source_text=source_text)
            work.commit()

        with pytest.raises(RuntimeError, match="simulated failure"):
            with _unit_of_work(engine) as work:
                work.idempotency.claim("rollback-request", _REQUEST_HASH)
                work.plans.activate(
                    plan,
                    expected_revision=0,
                    validation=ready,
                )
                raise RuntimeError("simulated failure")

        with _unit_of_work(engine) as work:
            assert work.plans.get_active(plan.symbol) is None
            assert work.idempotency.claim("rollback-request", _REQUEST_HASH).status == "PENDING"
        with create_session_factory(engine)() as session:
            assert (
                session.scalars(select(AuditLog).where(AuditLog.action == "PLAN_ACTIVATED")).all()
                == []
            )
    finally:
        engine.dispose()


def test_sqlite_engine_applies_required_pragmas_to_every_connection(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        with engine.connect() as first, engine.connect() as second:
            for connection in (first, second):
                assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
                assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
                assert (
                    connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one()
                    == DEFAULT_BUSY_TIMEOUT_MS
                )
    finally:
        engine.dispose()


def test_sqlite_engine_persists_wal_and_enforces_foreign_keys(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.db"
    engine = create_sqlite_engine(database_path, busy_timeout_ms=2345)

    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql(
                "CREATE TABLE child ("
                "id INTEGER PRIMARY KEY, "
                "parent_id INTEGER NOT NULL REFERENCES parent(id)"
                ")"
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql("INSERT INTO child (id, parent_id) VALUES (1, 99)")
    finally:
        engine.dispose()

    reopened = create_sqlite_engine(database_path, busy_timeout_ms=2345)
    try:
        assert _pragma_value(reopened, "journal_mode") == "wal"
        assert _pragma_value(reopened, "foreign_keys") == 1
        assert _pragma_value(reopened, "busy_timeout") == 2345
    finally:
        reopened.dispose()


@pytest.mark.parametrize(
    ("value", "error_type"),
    [
        (True, TypeError),
        ("5000", TypeError),
        (0, ValueError),
        (60_001, ValueError),
    ],
)
def test_sqlite_pragma_rejects_unsafe_busy_timeout_values(
    tmp_path: Path,
    value: object,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        create_sqlite_engine(tmp_path / "monitor.db", busy_timeout_ms=value)  # type: ignore[arg-type]


def test_sqlite_session_factory_is_bound_and_does_not_expire_on_commit(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    session_factory = create_session_factory(engine)

    try:
        with session_factory() as session:
            assert isinstance(session, Session)
            assert session.get_bind() is engine
            assert session.expire_on_commit is False
    finally:
        engine.dispose()


def test_sqlite_engine_rolls_back_ddl_inside_explicit_transaction(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.exec_driver_sql("CREATE TABLE rollback_probe (id INTEGER)")
            transaction.rollback()

        assert "rollback_probe" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_sqlite_migration_upgrades_empty_database_and_is_idempotent(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        first_tables = frozenset(inspect(engine).get_table_names())
        with engine.connect() as connection:
            first_revision = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()

        upgrade_database(engine)
        second_tables = frozenset(inspect(engine).get_table_names())
        with engine.connect() as connection:
            second_revision = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()

        assert first_tables == EXPECTED_APP_TABLES | {"alembic_version"}
        assert second_tables == first_tables
        assert first_revision == second_revision == "0002_ai_provider_configuration"
    finally:
        engine.dispose()


def test_sqlite_migration_rejects_an_engine_without_required_pragmas() -> None:
    unconfigured_engine = create_engine("sqlite+pysqlite:///:memory:")

    try:
        with pytest.raises(RuntimeError, match="WAL and foreign-key invariants"):
            upgrade_database(unconfigured_engine)
        assert inspect(unconfigured_engine).get_table_names() == []
    finally:
        unconfigured_engine.dispose()


def test_sqlite_migration_matches_model_metadata_and_has_no_secret_columns(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        inspector = inspect(engine)

        assert frozenset(Base.metadata.tables) == EXPECTED_APP_TABLES
        for table_name in EXPECTED_APP_TABLES:
            migrated_columns = {column["name"] for column in inspector.get_columns(table_name)}
            model_columns = set(Base.metadata.tables[table_name].columns.keys())
            assert migrated_columns == model_columns

            for column_name in migrated_columns:
                normalized = column_name.lower()
                assert not any(
                    marker in normalized
                    for marker in (
                        "api_key",
                        "authorization",
                        "credential",
                        "password",
                        "secret",
                    )
                )
                assert normalized != "token"
                assert not normalized.endswith("_token")
                assert "token_value" not in normalized
    finally:
        engine.dispose()


def test_sqlite_migration_has_no_metadata_drift(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        with engine.connect() as connection:
            migration_context = MigrationContext.configure(
                connection,
                opts={"render_as_batch": True},
            )
            assert compare_metadata(migration_context, Base.metadata) == []
    finally:
        engine.dispose()


def test_sqlite_migration_has_required_key_constraints_and_foreign_keys(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        inspector = inspect(engine)

        assert _key_constraints(inspector, "active_plan") >= {
            ("symbol",),
            ("plan_version_id",),
        }
        assert _key_constraints(inspector, "plan_version") >= {
            ("plan_id", "version"),
        }
        assert _key_constraints(inspector, "evaluation_ledger") >= {
            ("plan_hash", "symbol", "bucket_end", "formula_version"),
        }
        assert _key_constraints(inspector, "request_idempotency") >= {
            ("idempotency_key",),
        }
        assert _key_constraints(inspector, "alert_event") >= {
            ("id",),
            ("sequence",),
            ("dedup_key",),
        }
        assert _key_constraints(inspector, "delivery_attempt") >= {
            ("event_id", "channel", "attempt"),
        }

        assert _foreign_keys(inspector, "plan_version") >= {
            (("source_id",), "plan_source", ("id",)),
        }
        assert _foreign_keys(inspector, "active_plan") >= {
            (("plan_version_id",), "plan_version", ("id",)),
        }
        assert _foreign_keys(inspector, "position_lot") >= {
            (("related_alert_id",), "alert_event", ("id",)),
        }
        assert _foreign_keys(inspector, "delivery_attempt") >= {
            (("event_id",), "alert_event", ("id",)),
        }
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("key_ref", "environment_variable"),
    [
        ("sk-literal-secret", "MONITOR_AI_API_KEY"),
        ("ai/provider/provider-one", "sk-literal-secret"),
    ],
)
def test_ai_provider_configuration_rejects_literal_secret_in_reference_columns(
    tmp_path: Path,
    key_ref: str,
    environment_variable: str,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    timestamp = "2026-08-21T18:00:00+08:00"

    try:
        upgrade_database(engine)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO ai_provider_configuration "
                    "(id, display_name, provider_type, base_url, model_name, key_ref, "
                    "environment_variable, timeout_seconds, max_retries, max_input_chars, "
                    "max_output_tokens, temperature_milli, prompt_version, enabled, revision, "
                    "created_at, updated_at) VALUES "
                    "('provider-one', 'Provider', 'OPENAI_COMPATIBLE', "
                    "'https://ai.example.com/v1', 'model-one', :key_ref, "
                    ":environment_variable, 30, 2, 50000, 4096, 0, 'plan-extract-v1', 1, 0, "
                    ":created_at, :updated_at)",
                    {
                        "key_ref": key_ref,
                        "environment_variable": environment_variable,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                )
    finally:
        engine.dispose()


def test_ai_provider_configuration_accepts_non_secret_reference_metadata(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    timestamp = "2026-08-21T18:00:00+08:00"

    try:
        upgrade_database(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO ai_provider_configuration "
                "(id, display_name, provider_type, base_url, model_name, key_ref, "
                "environment_variable, timeout_seconds, max_retries, max_input_chars, "
                "max_output_tokens, temperature_milli, prompt_version, enabled, revision, "
                "created_at, updated_at) VALUES "
                "('provider-one', 'Provider', 'OPENAI_COMPATIBLE', "
                "'https://ai.example.com/v1', 'model-one', 'ai/provider/provider-one', "
                "'A', 30, 2, 50000, 4096, 0, 'plan-extract-v1', 1, 0, "
                ":created_at, :updated_at)",
                {"created_at": timestamp, "updated_at": timestamp},
            )
            stored = connection.exec_driver_sql(
                "SELECT key_ref, environment_variable, max_output_tokens "
                "FROM ai_provider_configuration WHERE id = 'provider-one'"
            ).one()

        assert stored == ("ai/provider/provider-one", "A", 4_096)
    finally:
        engine.dispose()


def test_sqlite_migration_enforces_app_identity_and_check_constraints(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    timestamp = "2026-08-20T10:00:00+08:00"

    try:
        upgrade_database(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO alert_event "
                "(id, sequence, dedup_key, payload_json, message_text, created_at) "
                "VALUES (:id, :sequence, :dedup_key, '{}', 'message', :created_at)",
                {
                    "id": "event-1",
                    "sequence": 1,
                    "dedup_key": "a" * 64,
                    "created_at": timestamp,
                },
            )
            connection.exec_driver_sql(
                "INSERT INTO evaluation_ledger "
                "(plan_hash, symbol, bucket_end, formula_version, result_hash, evaluated_at) "
                "VALUES (:plan_hash, '003043.SZ', :bucket_end, 'ta-v1', :result_hash, "
                ":evaluated_at)",
                {
                    "plan_hash": "b" * 64,
                    "bucket_end": timestamp,
                    "result_hash": "c" * 64,
                    "evaluated_at": timestamp,
                },
            )
            connection.exec_driver_sql(
                "INSERT INTO request_idempotency "
                "(idempotency_key, request_hash, status, created_at, updated_at) "
                "VALUES ('request-1', :request_hash, 'COMPLETED', :created_at, :updated_at)",
                {
                    "request_hash": "d" * 64,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO alert_event "
                    "(id, sequence, dedup_key, payload_json, message_text, created_at) "
                    "VALUES ('event-2', 1, :dedup_key, '{}', 'message', :created_at)",
                    {"dedup_key": "e" * 64, "created_at": timestamp},
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO alert_event "
                    "(id, sequence, dedup_key, payload_json, message_text, created_at) "
                    "VALUES ('event-3', 2, :dedup_key, '{}', 'message', :created_at)",
                    {"dedup_key": "a" * 64, "created_at": timestamp},
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO evaluation_ledger "
                    "(plan_hash, symbol, bucket_end, formula_version, result_hash, "
                    "evaluated_at) VALUES (:plan_hash, '003043.SZ', :bucket_end, 'ta-v1', "
                    ":result_hash, :evaluated_at)",
                    {
                        "plan_hash": "b" * 64,
                        "bucket_end": timestamp,
                        "result_hash": "f" * 64,
                        "evaluated_at": timestamp,
                    },
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO request_idempotency "
                    "(idempotency_key, request_hash, status, created_at, updated_at) "
                    "VALUES ('request-1', :request_hash, 'PENDING', :created_at, :updated_at)",
                    {
                        "request_hash": "1" * 64,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO delivery_attempt "
                    "(id, event_id, channel, attempt, status) "
                    "VALUES ('attempt-1', 'missing-event', 'IN_APP', 1, 'PENDING')"
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "INSERT INTO position_lot "
                    "(id, symbol, bucket, quantity, remaining_qty, acquired_trade_date, "
                    "cost_fen) VALUES "
                    "('lot-1', '003043.SZ', 'CORE', -100, 0, '2026-08-20', 6400)"
                )
    finally:
        engine.dispose()


def _key_constraints(inspector: Inspector, table_name: str) -> set[tuple[str, ...]]:
    primary_key = tuple(inspector.get_pk_constraint(table_name)["constrained_columns"])
    unique_keys = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table_name)
    }
    return {primary_key, *unique_keys}


def _foreign_keys(
    inspector: Inspector,
    table_name: str,
) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    return {
        (
            tuple(constraint["constrained_columns"]),
            constraint["referred_table"],
            tuple(constraint["referred_columns"]),
        )
        for constraint in inspector.get_foreign_keys(table_name)
    }
