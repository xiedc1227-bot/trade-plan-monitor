"""Offline legacy delivery policy, using real canonical evaluator results."""

from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

import pytest
from test_decision_engine import _context, _official_risk_context, _pressure_lot

from trade_plan_monitor.decision.engine import evaluate
from trade_plan_monitor.decision.models import EvaluationResult, RiskStatus
from trade_plan_monitor.decision.risk import _risk_exit_target
from trade_plan_monitor.domain.plan_hash import plan_sha256
from trade_plan_monitor.domain.plan_models import TradingDayActivation
from trade_plan_monitor.notifications.legacy_recovery_eligibility import (
    ActiveLegacyPlan,
    LegacyCurrentEvidence,
    LegacyInventoryEvidence,
    UnknownLegacyActivePlan,
    classify_legacy_risk_delivery,
)
from trade_plan_monitor.notifications.models import AlertEvent, AlertPayload, build_alert_payload
from trade_plan_monitor.notifications.recovery_eligibility import RecoveryBarrierEvidence
from trade_plan_monitor.notifications.recovery_provenance import (
    LegacyOriginUnknownReason,
    ProvenLegacyAlertOrigin,
    UnknownLegacyAlertOrigin,
)
from trade_plan_monitor.notifications.render import render_alert


def test_legacy_risk_decision_receipt_is_durable(tmp_path):
    from trade_plan_monitor.notifications.delivery_eligibility import DeliveryEligibilityRepository
    from trade_plan_monitor.notifications.outbox import AlertOutbox
    from trade_plan_monitor.state.database import (
        create_session_factory,
        create_sqlite_engine,
        upgrade_database,
    )

    _, values = inputs()
    engine = create_sqlite_engine(tmp_path / "legacy-delivery.db")
    upgrade_database(engine)
    factory = create_session_factory(engine)
    try:
        event = values["origin"].event
        with factory.begin() as session:
            persisted = AlertOutbox(
                session, clock=lambda: event.created_at, id_factory=lambda: str(uuid4()),
            ).enqueue(
                AlertPayload.model_validate(event.model_dump(
                    mode="python",
                    exclude={"sequence", "message_text", "created_at", "acknowledged_at"},
                ))
            )
        values["origin"] = replace(values["origin"], event=persisted)
        with factory.begin() as session:
            repository = DeliveryEligibilityRepository(session, clock=lambda: values["now"])
            initial = repository.initialize(persisted.event_id)
            classified = repository.classify_legacy_risk(
                persisted.event_id, expected_revision=initial.revision, **values,
            )
            assert classified.status.value == "ELIGIBLE"
            assert classified.reason == "CURRENT_INSTRUCTION"
        with factory() as session:
            assert DeliveryEligibilityRepository(session, clock=lambda: values["now"]).get(
                persisted.event_id,
            ) == classified
    finally:
        engine.dispose()


def origin_for(context, result, *, created_at=None):
    payload = build_alert_payload(event_id=uuid4(), plan=context.plan, result=result)
    event = AlertEvent(
        **payload.model_dump(mode="python"), sequence=1,
        message_text=render_alert(payload),
        created_at=created_at or result.snapshot.evaluated_at,
    )
    return ProvenLegacyAlertOrigin(
        event, "version-1", 1, result.evaluation_identity, result.result_hash,
    )


