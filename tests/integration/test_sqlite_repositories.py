import ast
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Barrier
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, event, inspect, select
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    ConditionEvidence,
    ConditionOutcome,
    DecisionZone,
    EvidenceFact,
    EvidenceUnit,
    NextStep,
    NextStepCode,
    SignalIntent,
)
from trade_plan_monitor.domain.plan_codec import dump_plan_json, load_plan_yaml
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import OfficialCloseBelowLevelCondition, TradePlan
from trade_plan_monitor.domain.plan_validation import (
    ALL_MARKET_EVIDENCE,
    DraftReviewIssue,
    PlanValidationResult,
    validate_trade_plan,
)
from trade_plan_monitor.notifications.identity import alert_dedup_key
from trade_plan_monitor.notifications.models import AlertPayload, AlertSeverity
from trade_plan_monitor.notifications.render import render_alert
from trade_plan_monitor.state.database import (
    DEFAULT_BUSY_TIMEOUT_MS,
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.events import MonitorEventType
from trade_plan_monitor.state.models import (
    ActivePlan,
    AlertEvent,
    AuditLog,
    Base,
    EvaluationLedger,
    MonitorSequence,
)
from trade_plan_monitor.state.repositories import (
    BoardLotViolationError,
    DuplicatePlanVersionError,
    EpisodeIdentityConflictError,
    EpisodeRecord,
    EpisodeTransitionError,
    EvaluationIdentityConflictError,
    EvaluationKind,
    EvaluationRecord,
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
        "monitor_event",
        "monitor_sequence",
        "plan_source",
        "plan_activation_state",
        "plan_version",
        "plan_version_review",
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


def _historical_alert_values(identity: int, sequence: int) -> dict[str, object]:
    event_id = UUID(int=identity)
    evaluated_at = _FIXED_NOW - timedelta(minutes=1)
    evidence = ConditionEvidence(
        condition=OfficialCloseBelowLevelCondition(level="RISK_LINE"),
        outcome=ConditionOutcome.SATISFIED,
        facts=(
            EvidenceFact(
                key="current_price_fen",
                value=6070,
                unit=EvidenceUnit.FEN,
            ),
        ),
    )
    signal = SignalIntent(
        signal_type=ActionableSignalType.RISK_BREACH,
        plan_hash="a" * 64,
        symbol="003043.SZ",
        trading_date=evaluated_at.date(),
        cause_id=f"historical-risk-{identity}",
        quantity=None,
        bucket=None,
        target_lot_id=None,
        matched_conditions=(evidence,),
        blockers=(),
        next_step=NextStep(code=NextStepCode.WAIT_FOR_NEXT_TRADING_DAY),
    )
    payload = AlertPayload(
        event_id=event_id,
        dedup_key=alert_dedup_key(signal),
        plan_id="huaya-smart",
        plan_version=1,
        plan_hash=signal.plan_hash,
        symbol=signal.symbol,
        name="华亚智能",
        signal_type=signal.signal_type,
        severity=AlertSeverity.RISK,
        trading_date=signal.trading_date,
        cause_id=signal.cause_id,
        evaluated_at=evaluated_at,
        market_data_at=evaluated_at,
        data_age_seconds=0,
        price_fen=6070,
        quantity=None,
        bucket=None,
        target_lot_id=None,
        matched_conditions=(evidence,),
        satisfied_conditions=(evidence,),
        unmet_conditions=(),
        blockers=(),
        zone=DecisionZone.BELOW_RISK,
        relevant_zone=None,
        risk_line_fen=6080,
        next_step=signal.next_step,
    )
    return {
        "id": str(event_id),
        "sequence": sequence,
        "dedup_key": payload.dedup_key,
        "payload_json": payload.model_dump_json(),
        "message_text": render_alert(payload),
        "created_at": _FIXED_NOW.isoformat(),
        "acknowledged_at": None,
    }


def _episode_audit_hash(record: EpisodeRecord) -> str:
    snapshot = {
        "alertedSignal": record.alerted_signal,
        "barsSinceLow": record.bars_since_low,
        "episodeLowFen": record.episode_low_fen,
        "id": record.id,
        "lastProcessedBucketEnd": record.last_processed_bucket_end.isoformat(),
        "planHash": record.plan_hash,
        "startedAt": record.started_at.isoformat(),
        "status": record.status,
        "symbol": record.symbol,
        "zone": record.zone,
    }
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _pragma_value(engine: Engine, pragma: str) -> object:
    with engine.connect() as connection:
        return connection.exec_driver_sql(f"PRAGMA {pragma}").scalar_one()


def _upgrade_to(engine: Engine, revision: str) -> None:
    migrations_path = (
        Path(__file__).resolve().parents[2] / "src" / "trade_plan_monitor" / "state" / "migrations"
    )
    alembic_config = Config()
    alembic_config.set_main_option("script_location", str(migrations_path))
    with engine.begin() as connection:
        alembic_config.attributes["connection"] = connection
        command.upgrade(alembic_config, revision)


def _downgrade_to(engine: Engine, revision: str) -> None:
    migrations_path = (
        Path(__file__).resolve().parents[2] / "src" / "trade_plan_monitor" / "state" / "migrations"
    )
    alembic_config = Config()
    alembic_config.set_main_option("script_location", str(migrations_path))
    with engine.begin() as connection:
        alembic_config.attributes["connection"] = connection
        command.downgrade(alembic_config, revision)


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
            assert (
                work.positions.sellable_quantity("003043.SZ", trade_date=date(2026, 8, 21)) == 200
            )
            assert (
                work.positions.sellable_quantity(
                    "003043.SZ",
                    trade_date=date(2026, 8, 21),
                    bucket="TACTICAL",
                )
                == 0
            )
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
    started_at = _FIXED_NOW + timedelta(minutes=1)
    first_cursor = datetime(2026, 8, 21, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
    lower_low_cursor = datetime(2026, 8, 21, 9, 40, tzinfo=ZoneInfo("Asia/Shanghai"))
    progress_cursor = datetime(2026, 8, 21, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai"))
    saturated_cursor = datetime(2026, 8, 21, 9, 50, tzinfo=ZoneInfo("Asia/Shanghai"))
    status_cursor = datetime(2026, 8, 21, 9, 55, tzinfo=ZoneInfo("Asia/Shanghai"))

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            started = work.episodes.start(
                episode_id=episode_id,
                plan_hash="b" * 64,
                symbol="003043.SZ",
                zone="LOW_BUY",
                started_at=started_at,
                episode_low_fen=6400,
                last_processed_bucket_end=first_cursor,
            )
            work.commit()

        with _unit_of_work(engine) as work:
            replayed = work.episodes.start(
                episode_id=episode_id,
                plan_hash="b" * 64,
                symbol="003043.SZ",
                zone="LOW_BUY",
                started_at=started_at,
                episode_low_fen=6400,
                last_processed_bucket_end=first_cursor,
            )
            no_op = work.episodes.revise(
                episode_id,
                episode_low_fen=6400,
                bars_since_low=0,
                status="ACTIVE",
                alerted_signal=None,
                last_processed_bucket_end=first_cursor,
            )
            lower_low = work.episodes.revise(
                episode_id,
                episode_low_fen=6300,
                bars_since_low=0,
                status="ACTIVE",
                alerted_signal=None,
                last_processed_bucket_end=lower_low_cursor,
            )
            stable_bar = work.episodes.revise(
                episode_id,
                episode_low_fen=6300,
                bars_since_low=1,
                status="ACTIVE",
                alerted_signal=None,
                last_processed_bucket_end=progress_cursor,
            )
            saturated = work.episodes.revise(
                episode_id,
                episode_low_fen=6300,
                bars_since_low=1,
                status="ACTIVE",
                alerted_signal=None,
                last_processed_bucket_end=saturated_cursor,
            )
            status_changed = work.episodes.revise(
                episode_id,
                episode_low_fen=6300,
                bars_since_low=1,
                status="ALERTED",
                alerted_signal="BUY_CORE_READY",
                last_processed_bucket_end=status_cursor,
            )
            work.commit()

        assert replayed == started
        assert no_op == started
        assert lower_low.episode_low_fen == 6300
        assert stable_bar.bars_since_low == 1
        assert saturated.last_processed_bucket_end == saturated_cursor
        assert status_changed.last_processed_bucket_end == status_cursor
        with _unit_of_work(engine) as work:
            delayed_start_replay = work.episodes.start(
                episode_id=episode_id,
                plan_hash="b" * 64,
                symbol="003043.SZ",
                zone="LOW_BUY",
                started_at=started_at,
                episode_low_fen=6400,
                last_processed_bucket_end=first_cursor,
            )
            for non_original_low, non_original_cursor in (
                (6500, first_cursor),
                (6400, lower_low_cursor),
            ):
                with pytest.raises(EpisodeIdentityConflictError):
                    work.episodes.start(
                        episode_id=episode_id,
                        plan_hash="b" * 64,
                        symbol="003043.SZ",
                        zone="LOW_BUY",
                        started_at=started_at,
                        episode_low_fen=non_original_low,
                        last_processed_bucket_end=non_original_cursor,
                    )
        assert delayed_start_replay == status_changed
        with _unit_of_work(engine) as work:
            with pytest.raises(EpisodeTransitionError) as increased_low:
                work.episodes.revise(
                    episode_id,
                    episode_low_fen=6350,
                    bars_since_low=2,
                    status="ACTIVE",
                    alerted_signal=None,
                    last_processed_bucket_end=datetime(
                        2026, 8, 21, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")
                    ),
                )
            assert increased_low.value.code == "EPISODE_TRANSITION_INVALID"
            with pytest.raises(EpisodeTransitionError):
                work.episodes.revise(
                    episode_id,
                    episode_low_fen=6200,
                    bars_since_low=1,
                    status="ACTIVE",
                    alerted_signal=None,
                    last_processed_bucket_end=datetime(
                        2026, 8, 21, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")
                    ),
                )
            with pytest.raises(EpisodeTransitionError, match="cursor cannot move backwards"):
                work.episodes.revise(
                    episode_id,
                    episode_low_fen=6300,
                    bars_since_low=1,
                    status="ALERTED",
                    alerted_signal="BUY_CORE_READY",
                    last_processed_bucket_end=progress_cursor,
                )
            same_cursor_changes = (
                (6200, 1, "ALERTED", "BUY_CORE_READY"),
                (6300, 2, "ALERTED", "BUY_CORE_READY"),
                (6300, 1, "ACTIVE", "BUY_CORE_READY"),
                (6300, 1, "ALERTED", "BUY_TACTICAL_READY"),
            )
            for low, bars, status, signal in same_cursor_changes:
                with pytest.raises(EpisodeTransitionError, match="same cursor"):
                    work.episodes.revise(
                        episode_id,
                        episode_low_fen=low,
                        bars_since_low=bars,
                        status=status,
                        alerted_signal=signal,
                        last_processed_bucket_end=status_cursor,
                    )
            with pytest.raises(EpisodeIdentityConflictError) as identity_conflict:
                work.episodes.start(
                    episode_id=episode_id,
                    plan_hash="b" * 64,
                    symbol="600000.SH",
                    zone="LOW_BUY",
                    started_at=started_at,
                    episode_low_fen=6400,
                    last_processed_bucket_end=first_cursor,
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
            "ZONE_EPISODE_REVISED",
            "ZONE_EPISODE_REVISED",
        ]
        assert all(
            "lastProcessedBucketEnd" in json.loads(entry.details_json) for entry in episode_audits
        )
        expected_records = (started, lower_low, stable_bar, saturated, status_changed)
        expected_hashes = tuple(_episode_audit_hash(record) for record in expected_records)
        assert tuple(entry.after_hash for entry in episode_audits) == expected_hashes
        assert tuple(entry.before_hash for entry in episode_audits) == (
            None,
            *expected_hashes[:-1],
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("episode_low_fen", "cursor"),
    [
        (6300, datetime(2026, 8, 21, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai"))),
        (6400, datetime(2026, 8, 21, 9, 40, tzinfo=ZoneInfo("Asia/Shanghai"))),
        (6300, datetime(2026, 8, 21, 9, 40, tzinfo=ZoneInfo("Asia/Shanghai"))),
    ],
    ids=("different-initial-low", "different-initial-cursor", "different-both"),
)
def test_low_zone_episode_start_rejects_conflicting_initial_state(
    tmp_path: Path,
    episode_low_fen: int,
    cursor: datetime,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    started_at = _FIXED_NOW + timedelta(minutes=1)
    first_cursor = datetime(2026, 8, 21, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai"))

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            work.episodes.start(
                episode_id="episode-start-conflict",
                plan_hash="b" * 64,
                symbol="003043.SZ",
                zone="LOW_BUY",
                started_at=started_at,
                episode_low_fen=6400,
                last_processed_bucket_end=first_cursor,
            )
            work.commit()

        with _unit_of_work(engine) as work, pytest.raises(EpisodeIdentityConflictError):
            work.episodes.start(
                episode_id="episode-start-conflict",
                plan_hash="b" * 64,
                symbol="003043.SZ",
                zone="LOW_BUY",
                started_at=started_at,
                episode_low_fen=episode_low_fen,
                last_processed_bucket_end=cursor,
            )
    finally:
        engine.dispose()


def test_low_zone_episode_start_uses_the_audited_initial_snapshot_for_a_late_cursor(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    started_at = _FIXED_NOW + timedelta(minutes=1)
    touch_cursor = datetime(2026, 8, 21, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
    late_initial_cursor = datetime(2026, 8, 21, 9, 40, tzinfo=ZoneInfo("Asia/Shanghai"))

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            initial = work.episodes.start(
                episode_id="episode-late-initial-cursor",
                plan_hash="b" * 64,
                symbol="003043.SZ",
                zone="LOW_BUY",
                started_at=started_at,
                episode_low_fen=6400,
                last_processed_bucket_end=late_initial_cursor,
            )
            work.commit()

        with _unit_of_work(engine) as work:
            exact_replay = work.episodes.start(
                episode_id="episode-late-initial-cursor",
                plan_hash="b" * 64,
                symbol="003043.SZ",
                zone="LOW_BUY",
                started_at=started_at,
                episode_low_fen=6400,
                last_processed_bucket_end=late_initial_cursor,
            )
            assert exact_replay == initial
            for conflicting_low, conflicting_cursor in (
                (6500, late_initial_cursor),
                (6400, touch_cursor),
            ):
                with pytest.raises(EpisodeIdentityConflictError):
                    work.episodes.start(
                        episode_id="episode-late-initial-cursor",
                        plan_hash="b" * 64,
                        symbol="003043.SZ",
                        zone="LOW_BUY",
                        started_at=started_at,
                        episode_low_fen=conflicting_low,
                        last_processed_bucket_end=conflicting_cursor,
                    )
    finally:
        engine.dispose()


def test_low_zone_episode_repository_enforces_forward_only_lifecycle_across_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.db"
    engine = create_sqlite_engine(database_path)
    started_at = _FIXED_NOW + timedelta(minutes=1)
    first_cursor = datetime(2026, 8, 21, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
    alerted_cursor = datetime(2026, 8, 21, 9, 40, tzinfo=ZoneInfo("Asia/Shanghai"))
    closed_cursor = datetime(2026, 8, 21, 9, 45, tzinfo=ZoneInfo("Asia/Shanghai"))

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            work.episodes.start(
                episode_id="episode-lifecycle",
                plan_hash="b" * 64,
                symbol="003043.SZ",
                zone="LOW_BUY",
                started_at=started_at,
                episode_low_fen=6400,
                last_processed_bucket_end=first_cursor,
            )
            for status, signal in (
                ("ACTIVE", "BUY_CORE_READY"),
                ("ALERTED", None),
                ("UNKNOWN", None),
            ):
                with pytest.raises(EpisodeTransitionError):
                    work.episodes.revise(
                        "episode-lifecycle",
                        episode_low_fen=6400,
                        bars_since_low=1,
                        status=status,
                        alerted_signal=signal,
                        last_processed_bucket_end=alerted_cursor,
                    )

            alerted = work.episodes.revise(
                "episode-lifecycle",
                episode_low_fen=6400,
                bars_since_low=1,
                status="ALERTED",
                alerted_signal="BUY_CORE_READY",
                last_processed_bucket_end=alerted_cursor,
            )
            assert alerted.status == "ALERTED"

            for status, signal in (
                ("ACTIVE", None),
                ("ALERTED", None),
                ("ALERTED", "BUY_TACTICAL_READY"),
            ):
                with pytest.raises(EpisodeTransitionError):
                    work.episodes.revise(
                        "episode-lifecycle",
                        episode_low_fen=6400,
                        bars_since_low=1,
                        status=status,
                        alerted_signal=signal,
                        last_processed_bucket_end=closed_cursor,
                    )

            closed = work.episodes.revise(
                "episode-lifecycle",
                episode_low_fen=6400,
                bars_since_low=1,
                status="CLOSED",
                alerted_signal="BUY_CORE_READY",
                last_processed_bucket_end=closed_cursor,
            )
            work.commit()
        assert closed.status == "CLOSED"
    finally:
        engine.dispose()

    reopened = create_sqlite_engine(database_path)
    try:
        with _unit_of_work(reopened) as work:
            restored = work.episodes.get("episode-lifecycle")
            assert restored == closed
            later_cursor = datetime(2026, 8, 21, 9, 50, tzinfo=ZoneInfo("Asia/Shanghai"))
            for status, signal in (
                ("ACTIVE", None),
                ("ALERTED", "BUY_CORE_READY"),
                ("CLOSED", "BUY_CORE_READY"),
            ):
                with pytest.raises(EpisodeTransitionError):
                    work.episodes.revise(
                        "episode-lifecycle",
                        episode_low_fen=6400,
                        bars_since_low=1,
                        status=status,
                        alerted_signal=signal,
                        last_processed_bucket_end=later_cursor,
                    )
    finally:
        reopened.dispose()


@pytest.mark.parametrize(
    "cursor",
    [
        datetime(2026, 8, 21, 9, 35),
        datetime(2026, 8, 21, 9, 35, tzinfo=UTC),
        datetime(2026, 8, 21, 9, 36, tzinfo=ZoneInfo("Asia/Shanghai")),
        datetime(2026, 8, 21, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    ],
)
def test_low_zone_episode_cursor_requires_canonical_shanghai_five_minute_bucket(
    tmp_path: Path,
    cursor: datetime,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work, pytest.raises(ValueError):
            work.episodes.start(
                episode_id="episode-invalid-cursor",
                plan_hash="b" * 64,
                symbol="003043.SZ",
                zone="LOW_BUY",
                started_at=_FIXED_NOW,
                episode_low_fen=6400,
                last_processed_bucket_end=cursor,
            )
    finally:
        engine.dispose()


def test_low_zone_episode_cursor_cannot_precede_its_touch_bucket(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work, pytest.raises(ValueError, match="touch bucket"):
            work.episodes.start(
                episode_id="episode-cursor-before-touch",
                plan_hash="b" * 64,
                symbol="003043.SZ",
                zone="LOW_BUY",
                started_at=datetime(
                    2026,
                    8,
                    21,
                    9,
                    36,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
                episode_low_fen=6400,
                last_processed_bucket_end=datetime(
                    2026,
                    8,
                    21,
                    9,
                    35,
                    tzinfo=ZoneInfo("Asia/Shanghai"),
                ),
            )
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
                evaluation_kind="INTRADAY",
                bucket_end=bucket_end,
                official_trade_date=None,
                formula_version="ta-v1",
                result_hash="c" * 64,
                evaluated_at=_FIXED_NOW,
            )
            replay = work.evaluations.claim(
                plan_hash="b" * 64,
                symbol="003043.SZ",
                evaluation_kind="INTRADAY",
                bucket_end=bucket_end.astimezone(UTC),
                official_trade_date=None,
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
                    evaluation_kind="INTRADAY",
                    bucket_end=bucket_end,
                    official_trade_date=None,
                    formula_version="ta-v1",
                    result_hash="d" * 64,
                    evaluated_at=_FIXED_NOW,
                )
            assert conflict.value.code == "EVALUATION_IDENTITY_CONFLICT"

        with create_session_factory(engine)() as session:
            entries = session.scalars(select(EvaluationLedger)).all()
        assert len(entries) == 1
        assert entries[0].evaluation_kind == "INTRADAY"
        assert entries[0].target_value == bucket_end.isoformat()
        assert entries[0].result_hash == "c" * 64
    finally:
        engine.dispose()


def test_evaluation_record_revalidates_discriminated_target_copies() -> None:
    bucket_end = datetime(2026, 8, 21, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
    record = EvaluationRecord(
        plan_hash="b" * 64,
        symbol="003043.SZ",
        evaluation_kind=EvaluationKind.INTRADAY,
        bucket_end=bucket_end,
        official_trade_date=None,
        formula_version="ta-v1",
        result_hash="c" * 64,
        evaluated_at=_FIXED_NOW,
    )

    assert record.evaluation_kind is EvaluationKind.INTRADAY
    with pytest.raises(ValueError):
        record.model_copy(update={"official_trade_date": date(2026, 8, 21)})


def test_evaluation_identity_keeps_intraday_1500_and_official_close_distinct(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    bucket_end = datetime(2026, 8, 21, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            intraday = work.evaluations.claim(
                plan_hash="b" * 64,
                symbol="003043.SZ",
                evaluation_kind="INTRADAY",
                bucket_end=bucket_end,
                official_trade_date=None,
                formula_version="ta-v1",
                result_hash="c" * 64,
                evaluated_at=_FIXED_NOW.replace(hour=15, minute=1),
            )
            official = work.evaluations.claim(
                plan_hash="b" * 64,
                symbol="003043.SZ",
                evaluation_kind="OFFICIAL_CLOSE",
                bucket_end=None,
                official_trade_date=date(2026, 8, 21),
                formula_version="ta-v1",
                result_hash="d" * 64,
                evaluated_at=_FIXED_NOW.replace(hour=15, minute=20),
            )
            official_replay = work.evaluations.claim(
                plan_hash="b" * 64,
                symbol="003043.SZ",
                evaluation_kind="OFFICIAL_CLOSE",
                bucket_end=None,
                official_trade_date=date(2026, 8, 21),
                formula_version="ta-v1",
                result_hash="d" * 64,
                evaluated_at=_FIXED_NOW.replace(hour=16),
            )
            work.commit()

        assert intraday.created is True
        assert intraday.record.bucket_end == bucket_end
        assert intraday.record.official_trade_date is None
        assert official.created is True
        assert official.record.bucket_end is None
        assert official.record.official_trade_date == date(2026, 8, 21)
        assert official_replay.created is False
        assert official_replay.record == official.record
        with _unit_of_work(engine) as work:
            with pytest.raises(EvaluationIdentityConflictError):
                work.evaluations.claim(
                    plan_hash="b" * 64,
                    symbol="003043.SZ",
                    evaluation_kind="OFFICIAL_CLOSE",
                    bucket_end=None,
                    official_trade_date=date(2026, 8, 21),
                    formula_version="ta-v1",
                    result_hash="e" * 64,
                    evaluated_at=_FIXED_NOW.replace(hour=17),
                )
        with create_session_factory(engine)() as session:
            entries = session.scalars(select(EvaluationLedger)).all()
        assert {(entry.evaluation_kind, entry.target_value) for entry in entries} == {
            ("INTRADAY", bucket_end.isoformat()),
            ("OFFICIAL_CLOSE", "2026-08-21"),
        }
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("evaluation_kind", "bucket_end", "official_trade_date"),
    [
        ("INTRADAY", None, None),
        ("INTRADAY", _FIXED_NOW.replace(minute=35), date(2026, 8, 21)),
        ("INTRADAY", _FIXED_NOW.replace(minute=36), None),
        ("OFFICIAL_CLOSE", _FIXED_NOW.replace(minute=35), None),
        ("OFFICIAL_CLOSE", None, None),
        ("UNKNOWN", _FIXED_NOW.replace(minute=35), None),
    ],
)
def test_evaluation_identity_rejects_kind_target_mismatch(
    tmp_path: Path,
    evaluation_kind: str,
    bucket_end: datetime | None,
    official_trade_date: date | None,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            with pytest.raises(ValueError):
                work.evaluations.claim(
                    plan_hash="b" * 64,
                    symbol="003043.SZ",
                    evaluation_kind=evaluation_kind,
                    bucket_end=bucket_end,
                    official_trade_date=official_trade_date,
                    formula_version="ta-v1",
                    result_hash="c" * 64,
                    evaluated_at=_FIXED_NOW,
                )
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


def test_plan_repository_reports_the_next_immutable_version(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan_v1, source_text = _sample_plan()
    plan_v3 = plan_v1.model_copy(update={"version": 3})

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            assert work.plans.next_version(plan_v1.plan_id) == 1
            work.plans.save_draft(plan_v1, source_text=source_text)
            work.plans.save_draft(plan_v3, source_text="third source")
            assert work.plans.next_version(plan_v1.plan_id) == 4
            work.commit()

        with _unit_of_work(engine) as work:
            assert work.plans.next_version(plan_v1.plan_id) == 4
            assert work.plans.get_version(plan_v1.plan_id, 1) is not None
            assert work.plans.get_version(plan_v1.plan_id, 3) is not None
    finally:
        engine.dispose()


def test_plan_draft_persists_review_details_and_initial_activation_state(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.db"
    engine = create_sqlite_engine(database_path)
    plan_v1, source_text = _sample_plan()
    plan_v2 = plan_v1.model_copy(update={"version": 2})
    review_issues = (
        DraftReviewIssue(
            kind="WARNING",
            path="levels.pressure",
            material=True,
            resolved=False,
        ),
    )

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            saved_v1 = work.plans.save_draft(
                plan_v1,
                source_text=source_text,
                review_issues=review_issues,
            )
            saved_v2 = work.plans.save_draft(plan_v2, source_text="second source")
            work.commit()
    finally:
        engine.dispose()

    restarted = create_sqlite_engine(database_path)
    try:
        with _unit_of_work(restarted) as work:
            details = work.plans.get_version_details(saved_v1.id)
            items, total = work.plans.list_version_details(
                offset=0,
                limit=10,
                symbol=plan_v1.symbol,
                status="DRAFT",
            )
            empty, empty_total = work.plans.list_version_details(
                offset=0,
                limit=10,
                symbol="600000.SH",
                status=None,
            )
            activation = work.plans.get_activation_state(plan_v1.symbol)

        assert details is not None
        assert details.id == saved_v1.id
        assert details.source_text == source_text
        assert details.review_issues == review_issues
        assert total == 2
        assert tuple(item.id for item in items) == tuple(
            sorted((saved_v1.id, saved_v2.id), reverse=True)
        )
        assert empty == ()
        assert empty_total == 0
        assert activation is not None
        assert activation.symbol == plan_v1.symbol
        assert activation.plan_version_id is None
        assert activation.revision == 0
        assert activation.changed_at == _FIXED_NOW
    finally:
        restarted.dispose()


def test_plan_detail_rejects_invalid_persisted_review_json_without_leaking_it(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan, source_text = _sample_plan()
    sentinel = "SENSITIVE-INVALID-REVIEW"

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            saved = work.plans.save_draft(plan, source_text=source_text)
            work.commit()
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE plan_version_review SET review_issues_json = :value "
                "WHERE plan_version_id = :plan_version_id",
                {"value": sentinel, "plan_version_id": saved.id},
            )

        with pytest.raises(RepositoryError) as captured:
            with _unit_of_work(engine) as work:
                work.plans.get_version_details(saved.id)

        assert captured.value.__cause__ is None
        assert captured.value.__context__ is None
        assert sentinel not in str(captured.value)
        assert sentinel not in repr(captured.value)
    finally:
        engine.dispose()


def test_plan_detail_and_page_reject_a_missing_persisted_review_row(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan, source_text = _sample_plan()

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            saved = work.plans.save_draft(plan, source_text=source_text)
            work.commit()
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "DELETE FROM plan_version_review WHERE plan_version_id = :plan_version_id",
                {"plan_version_id": saved.id},
            )

        with pytest.raises(RepositoryError) as detail_error:
            with _unit_of_work(engine) as work:
                work.plans.get_version_details(saved.id)
        with pytest.raises(RepositoryError) as page_error:
            with _unit_of_work(engine) as work:
                work.plans.list_version_details(offset=0, limit=20)

        for error in (detail_error.value, page_error.value):
            assert error.__cause__ is None
            assert error.__context__ is None
            assert saved.id not in str(error)
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


def test_plan_deactivation_revision_and_review_state_survive_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "monitor.db"
    engine = create_sqlite_engine(database_path)
    plan_v1, source_text = _sample_plan()
    plan_v2 = plan_v1.model_copy(update={"version": 2})
    ready_v1 = validate_trade_plan(plan_v1, available_market_evidence=ALL_MARKET_EVIDENCE)
    ready_v2 = validate_trade_plan(plan_v2, available_market_evidence=ALL_MARKET_EVIDENCE)

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            saved_v1 = work.plans.save_draft(plan_v1, source_text=source_text)
            work.plans.save_draft(plan_v2, source_text=source_text)
            work.commit()
        with _unit_of_work(engine) as work:
            active = work.plans.activate(plan_v1, expected_revision=0, validation=ready_v1)
            work.commit()
        with _unit_of_work(engine) as work:
            inactive = work.plans.deactivate(plan_v1.symbol, expected_revision=1)
            work.commit()

        assert active.revision == 1
        assert inactive.plan_version_id is None
        assert inactive.revision == 2
        with _unit_of_work(engine) as work:
            assert work.plans.get_active(plan_v1.symbol) is None
            deactivated_version = work.plans.get_version(plan_v1.plan_id, plan_v1.version)
        assert deactivated_version is not None
        assert deactivated_version.id == saved_v1.id
        assert deactivated_version.status == "SUPERSEDED"
        assert deactivated_version.revision == 2
    finally:
        engine.dispose()

    restarted = create_sqlite_engine(database_path)
    try:
        with _unit_of_work(restarted) as work:
            restored = work.plans.get_activation_state(plan_v1.symbol)
            reactivated = work.plans.activate(
                plan_v2,
                expected_revision=2,
                validation=ready_v2,
            )
            work.commit()
        assert restored is not None
        assert restored.plan_version_id is None
        assert restored.revision == 2
        assert reactivated.revision == 3

        with _unit_of_work(restarted) as work:
            events = work.events.replay_page_after(0).events
        deactivated = next(
            event for event in events if event.event_type is MonitorEventType.PLAN_DEACTIVATED
        )
        assert deactivated.aggregate_id == plan_v1.symbol
        assert deactivated.payload.model_dump(exclude_none=True) == {
            "entity_id": plan_v1.symbol,
            "symbol": plan_v1.symbol,
            "revision": 2,
        }
        with create_session_factory(restarted)() as session:
            plan_audits = [
                audit
                for audit in session.scalars(select(AuditLog)).all()
                if audit.action in {"PLAN_ACTIVATED", "PLAN_DEACTIVATED"}
            ]
        deactivation_audit = next(
            audit for audit in plan_audits if audit.action == "PLAN_DEACTIVATED"
        )
        activation_audits = [audit for audit in plan_audits if audit.action == "PLAN_ACTIVATED"]
        initial_activation_audit = next(
            audit for audit in activation_audits if json.loads(audit.details_json)["revision"] == 1
        )
        reactivation_audit = next(
            audit for audit in activation_audits if json.loads(audit.details_json)["revision"] == 3
        )
        assert deactivation_audit.entity_id == plan_v1.symbol
        assert deactivation_audit.before_hash == initial_activation_audit.after_hash
        assert reactivation_audit.before_hash == deactivation_audit.after_hash
        assert len(deactivation_audit.after_hash or "") == 64
    finally:
        restarted.dispose()


def test_plan_deactivation_rejects_a_stale_revision_without_mutation(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan, source_text = _sample_plan()
    ready = validate_trade_plan(plan, available_market_evidence=ALL_MARKET_EVIDENCE)

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            work.plans.save_draft(plan, source_text=source_text)
            work.commit()
        with _unit_of_work(engine) as work:
            active = work.plans.activate(plan, expected_revision=0, validation=ready)
            work.commit()

        with pytest.raises(RevisionConflictError) as captured:
            with _unit_of_work(engine) as work:
                work.plans.deactivate(plan.symbol, expected_revision=0)

        assert captured.value.current_revision == 1
        with _unit_of_work(engine) as work:
            assert work.plans.get_active(plan.symbol) == active
            assert work.plans.get_activation_state(plan.symbol).revision == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "drift",
    (
        "missing_pointer",
        "plan_version_id",
        "revision",
        "timestamp",
        "invalid_timestamp",
    ),
)
def test_plan_activation_state_read_rejects_legacy_pointer_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan_v1, source_text = _sample_plan()
    plan_v2 = plan_v1.model_copy(update={"version": 2})
    ready = validate_trade_plan(plan_v1, available_market_evidence=ALL_MARKET_EVIDENCE)

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            work.plans.save_draft(plan_v1, source_text=source_text)
            saved_v2 = work.plans.save_draft(plan_v2, source_text=source_text)
            work.commit()
        with _unit_of_work(engine) as work:
            work.plans.activate(plan_v1, expected_revision=0, validation=ready)
            work.commit()

        with engine.begin() as connection:
            if drift == "missing_pointer":
                connection.exec_driver_sql(
                    "DELETE FROM active_plan WHERE symbol = :symbol",
                    {"symbol": plan_v1.symbol},
                )
            elif drift == "plan_version_id":
                connection.exec_driver_sql(
                    "UPDATE active_plan SET plan_version_id = :plan_version_id "
                    "WHERE symbol = :symbol",
                    {"plan_version_id": saved_v2.id, "symbol": plan_v1.symbol},
                )
            elif drift == "revision":
                connection.exec_driver_sql(
                    "UPDATE active_plan SET revision = revision + 1 WHERE symbol = :symbol",
                    {"symbol": plan_v1.symbol},
                )
            elif drift == "timestamp":
                connection.exec_driver_sql(
                    "UPDATE active_plan SET activated_at = :activated_at WHERE symbol = :symbol",
                    {
                        "activated_at": (_FIXED_NOW + timedelta(minutes=1)).isoformat(),
                        "symbol": plan_v1.symbol,
                    },
                )
            else:
                connection.exec_driver_sql(
                    "UPDATE active_plan SET activated_at = 'SENSITIVE-INVALID-TIMESTAMP' "
                    "WHERE symbol = :symbol",
                    {"symbol": plan_v1.symbol},
                )

        with pytest.raises(RepositoryError) as captured:
            with _unit_of_work(engine) as work:
                work.plans.get_activation_state(plan_v1.symbol)
        assert captured.value.__cause__ is None
        assert captured.value.__context__ is None
        assert saved_v2.id not in str(captured.value)
        assert "SENSITIVE-INVALID-TIMESTAMP" not in str(captured.value)
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


def test_request_idempotency_accepts_four_mib_response_and_rejects_the_next_byte(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    response_limit = 4 * 1024 * 1024
    canonical_overhead = len('{"value":""}')

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            work.idempotency.claim("four-mib-response", "d" * 64)
            accepted = work.idempotency.complete(
                "four-mib-response",
                "d" * 64,
                response_code=200,
                response={"value": "x" * (response_limit - canonical_overhead)},
            )
            work.commit()
        assert accepted.response_json is not None
        assert len(accepted.response_json.encode("utf-8")) == response_limit

        with pytest.raises(ValueError, match="response exceeds"):
            with _unit_of_work(engine) as work:
                work.idempotency.claim("over-four-mib-response", "e" * 64)
                work.idempotency.complete(
                    "over-four-mib-response",
                    "e" * 64,
                    response_code=200,
                    response={"value": "x" * (response_limit - canonical_overhead + 1)},
                )
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
        assert statements[0].startswith("UPDATE plan_activation_state")
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
        assert first_revision == second_revision == "0007_plan_web_state"
    finally:
        engine.dispose()


def test_sqlite_migration_upgrades_empty_0002_episode_table_with_required_cursor(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        _upgrade_to(engine, "0002_ai_provider_configuration")
        assert "last_processed_bucket_end" not in {
            column["name"] for column in inspect(engine).get_columns("zone_episode")
        }

        upgrade_database(engine)

        cursor_column = next(
            column
            for column in inspect(engine).get_columns("zone_episode")
            if column["name"] == "last_processed_bucket_end"
        )
        assert cursor_column["nullable"] is False
        assert cursor_column["type"].length == 40
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == "0007_plan_web_state"
            )
    finally:
        engine.dispose()


def test_plan_web_state_migration_backfills_without_changing_existing_plan_rows(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan, source_text = _sample_plan()
    inactive_plan = plan.model_copy(update={"plan_id": "inactive-plan", "symbol": "003044.SZ"})
    source_id = "00000000-0000-0000-0000-000000000701"
    version_id = "00000000-0000-0000-0000-000000000702"
    inactive_source_id = "00000000-0000-0000-0000-000000000703"
    inactive_version_id = "00000000-0000-0000-0000-000000000704"
    changed_at = "2026-08-21T09:31:00+08:00"
    inactive_changed_at = "2026-08-20T09:31:00+08:00"

    try:
        _upgrade_to(engine, "0006_monitor_event")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO plan_source (id, source_text, source_hash, created_at) "
                "VALUES (:id, :source_text, :source_hash, :created_at)",
                {
                    "id": source_id,
                    "source_text": source_text,
                    "source_hash": sha256(source_text.encode("utf-8")).hexdigest(),
                    "created_at": changed_at,
                },
            )
            connection.exec_driver_sql(
                "INSERT INTO plan_version "
                "(id, plan_id, version, symbol, plan_hash, status, payload_json, source_id, "
                "revision, created_at) VALUES "
                "(:id, :plan_id, :version, :symbol, :plan_hash, 'ACTIVE', :payload_json, "
                ":source_id, 1, :created_at)",
                {
                    "id": version_id,
                    "plan_id": plan.plan_id,
                    "version": plan.version,
                    "symbol": plan.symbol,
                    "plan_hash": plan_sha256(plan),
                    "payload_json": dump_plan_json(plan),
                    "source_id": source_id,
                    "created_at": changed_at,
                },
            )
            connection.exec_driver_sql(
                "INSERT INTO active_plan "
                "(symbol, plan_version_id, activated_at, revision) "
                "VALUES (:symbol, :plan_version_id, :activated_at, 3)",
                {
                    "symbol": plan.symbol,
                    "plan_version_id": version_id,
                    "activated_at": changed_at,
                },
            )
            connection.exec_driver_sql(
                "INSERT INTO plan_source (id, source_text, source_hash, created_at) "
                "VALUES (:id, :source_text, :source_hash, :created_at)",
                {
                    "id": inactive_source_id,
                    "source_text": source_text,
                    "source_hash": sha256(source_text.encode("utf-8")).hexdigest(),
                    "created_at": inactive_changed_at,
                },
            )
            connection.exec_driver_sql(
                "INSERT INTO plan_version "
                "(id, plan_id, version, symbol, plan_hash, status, payload_json, source_id, "
                "revision, created_at) VALUES "
                "(:id, :plan_id, :version, :symbol, :plan_hash, 'DRAFT', :payload_json, "
                ":source_id, 0, :created_at)",
                {
                    "id": inactive_version_id,
                    "plan_id": inactive_plan.plan_id,
                    "version": inactive_plan.version,
                    "symbol": inactive_plan.symbol,
                    "plan_hash": plan_sha256(inactive_plan),
                    "payload_json": dump_plan_json(inactive_plan),
                    "source_id": inactive_source_id,
                    "created_at": inactive_changed_at,
                },
            )
            before = connection.exec_driver_sql(
                "SELECT id, plan_id, version, symbol, plan_hash, status, payload_json, "
                "source_id, revision, created_at FROM plan_version ORDER BY id"
            ).all()

        upgrade_database(engine)

        with engine.connect() as connection:
            after = connection.exec_driver_sql(
                "SELECT id, plan_id, version, symbol, plan_hash, status, payload_json, "
                "source_id, revision, created_at FROM plan_version ORDER BY id"
            ).all()
            reviews = connection.exec_driver_sql(
                "SELECT plan_version_id, review_issues_json FROM plan_version_review "
                "ORDER BY plan_version_id"
            ).all()
            activations = connection.exec_driver_sql(
                "SELECT symbol, plan_version_id, revision, changed_at "
                "FROM plan_activation_state ORDER BY symbol"
            ).all()

        assert after == before
        assert reviews == [(version_id, "[]"), (inactive_version_id, "[]")]
        assert activations == [
            (plan.symbol, version_id, 3, changed_at),
            (inactive_plan.symbol, None, 0, inactive_changed_at),
        ]
    finally:
        engine.dispose()


def test_plan_web_state_migration_round_trips_reconstructible_state(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan, source_text = _sample_plan()

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            saved = work.plans.save_draft(plan, source_text=source_text)
            work.commit()

        _downgrade_to(engine, "0006_monitor_event")

        tables = frozenset(inspect(engine).get_table_names())
        assert "plan_version_review" not in tables
        assert "plan_activation_state" not in tables
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == "0006_monitor_event"
            )

        upgrade_database(engine)

        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT plan_version_id, review_issues_json FROM plan_version_review"
            ).one() == (saved.id, "[]")
            assert connection.exec_driver_sql(
                "SELECT symbol, plan_version_id, revision, changed_at FROM plan_activation_state"
            ).one() == (plan.symbol, None, 0, _FIXED_NOW.isoformat())
    finally:
        engine.dispose()


def test_plan_web_state_migration_round_trips_an_active_pointer(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    plan, source_text = _sample_plan()
    validation = validate_trade_plan(plan, available_market_evidence=ALL_MARKET_EVIDENCE)

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            saved = work.plans.save_draft(plan, source_text=source_text)
            work.commit()
        with _unit_of_work(engine) as work:
            active = work.plans.activate(plan, expected_revision=0, validation=validation)
            work.commit()

        _downgrade_to(engine, "0006_monitor_event")
        upgrade_database(engine)

        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT plan_version_id, review_issues_json FROM plan_version_review"
            ).one() == (saved.id, "[]")
            assert connection.exec_driver_sql(
                "SELECT symbol, plan_version_id, revision, changed_at FROM plan_activation_state"
            ).one() == (
                plan.symbol,
                active.plan_version_id,
                active.revision,
                active.activated_at.isoformat(),
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("loss_kind", ("review", "deactivation"))
def test_plan_web_state_migration_refuses_lossy_downgrade_atomically(
    tmp_path: Path,
    loss_kind: str,
) -> None:
    engine = create_sqlite_engine(tmp_path / f"monitor-{loss_kind}.db")
    plan, source_text = _sample_plan()

    try:
        upgrade_database(engine)
        with _unit_of_work(engine) as work:
            saved = work.plans.save_draft(plan, source_text=source_text)
            work.commit()
        if loss_kind == "review":
            issue = DraftReviewIssue(
                kind="WARNING",
                path="levels.pressure",
                material=True,
                resolved=False,
            )
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE plan_version_review SET review_issues_json = :review "
                    "WHERE plan_version_id = :plan_version_id",
                    {
                        "plan_version_id": saved.id,
                        "review": json.dumps(
                            [issue.model_dump(mode="json")],
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    },
                )
        else:
            validation = validate_trade_plan(
                plan,
                available_market_evidence=ALL_MARKET_EVIDENCE,
            )
            with _unit_of_work(engine) as work:
                work.plans.activate(plan, expected_revision=0, validation=validation)
                work.commit()
            with _unit_of_work(engine) as work:
                work.plans.deactivate(plan.symbol, expected_revision=1)
                work.commit()

        with engine.connect() as connection:
            reviews_before = connection.exec_driver_sql(
                "SELECT plan_version_id, review_issues_json FROM plan_version_review "
                "ORDER BY plan_version_id"
            ).all()
            states_before = connection.exec_driver_sql(
                "SELECT symbol, plan_version_id, revision, changed_at "
                "FROM plan_activation_state ORDER BY symbol"
            ).all()

        with pytest.raises(RuntimeError, match="refuses to discard plan Web state"):
            _downgrade_to(engine, "0006_monitor_event")

        assert {"plan_version_review", "plan_activation_state"} <= frozenset(
            inspect(engine).get_table_names()
        )
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == "0007_plan_web_state"
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT plan_version_id, review_issues_json FROM plan_version_review "
                    "ORDER BY plan_version_id"
                ).all()
                == reviews_before
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT symbol, plan_version_id, revision, changed_at "
                    "FROM plan_activation_state ORDER BY symbol"
                ).all()
                == states_before
            )
    finally:
        engine.dispose()


def test_alert_sequence_migration_backfills_existing_high_water(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        _upgrade_to(engine, "0003_episode_cursor")
        with create_session_factory(engine).begin() as session:
            session.add(AlertEvent(**_historical_alert_values(41, 41)))

        upgrade_database(engine)

        with create_session_factory(engine)() as session:
            sequence = session.get(MonitorSequence, 1)
            assert sequence is not None
            assert sequence.last_sequence == 41
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == "0007_plan_web_state"
            )
    finally:
        engine.dispose()


def test_monitor_event_migration_renames_high_water_and_backfills_alerts(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        _upgrade_to(engine, "0005_evaluation_kind")
        alert_values = _historical_alert_values(42, 42)
        alert_id = str(alert_values["id"])
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO alert_event "
                "(id, sequence, dedup_key, payload_json, message_text, created_at, "
                "acknowledged_at) VALUES (:id, :sequence, :dedup_key, :payload_json, "
                ":message_text, :created_at, :acknowledged_at)",
                alert_values,
            )
            connection.exec_driver_sql(
                "UPDATE alert_sequence SET last_sequence = 42 WHERE singleton_id = 1"
            )

        upgrade_database(engine)

        tables = frozenset(inspect(engine).get_table_names())
        assert "monitor_event" in tables
        assert "monitor_sequence" in tables
        assert "alert_sequence" not in tables
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT id, sequence, event_type, aggregate_id, payload_json, occurred_at "
                "FROM monitor_event"
            ).one()
            high_water = connection.exec_driver_sql(
                "SELECT last_sequence FROM monitor_sequence WHERE singleton_id = 1"
            ).scalar_one()
            revision = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()

        assert row[:4] == (alert_id, 42, "alert.created", alert_id)
        assert json.loads(row.payload_json) == {
            "entityId": alert_id,
            "revision": 0,
            "symbol": "003043.SZ",
        }
        assert row.occurred_at == _FIXED_NOW.isoformat()
        assert high_water == 42
        assert revision == "0007_plan_web_state"
    finally:
        engine.dispose()


def test_monitor_event_migration_contract_is_frozen_inside_its_revision() -> None:
    revision_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "trade_plan_monitor"
        / "state"
        / "migrations"
        / "versions"
        / "0006_monitor_event.py"
    )
    tree = ast.parse(revision_path.read_text(encoding="utf-8"))
    application_imports = tuple(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("trade_plan_monitor")
    )

    assert application_imports == ()


@pytest.mark.parametrize(
    "invalid_field",
    (
        "payload_event_id",
        "missing_payload_field",
        "dedup_key",
        "matched_evidence_shape",
        "unmet_evidence_shape",
        "partition_outcome",
        "condition_shape",
        "fact_type",
        "evidence_budget",
        "numeric_budget",
        "next_step",
        "market_age",
        "market_age_overflow",
        "message_text",
        "message_control",
        "created_at",
        "high_water",
    ),
)
def test_monitor_event_migration_rejects_invalid_historical_alert_atomically(
    tmp_path: Path,
    invalid_field: str,
) -> None:
    engine = create_sqlite_engine(tmp_path / f"monitor-{invalid_field}.db")
    values = _historical_alert_values(45, 45)
    if invalid_field == "payload_event_id":
        payload = json.loads(str(values["payload_json"]))
        payload["event_id"] = str(UUID(int=46))
        values["payload_json"] = json.dumps(payload, separators=(",", ":"))
    elif invalid_field == "missing_payload_field":
        payload = json.loads(str(values["payload_json"]))
        del payload["plan_id"]
        values["payload_json"] = json.dumps(payload, separators=(",", ":"))
    elif invalid_field == "dedup_key":
        values["dedup_key"] = "f" * 64
    elif invalid_field == "matched_evidence_shape":
        payload = json.loads(str(values["payload_json"]))
        payload["matched_conditions"] = [{}]
        payload["satisfied_conditions"] = [{}]
        values["payload_json"] = json.dumps(payload, separators=(",", ":"))
    elif invalid_field == "unmet_evidence_shape":
        payload = json.loads(str(values["payload_json"]))
        payload["unmet_conditions"] = [{}]
        values["payload_json"] = json.dumps(payload, separators=(",", ":"))
    elif invalid_field == "partition_outcome":
        payload = json.loads(str(values["payload_json"]))
        payload["matched_conditions"][0]["outcome"] = "UNSATISFIED"
        payload["satisfied_conditions"][0]["outcome"] = "UNSATISFIED"
        values["payload_json"] = json.dumps(payload, separators=(",", ":"))
    elif invalid_field == "condition_shape":
        payload = json.loads(str(values["payload_json"]))
        payload["matched_conditions"][0]["condition"]["unexpected"] = True
        payload["satisfied_conditions"][0]["condition"]["unexpected"] = True
        values["payload_json"] = json.dumps(payload, separators=(",", ":"))
    elif invalid_field == "fact_type":
        payload = json.loads(str(values["payload_json"]))
        payload["matched_conditions"][0]["facts"][0]["value"] = True
        payload["satisfied_conditions"][0]["facts"][0]["value"] = True
        values["payload_json"] = json.dumps(payload, separators=(",", ":"))
    elif invalid_field == "evidence_budget":
        payload = json.loads(str(values["payload_json"]))
        oversized = payload["satisfied_conditions"][0]
        oversized["facts"] = [
            {"key": f"fact_{index:03d}", "value": index, "unit": "COUNT"} for index in range(300)
        ]
        second = json.loads(json.dumps(oversized))
        second["facts"] = [
            {"key": f"other_{index:03d}", "value": index, "unit": "COUNT"} for index in range(300)
        ]
        payload["satisfied_conditions"] = [
            payload["matched_conditions"][0],
            oversized,
            second,
        ]
        values["payload_json"] = json.dumps(payload, separators=(",", ":"))
    elif invalid_field == "numeric_budget":
        payload = json.loads(str(values["payload_json"]))
        payload["plan_version"] = 10**256
        values["payload_json"] = json.dumps(payload, separators=(",", ":"))
    elif invalid_field == "next_step":
        payload = json.loads(str(values["payload_json"]))
        payload["next_step"]["required_inputs"] = ["NOT_A_REAL_INPUT"]
        values["payload_json"] = json.dumps(payload, separators=(",", ":"))
    elif invalid_field == "market_age":
        payload = json.loads(str(values["payload_json"]))
        payload["evaluated_at"] = "2026-08-21T09:29:00.500000+08:00"
        payload["market_data_at"] = "2026-08-21T09:29:00+08:00"
        payload["data_age_seconds"] = 0
        values["payload_json"] = json.dumps(payload, separators=(",", ":"))
    elif invalid_field == "market_age_overflow":
        payload = json.loads(str(values["payload_json"]))
        payload["data_age_seconds"] = 10**256
        values["payload_json"] = json.dumps(payload, separators=(",", ":"))
    elif invalid_field == "message_text":
        values["message_text"] = "clean but non-deterministic historical message"
    elif invalid_field == "message_control":
        values["message_text"] = "invalid\x00historical message"
    elif invalid_field == "created_at":
        values["created_at"] = "not-a-timestamp"

    try:
        _upgrade_to(engine, "0005_evaluation_kind")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO alert_event "
                "(id, sequence, dedup_key, payload_json, message_text, created_at, "
                "acknowledged_at) VALUES (:id, :sequence, :dedup_key, :payload_json, "
                ":message_text, :created_at, :acknowledged_at)",
                values,
            )
            connection.exec_driver_sql(
                "UPDATE alert_sequence SET last_sequence = 45 WHERE singleton_id = 1"
            )
            if invalid_field == "high_water":
                connection.exec_driver_sql(
                    "UPDATE alert_sequence SET last_sequence = 44 WHERE singleton_id = 1"
                )

        with pytest.raises(RuntimeError, match="invalid historical alert") as error_info:
            upgrade_database(engine)

        assert error_info.value.__context__ is None
        assert error_info.value.__cause__ is None
        tables = frozenset(inspect(engine).get_table_names())
        assert "alert_sequence" in tables
        assert "monitor_sequence" not in tables
        assert "monitor_event" not in tables
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == "0005_evaluation_kind"
            )
            assert connection.exec_driver_sql("SELECT COUNT(*) FROM alert_event").scalar_one() == 1
    finally:
        engine.dispose()


def test_monitor_event_migration_downgrades_without_new_event_identities(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        _downgrade_to(engine, "0005_evaluation_kind")

        tables = frozenset(inspect(engine).get_table_names())
        assert "alert_sequence" in tables
        assert "monitor_sequence" not in tables
        assert "monitor_event" not in tables
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == "0005_evaluation_kind"
            )
    finally:
        engine.dispose()


def test_monitor_event_migration_refuses_lossy_non_alert_downgrade(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO monitor_event "
                "(id, sequence, event_type, schema_version, aggregate_id, payload_json, "
                "occurred_at) VALUES (:id, 1, 'system.health.updated', 1, "
                "'TUSHARE_RT_MIN', :payload, :occurred_at)",
                {
                    "id": "00000000-0000-0000-0000-000000000043",
                    "payload": '{"entityId":"TUSHARE_RT_MIN","status":"READY"}',
                    "occurred_at": _FIXED_NOW.isoformat(),
                },
            )
            connection.exec_driver_sql(
                "UPDATE monitor_sequence SET last_sequence = 1 WHERE singleton_id = 1"
            )

        with pytest.raises(RuntimeError, match="refuses to discard monitor event"):
            _downgrade_to(engine, "0005_evaluation_kind")

        assert "monitor_event" in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == "0007_plan_web_state"
            )
    finally:
        engine.dispose()


def test_evaluation_kind_migration_preserves_populated_0004_intraday_rows(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    bucket_end = "2026-08-21T15:00:00+08:00"
    evaluated_at = "2026-08-21T15:01:00+08:00"

    try:
        _upgrade_to(engine, "0004_alert_sequence")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO evaluation_ledger "
                "(plan_hash, symbol, bucket_end, formula_version, result_hash, evaluated_at) "
                "VALUES (:plan_hash, '003043.SZ', :bucket_end, 'ta-v1', :result_hash, "
                ":evaluated_at)",
                {
                    "plan_hash": "b" * 64,
                    "bucket_end": bucket_end,
                    "result_hash": "c" * 64,
                    "evaluated_at": evaluated_at,
                },
            )

        upgrade_database(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("evaluation_ledger")}
        assert "bucket_end" not in columns
        assert {"evaluation_kind", "target_value"} <= columns
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT plan_hash, symbol, evaluation_kind, target_value, formula_version, "
                "result_hash, evaluated_at FROM evaluation_ledger"
            ).one()
            revision = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()

        assert row == (
            "b" * 64,
            "003043.SZ",
            "INTRADAY",
            bucket_end,
            "ta-v1",
            "c" * 64,
            evaluated_at,
        )
        assert revision == "0007_plan_web_state"
    finally:
        engine.dispose()


def test_evaluation_kind_migration_downgrades_intraday_rows_without_loss(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    bucket_end = "2026-08-21T15:00:00+08:00"

    try:
        upgrade_database(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO evaluation_ledger "
                "(plan_hash, symbol, evaluation_kind, target_value, formula_version, "
                "result_hash, evaluated_at) VALUES (:plan_hash, '003043.SZ', "
                "'INTRADAY', :target_value, 'ta-v1', :result_hash, :evaluated_at)",
                {
                    "plan_hash": "b" * 64,
                    "target_value": bucket_end,
                    "result_hash": "c" * 64,
                    "evaluated_at": "2026-08-21T15:01:00+08:00",
                },
            )

        _downgrade_to(engine, "0004_alert_sequence")

        assert {column["name"] for column in inspect(engine).get_columns("evaluation_ledger")} >= {
            "bucket_end"
        }
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT bucket_end, result_hash FROM evaluation_ledger"
            ).one()
            revision = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()
        assert row == (bucket_end, "c" * 64)
        assert revision == "0004_alert_sequence"
    finally:
        engine.dispose()


def test_evaluation_kind_migration_refuses_lossy_official_close_downgrade(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")

    try:
        upgrade_database(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO evaluation_ledger "
                "(plan_hash, symbol, evaluation_kind, target_value, formula_version, "
                "result_hash, evaluated_at) VALUES (:plan_hash, '003043.SZ', "
                "'OFFICIAL_CLOSE', '2026-08-21', 'ta-v1', :result_hash, :evaluated_at)",
                {
                    "plan_hash": "b" * 64,
                    "result_hash": "c" * 64,
                    "evaluated_at": "2026-08-21T15:20:00+08:00",
                },
            )

        with pytest.raises(RuntimeError, match="refuses to discard official-close"):
            _downgrade_to(engine, "0004_alert_sequence")

        columns = {column["name"] for column in inspect(engine).get_columns("evaluation_ledger")}
        assert {"evaluation_kind", "target_value"} <= columns
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == "0007_plan_web_state"
            )
            assert connection.exec_driver_sql(
                "SELECT evaluation_kind, target_value FROM evaluation_ledger"
            ).one() == ("OFFICIAL_CLOSE", "2026-08-21")
    finally:
        engine.dispose()


def test_sqlite_migration_rejects_populated_0002_episode_table_before_ddl(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "monitor.db")
    timestamp = "2026-08-21T09:30:00+08:00"

    try:
        _upgrade_to(engine, "0002_ai_provider_configuration")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO zone_episode "
                "(id, plan_hash, symbol, zone, started_at, episode_low_fen, "
                "bars_since_low, status, alerted_signal) VALUES "
                "('episode-existing', :plan_hash, '003043.SZ', 'LOW_BUY', :started_at, "
                "6400, 0, 'ACTIVE', NULL)",
                {"plan_hash": "b" * 64, "started_at": timestamp},
            )

        with pytest.raises(RuntimeError, match="refuses populated zone_episode"):
            upgrade_database(engine)

        inspector = inspect(engine)
        assert "last_processed_bucket_end" not in {
            column["name"] for column in inspector.get_columns("zone_episode")
        }
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == "0002_ai_provider_configuration"
            )
            assert (
                connection.exec_driver_sql("SELECT id FROM zone_episode").scalar_one()
                == "episode-existing"
            )
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


def test_state_mutations_append_one_global_event_in_the_same_unit_of_work(
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

        with _unit_of_work(engine) as work:
            active = work.plans.activate(plan, expected_revision=0, validation=ready)
            bought = work.positions.record_buy(
                symbol=plan.symbol,
                bucket="CORE",
                quantity=200,
                acquired_trade_date=date(2026, 8, 20),
                cost_fen=6400,
                board_lot=100,
                max_position_qty=200,
            )
            reduced = work.positions.reduce_lot(
                bought.id,
                quantity=100,
                trade_date=date(2026, 8, 21),
            )
            provider = work.health.upsert_provider(
                capability="realtime_minutes",
                status="READY",
                checked_at=_FIXED_NOW,
                latency_ms=18,
                error_code=None,
                next_retry_at=None,
            )
            assert (
                work.health.upsert_provider(
                    capability="realtime_minutes",
                    status="READY",
                    checked_at=_FIXED_NOW,
                    latency_ms=18,
                    error_code=None,
                    next_retry_at=None,
                )
                == provider
            )
            health = work.health.upsert_symbol(
                symbol=plan.symbol,
                status="LIVE",
                latest_bar_end=_FIXED_NOW,
                data_age_seconds=0,
                gaps={"missingBucketEnds": []},
                error_streak=0,
                expected_revision=0,
            )
            work.commit()

        with _unit_of_work(engine) as work:
            events = work.events.replay_page_after(0).events

        assert tuple(event.sequence for event in events) == (1, 2, 3, 4, 5)
        assert tuple(event.event_type for event in events) == (
            MonitorEventType.PLAN_ACTIVATED,
            MonitorEventType.POSITION_UPDATED,
            MonitorEventType.POSITION_UPDATED,
            MonitorEventType.SYSTEM_HEALTH_UPDATED,
            MonitorEventType.SYMBOL_HEALTH_UPDATED,
        )
        assert events[0].payload.model_dump(exclude_none=True) == {
            "entity_id": active.plan_version_id,
            "symbol": plan.symbol,
            "revision": active.revision,
        }
        assert events[1].payload.entity_id == bought.id
        assert events[2].payload.entity_id == reduced.id
        assert events[3].payload.model_dump(exclude_none=True) == {
            "entity_id": provider.capability,
            "status": provider.status.value,
        }
        assert events[4].payload.model_dump(exclude_none=True) == {
            "entity_id": health.symbol,
            "symbol": health.symbol,
            "revision": health.revision,
            "status": health.status.value,
        }
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
        assert _key_constraints(inspector, "plan_version_review") >= {
            ("plan_version_id",),
        }
        assert _key_constraints(inspector, "plan_activation_state") >= {
            ("symbol",),
        }
        assert _key_constraints(inspector, "evaluation_ledger") >= {
            (
                "plan_hash",
                "symbol",
                "evaluation_kind",
                "target_value",
                "formula_version",
            ),
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
        assert _foreign_keys(inspector, "plan_version_review") >= {
            (("plan_version_id",), "plan_version", ("id",)),
        }
        assert _foreign_keys(inspector, "plan_activation_state") >= {
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
                "(plan_hash, symbol, evaluation_kind, target_value, formula_version, "
                "result_hash, evaluated_at) "
                "VALUES (:plan_hash, '003043.SZ', 'INTRADAY', :target_value, 'ta-v1', "
                ":result_hash, "
                ":evaluated_at)",
                {
                    "plan_hash": "b" * 64,
                    "target_value": timestamp,
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
                    "(plan_hash, symbol, evaluation_kind, target_value, formula_version, "
                    "result_hash, evaluated_at) VALUES (:plan_hash, '003043.SZ', "
                    "'INTRADAY', :target_value, 'ta-v1', :result_hash, :evaluated_at)",
                    {
                        "plan_hash": "b" * 64,
                        "target_value": timestamp,
                        "result_hash": "f" * 64,
                        "evaluated_at": timestamp,
                    },
                )

        for invalid_kind, invalid_target in (
            ("UNKNOWN", timestamp),
            ("OFFICIAL_CLOSE", timestamp),
        ):
            with pytest.raises(IntegrityError):
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "INSERT INTO evaluation_ledger "
                        "(plan_hash, symbol, evaluation_kind, target_value, formula_version, "
                        "result_hash, evaluated_at) VALUES (:plan_hash, '003043.SZ', "
                        ":evaluation_kind, :target_value, 'ta-v1', :result_hash, "
                        ":evaluated_at)",
                        {
                            "plan_hash": "e" * 64,
                            "evaluation_kind": invalid_kind,
                            "target_value": invalid_target,
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
