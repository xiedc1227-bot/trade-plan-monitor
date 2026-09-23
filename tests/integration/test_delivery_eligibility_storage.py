"""Delivery metadata never mutates canonical alerts or grants standing send authority."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event as sql_event
from sqlalchemy import select, text
from test_explicit_runtime_production import TARGET, _three_rule_plan
from test_notification_delivery import NOW, _payload

from trade_plan_monitor.decision.explicit_rules import (
    ExplicitInventorySnapshot,
    evaluate_explicit_rules,
)
from trade_plan_monitor.decision.models import (
    ActionableSignalType,
    DecisionZone,
    NextStep,
    NextStepCode,
    SignalIntent,
)
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import ExplicitTradePlan
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar
from trade_plan_monitor.notifications.delivery_eligibility import (
    DeliveryEligibilityRepository,
    DeliveryMetadataConflict,
    DeliveryMetadataError,
)
from trade_plan_monitor.notifications.identity import alert_dedup_key, explicit_alert_event_id
from trade_plan_monitor.notifications.models import (
    AlertPayload,
    AlertPriceZone,
    build_explicit_alert_payload,
)
from trade_plan_monitor.notifications.outbox import AlertOutbox
from trade_plan_monitor.notifications.recovery_eligibility import (
    ActiveExplicitPlan,
    RecoveryBarrierEvidence,
)
from trade_plan_monitor.state.database import (
    create_session_factory,
    create_sqlite_engine,
    upgrade_database,
)
from trade_plan_monitor.state.models import AlertDeliveryEligibility, AuditLog
from trade_plan_monitor.state.models import AlertEvent as AlertRow


@pytest.fixture
def database(tmp_path):
    engine = create_sqlite_engine(tmp_path / "delivery.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        event = AlertOutbox(session, clock=lambda: NOW, id_factory=lambda: str(uuid4())).enqueue(
            _payload(1)
        )
    yield engine, factory, event
    engine.dispose()


def _repository(session, now=NOW):
    return DeliveryEligibilityRepository(session, clock=lambda: now)


def _migration(engine, target, *, down=False):
    import trade_plan_monitor.state.database as database_module

    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(database_module.__file__).with_name("migrations")),
    )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        (command.downgrade if down else command.upgrade)(config, target)


def test_missing_metadata_is_not_eligible_and_initialization_is_idempotent(database):
    engine, factory, event = database
    with factory.begin() as session:
        repository = _repository(session)
        assert repository.get(event.event_id) is None
        before = session.get(AlertRow, str(event.event_id)).payload_json
        record = repository.initialize(event.event_id)
        assert record.status.value == "HOLD"
        assert record.reason == "RECOVERY_REQUIRED"
        assert record.delivery_class.value == "STATE_RISK"
        assert record.expires_at is None
        assert repository.initialize(event.event_id) == record
        assert session.get(AlertRow, str(event.event_id)).payload_json == before
        assert len(session.scalars(select(AuditLog)).all()) == 1
    upgrade_database(engine)
    with factory() as session:
        assert _repository(session).get(event.event_id) == record


def test_initialization_rolls_back_with_caller_state(database):
    _, factory, event = database
    with pytest.raises(RuntimeError, match="rollback"):
        with factory.begin() as session:
            _repository(session).initialize(event.event_id)
            raise RuntimeError("rollback")
    with factory() as session:
        assert session.get(AlertDeliveryEligibility, str(event.event_id)) is None
        assert session.scalars(select(AuditLog)).all() == []


def test_invalidated_identity_creates_terminal_receipt_for_old_alert(database):
    _, factory, event = database
    with factory.begin() as session:
        repository = _repository(session)
        receipt = repository.suppress_invalidated_identity(
            event.event_id,
            plan_id=event.plan_id,
            plan_version=event.plan_version,
            plan_hash=event.plan_hash,
            symbol=event.symbol,
        )
        assert receipt.status.value == "SUPPRESS"
        assert receipt.reason == "ACTIVE_IDENTITY_INVALID"
        assert receipt.revision == 1
        assert repository.suppress_invalidated_identity(
            event.event_id,
            plan_id=event.plan_id,
            plan_version=event.plan_version,
            plan_hash=event.plan_hash,
            symbol=event.symbol,
        ) == receipt
    with factory() as session:
        assert _repository(session).get(event.event_id) == receipt
        assert len(session.scalars(select(AuditLog)).all()) == 2


def test_invalidated_identity_does_not_write_for_different_plan(database):
    _, factory, event = database
    with factory.begin() as session:
        repository = _repository(session)
        with pytest.raises(DeliveryMetadataConflict, match="identity"):
            repository.suppress_invalidated_identity(
                event.event_id,
                plan_id="different-plan",
                plan_version=event.plan_version,
                plan_hash=event.plan_hash,
                symbol=event.symbol,
            )
        assert repository.get(event.event_id) is None
        assert session.scalars(select(AuditLog)).all() == []


def test_invalidated_identity_suppresses_existing_hold_and_rolls_back(database):
    _, factory, event = database
    with factory.begin() as session:
        _repository(session).initialize(event.event_id)
    with pytest.raises(RuntimeError, match="cancel invalidation"):
        with factory.begin() as session:
            receipt = _repository(session).suppress_invalidated_identity(
                event.event_id,
                plan_id=event.plan_id,
                plan_version=event.plan_version,
                plan_hash=event.plan_hash,
                symbol=event.symbol,
            )
            assert receipt.status.value == "SUPPRESS"
            raise RuntimeError("cancel invalidation")
    with factory() as session:
        receipt = _repository(session).get(event.event_id)
        assert receipt.status.value == "HOLD"
        assert receipt.revision == 0
        assert len(session.scalars(select(AuditLog)).all()) == 1


def test_backfill_is_bounded_and_does_not_skip_old_records(database):
    _, factory, first = database
    with factory.begin() as session:
        outbox = AlertOutbox(session, clock=lambda: NOW, id_factory=lambda: str(uuid4()))
        events = [first, *(outbox.enqueue(_payload(n)) for n in range(2, 6))]
    with factory.begin() as session:
        repository = _repository(session)
        assert [row.event_id for row in repository.initialize_batch(limit=2)] == [
            item.event_id for item in events[:2]
        ]
    with factory.begin() as session:
        assert len(_repository(session).initialize_batch(limit=100)) == 3
        assert _repository(session).initialize_batch(limit=100) == ()


@pytest.mark.parametrize("limit", [0, 101, True, -1])
def test_backfill_rejects_unbounded_or_invalid_limits(database, limit):
    _, factory, _ = database
    with factory.begin() as session, pytest.raises(ValueError):
        _repository(session).initialize_batch(limit=limit)


def test_risk_does_not_expire_by_age(database):
    _, factory, event = database
    with factory.begin() as session:
        repository = _repository(session, NOW + timedelta(days=5))
        initial = repository.initialize(event.event_id)
        assert repository.expire_actionable(event.event_id, expected_revision=0) == initial


def test_missing_event_cannot_create_orphan_metadata(database):
    _, factory, _ = database
    with factory.begin() as session, pytest.raises(DeliveryMetadataError):
        _repository(session).initialize(UUID(int=999))


def test_corrupt_metadata_is_not_a_missing_or_eligible_record(database):
    engine, factory, event = database
    with factory.begin() as session:
        _repository(session).initialize(event.event_id)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alert_delivery_eligibility SET updated_at='invalid'"))
    with factory() as session, pytest.raises(DeliveryMetadataError):
        _repository(session).get(event.event_id)


def test_stale_revision_fails_without_audit_or_state_change(database):
    _, factory, event = database
    with factory.begin() as session:
        repository = _repository(session)
        initial = repository.initialize(event.event_id)
        with pytest.raises(DeliveryMetadataConflict):
            repository.expire_actionable(event.event_id, expected_revision=8)
        assert repository.get(event.event_id) == initial
        assert len(session.scalars(select(AuditLog)).all()) == 1


def test_downgrade_refuses_metadata_and_empty_down_up_preserves_alert(database):
    engine, factory, event = database
    _migration(engine, "0018_provider_recovery", down=True)
    upgrade_database(engine)
    with factory.begin() as session:
        _repository(session).initialize(event.event_id)
    with pytest.raises(RuntimeError, match="refuses to discard"):
        _migration(engine, "0018_provider_recovery", down=True)
    with factory() as session:
        assert _repository(session).get(event.event_id).status.value == "HOLD"
        assert session.get(AlertRow, str(event.event_id)) is not None


def test_interrupted_upgrade_rolls_back_and_can_resume(database):
    engine, factory, event = database
    _migration(engine, "0018_provider_recovery", down=True)

    def fail_after_create(_connection, _cursor, statement, *_args):
        if statement.lstrip().startswith("CREATE TABLE alert_delivery_eligibility"):
            raise RuntimeError("injected interruption")

    sql_event.listen(engine, "after_cursor_execute", fail_after_create)
    try:
        with pytest.raises(RuntimeError, match="injected interruption"):
            upgrade_database(engine)
    finally:
        sql_event.remove(engine, "after_cursor_execute", fail_after_create)
    upgrade_database(engine)
    with factory.begin() as session:
        assert _repository(session).initialize(event.event_id).revision == 0


def _pressure_payload():
    original = _payload(9)
    signal = SignalIntent(
        signal_type=ActionableSignalType.PRESSURE_REDUCE_READY,
        plan_hash=original.plan_hash,
        symbol=original.symbol,
        trading_date=original.trading_date,
        cause_id="pressure",
        quantity=100,
        bucket="TACTICAL",
        target_lot_id="lot-one",
        matched_conditions=original.matched_conditions,
        blockers=(),
        next_step=NextStep(code=NextStepCode.RECORD_CONFIRMED_FILL),
    )
    return AlertPayload.model_validate(
        {
            **original.model_dump(mode="python"),
            "signal_type": signal.signal_type,
            "cause_id": signal.cause_id,
            "dedup_key": alert_dedup_key(signal),
            "quantity": 100,
            "bucket": "TACTICAL",
            "target_lot_id": "lot-one",
            "next_step": signal.next_step,
            "zone": DecisionZone.PRESSURE,
            "relevant_zone": AlertPriceZone(
                zone=DecisionZone.PRESSURE,
                low_fen=6000,
                high_fen=6100,
                include_low=True,
                include_high=True,
            ),
        }
    )


@pytest.mark.parametrize("offset, expected", [(89, "HOLD"), (90, "SUPPRESS"), (91, "SUPPRESS")])
def test_pressure_reduction_expires_from_source_not_creation_despite_risk_severity(
    database,
    offset,
    expected,
):
    _, factory, _ = database
    payload = _pressure_payload()
    now = payload.market_data_at + timedelta(seconds=offset)
    with factory.begin() as session:
        event = AlertOutbox(session, clock=lambda: NOW, id_factory=lambda: str(uuid4())).enqueue(
            payload
        )
        repository = _repository(session, now)
        before = repository.initialize(event.event_id)
        assert before.delivery_class.value == "INTRADAY_ACTIONABLE"
        after = repository.expire_actionable(event.event_id, expected_revision=0)
        assert after.status.value == expected
        assert after.expires_at == payload.market_data_at + timedelta(seconds=90)
        assert _repository(session, NOW).initialize(event.event_id) == after


def test_missing_source_cutoff_never_uses_evaluation_or_creation_clock(database):
    _, factory, _ = database
    payload = _pressure_payload().model_copy(
        update={
            "market_data_at": None,
            "data_age_seconds": None,
            "price_fen": None,
        }
    )
    with factory.begin() as session:
        event = AlertOutbox(session, clock=lambda: NOW, id_factory=lambda: str(uuid4())).enqueue(
            payload
        )
        repository = _repository(session, NOW + timedelta(days=1))
        initial = repository.initialize(event.event_id)
        after = repository.expire_actionable(event.event_id, expected_revision=0)
        assert after == initial
        assert after.status.value == "HOLD"
        assert after.reason == "SOURCE_CUTOFF_UNKNOWN"
        assert after.source_cutoff is None and after.expires_at is None


def _explicit_fixture(factory, *, close=930):
    values = _three_rule_plan().model_dump(mode="python")
    values["rules"] = [values["rules"][-1]]
    plan = ExplicitTradePlan.model_validate(values)

    def evaluate(target, price):
        return evaluate_explicit_rules(
            plan=plan,
            bars=(
                FiveMinuteBar(
                    symbol=plan.symbol,
                    bar_end=target,
                    open_fen=price,
                    high_fen=price,
                    low_fen=price,
                    close_fen=price,
                    volume_shares=100,
                    amount_yuan=Decimal("100"),
                ),
            ),
            trading_calendar=(),
            target_bucket_end=target,
            evaluated_at=target + timedelta(seconds=2),
            activation_revision=1,
            inventory=ExplicitInventorySnapshot(
                status="UNKNOWN",
                total_qty=None,
                inventory_revision=0,
            ),
            rule_states=(),
        )

    original = evaluate(TARGET, 930)
    signal = original.signal_intents[0]
    payload = build_explicit_alert_payload(
        event_id=explicit_alert_event_id(signal),
        plan=plan,
        result=original,
        signal=signal,
    )
    with factory.begin() as session:
        event = AlertOutbox(
            session, clock=lambda: original.evaluated_at, id_factory=lambda: str(uuid4())
        ).enqueue_explicit(payload)
    target = TARGET + timedelta(minutes=5)
    now = target + timedelta(seconds=5)
    generation = UUID(int=55)
    return (
        event,
        {
            "active": ActiveExplicitPlan(
                plan=plan,
                activation_revision=1,
                activated_at=TARGET - timedelta(minutes=10),
                observed_at=now,
            ),
            "latest": evaluate(target, close),
            "barrier": RecoveryBarrierEvidence(
                symbol=plan.symbol,
                plan_hash=plan_sha256(plan),
                activation_revision=1,
                runtime_generation=generation,
                target_bucket_end=target,
                reconciled_through=target,
                pending_obligations=0,
                observed_at=now,
            ),
            "target_bucket_end": target,
            "runtime_generation": generation,
        },
        now,
    )


def test_repeated_explicit_classification_does_not_append_identical_audit(database):
    _, factory, _ = database
    event, arguments, now = _explicit_fixture(factory)
    with factory.begin() as session:
        repository = _repository(session, now)
        repository.initialize(event.event_id)
        first = repository.classify_explicit_risk(
            event.event_id, expected_revision=0, **arguments,
        )
    later = now + timedelta(seconds=1)
    arguments["active"] = arguments["active"].model_copy(update={"observed_at": later})
    arguments["barrier"] = arguments["barrier"].model_copy(update={"observed_at": later})
    with factory.begin() as session:
        repository = _repository(session, later)
        second = repository.classify_explicit_risk(
            event.event_id, expected_revision=first.revision, **arguments,
        )
    assert second == first
    with factory() as session:
        assert len(session.scalars(select(AuditLog).where(
            AuditLog.action == "ALERT_DELIVERY_CLASSIFIED",
            AuditLog.entity_id == str(event.event_id),
        )).all()) == 2


@pytest.mark.parametrize("close, expected", [(930, "ELIGIBLE"), (960, "SUPPRESS")])
def test_explicit_policy_receipt_and_audit_survive_restart_without_changing_event(
    database,
    close,
    expected,
):
    _, factory, _ = database
    event, arguments, now = _explicit_fixture(factory, close=close)
    with factory.begin() as session:
        repository = _repository(session, now)
        repository.initialize(event.event_id)
        canonical = session.get(AlertRow, str(event.event_id)).payload_json
        record = repository.classify_explicit_risk(event.event_id, expected_revision=0, **arguments)
        assert record.status.value == expected
        assert record.revision == 1
        assert record.barrier == arguments["barrier"]
        assert record.result_hash == arguments["latest"].result_hash
        assert session.get(AlertRow, str(event.event_id)).payload_json == canonical
    with factory() as session:
        assert _repository(session).get(event.event_id) == record
        assert len(session.scalars(select(AuditLog)).all()) == 2


def test_eligible_receipt_can_return_to_hold_when_barrier_is_missing(database):
    _, factory, _ = database
    event, arguments, now = _explicit_fixture(factory)
    with factory.begin() as session:
        repository = _repository(session, now)
        repository.initialize(event.event_id)
        repository.classify_explicit_risk(event.event_id, expected_revision=0, **arguments)
        arguments["barrier"] = None
        receipt = repository.classify_explicit_risk(
            event.event_id, expected_revision=1, **arguments
        )
        assert receipt.status.value == "HOLD"
        assert receipt.reason == "BARRIER_INCOMPLETE"
        assert receipt.revision == 2


def test_terminal_suppression_cannot_be_revived(database):
    _, factory, _ = database
    event, arguments, now = _explicit_fixture(factory)
    with factory.begin() as session:
        repository = _repository(session, now)
        repository.initialize(event.event_id)
        repository.classify_explicit_risk(
            event.event_id, expected_revision=0, **{**arguments, "active": None}
        )
        with pytest.raises(DeliveryMetadataConflict):
            repository.classify_explicit_risk(event.event_id, expected_revision=1, **arguments)
        assert repository.get(event.event_id).reason == "ACTIVE_IDENTITY_INVALID"


def test_legacy_event_cannot_acquire_explicit_eligibility(database):
    _, factory, legacy_event = database
    _, arguments, now = _explicit_fixture(factory)
    with factory.begin() as session:
        repository = _repository(session, now)
        repository.initialize(legacy_event.event_id)
        with pytest.raises(ValueError, match="explicit risk"):
            repository.classify_explicit_risk(
                legacy_event.event_id, expected_revision=0, **arguments
            )
        assert repository.get(legacy_event.event_id).revision == 0


def test_concurrent_initialization_creates_exactly_one_receipt_and_audit(database):
    _, factory, event = database
    ready = Barrier(2)

    def initialize():
        with factory.begin() as session:
            ready.wait(timeout=5)
            return _repository(session).initialize(event.event_id)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first, second = [
            future.result()
            for future in [
                workers.submit(initialize),
                workers.submit(initialize),
            ]
        ]
    assert first == second
    with factory() as session:
        assert len(session.scalars(select(AuditLog)).all()) == 1


def test_concurrent_classification_compare_and_swap_has_one_winner(database):
    _, factory, _ = database
    event, arguments, now = _explicit_fixture(factory)
    with factory.begin() as session:
        _repository(session, now).initialize(event.event_id)
    ready = Barrier(2)

    def classify():
        try:
            with factory.begin() as session:
                ready.wait(timeout=5)
                return (
                    _repository(session, now)
                    .classify_explicit_risk(
                        event.event_id,
                        expected_revision=0,
                        **arguments,
                    )
                    .status.value
                )
        except DeliveryMetadataConflict:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = [
            future.result()
            for future in [
                workers.submit(classify),
                workers.submit(classify),
            ]
        ]
    assert sorted(outcomes) == ["CONFLICT", "ELIGIBLE"]
    with factory() as session:
        assert len(session.scalars(select(AuditLog)).all()) == 2


def test_audit_failure_rolls_back_classification_and_other_caller_changes(database):
    engine, factory, _ = database
    event, arguments, now = _explicit_fixture(factory)
    with factory.begin() as session:
        _repository(session, now).initialize(event.event_id)

    def fail_audit(_connection, _cursor, statement, *_args):
        if statement.startswith("INSERT INTO audit_log"):
            raise RuntimeError("injected audit failure")

    sql_event.listen(engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="injected audit failure"):
            with factory.begin() as session:
                session.get(AlertRow, str(event.event_id)).acknowledged_at = now.isoformat()
                _repository(session, now).classify_explicit_risk(
                    event.event_id,
                    expected_revision=0,
                    **arguments,
                )
    finally:
        sql_event.remove(engine, "before_cursor_execute", fail_audit)
    with factory() as session:
        assert _repository(session).get(event.event_id).revision == 0
        assert session.get(AlertRow, str(event.event_id)).acknowledged_at is None
        assert len(session.scalars(select(AuditLog)).all()) == 1


def test_metadata_write_requires_caller_owned_transaction(database):
    _, factory, event = database
    with factory() as session, pytest.raises(DeliveryMetadataError, match="caller-owned"):
        _repository(session).initialize(event.event_id)


@pytest.mark.parametrize(
    "change",
    [
        {"reason": "RISK_FALSE"},
        {"source_cutoff": "2026-09-14T10:10:00+08:00"},
        {"barrier_field": "activation_revision", "value": 2},
        {"barrier_field": "plan_hash", "value": "0" * 64},
    ],
)
def test_inconsistent_eligible_receipt_is_rejected(database, change):
    import json

    _, factory, _ = database
    event, arguments, now = _explicit_fixture(factory)
    with factory.begin() as session:
        repository = _repository(session, now)
        repository.initialize(event.event_id)
        repository.classify_explicit_risk(event.event_id, expected_revision=0, **arguments)
    with factory.begin() as session:
        row = session.get(AlertDeliveryEligibility, str(event.event_id))
        if "barrier_field" in change:
            barrier = json.loads(row.barrier_json)
            barrier[change["barrier_field"]] = change["value"]
            row.barrier_json = json.dumps(barrier)
        else:
            for key, value in change.items():
                setattr(row, key, value)
    with factory() as session, pytest.raises(DeliveryMetadataError):
        _repository(session).get(event.event_id)


@pytest.mark.parametrize("change", ["class", "deadline"])
def test_existing_actionable_metadata_cannot_override_canonical_source(database, change):
    _, factory, _ = database
    payload = _pressure_payload()
    with factory.begin() as session:
        event = AlertOutbox(session, clock=lambda: NOW, id_factory=lambda: str(uuid4())).enqueue(
            payload
        )
        _repository(session).initialize(event.event_id)
    with factory.begin() as session:
        row = session.get(AlertDeliveryEligibility, str(event.event_id))
        if change == "class":
            row.delivery_class, row.expires_at = "STATE_RISK", None
        else:
            row.source_cutoff = (payload.market_data_at + timedelta(days=1)).isoformat()
            row.expires_at = (payload.market_data_at + timedelta(days=1, seconds=90)).isoformat()
    with factory.begin() as session, pytest.raises(DeliveryMetadataError):
        _repository(session).initialize(event.event_id)


def test_reused_session_refreshes_canonical_alert_when_reading_receipt(database):
    engine, factory, event = database
    with factory() as session:
        with session.begin():
            _repository(session).initialize(event.event_id)
            cached = session.get(AlertRow, str(event.event_id))
        with engine.begin() as connection:
            connection.execute(text("UPDATE alert_event SET message_text='corrupt'"))
        with pytest.raises(DeliveryMetadataError):
            _repository(session).get(event.event_id)
        assert cached.message_text == "corrupt"


@pytest.mark.parametrize("clock_timezone", [UTC, timezone(timedelta(hours=-4))])
def test_recoverable_enqueue_normalizes_the_outbox_aware_clock(database, clock_timezone):
    _, factory, _ = database
    with factory.begin() as session:
        outbox = AlertOutbox(
            session,
            clock=lambda: NOW.astimezone(clock_timezone),
            id_factory=lambda: str(uuid4()),
        )
        event = outbox.enqueue_recoverable(_pressure_payload())
        record = _repository(session).get(event.event_id)
        assert record.status.value == "HOLD"
        assert record.updated_at == event.created_at == NOW
        assert record.updated_at.utcoffset() == timedelta(hours=8)


def test_recoverable_outbox_enqueue_commits_hold_with_event_and_never_resets_it(database):
    _, factory, _ = database
    payload = _pressure_payload()
    with factory.begin() as session:
        outbox = AlertOutbox(session, clock=lambda: NOW, id_factory=lambda: str(uuid4()))
        event = outbox.enqueue_recoverable(payload)
        repository = _repository(session, NOW + timedelta(minutes=5))
        assert repository.get(event.event_id).status.value == "HOLD"
        suppressed = repository.expire_actionable(event.event_id, expected_revision=0)
        assert outbox.enqueue_recoverable(payload) == event
        assert repository.get(event.event_id) == suppressed
    with factory() as session:
        assert _repository(session).get(event.event_id).status.value == "SUPPRESS"


def test_recoverable_explicit_enqueue_and_caller_rollback_are_atomic(database):
    _, factory, _ = database
    existing, _, now = _explicit_fixture(factory)
    from trade_plan_monitor.notifications.models import ExplicitAlertPayload

    payload = ExplicitAlertPayload.model_validate(
        existing.model_dump(
            mode="python",
            exclude={"sequence", "message_text", "created_at", "acknowledged_at"},
        )
    )
    with pytest.raises(RuntimeError, match="cancel transaction"):
        with factory.begin() as session:
            outbox = AlertOutbox(session, clock=lambda: now, id_factory=lambda: str(uuid4()))
            returned = outbox.enqueue_recoverable(payload)
            assert returned.event_id == existing.event_id
            assert _repository(session).get(existing.event_id).status.value == "HOLD"
            raise RuntimeError("cancel transaction")
    with factory() as session:
        assert _repository(session).get(existing.event_id) is None
        assert session.get(AlertRow, str(existing.event_id)) is not None


def test_legacy_metadata_cannot_acquire_explicit_risk_false_reason(database):
    _, factory, event = database
    with factory.begin() as session:
        _repository(session).initialize(event.event_id)
    with factory.begin() as session:
        row = session.get(AlertDeliveryEligibility, str(event.event_id))
        row.status, row.reason = "SUPPRESS", "RISK_FALSE"
    with factory() as session, pytest.raises(DeliveryMetadataError):
        _repository(session).get(event.event_id)


@pytest.mark.parametrize("change", ["missing_evidence", "off_grid_target"])
def test_resolved_risk_receipt_requires_complete_canonical_barrier(database, change):
    import json

    _, factory, _ = database
    event, arguments, now = _explicit_fixture(factory, close=960)
    with factory.begin() as session:
        repository = _repository(session, now)
        repository.initialize(event.event_id)
        repository.classify_explicit_risk(event.event_id, expected_revision=0, **arguments)
    with factory.begin() as session:
        row = session.get(AlertDeliveryEligibility, str(event.event_id))
        if change == "missing_evidence":
            row.barrier_json, row.result_hash = None, None
        else:
            barrier = json.loads(row.barrier_json)
            off_grid = (arguments["target_bucket_end"] - timedelta(minutes=1)).isoformat()
            barrier["target_bucket_end"] = off_grid
            barrier["reconciled_through"] = off_grid
            row.barrier_json = json.dumps(barrier)
    with factory() as session, pytest.raises(DeliveryMetadataError):
        _repository(session).get(event.event_id)