def inputs(*, breach=False, pending=False, expires=False):
    lot = _pressure_lot(
        "lot-tactical", acquired_trade_date=date(2026, 8, 7) if pending else date(2026, 8, 5),
    )
    context = _official_risk_context(
        positions=(lot,), risk_status=RiskStatus.CLEAR if breach
        else RiskStatus.BREACHED_PENDING_CONFIRMATION,
    )
    if expires:
        plan = context.plan.model_copy(update={
            "activation": TradingDayActivation(trading_day=context.trade_date),
        })
        digest = plan_sha256(plan)
        context = context.model_copy(update={
            "plan": plan, "plan_hash": digest,
            "risk_state": context.risk_state.model_copy(update={"plan_hash": digest}),
        })
    result = evaluate(context)
    target = context.evaluated_at.replace(minute=0)
    now = context.evaluated_at + timedelta(minutes=1)
    generation = uuid4()
    return context, dict(
        origin=origin_for(context, result),
        active=ActiveLegacyPlan(
            plan=context.plan, plan_version_id="version-1", activation_revision=1,
            activated_at=context.activated_at, observed_at=now,
        ),
        current=LegacyCurrentEvidence(
            origin_plan=context.plan, origin_result=result, latest=result, latest_stage=result,
            activation_revision=1,
            target_bucket_end=target, latest_official_trade_date=context.trade_date,
            observed_at=now,
            inventory=LegacyInventoryEvidence(
                symbol=context.plan.symbol, plan_hash=context.plan_hash, activation_revision=1,
                target_bucket_end=target, observed_at=now,
                settlement_trade_date=context.trade_date,
                selected_target=_risk_exit_target(context), sellable=not pending,
            ),
        ),
        barrier=RecoveryBarrierEvidence(
            symbol=context.plan.symbol, plan_hash=context.plan_hash, activation_revision=1,
            runtime_generation=generation, target_bucket_end=target, reconciled_through=target,
            pending_obligations=0, observed_at=now,
        ),
        target_bucket_end=target, runtime_generation=generation, now=now,
    )


def advance(values, result, *, stage=None, occurrence=None):
    target = result.snapshot.evaluated_at.replace(minute=0)
    now = result.snapshot.evaluated_at + timedelta(minutes=1)
    current = values["current"]
    inventory = current.inventory.model_copy(update={
        "target_bucket_end": target, "observed_at": now, "settlement_trade_date": target.date(),
    })
    return dict(values, now=now, target_bucket_end=target,
        active=values["active"].model_copy(update={"observed_at": now}),
        current=current.model_copy(update={
            "latest": result, "latest_stage": stage or result,
            "latest_official_trade_date": result.evaluation_identity.official_trade_date,
            "target_bucket_end": target, "observed_at": now,
            "inventory": inventory, "latest_occurrence": occurrence,
        }),
        barrier=values["barrier"].model_copy(update={
            "target_bucket_end": target, "reconciled_through": target, "observed_at": now,
        }),
    )


def observe_at(values, now):
    """Simulate one freshly certified authority snapshot with unchanged target."""
    values["now"] = now
    values["active"] = values["active"].model_copy(update={"observed_at": now})
    values["current"] = values["current"].model_copy(update={
        "observed_at": now,
        "inventory": values["current"].inventory.model_copy(update={"observed_at": now}),
    })
    values["barrier"] = values["barrier"].model_copy(update={"observed_at": now})


@pytest.mark.parametrize("kind", ["breach", "exit", "pending"])
def test_same_original_instruction_can_be_eligible(kind):
    _, values = inputs(breach=kind == "breach", pending=kind == "pending")
    assert classify_legacy_risk_delivery(**values).status == "ELIGIBLE"


def test_confirmed_opening_only_exit_keeps_quantity_without_inventing_a_lot():
    context, values = inputs()
    opening_context = context.model_copy(update={
        "positions": (), "opening_quantity": 300, "opening_sellable_quantity": 300,
    })
    result = evaluate(opening_context)
    assert result.signal_intent.target_lot_id is None
    values["origin"] = origin_for(opening_context, result)
    inventory = values["current"].inventory.model_dump(mode="python")
    inventory.update({
        "selected_target": None, "opening_quantity": 300,
        "opening_sellable_quantity": 300, "sellable": True,
    })
    values["current"] = values["current"].model_copy(update={
        "origin_result": result, "latest": result, "latest_stage": result,
        "inventory": LegacyInventoryEvidence.model_validate(inventory),
    })
    assert classify_legacy_risk_delivery(**values).status == "ELIGIBLE"


