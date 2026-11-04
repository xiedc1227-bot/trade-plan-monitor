"""Actual market completion stays separate from the unchanged whole-state wrapper."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, event, select, update
from tests.integration import test_current_condition_plan_authority as current_fixture
from tests.integration.test_current_condition_plan_authority import owned_family as owned_family

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.runtime import production, status_authority
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import FiveMinuteBar, MinuteBar, TradingCalendar

pytestmark = pytest.mark.parametrize("owned_family", [5], indirect=True)


@pytest.fixture
def actual(owned_family):
    case = owned_family
    case.now = case.pipeline._clock.now()
    case.proof = case.pipeline.runtime_status_snapshot()[2][0].completion
    case.sdk = production.create_tushare_client(None)  # Existing fixture's retained offline SDK.
    assert case.proof is not None
    assert case.proof.input_stamp.immutable_record_id == case.result.evaluation_id
    assert case.proof.runtime_generation == case.pipeline._runtime_generation
    assert not case.result.duplicate
    return case


def market(case, session, *, proof=None, snapshot=None, now=None):
    return status_authority.condition_market_completion_matches(
        session,
        proof=case.proof if proof is None else proof,
        snapshot=case.result.snapshot if snapshot is None else snapshot,
        now=case.now if now is None else now,
    )


def whole(case, session, *, proof=None, snapshot=None, now=None):
    return status_authority.condition_completion_matches(
        session,
        proof=case.proof if proof is None else proof,
        snapshot=case.result.snapshot if snapshot is None else snapshot,
        now=case.now if now is None else now,
    )


def test_real_owned_immutable_completion_passes_both_checks(actual):
    case = actual
    with case.work() as work:
        assert market(case, work.daily.session) is True
        assert whole(case, work.daily.session) is True
        assert status_authority.condition_plan_completion_matches(
            work.daily.session,
            plan=case.plan,
            proof=case.proof,
            snapshot=case.result.snapshot,
            admission=None,
            now=case.now,
        )
        false = next(
            row
            for row in case.result.snapshot["ordinary_evaluations"]
            if row["rule_id"] == "sell-100"
        )
        assert false["evidence"]["outcome"] == "UNSATISFIED"


@pytest.mark.parametrize("kind", ["FACT", "POSITION", "SIGNAL", "RISK"])
def test_business_revision_leaves_market_proof_but_invalidates_old_wrapper(actual, kind):
    case = actual
    with case.work() as work:
        session = work.daily.session
        assert market(case, session) and whole(case, session)
        if kind == "RISK":
            # This valid CLEAR negative fixture adds only unrelated business state.
            work.daily.save(
                "unrelated-clear-risk",
                kind="RISK",
                symbol=case.plan.symbol,
                lineage=case.plan.symbol,
                expected_revision=0,
                payload=dict(
                    kind="ORDINARY_TECHNICAL",
                    status="CLEAR",
                    priority=3,
                    target_core_qty=0,
                    target_tactical_qty=0,
                    involves_core=True,
                    scope_evidence="Synthetic reviewed holding structure invalidation",
                    evidence_ids=[],
                    earliest_execution_date=None,
                    blockers=[],
                ),
            )
        else:
            identity = session.scalar(
                select(DailyRecord.id).where(
                    DailyRecord.symbol == case.plan.symbol, DailyRecord.kind == kind
                )
            )
            assert identity is not None
            session.execute(
                update(DailyRecord)
                .where(DailyRecord.id == identity)
                .values(revision=DailyRecord.revision + 1)
            )
        assert market(case, session) is True
        assert whole(case, session) is False
        assert not status_authority.condition_plan_completion_matches(
            session,
            plan=case.plan,
            proof=case.proof,
            snapshot=case.result.snapshot,
            admission=None,
            now=case.now,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-proof",
        "wrong-stamp",
        "result-hash",
        "missing-immutable",
        "wrong-kind",
        "wrong-symbol",
        "head",
        "different-payload",
        "future",
        "calendar",
        "minute",
        "five",
        "calendar-fingerprint",
        "minute-fingerprint",
        "five-fingerprint",
    ],
)
def test_both_paths_preserve_original_immutable_time_and_market_rejections(actual, mutation):
    case = actual
    proof, snapshot = case.proof, case.result.snapshot
    with case.work() as work:
        session = work.daily.session
        assert market(case, session) and whole(case, session)
        if mutation in {"missing-proof", "wrong-stamp"}:
            proof = None if mutation == "missing-proof" else replace(proof, input_stamp=None)
        elif mutation == "result-hash":
            proof = replace(proof, result_hash="f" * 64)
        elif mutation == "missing-immutable":
            session.execute(delete(DailyRecord).where(DailyRecord.id == case.result.evaluation_id))
        elif mutation == "wrong-kind":
            session.execute(
                update(DailyRecord)
                .where(DailyRecord.id == case.result.evaluation_id)
                .values(kind="REPORT")
            )
        elif mutation == "wrong-symbol":
            session.execute(
                update(DailyRecord)
                .where(DailyRecord.id == case.result.evaluation_id)
                .values(symbol="000001.SZ")
            )
        elif mutation == "head":
            proof = replace(
                proof,
                input_stamp=replace(
                    proof.input_stamp, immutable_record_id="evaluation-head-" + case.plan.symbol
                ),
            )
        elif mutation == "different-payload":
            altered = deepcopy(snapshot)
            altered["data_blockers"] = ["SYNTHETIC_CHANGED_RESULT"]
            session.execute(
                update(DailyRecord)
                .where(DailyRecord.id == case.result.evaluation_id)
                .values(payload_json=canonical(altered))
            )
        elif mutation == "future":
            snapshot = {**snapshot, "evaluated_at": (case.now + timedelta(seconds=1)).isoformat()}
            session.execute(
                update(DailyRecord)
                .where(DailyRecord.id == case.result.evaluation_id)
                .values(payload_json=canonical(snapshot))
            )
            proof = replace(
                proof, result_hash=status_authority._fingerprint("condition-result-v1", snapshot)
            )
        elif mutation == "calendar":
            session.execute(
                update(TradingCalendar)
                .where(
                    TradingCalendar.exchange == case.plan.market,
                    TradingCalendar.cal_date == case.now.date(),
                )
                .values(is_open=False)
            )
        elif mutation == "minute":
            session.execute(
                update(MinuteBar)
                .where(
                    MinuteBar.symbol == case.plan.symbol,
                    MinuteBar.bar_end == snapshot["minute_prefix"][0]["bar_end"],
                )
                .values(volume_shares=MinuteBar.volume_shares + 1)
            )
        elif mutation == "five":
            session.execute(
                update(FiveMinuteBar)
                .where(
                    FiveMinuteBar.symbol == case.plan.symbol,
                    FiveMinuteBar.bar_end == snapshot["five_minute_bars"][0]["bar_end"],
                    FiveMinuteBar.formula_version == "ta-v1",
                )
                .values(volume_shares=FiveMinuteBar.volume_shares + 1)
            )
        else:
            key = {
                "calendar-fingerprint": "calendar_fingerprint",
                "minute-fingerprint": "minute_fingerprint",
                "five-fingerprint": "five_minute_fingerprint",
            }[mutation]
            proof = replace(proof, input_stamp=replace(proof.input_stamp, **{key: "f" * 64}))
        assert (
            status_authority.condition_market_completion_matches(
                session, proof=proof, snapshot=snapshot, now=case.now
            )
            is False
        )
        assert (
            status_authority.condition_completion_matches(
                session, proof=proof, snapshot=snapshot, now=case.now
            )
            is False
        )


def test_only_original_market_windows_are_relevant(actual):
    case = actual
    with case.work() as work:
        session = work.daily.session
        first_five = datetime.fromisoformat(case.result.snapshot["five_minute_bars"][0]["bar_end"])
        outside = first_five - timedelta(minutes=5)
        consumed = datetime.fromisoformat(case.result.snapshot["minute_prefix"][0]["bar_end"])
        row = work.history.list_minutes(case.plan.symbol, start=consumed, end=consumed)[0]
        work.history.upsert_minutes(
            (
                row.model_copy(
                    update={
                        "bar_end": outside,
                        "volume_shares": row.volume_shares + 1,
                        "received_at": case.now,
                    }
                ),
            )
        )
        session.add(
            TradingCalendar(
                exchange=case.plan.market,
                cal_date=case.proof.input_stamp.calendar_end + timedelta(days=1),
                is_open=True,
                previous_trade_date=case.proof.input_stamp.calendar_end,
            )
        )
        session.flush()
        assert market(case, session) is True and whole(case, session) is True


def test_new_path_never_reads_whole_business_state_and_performs_no_acquisition_or_writes(
    actual, monkeypatch
):
    case = actual
    calls, writes = [], []
    native_state = status_authority._condition_state

    def state(session, symbol):
        calls.append(symbol)
        return native_state(session, symbol)

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().split()[0].upper() in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "ALTER",
        }:
            writes.append(statement)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("proof verification must not acquire provider input")

    monkeypatch.setattr(status_authority, "_condition_state", state)
    for name in ("rt_min", "rt_min_daily", "daily", "adj_factor", "trade_cal"):
        monkeypatch.setattr(case.sdk, name, forbidden, raising=False)
    event.listen(case.engine, "before_cursor_execute", capture)
    try:
        with case.work() as work:
            assert market(case, work.daily.session) is True
            assert calls == []
            assert whole(case, work.daily.session) is True
            assert calls == [case.plan.symbol]
            assert not work.daily.session.new and not work.daily.session.dirty
    finally:
        event.remove(case.engine, "before_cursor_execute", capture)
    assert writes == []


@pytest.mark.parametrize("reject", [None, "index", "minute"])
def test_guard_spies_preserve_original_order_without_claiming_a_real_p3_source(
    actual, monkeypatch, reject
):
    from trade_plan_monitor.runtime import daily_service
    from trade_plan_monitor.state import market_linkage_authority

    case = actual
    calls = []
    native_index = market_linkage_authority.linked_index_current
    native_minute = daily_service.minute_source_current
    native_sources, native_state = (
        status_authority._condition_sources,
        status_authority._condition_state,
    )

    def index(*args):
        calls.append("index")
        return False if reject == "index" else native_index(*args)

    def minute(*args):
        calls.append("minute")
        return False if reject == "minute" else native_minute(*args)

    def sources(*args):
        calls.append("sources")
        return native_sources(*args)

    def state(*args):
        calls.append("state")
        return native_state(*args)

    monkeypatch.setattr(market_linkage_authority, "linked_index_current", index)
    monkeypatch.setattr(daily_service, "minute_source_current", minute)
    monkeypatch.setattr(status_authority, "_condition_sources", sources)
    monkeypatch.setattr(status_authority, "_condition_state", state)
    expected = (
        ["index"]
        if reject == "index"
        else ["index", "minute"]
        if reject
        else ["index", "minute", "sources"]
    )
    with case.work() as work:
        assert market(case, work.daily.session) is (reject is None)
        assert calls == expected
        calls.clear()
        assert whole(case, work.daily.session) is (reject is None)
        assert calls == expected + (["state"] if reject is None else [])


@pytest.fixture
def missing_plan(monkeypatch):
    native = current_fixture.current_plan

    def plan(schema):
        raw = native(schema).model_dump(mode="json")
        raw["ordinary_rules"] = raw["ordinary_rules"][:1]
        raw["ordinary_rules"][0]["condition"] = {
            "type": "REVIEWED_FACT",
            "fact_kind": "TECHNICAL",
            "validity_scope": "TRADE_DATE",
            "evidence_requirement": "Human verifies the completed five-minute pattern",
        }
        return UnifiedTradePlan.model_validate(raw)

    monkeypatch.setattr(current_fixture, "current_plan", plan)


def test_actual_missing_fact_root_remains_missing_when_market_sources_are_complete(
    missing_plan, actual
):
    case = actual
    before = canonical(case.result.snapshot)
    assert case.result.snapshot["ordinary_evaluations"][0]["evidence"]["outcome"] == "MISSING_INPUT"
    with case.work() as work:
        assert market(case, work.daily.session) and whole(case, work.daily.session)
    assert canonical(case.result.snapshot) == before
