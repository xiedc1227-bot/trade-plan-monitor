"""A staged wait needs an actual public fill and a real subsequent FALSE root."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import pytest
from tests.integration.current_pipeline_fixture import current_three_rule_plan
from tests.integration.test_current_condition_plan_authority import OwnedProgress
from tests.integration.test_daily_plan_chain import Chain
from tests.integration.test_runtime_status_projection import _current_status
from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.runtime import production
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


@pytest.fixture
def staged_case(tmp_path, monkeypatch, request):
    variant = getattr(request, "param", "daily")
    factory = production.ProductionMonitorPipeline
    trackers = []

    def owned(**kwargs):
        owner = OwnedProgress(kwargs["runtime_generation"], kwargs["clock"])
        trackers.append(owner.tracker)
        return factory(**kwargs, progress_owner=owner)

    monkeypatch.setattr(production, "ProductionMonitorPipeline", owned)
    raw = current_three_rule_plan().model_dump(mode="json")
    raw["alert_rules"] = []
    raw["monitoring"] = unified_payload()["monitoring"]
    raw["ordinary_rules"][0]["independent_signal"] = {"mode": "ONCE_PER_RULE"}
    raw["ordinary_rules"][1].update(
        independent_signal={"mode": "AFTER_RULE_COMPLETED", "prior_rule_id": "low-buy"},
        confirmation={"kind": "OFFICIAL_DAILY_CLOSE"},
        execution_window="NEXT_EXCHANGE_SESSION_ONLY",
        condition={"type": "DAILY_PRICE_COMPARE", "field": "close", "offset": 0,
            "comparator": "LT", "reference": {"mode": "FIXED", "value": "4000",
                "unit": "FEN", "as_of": "2026-09-11", "source": "fixture"}})
    if variant in {"minute", "same-day-minute"}:
        raw["ordinary_rules"][1].update(
            confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
            execution_window="CURRENT_SESSION",
            condition={"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 900})
    if variant == "date-range":
        raw["ordinary_rules"][1]["validity"] = {
            "mode": "DATE_RANGE", "start_date": "2026-09-11", "end_date": "2026-09-14"}
    plan = UnifiedTradePlan.model_validate(raw)
    sources = []

    def configure(sdk, clock, current):
        source = CurrentCloseSDK(clock, (current.symbol,), official_closes={
            clock.now().date() - timedelta(days=3): "55.00", clock.now().date(): "55.00"})
        sdk.daily, sdk.adj_factor = source.daily, source.adj_factor
        sources.append(source)

    case = _current_status(tmp_path, monkeypatch, plan=plan, configure_sdk=configure)
    case.tmp_path, case.daily_source = tmp_path, sources[0]

    def owner():
        token, revision, plans = case.pipeline.runtime_status_snapshot()
        return replace(case.current[0], token=token, configuration_revision=revision,
            plans=plans, progress=trackers[0].snapshot())

    case.owner = owner
    case.reader = RuntimeStatusReadService(case.sessions, owner, clock=case.pipeline._clock.now)
    try:
        signal = next(item for item in case.result.snapshot["signals"]
                      if item["rule_id"] == "low-buy")
        assert signal["state"] == "READY" and signal["executable_qty"] == signal["planned_qty"]
        chain = Chain(tmp_path)
        chain.now = case.pipeline._clock.now()
        with chain.client:
            receipt = chain.post("simulated-trades", {
                "planVersionId": case.result.snapshot["plan_version_id"],
                "causeId": signal["signal_id"], "expectedCauseRevision": signal["revision"],
                "expectedInventoryRevision": case.result.snapshot["inventory"]["revision"],
                "quantity": signal["planned_qty"],
            })
        assert receipt["quantity"] == signal["planned_qty"]
        case.predecessor_id, case.public_receipt = signal["signal_id"], receipt
        execution_day = case.pipeline._clock.now().date()
        if variant == "same-day-minute":
            case.pipeline._clock.current += timedelta(seconds=1)
        else:
            case.pipeline._clock.current += timedelta(days=1)
        case.sdk.source_time = case.pipeline._clock.now().replace(second=0) - timedelta(minutes=1)

        async def real_successor():
            now = case.pipeline._clock.now()
            await case.pipeline.refresh_references(now.date())
            await case.pipeline.recover_startup(now.date())
            with case.work() as work:
                minutes = work.history.list_minutes(case.plan.symbol,
                    start=now.replace(hour=9, minute=31, second=0),
                    end=now.replace(second=0))
            # Existing explicit full daily admission; no reuse refresh or producer
            # policy is changed to manufacture the subsequent comparison.
            with case.pipeline._status_progress_unit(timeout_seconds=30):
                return await case.pipeline.daily_evaluations.run_target(plan=case.plan,
                    evaluated_at=now, official_trade_date=execution_day - timedelta(days=3)
                    if variant in {"before-execution", "same-day-minute"} else execution_day,
                    minutes=minutes)

        if variant == "occurrence":
            case.daily_source.official_closes[execution_day] = "35.00"
            emitted = asyncio.run(real_successor())
            assert any(row["rule_id"] == "sell-100" for row in emitted.snapshot["signals"])
            case.pipeline._clock.current += timedelta(seconds=1)
            case.daily_source.official_closes[execution_day] = "55.00"
        case.result = asyncio.run(real_successor())
        assert case.result is not None and not case.result.duplicate
        observations = case.result.snapshot.get("ordinary_evaluations", ())
        successor = [row for row in observations if row["rule_id"] == "sell-100"]
        if variant in {"same-day-minute", "before-execution", "occurrence"}:
            assert not successor, "native admission must not invent a successor comparison"
        else:
            assert len(successor) == 1, "actual producer must record successor FALSE before WAIT"
            assert successor[0]["evidence"]["outcome"] == "UNSATISFIED"
        assert case.owner().plans[0].completion is not None
        yield case
    finally:
        case.close()


def read(case):
    return asyncio.run(case.reader.get_plan_readiness(
        version_id=case.result.snapshot["plan_version_id"]))


def successor(result):
    return next(rule for rule in result.rules if rule.facts.owner_id == "sell-100")


def test_public_whole_fill_and_real_daily_false_can_wait_for_next_confirmation(staged_case):
    case = staged_case
    with case.work() as work:
        original = work.daily.get(case.predecessor_id)
    assert original["payload"]["state"] == "SIMULATED"
    assert original["payload"]["simulated_qty"] == original["payload"]["planned_qty"] > 0
    actual = successor(read(case))
    assert actual.facts.root_outcome == "UNSATISFIED"
    assert actual.state == "WAITING_OFFICIAL_CONFIRMATION"
    wait = actual.facts.expected_confirmation
    assert wait.target.trade_date == case.pipeline._clock.now().date()
    assert actual.facts.evaluated_target.trade_date < wait.target.trade_date
    assessed = read(case)
    assert assessed.rules[0].state == "UNKNOWN"  # Consumed predecessor has no new root.
    assert assessed.fresh_until is None and assessed.authority_granted is False


def test_every_original_predecessor_binding_is_required(staged_case, monkeypatch):
    case = staged_case
    native_read = ActionOwnerReader.daily
    with case.work() as work:
        original = work.daily.get(case.predecessor_id)
    changes = {
        "missing": None, "id": "wrong-original", "kind": "RISK",
        "symbol": "000001.SZ", "lineage": "wrong-lineage", "revision": original["revision"] + 1,
        "payload.signal_id": "wrong-original", "payload.rule_id": "sell-100",
        "payload.side": "SELL", "payload.lineage": "wrong-lineage",
        "payload.plan_version_id": "wrong-version", "payload.review_id": "wrong-review",
        "payload.basis_id": "wrong-basis", "payload.evidence_fingerprint": "f" * 64,
        "payload.occurrence_mode": None,
    }
    for field, wrong in changes.items():
        def altered(owner, identity, field=field, wrong=wrong):
            row = native_read(owner, identity)
            if identity != case.predecessor_id:
                return row
            if field == "missing":
                return None
            row = deepcopy(row)
            if field.startswith("payload."):
                row["payload"][field.removeprefix("payload.")] = wrong
            else:
                row[field] = wrong
            return row

        # Negative input-boundary corruption only: no replacement EVAL or positive proof.
        with monkeypatch.context() as patch:
            patch.setattr(ActionOwnerReader, "daily", altered)
            actual = successor(read(case))
        assert actual.state == "UNKNOWN", field
        assert actual.facts.expected_confirmation is None, field
        assert actual.facts.root_outcome == "UNSATISFIED", field


@pytest.mark.parametrize("changed", ["unconsumed", "late", "partial", "fractional-revision"])
def test_nonwhole_or_later_predecessor_cannot_prove_old_admission(staged_case, changed):
    from trade_plan_monitor.web.errors import ApiError

    case = staged_case
    case.pipeline._clock.current += timedelta(seconds=2)
    with case.work() as work:
        row = work.daily.session.get(DailyRecord, case.predecessor_id)
        if changed == "late":
            # This is not a completion time; even unchanged payload cannot postdate FALSE.
            row.updated_at = (case.pipeline._clock.now() - timedelta(seconds=1)).isoformat()
        elif changed == "fractional-revision":
            row.revision = 1.5
        else:
            payload = deepcopy(work.daily.get(case.predecessor_id)["payload"])
            payload.update(state="READY", simulated_qty=0, executable_qty=payload["planned_qty"])
            if changed == "partial":
                payload["simulated_qty"] = payload["planned_qty"] // 2
            row.payload_json = canonical(payload)
        work.commit()
    if changed == "partial":
        # Native atomic-quantity validation rejects this invalid stored state before projection.
        with pytest.raises(ApiError):
            read(case)
    else:
        assessed = read(case)
        actual = successor(assessed)
        assert actual.state == "UNKNOWN" and actual.facts.expected_confirmation is None
        assert len(assessed.rules) == 2 and actual.facts.root_outcome == "UNSATISFIED"


@pytest.mark.parametrize("staged_case", ["same-day-minute", "before-execution", "occurrence"],
                         indirect=True)
def test_native_date_and_missing_completion_time_return_no_successor_root(staged_case):
    actual = successor(read(staged_case))
    assert actual.state == "UNKNOWN" and actual.facts.expected_confirmation is None
    assert actual.facts.root_outcome is None and actual.facts.evaluated_at is None


@pytest.mark.parametrize("staged_case", ["date-range"], indirect=True)
def test_future_wait_keeps_original_date_restriction(staged_case):
    actual = successor(read(staged_case))
    assert actual.state in {"UNKNOWN", "MISSING_INPUT"}
    assert actual.facts.root_outcome == "UNSATISFIED"
    assert actual.facts.expected_confirmation is None


@pytest.mark.parametrize("staged_case", ["minute"], indirect=True)
@pytest.mark.parametrize("partial_present", [True, False])
def test_later_day_minute_wait_requires_actual_partial_history(staged_case, partial_present):
    from trade_plan_monitor.market_data.models import MinuteBar

    case = staged_case
    case.pipeline._clock.current += timedelta(seconds=91)
    if partial_present:
        bar = MinuteBar.model_validate_json(canonical(case.result.snapshot["minute_prefix"][-1]))
        case.pipeline.persist_minutes((bar.model_copy(update={
            "bar_end": bar.bar_end + timedelta(minutes=1),
            "received_at": case.pipeline._clock.now()}),))
    asyncio.run(case.pipeline.refresh_references(case.pipeline._clock.now().date()))
    actual = successor(read(case))
    assert actual.state == ("WAITING_OFFICIAL_CONFIRMATION" if partial_present else "MISSING_INPUT")
    assert actual.facts.root_outcome == "UNSATISFIED"
    if partial_present:
        assert (actual.facts.expected_confirmation.target.bucket_end
                > actual.facts.evaluated_target.bucket_end)
    else:
        assert actual.facts.expected_confirmation is None


@pytest.mark.parametrize("exhausts", [False, True])
def test_original_row_change_during_double_read_revokes_wait(staged_case, monkeypatch, exhausts):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case, calls = staged_case, []
    original = projection.read_readiness_binding

    def changed(*args):
        if exhausts or not calls:
            with case.work() as work:
                row = work.daily.session.get(DailyRecord, case.predecessor_id)
                row.revision += 1
                work.commit()
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    actual = successor(read(case))
    assert len(calls) == 2
    assert actual.state == "UNKNOWN" and actual.facts.expected_confirmation is None


def test_staged_get_neither_performs_work_nor_renews_bounds(staged_case, monkeypatch):
    from sqlalchemy import event

    from trade_plan_monitor.runtime import status_authority
    from trade_plan_monitor.state.daily_repository import DailyRepository

    case = staged_case
    first = successor(read(case))
    expiry = first.facts.observation.expires_at

    def forbidden(*args, **kwargs):
        pytest.fail("GET must reuse bounded original facts without work or historical evaluation")

    for owner, name in ((case.pipeline, "prepare_daily_inputs"),
                        (case.pipeline.daily_evaluations, "run_target"),
                        (case.sdk, "daily"), (case.sdk, "adj_factor"),
                        (DailyRepository, "current_signals"),
                        (status_authority, "_condition_state")):
        monkeypatch.setattr(owner, name, forbidden)

    def readonly(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().split()[0].upper() not in {
            "INSERT", "UPDATE", "DELETE", "REPLACE"}

    event.listen(case.engine, "before_cursor_execute", readonly)
    try:
        case.pipeline._clock.current += timedelta(seconds=1)
        again = successor(read(case))
        assert again.state == "WAITING_OFFICIAL_CONFIRMATION"
        assert again.facts.observation.expires_at == expiry
        assert again.facts.evaluated_at == first.facts.evaluated_at
        case.pipeline._clock.current = expiry
        expired = successor(read(case))
        assert expired.state == "UNKNOWN" and expired.facts.expected_confirmation is None
    finally:
        event.remove(case.engine, "before_cursor_execute", readonly)