@pytest.mark.parametrize("field", ["current", "barrier"])
def test_missing_current_authority_holds(field):
    _, values = inputs()
    values[field] = None
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


def test_unknown_origin_or_active_is_not_authoritative_absence():
    _, values = inputs()
    assert classify_legacy_risk_delivery(**dict(values, active=None)).status == "SUPPRESS"
    assert classify_legacy_risk_delivery(
        **dict(values, active=UnknownLegacyActivePlan())
    ).status == "HOLD"
    assert classify_legacy_risk_delivery(**dict(values, origin=UnknownLegacyAlertOrigin(
        LegacyOriginUnknownReason.MISSING_EVIDENCE,
    ))).status == "HOLD"


@pytest.mark.parametrize("update", [{"activation_revision": 2}, {"plan_version_id": "other"}])
def test_same_hash_reactivation_or_replacement_suppresses(update):
    _, values = inputs()
    values["active"] = values["active"].model_copy(update=update)
    assert classify_legacy_risk_delivery(**values).status == "SUPPRESS"


@pytest.mark.parametrize("update", [
    {"pending_obligations": 1}, {"reconciled_through": None},
    {"runtime_generation": uuid4()},
])
def test_barrier_is_exact_and_nonterminal(update):
    _, values = inputs()
    values["barrier"] = values["barrier"].model_copy(update=update)
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


def test_inconsistent_proven_origin_is_not_trusted():
    _, values = inputs()
    values["origin"] = replace(values["origin"], result_hash="0" * 64)
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


@pytest.mark.parametrize("clear", [True, False])
def test_resolved_or_different_breach_episode_suppresses(clear):
    _, values = inputs()
    later = evaluate(_official_risk_context(
        target_date=date(2026, 8, 10), current_close_fen=6080 if clear else 6070,
        breach_trade_date=date(2026, 8, 7), previous_trade_date=date(2026, 8, 7),
        positions=(_pressure_lot("lot-tactical"),),
    ))
    assert classify_legacy_risk_delivery(**advance(values, later)).status == "SUPPRESS"


def test_later_wait_does_not_resurrect_a_superseded_breach():
    _, values = inputs(breach=True)
    later_context = _official_risk_context(
        target_date=date(2026, 8, 10), breach_trade_date=date(2026, 8, 7),
        previous_trade_date=date(2026, 8, 7), positions=(_pressure_lot("lot-tactical"),),
    )
    exit_result = evaluate(later_context)
    wait = evaluate(_official_risk_context(
        target_date=date(2026, 8, 11), breach_trade_date=date(2026, 8, 7),
        previous_trade_date=date(2026, 8, 10), current_volume_shares=8000,
        current_macd_histogram=0.1, positions=(_pressure_lot("lot-tactical"),),
    ))
    assert wait.snapshot.signal_type == "WAIT"
    assert classify_legacy_risk_delivery(
        **advance(values, wait, stage=exit_result)
    ).reason == "STAGE_SUPERSEDED"


def test_later_complete_wait_alone_does_not_preserve_or_suppress_exit():
    _, values = inputs()
    wait = evaluate(_official_risk_context(
        target_date=date(2026, 8, 10), previous_trade_date=date(2026, 8, 7),
        current_volume_shares=8000, current_macd_histogram=0.1,
        positions=(_pressure_lot("lot-tactical"),),
    ))
    assert wait.snapshot.signal_type == "WAIT"
    assert classify_legacy_risk_delivery(**advance(
        values, wait, stage=values["current"].latest_stage,
    )).status == "HOLD"


@pytest.mark.parametrize("known", [True, False])
def test_inventory_absence_suppresses_but_unknown_inventory_holds(known):
    _, values = inputs()
    inventory = values["current"].inventory.model_copy(update={"selected_target": None})
    values["current"] = values["current"].model_copy(update={
        "inventory": inventory if known else None,
    })
    assert classify_legacy_risk_delivery(**values).status == ("SUPPRESS" if known else "HOLD")


