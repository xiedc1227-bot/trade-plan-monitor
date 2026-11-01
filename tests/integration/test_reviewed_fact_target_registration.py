"""Private ordinary confirmation registration on real temporary SQL owners."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import select
from tests.integration.test_daily_plan_chain import SH, TUESDAY, Chain
from tests.integration.test_unified_runtime import current_plan, minute_inputs
from tests.unit.test_daily_state_models import signal_payload

from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.reviewed_fact_targets import list_reviewed_fact_targets
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import AuditLog, PlanVersion, RequestIdempotency
from trade_plan_monitor.state.repositories import (
    IdempotencyKeyReuseError,
    PlanSaveBlockedError,
    RevisionConflictError,
)
from trade_plan_monitor.web.daily_service import _record_fact, mutate_daily
from trade_plan_monitor.web.idempotency import operation_hash
from trade_plan_monitor.web.routers.daily_plans import DailyFactCommand
from trade_plan_monitor.web.schemas import MutationContext

SELECTION = ("ORDINARY_RULE", "low-buy", "condition.conditions[0]")


def _plan(scope="TRADE_DATE", daily=False):
    raw = current_plan(mixed=False).model_dump(mode="json")
    raw["ordinary_rules"][0]["condition"] = dict(type="ALL", conditions=[
        dict(type="REVIEWED_FACT", fact_kind="VOLUME_OR_CANDLE",
             evidence_requirement=requirement, validity_scope=scope)
        for requirement in ("成交不异常放大", "明显下影")])
    raw["ordinary_rules"][0]["independent_signal"] = dict(
        mode="LATER_CLOSE_RESET_THEN_CONFIRM",
        reset_condition=raw["ordinary_rules"][0]["condition"]["conditions"][0])
    if daily:
        raw["ordinary_rules"][0].update(confirmation={"kind": "OFFICIAL_DAILY_CLOSE"},
                                        execution_window="NEXT_EXCHANGE_SESSION_ONLY")
    second = {**raw["ordinary_rules"][0], "rule_id": "sell-other", "side": "SELL"}
    raw["ordinary_rules"].append(second)
    return UnifiedTradePlan.model_validate(raw)


@contextmanager
def _current(tmp_path, *, scope="TRADE_DATE", daily=False):
    chain = Chain(tmp_path)
    chain.plan = _plan(scope, daily)
    with chain.client:
        chain.activate()
        chain.now = datetime(2026, 9, 22, 16 if daily else 9, 35, 12, tzinfo=SH)
        if daily:
            chain.evaluate(series=chain.series(TUESDAY), official=TUESDAY)
        else:
            chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
        yield chain


def _command(chain, **changes):
    values = dict(
        planVersionId=chain.version["id"], contentHash=chain.version["contentHash"],
        factId="registered-private", kind="VOLUME_OR_CANDLE", tradeDate=str(TUESDAY),
        evidence="Synthetic human verifies only the exact selected completed condition.",
        expectedRevision=0)
    return DailyFactCommand.model_validate({**values, **changes})


def _identity(chain):
    return daily_hash("daily-human-fact-v1", dict(symbol=chain.plan.symbol,
                                                fact_id="registered-private"))


def _snapshot(chain):
    with chain.plans._unit_of_work() as work:
        return tuple((model.__tablename__, tuple(tuple(row) for row in work.daily.session.execute(
            select(model.__table__).order_by(*model.__table__.primary_key.columns))))
            for model in (DailyRecord, AuditLog, RequestIdempotency))


def _write(chain, command, **private):
    with chain.plans._unit_of_work() as work:
        details = work.plans.get_version_details(str(command.plan_version_id))
        work.daily.lock_symbol(details.symbol)
        result = _record_fact(work, details, command, chain.now, **private)
        work.commit()
        return result


def _seed_bound_fact(chain):
    """Engineering arrangement, not a claim that a public target command exists."""
    command = _command(chain)
    with chain.plans._unit_of_work() as work:
        details = work.plans.get_version_details(str(command.plan_version_id))
        plan = load_plan_json(details.payload_json)
        target = next(t for t in list_reviewed_fact_targets(plan, plan_version_id=details.id,
                      content_hash=details.content_hash)
                      if (t.owner_kind, t.owner_id, t.condition_path) == SELECTION)
        payload = dict(plan_version_id=details.id, content_hash=details.content_hash,
                       kind=command.kind, trade_date=str(command.trade_date), signal_id=None,
                       evidence=command.evidence, verified=True, satisfied=True,
                       prior_signal_id=None,
                       verified_at=chain.now.isoformat(), available_at=chain.now.isoformat(),
                       official_evidence=None, reviewed_fact_target=target.model_dump())
        previous = work.daily.get(_identity(chain))
        work.daily.save(_identity(chain), kind="FACT", symbol=details.symbol,
                        lineage=details.plan_id,
                        expected_revision=0 if previous is None else previous["revision"],
                        payload=payload)
        work.commit()
        return payload


def test_old_target_free_command_cannot_erase_an_actual_bound_fact(tmp_path):
    with _current(tmp_path) as chain:
        original = _seed_bound_fact(chain)
        before = _snapshot(chain)
        command = _command(chain).model_copy(update={"expected_revision": 1})
        with pytest.raises(ValueError):
            _write(chain, command)
        assert _snapshot(chain) == before
        with chain.plans._unit_of_work() as work:
            assert canonical(work.daily.get(_identity(chain))["payload"]) == canonical(original)


@pytest.mark.parametrize("daily", [False, True])
def test_private_server_target_and_same_binding_revision_keep_cas(tmp_path, daily):
    with _current(tmp_path, daily=daily) as chain:
        first = _write(chain, _command(chain), fact_selection=SELECTION)
        target = first["payload"]["reviewed_fact_target"]
        assert target["plan_version_id"] == chain.version["id"]
        assert target["owner_id"] == SELECTION[1] and target["condition_path"] == SELECTION[2]
        update = _command(chain, expectedRevision=1, satisfied=False)
        second = _write(chain, update, fact_selection=SELECTION)
        assert second["revision"] == 2 and second["payload"]["satisfied"] is False
        assert second["payload"]["reviewed_fact_target"] == target
        before = _snapshot(chain)
        with pytest.raises(RevisionConflictError):
            _write(chain, update, fact_selection=SELECTION)
        assert _snapshot(chain) == before


@pytest.mark.parametrize("selection", [
    ("ALERT_RULE", "low-buy", "condition.conditions[0]"),
    ("RISK_BRANCH", "low-buy", "condition.conditions[0]"),
    ("ORDINARY_RULE", "not-a-rule", "condition.conditions[0]"),
    ("ORDINARY_RULE", "low-buy", "independent_signal.reset_condition"),
    ("ORDINARY_RULE", "low-buy", "condition.conditions[99]"),
])
def test_unsupported_or_wrong_selection_rejects_without_fact_audit_or_receipt(tmp_path, selection):
    with _current(tmp_path) as chain:
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain), fact_selection=selection)
        assert _snapshot(chain) == before


@pytest.mark.parametrize("changes", [
    {"kind": "TECHNICAL"}, {"contentHash": "0" * 64}, {"tradeDate": "2026-09-23"},
])
def test_wrong_kind_content_or_future_date_has_zero_effects(tmp_path, changes):
    with _current(tmp_path) as chain:
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain, **changes), fact_selection=SELECTION)
        assert _snapshot(chain) == before


@pytest.mark.parametrize("field,value", [
    ("minute_prefix", []), ("five_minute_bars", []), ("minute_target", None),
    ("plan_hash", "0" * 64), ("content_hash", "0" * 64),
    ("plan_version_id", "another-version"), ("review_id", "another-review"),
])
def test_actual_head_must_belong_to_exact_complete_observation(tmp_path, field, value):
    with _current(tmp_path) as chain:
        with chain.plans._unit_of_work() as work:
            head = work.daily.get("evaluation-head-" + chain.plan.symbol)
            work.daily.save(head["id"], kind="EVALUATION", symbol=head["symbol"],
                            lineage=head["lineage"], expected_revision=head["revision"],
                            payload={**head["payload"], field: value})
            work.commit()
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain), fact_selection=SELECTION)
        assert _snapshot(chain) == before


def test_daily_head_cannot_borrow_an_internally_coherent_other_symbol_series(tmp_path):
    with _current(tmp_path, daily=True) as chain:
        with chain.plans._unit_of_work() as work:
            head = work.daily.get("evaluation-head-" + chain.plan.symbol)
            payload = deepcopy(head["payload"])
            payload["symbol"] = payload["inventory"]["symbol"] = "600000.SH"
            payload["daily_evidence"]["symbol"] = "600000.SH"
            for bar in payload["daily_evidence"]["bars"]:
                bar["symbol"] = "600000.SH"
            work.daily.save(head["id"], kind="EVALUATION", symbol=head["symbol"],
                            lineage=head["lineage"], expected_revision=head["revision"],
                            payload=payload)
            work.commit()
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain), fact_selection=SELECTION)
        assert _snapshot(chain) == before


@pytest.mark.parametrize("missing", [True, False])
def test_official_day_declaration_cannot_replace_available_completed_daily_data(tmp_path, missing):
    with _current(tmp_path, daily=True) as chain:
        before = _snapshot(chain)
        with chain.plans._unit_of_work() as work:
            head = work.daily.get("evaluation-head-" + chain.plan.symbol)
            payload = deepcopy(head["payload"])
            if missing:
                payload["daily_evidence"] = None
                work.daily.save(head["id"], kind="EVALUATION", symbol=head["symbol"],
                                lineage=head["lineage"], expected_revision=head["revision"],
                                payload=payload)
                work.commit()
            else:
                payload["daily_evidence"]["bars"][-1]["available_at"] = (
                    "2026-09-22T09:00:00+08:00")
                with pytest.raises(ValueError, match="official close"):
                    work.daily.save(head["id"], kind="EVALUATION", symbol=head["symbol"],
                                    lineage=head["lineage"], expected_revision=head["revision"],
                                    payload=payload)
        if missing:
            before = _snapshot(chain)
            with pytest.raises(ValueError):
                _write(chain, _command(chain), fact_selection=SELECTION)
        assert _snapshot(chain) == before


def _signal(chain, **changes):
    """Typed engineering SIGNAL owner row; never an assertion of action eligibility."""
    with chain.plans._unit_of_work() as work:
        review_id = work.plans.get_version_details(chain.version["id"]).review_id
    payload = {**signal_payload(), "plan_version_id": chain.version["id"],
               "review_id": review_id, "lineage": chain.plan.plan_id,
               "confirmed_trade_date": str(TUESDAY), "execution_date": str(TUESDAY),
               "confirmation_kind": "COMPLETED_BAR_CLOSE", "execution_window": "CURRENT_SESSION",
               "confirmed_at": "2026-09-22T09:35:00+08:00", "state": "CONFIRMED",
               "executable_qty": 0, **changes}
    with chain.plans._unit_of_work() as work:
        work.daily.save("signal", kind="SIGNAL", symbol=chain.plan.symbol,
                        lineage=chain.plan.plan_id, expected_revision=0, payload=payload)
        work.commit()
    return "signal"


def test_signal_scope_requires_exact_existing_signal(tmp_path):
    with _current(tmp_path, scope="SIGNAL") as chain:
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain), fact_selection=SELECTION)
        assert _snapshot(chain) == before
        signal = _signal(chain)
        result = _write(chain, _command(chain, signalId=signal), fact_selection=SELECTION)
        assert result["payload"]["signal_id"] == signal


@pytest.mark.parametrize("changes", [
    {"rule_id": "sell-other"}, {"plan_version_id": "another-version"},
    {"review_id": "another-review"}, {"side": "SELL"},
    {"confirmed_trade_date": "2026-09-18"}, {"confirmed_at": "2026-09-22T09:30:00+08:00"},
    {"confirmation_kind": "OFFICIAL_DAILY_CLOSE"},
])
def test_same_symbol_wrong_signal_owner_or_period_is_not_borrowed(tmp_path, changes):
    with _current(tmp_path, scope="SIGNAL") as chain:
        signal = _signal(chain, **changes)
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain, signalId=signal), fact_selection=SELECTION)
        assert _snapshot(chain) == before


@pytest.mark.parametrize("selection", [
    ("ORDINARY_RULE", "low-buy", "condition.conditions[1]"),
    ("ORDINARY_RULE", "sell-other", "condition.conditions[0]"),
])
def test_existing_target_cannot_be_retargeted(tmp_path, selection):
    with _current(tmp_path) as chain:
        _seed_bound_fact(chain)
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain, expectedRevision=1), fact_selection=selection)
        assert _snapshot(chain) == before


def test_existing_date_binding_cannot_widen_to_an_attached_signal(tmp_path):
    with _current(tmp_path) as chain:
        _seed_bound_fact(chain)
        signal = _signal(chain)
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain, expectedRevision=1, signalId=signal),
                   fact_selection=SELECTION)
        assert _snapshot(chain) == before


def test_existing_fact_cannot_move_to_equal_content_new_version(tmp_path):
    with _current(tmp_path) as chain:
        _seed_bound_fact(chain)
        chain.activate(version=2, activation_revision=1, supplement_revision=1)
        chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain, expectedRevision=1), fact_selection=SELECTION)
        assert _snapshot(chain) == before


def test_private_selection_cannot_use_replay_head_or_flush_pending_owner(tmp_path):
    with _current(tmp_path) as chain:
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain), fact_selection=SELECTION, evidence_head={})
        with chain.plans._unit_of_work() as work:
            details = work.plans.get_version_details(chain.version["id"])
            work.daily.lock_symbol(details.symbol)
            owner = work.daily.session.get(PlanVersion, details.id)
            owner.plan_hash = "0" * 64
            with pytest.raises(ValueError):
                _record_fact(work, details, _command(chain), chain.now, fact_selection=SELECTION)
            assert owner in work.daily.session.dirty and owner.plan_hash == "0" * 64
        assert _snapshot(chain) == before


def test_target_save_rolls_back_with_existing_transaction(tmp_path):
    with _current(tmp_path) as chain:
        before = _snapshot(chain)
        with pytest.raises(RuntimeError, match="rollback probe"):
            with chain.plans._unit_of_work() as work:
                details = work.plans.get_version_details(chain.version["id"])
                work.daily.lock_symbol(details.symbol)
                _record_fact(work, details, _command(chain), chain.now, fact_selection=SELECTION)
                raise RuntimeError("rollback probe")
        assert _snapshot(chain) == before


def test_old_receipt_replay_keeps_outcome_but_fresh_update_cannot_erase_target(tmp_path):
    with _current(tmp_path) as chain:
        command = _command(chain)
        context = MutationContext(idempotency_key="old-fact-replay", request_id=uuid4().hex)
        digest = operation_hash("DAILY_FACT", command)
        receipt = mutate_daily(chain.plans, operation_name="FACT", command=command,
                               context=context, request_hash=digest)
        _seed_bound_fact(chain)
        before = _snapshot(chain)
        assert mutate_daily(chain.plans, operation_name="FACT", command=command,
                            context=context, request_hash=digest) == receipt
        assert _snapshot(chain) == before
        with pytest.raises(IdempotencyKeyReuseError):
            mutate_daily(chain.plans, operation_name="FACT", command=command,
                         context=context, request_hash="0" * 64)
        fresh = _command(chain, expectedRevision=2)
        with pytest.raises(PlanSaveBlockedError):
            mutate_daily(chain.plans, operation_name="FACT", command=fresh,
                         context=MutationContext(idempotency_key="new-erasure",
                                                 request_id=uuid4().hex),
                         request_hash=operation_hash("DAILY_FACT", fresh))
        assert _snapshot(chain) == before


def test_legacy_target_free_payload_and_audit_hash_do_not_change(tmp_path):
    with _current(tmp_path) as chain:
        command = _command(chain)
        row = _write(chain, command)
        expected = dict(plan_version_id=chain.version["id"], content_hash=command.content_hash,
                        kind=command.kind, trade_date=str(command.trade_date), signal_id=None,
                        evidence=command.evidence, verified=True, satisfied=True,
                        prior_signal_id=None,
                        verified_at=chain.now.isoformat(), available_at=chain.now.isoformat(),
                        official_evidence=None)
        assert canonical(row["payload"]) == canonical(expected)
        with chain.plans._unit_of_work() as work:
            stored = work.daily.session.get(DailyRecord, row["id"])
            audit = work.daily.session.scalar(select(AuditLog).where(
                AuditLog.entity_id == row["id"]))
            assert stored.payload_json == canonical(expected)
            assert audit.after_hash == sha256(canonical(expected).encode()).hexdigest()
