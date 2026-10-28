"""Real producers recheck current source inside the existing symbol writer."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from tests.integration.test_alert_only_legacy_storage import _legacy_layout, _price_alert_plan
from tests.integration.test_daily_plan_chain import FRIDAY, Chain
from tests.integration.test_daily_plan_chain import chain as chain
from tests.integration.test_market_exception_runtime import (
    exception_chain as exception_chain,
)
from tests.integration.test_market_exception_runtime import exception_inputs
from tests.integration.test_source_coverage_simulation_actions import (
    _stale,
)
from tests.integration.test_source_coverage_simulation_actions import (
    current as current,
)

from trade_plan_monitor.runtime.daily_service import DailyRuntimeEvaluationService


def test_stale_source_cannot_produce_a_new_signal_from_complete_market_facts(chain):
    series = chain.series()
    assert chain.evaluate(series=series, official=FRIDAY).snapshot["signals"] == []
    _stale(chain)
    chain.facts()
    result = chain.evaluate(series=series, official=FRIDAY)
    assert result.snapshot["signals"] == []
    assert result.event_ids == ()
    assert "SOURCE_COVERAGE_STALE" in result.snapshot["data_blockers"]
    with chain.plans._unit_of_work() as work:
        assert work.daily.list(symbol=chain.plan.symbol, kind="SIGNAL") == ()


def test_same_market_target_cannot_replay_an_old_executable_snapshot_after_source_changes(current):
    chain, old = current
    series = chain.series()
    assert chain.evaluate(series=series, price=3970).duplicate
    _stale(chain)
    result = chain.evaluate(series=series, price=3970)
    assert not result.duplicate
    signal, = result.snapshot["signals"]
    assert signal["executable_qty"] == 0 and result.event_ids == ()
    assert "SOURCE_COVERAGE_STALE" in signal["blockers"]
    assert (signal["signal_id"], signal["planned_qty"], signal["simulated_qty"]) == (
        old["signal_id"], old["planned_qty"], 0)


def test_stale_source_keeps_the_consumed_state_and_quantity_of_an_existing_signal(current):
    chain, old = current
    chain.simulate(old)
    _stale(chain)
    result = chain.evaluate(series=chain.series(), price=3970)
    signal, = result.snapshot["signals"]
    assert signal["state"] == "SIMULATED" and signal["simulated_qty"] == 100
    assert signal["planned_qty"] == old["planned_qty"] and signal["executable_qty"] == 0
    assert result.event_ids == ()


def test_source_changed_after_acquisition_is_rechecked_by_the_actual_commit_participant(current):
    chain, _ = current
    inputs = chain.runtime._current_inputs[chain.plan.symbol]

    async def prepare(*_args):
        _stale(chain)
        return inputs

    runtime = DailyRuntimeEvaluationService(chain.plans._unit_of_work, prepare_inputs=prepare)
    result = asyncio.run(runtime.run_target(plan=chain.plan, evaluated_at=chain.now))
    assert result is not None and not result.duplicate
    assert all(signal["executable_qty"] == 0 for signal in result.snapshot["signals"])
    assert result.event_ids == ()
    assert "SOURCE_COVERAGE_STALE" in result.snapshot["data_blockers"]


def test_stale_source_cannot_produce_new_exception_candidates_or_review_events(exception_chain):
    chain = exception_chain
    _stale(chain)
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    assert result.snapshot["exception_candidates"] == []
    assert result.snapshot["signals"] == [] and result.event_ids == ()
    assert "SOURCE_COVERAGE_STALE" in result.snapshot["data_blockers"]


def test_existing_pending_candidate_keeps_its_original_window_without_new_review_authority(
    exception_chain,
):
    chain = exception_chain
    first = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    pending, = first.snapshot["exception_candidates"]
    assert pending["candidate"]["state"] == "PENDING"
    _stale(chain)
    result = chain.runtime.run_inputs(plan=chain.plan, inputs=exception_inputs(chain))
    assert not result.duplicate and result.event_ids == ()
    assert result.snapshot["exception_candidates"] == [pending]
    assert result.snapshot["signals"] == []
    assert "SOURCE_COVERAGE_STALE" in result.snapshot["data_blockers"]


def test_read_only_price_reminder_keeps_the_original_legacy_storage_contract(tmp_path):
    chain = Chain(tmp_path)
    raw = _price_alert_plan().model_dump(mode="json")
    # Use the registered annotation in this new fixture; the old fixture and its
    # independent unresolved annotation are deliberately left unchanged.
    raw["alert_rules"][0]["condition"]["reference"]["source"] = "Exact synthetic fixed threshold"
    chain.plan = type(chain.plan).model_validate(raw)
    with chain.client:
        _legacy_layout(chain)
        chain.activate()
        result = chain.evaluate(series=chain.series(), official=FRIDAY)
        assert result.snapshot["alerts"][0]["outcome"] == "SATISFIED"
        assert len(result.event_ids) == 1
        assert result.snapshot["signals"] == result.snapshot["risks"] == []
        assert not result.snapshot["inventory"]["known"]
        assert not any(code.startswith("SOURCE_") for code in result.snapshot["data_blockers"])


@pytest.mark.parametrize("invalid", ["none", "unknown", "current", "version", "activation",
                                   "boolean-revision", "complete", "hash", "missing"])
def test_private_replay_reader_cannot_assert_current_or_return_another_actual_binding(
    chain, invalid
):
    from trade_plan_monitor.runtime.daily_service import _action_source

    with chain.plans._unit_of_work() as work:
        active = work.plans.get_active(chain.plan.symbol)
        value = dict(basis="REPLAY_OBSERVATION", plan_version_id=active.plan_version_id,
            activation_revision=active.revision, risk_rows=())
        if invalid == "unknown":
            value["basis"] = "UNKNOWN"
        elif invalid == "current":
            value["basis"] = "CURRENT"
        elif invalid == "version":
            value["plan_version_id"] = "another-version"
        elif invalid == "activation":
            value["activation_revision"] += 1
        elif invalid == "boolean-revision":
            value["activation_revision"] = True
        elif invalid == "complete":
            value["coverage_complete"] = True
        elif invalid == "hash":
            value["coverage_evidence_hash"] = "a" * 64
        elif invalid == "missing":
            del value["activation_revision"]
        basis, reason = _action_source(work, active.plan_version_id,
            reader=lambda *_a, **_kw: None if invalid == "none" else SimpleNamespace(**value),
            activation_revision=active.revision)
        assert basis is None and reason["blocker"].startswith("SOURCE_COVERAGE_")


def test_configured_reader_failure_cannot_fall_back_to_live_current_source(current):
    chain, _ = current
    runtime = DailyRuntimeEvaluationService(chain.plans._unit_of_work,
        _source_authority_reader=lambda *_a, **_kw: None)
    result = runtime.run_inputs(plan=chain.plan,
        inputs=chain.runtime._current_inputs[chain.plan.symbol])
    assert not result.duplicate and result.event_ids == ()
    assert all(signal["executable_qty"] == 0 for signal in result.snapshot["signals"])
    assert "SOURCE_COVERAGE_REQUIRED" in result.snapshot["data_blockers"]


def test_private_replay_protocol_omits_source_generation_from_the_historical_target(current,
                                                                                 monkeypatch):
    from trade_plan_monitor.runtime import daily_service

    chain, _ = current
    targets = []
    original = daily_service.daily_hash

    def capture(domain, value):
        if domain == "daily-decision-result-v1":
            targets.append(deepcopy(value))
        return original(domain, value)

    def reader(work, version_id, *, cause_id):
        # This tests the private participant protocol only. Frozen schedule and
        # private-engine ownership are verified by the separately owned adapter.
        active = work.plans.get_active(chain.plan.symbol)
        assert version_id == active.plan_version_id and cause_id is None
        return SimpleNamespace(basis="REPLAY_OBSERVATION", plan_version_id=version_id,
            activation_revision=active.revision,
            risk_rows=work.daily.list(symbol=chain.plan.symbol, kind="RISK"))

    monkeypatch.setattr(daily_service, "daily_hash", capture)
    inputs = chain.runtime._current_inputs[chain.plan.symbol]
    chain.now += timedelta(seconds=1)
    inputs = inputs.model_copy(update={"evaluated_at": chain.now,
        "data_blockers": ("OFFLINE_WARNING", "OFFLINE_WARNING")})
    chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
    replay = DailyRuntimeEvaluationService(chain.plans._unit_of_work,
        _source_authority_reader=reader).run_inputs(plan=chain.plan, inputs=inputs)
    live_target, replay_target = targets
    assert "source_generation" in live_target and "source_generation" not in replay_target
    assert replay_target == {k: v for k, v in live_target.items() if k != "source_generation"}
    assert replay.evaluation_id == original("daily-decision-result-v1", replay_target)
    assert replay.snapshot["data_blockers"] == ["OFFLINE_WARNING", "OFFLINE_WARNING"]
    assert not any(code.startswith("SOURCE_") for code in replay.snapshot["data_blockers"])