@pytest.mark.parametrize("change", ["lot", "bucket", "quantity", "settlement"])
def test_exit_never_retargets_or_changes_quantity(change):
    _, values = inputs()
    inventory = values["current"].inventory
    lot = inventory.selected_target
    updates = {
        "lot": {"lot_id": "preferred-new-lot"}, "bucket": {"bucket": "CORE"},
        "quantity": {"remaining_quantity": 0}, "settlement": {},
    }
    inventory = inventory.model_copy(update={
        "selected_target": lot.model_copy(update=updates[change]),
        "sellable": change != "settlement",
    })
    values["current"] = values["current"].model_copy(update={"inventory": inventory})
    assert classify_legacy_risk_delivery(**values).status == (
        "HOLD" if change == "settlement" else "SUPPRESS"
    )


def test_repeated_exit_needs_proven_matching_newer_occurrence():
    _, values = inputs()
    context = _official_risk_context(
        target_date=date(2026, 8, 10), previous_trade_date=date(2026, 8, 7),
        positions=(_pressure_lot("lot-tactical", acquired_trade_date=date(2026, 8, 5)),),
    )
    later = evaluate(context)
    assert classify_legacy_risk_delivery(**advance(values, later)).status == "HOLD"
    occurrence = origin_for(context, later)
    advanced = advance(values, later, occurrence=occurrence)
    assert classify_legacy_risk_delivery(**advanced).reason == "NEWER_EXIT_OCCURRENCE"
    advanced["current"] = advanced["current"].model_copy(update={"origin_result": later})
    advanced["origin"] = occurrence
    assert classify_legacy_risk_delivery(**advanced).status == "ELIGIBLE"


@pytest.mark.parametrize("change", ["activation_revision", "result_hash"])
def test_unproven_newer_exit_does_not_suppress(change):
    _, values = inputs()
    context = _official_risk_context(
        target_date=date(2026, 8, 10), previous_trade_date=date(2026, 8, 7),
        positions=(_pressure_lot("lot-tactical"),),
    )
    later = evaluate(context)
    occurrence = replace(origin_for(context, later), **{
        change: 2 if change == "activation_revision" else "0" * 64,
    })
    assert classify_legacy_risk_delivery(
        **advance(values, later, occurrence=occurrence)
    ).status == "HOLD"


def test_latest_exit_cannot_claim_an_older_breach_is_the_latest_stage():
    _, values = inputs(breach=True)
    later = evaluate(_official_risk_context(
        target_date=date(2026, 8, 10), breach_trade_date=date(2026, 8, 7),
        previous_trade_date=date(2026, 8, 7), positions=(_pressure_lot("lot-tactical"),),
    ))
    assert classify_legacy_risk_delivery(**advance(
        values, later, stage=values["current"].origin_result,
    )).status == "HOLD"


def test_two_different_results_for_same_official_identity_are_not_authoritative():
    _, values = inputs()
    conflicting = evaluate(_official_risk_context(current_close_fen=6080))
    assert classify_legacy_risk_delivery(**advance(values, conflicting)).status == "HOLD"


def test_recovery_write_time_does_not_reorder_official_source_dates():
    _, values = inputs()
    result = values["current"].origin_result
    replay_at = result.snapshot.evaluated_at + timedelta(days=3, hours=1)
    replayed = EvaluationResult.build(**dict(
        result.model_dump(mode="python", exclude={"result_hash"}),
        snapshot=result.snapshot.model_copy(update={
            "evaluated_at": replay_at,
        }),
    ))
    context = _official_risk_context(positions=(_pressure_lot("lot-tactical"),))
    values["origin"] = origin_for(context, replayed)
    values["current"] = values["current"].model_copy(update={"origin_result": replayed})
    later_context = _official_risk_context(
        target_date=date(2026, 8, 10), previous_trade_date=date(2026, 8, 7),
        positions=(_pressure_lot("lot-tactical"),),
    )
    later = evaluate(later_context)
    advanced = advance(values, later, occurrence=origin_for(later_context, later))
    observe_at(advanced, replay_at + timedelta(minutes=1))
    assert classify_legacy_risk_delivery(**advanced).reason == "NEWER_EXIT_OCCURRENCE"


