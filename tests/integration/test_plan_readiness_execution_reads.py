"""Read exact stored signal facts without invoking execution or sizing decisions."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from tests.integration.test_current_condition_plan_authority import OwnedProgress
from tests.integration.test_daily_plan_chain import Chain
from tests.integration.test_runtime_status_projection import _current_status

from trade_plan_monitor.runtime import production
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


@pytest.fixture
def execution_case(tmp_path, monkeypatch):
    native_pipeline = production.ProductionMonitorPipeline
    trackers = []

    def build(**kwargs):
        progress = OwnedProgress(kwargs["runtime_generation"], kwargs["clock"])
        trackers.append(progress.tracker)
        return native_pipeline(**kwargs, progress_owner=progress)

    monkeypatch.setattr(production, "ProductionMonitorPipeline", build)
    case = _current_status(tmp_path, monkeypatch)
    try:

        def owner():
            token, configuration, plans = case.pipeline.runtime_status_snapshot()
            return replace(
                case.current[0],
                token=token,
                configuration_revision=configuration,
                plans=plans,
                progress=trackers[0].snapshot(),
            )

        case.reader = RuntimeStatusReadService(case.sessions, owner, clock=case.pipeline._clock.now)
        case.tmp_path = tmp_path
        yield case
    finally:
        case.close()


def execution(case, side="BUY"):
    assessed = asyncio.run(
        case.reader.get_plan_readiness(version_id=case.result.snapshot["plan_version_id"])
    )
    return next(
        rule.facts.execution
        for rule in assessed.rules
        if rule.facts.owner_kind == "ORDINARY_RULE" and rule.facts.side == side
    )


def test_unique_actual_signal_copies_approved_quantity_and_current_execution(
    execution_case, monkeypatch,
):
    from trade_plan_monitor.state.source_action_reads import ActionOwnerReader

    case = execution_case
    signal = case.result.snapshot["signals"][0]
    assert signal["state"] == "READY" and signal["executable_qty"] > 0
    calls = []
    native_read = ActionOwnerReader.daily

    def read(owner, identity):
        calls.append(identity)
        return native_read(owner, identity)

    monkeypatch.setattr(ActionOwnerReader, "daily", read)
    observed = execution(case)
    assert calls.count(signal["signal_id"]) == 2  # One exact lookup in each bounded snapshot.
    assert observed.approved_quantity == signal["planned_qty"]
    assert observed.consumed is False
    assert observed.execution_window == signal["execution_window"]
    assert observed.window_state == "OPEN"
    assert observed.eligible is True


def test_actual_false_does_not_turn_rule_quantity_into_approval(execution_case):
    observed = execution(execution_case, "SELL")
    assert observed.approved_quantity is None
    assert observed.consumed is None and observed.eligible is None


def test_expired_evaluation_cannot_keep_old_executable_quantity_eligible(execution_case):
    case = execution_case
    case.pipeline._clock.current += timedelta(seconds=91)
    asyncio.run(case.pipeline.refresh_references(case.pipeline._clock.now().date()))
    observed = execution(case)
    assert observed.approved_quantity == case.result.snapshot["signals"][0]["planned_qty"]
    assert observed.eligible is None


def test_closed_session_is_known_without_reopening_the_occurrence(execution_case):
    case = execution_case
    case.pipeline._clock.current = case.now.replace(hour=12, minute=0, second=0)
    asyncio.run(case.pipeline.refresh_references(case.pipeline._clock.now().date()))
    observed = execution(case)
    assert observed.window_state == "CLOSED" and observed.eligible is False
    assert observed.consumed is False


@pytest.mark.parametrize("calendar", ["closed", "missing"])
def test_execution_window_uses_the_actual_official_calendar(execution_case, calendar):
    from trade_plan_monitor.state.models import TradingCalendar

    case = execution_case
    with case.sessions.begin() as session:
        row = session.get(TradingCalendar, (case.plan.market, case.now.date()))
        if calendar == "closed":
            row.is_open = False
        else:
            session.delete(row)
    observed = execution(case)
    assert observed.window_state == ("CLOSED" if calendar == "closed" else "UNKNOWN")
    assert observed.eligible is (False if calendar == "closed" else None)


def test_atomic_public_consumption_is_read_from_the_exact_signal_row(execution_case):
    case = execution_case
    signal = case.result.snapshot["signals"][0]
    chain = Chain(case.tmp_path)
    chain.now = case.now
    with chain.client:
        receipt = chain.post(
            "simulated-trades",
            {
                "planVersionId": case.result.snapshot["plan_version_id"],
                "causeId": signal["signal_id"],
                "expectedCauseRevision": signal["revision"],
                "expectedInventoryRevision": case.result.snapshot["inventory"]["revision"],
                "quantity": signal["planned_qty"],
            },
        )
    assert receipt["quantity"] == signal["planned_qty"]
    observed = execution(case)
    assert observed.approved_quantity == signal["planned_qty"]
    assert observed.consumed is True and observed.eligible is False


def test_successor_version_cannot_borrow_the_old_signal(execution_case):
    from tests.integration.current_pipeline_fixture import replace_current_plan

    case = execution_case
    replace_current_plan(case.tmp_path)
    observed = execution(case)
    assert observed.approved_quantity is None and observed.consumed is None
    assert observed.eligible is None


def test_two_stored_occurrences_are_ambiguous_after_real_pipeline_observation(
    execution_case, monkeypatch,
):
    from trade_plan_monitor.state.source_action_reads import ActionOwnerReader

    case = execution_case
    original = case.result.snapshot["signals"][0]
    # A negative engineering ledger fixture: two well-shaped historical rows.
    # The producer must observe both; no fabricated evaluation/proof is installed.
    with case.work() as work:
        work.daily.save(
            "ambiguous-original-occurrence",
            kind="SIGNAL",
            symbol=case.plan.symbol,
            lineage=case.plan.plan_id,
            expected_revision=0,
            payload={
                key: value
                for key, value in {**original, "signal_id": "ambiguous-original-occurrence"}.items()
                if key != "revision"
            },
        )
        work.commit()
    case.pipeline._clock.current += timedelta(seconds=1)
    asyncio.run(
        case.pipeline.daily_evaluations.reevaluate_version(case.result.snapshot["plan_version_id"])
    )
    calls = []
    native_read = ActionOwnerReader.daily

    def read(owner, identity):
        calls.append(identity)
        return native_read(owner, identity)

    monkeypatch.setattr(ActionOwnerReader, "daily", read)
    observed = execution(case)
    assert not {original["signal_id"], "ambiguous-original-occurrence"}.intersection(calls)
    assert observed.approved_quantity is None
    assert observed.consumed is None and observed.eligible is None


def test_signal_revision_change_between_reads_reloads_the_atomic_fact(execution_case, monkeypatch):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case, calls = execution_case, []
    original = projection.read_readiness_binding
    signal = case.result.snapshot["signals"][0]

    def changed(*args):
        if not calls:
            chain = Chain(case.tmp_path)
            chain.now = case.now
            with chain.client:
                chain.post(
                    "simulated-trades",
                    {
                        "planVersionId": case.result.snapshot["plan_version_id"],
                        "causeId": signal["signal_id"],
                        "expectedCauseRevision": signal["revision"],
                        "expectedInventoryRevision": case.result.snapshot["inventory"]["revision"],
                        "quantity": signal["planned_qty"],
                    },
                )
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    observed = execution(case)
    assert len(calls) == 2
    assert observed.consumed is True and observed.eligible is False