@pytest.mark.parametrize("breach,delayed,expected", [
    (True, True, "ELIGIBLE"), (True, False, "SUPPRESS"), (False, True, "SUPPRESS"),
    (False, False, "SUPPRESS"),
])
def test_cross_day_activation_exception_is_only_for_delayed_breach(breach, delayed, expected):
    context, values = inputs(breach=breach, expires=True)
    now = values["now"] + timedelta(days=3)
    observe_at(values, now)
    if delayed:
        values["origin"] = origin_for(context, values["current"].origin_result, created_at=now)
    assert classify_legacy_risk_delivery(**values).status == expected


@pytest.mark.parametrize("change", ["calendar_target", "future_date", "revision", "inventory"])
def test_missing_or_mismatched_current_scope_holds(change):
    _, values = inputs()
    current = values["current"]
    updates = {
        "calendar_target": {
            "target_bucket_end": values["target_bucket_end"] - timedelta(minutes=5),
        },
        "future_date": {"latest_official_trade_date": date(2026, 8, 10)},
        "revision": {"activation_revision": 2},
        "inventory": {"inventory": current.inventory.model_copy(update={"sellable": None})},
    }
    values["current"] = current.model_copy(update=updates[change])
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


def test_blocked_latest_official_evidence_holds():
    _, values = inputs()
    context = _official_risk_context(
        target_date=date(2026, 8, 10), previous_trade_date=date(2026, 8, 7),
        include_breach_bar=False,
    )
    blocked = evaluate(context)
    assert blocked.snapshot.signal_type == "BLOCKED_DATA"
    assert classify_legacy_risk_delivery(**advance(
        values, blocked, stage=values["current"].latest_stage,
    )).status == "HOLD"


def test_intraday_result_cannot_replace_official_evidence():
    _, values = inputs()
    values["current"] = values["current"].model_copy(update={"latest": evaluate(_context())})
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


def test_missing_stage_history_is_unknown_even_when_risk_remains_active():
    _, values = inputs(breach=True)
    values["current"] = values["current"].model_copy(update={"latest_stage": None})
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


def test_proven_dataclass_cannot_change_original_alert_semantics():
    context, values = inputs()
    payload = build_alert_payload(
        event_id=values["origin"].event.event_id, plan=context.plan,
        result=values["current"].origin_result,
    ).model_copy(update={"name": "different-plan-name"})
    altered = values["origin"].event.model_copy(update={
        "name": payload.name, "message_text": render_alert(payload),
    })
    values["origin"] = replace(values["origin"], event=altered)
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


def test_later_wait_with_complete_stage_history_preserves_same_breach():
    _, values = inputs(breach=True)
    later = evaluate(_official_risk_context(
        target_date=date(2026, 8, 10), breach_trade_date=date(2026, 8, 7),
        previous_trade_date=date(2026, 8, 7), current_volume_shares=8000,
        current_macd_histogram=0.1, positions=(_pressure_lot("lot-tactical"),),
    ))
    assert later.snapshot.signal_type == "WAIT"
    advanced = advance(values, later, stage=values["current"].latest_stage)
    before = advanced["current"].model_dump_json()
    assert classify_legacy_risk_delivery(**advanced).status == "ELIGIBLE"
    assert advanced["current"].model_dump_json() == before


def test_future_inventory_acquisition_cannot_authorize_exit():
    _, values = inputs()
    inventory = values["current"].inventory
    future_lot = inventory.selected_target.model_copy(
        update={"acquired_trade_date": values["now"].date() + timedelta(days=1)},
    )
    inventory = inventory.model_copy(update={"selected_target": future_lot})
    values["current"] = values["current"].model_copy(update={"inventory": inventory})
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


def test_same_day_acquisition_cannot_claim_sellable():
    _, values = inputs()
    inventory = values["current"].inventory
    same_day_lot = inventory.selected_target.model_copy(update={
        "acquired_trade_date": values["now"].date(),
    })
    values["current"] = values["current"].model_copy(update={
        "inventory": inventory.model_copy(update={"selected_target": same_day_lot}),
    })
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


@pytest.mark.parametrize("invalid", [{"activation_revision": 0}, {"result_hash": "0" * 64}])
def test_invalid_origin_is_held_before_inactive_identity_can_suppress(invalid):
    _, values = inputs()
    values["origin"] = replace(values["origin"], **invalid)
    values["active"] = None
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


def test_stale_observation_cannot_recertify_an_old_target():
    _, values = inputs()
    values["now"] += timedelta(days=200)
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


def test_new_occurrence_cannot_postdate_the_claimed_snapshot():
    _, values = inputs()
    context = _official_risk_context(
        target_date=date(2026, 8, 10), previous_trade_date=date(2026, 8, 7),
        positions=(_pressure_lot("lot-tactical"),),
    )
    result = evaluate(context)
    late_creation = result.snapshot.evaluated_at + timedelta(minutes=2)
    advanced = advance(values, result, occurrence=origin_for(
        context, result, created_at=late_creation,
    ))
    advanced["now"] = late_creation + timedelta(minutes=1)
    assert classify_legacy_risk_delivery(**advanced).status == "HOLD"


def test_closed_day_can_recertify_the_previous_completed_target():
    _, values = inputs()
    observe_at(values, values["now"] + timedelta(days=1))  # Saturday, target remains Friday.
    assert values["current"].inventory.settlement_trade_date == date(2026, 8, 7)
    assert classify_legacy_risk_delivery(**values).status == "ELIGIBLE"


def test_closed_day_acquisition_cannot_postdate_certified_settlement_session():
    _, values = inputs(pending=True)
    observe_at(values, values["now"] + timedelta(days=1))  # Saturday observation.
    inventory = values["current"].inventory
    saturday_lot = inventory.selected_target.model_copy(update={
        "acquired_trade_date": date(2026, 8, 8),
    })
    values["current"] = values["current"].model_copy(update={
        "inventory": inventory.model_copy(update={"selected_target": saturday_lot}),
    })
    assert inventory.settlement_trade_date == date(2026, 8, 7)
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


@pytest.mark.parametrize("field", ["active", "current", "barrier", "inventory"])
def test_every_current_authority_observation_must_match_now(field):
    _, values = inputs()
    if field == "inventory":
        inventory = values["current"].inventory.model_copy(update={
            "observed_at": values["now"] - timedelta(seconds=1),
        })
        values["current"] = values["current"].model_copy(update={"inventory": inventory})
    else:
        values[field] = values[field].model_copy(update={
            "observed_at": values["now"] - timedelta(seconds=1),
        })
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


@pytest.mark.parametrize("settlement_date", [date(2026, 8, 6), date(2026, 8, 8)])
def test_settlement_session_outside_current_calendar_scope_holds(settlement_date):
    _, values = inputs()
    inventory = values["current"].inventory.model_copy(update={
        "settlement_trade_date": settlement_date,
    })
    values["current"] = values["current"].model_copy(update={"inventory": inventory})
    assert classify_legacy_risk_delivery(**values).status == "HOLD"


def test_known_pending_target_that_has_settled_is_suppressed():
    _, values = inputs(pending=True)
    observe_at(values, values["now"] + timedelta(days=3))
    inventory = values["current"].inventory.model_copy(update={
        "settlement_trade_date": date(2026, 8, 10), "sellable": True,
    })
    values["current"] = values["current"].model_copy(update={"inventory": inventory})
    assert classify_legacy_risk_delivery(**values).reason == "TARGET_INAPPLICABLE"
