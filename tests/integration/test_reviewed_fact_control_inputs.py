"""Actual production input preparation with temporary SQL and no provider I/O.

Target-bearing control rows are shape-valid storage engineering arrangements,
not claims of reviewed native TRADABILITY/suspension target admission. The
production method is unchanged; only its SDK/controller owners are offline.
"""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from tests.integration.test_daily_plan_chain import FRIDAY, TUESDAY, WEDNESDAY, official_proof
from tests.integration.test_reviewed_fact_target_authority import _register
from tests.integration.test_reviewed_fact_target_registration import _command, _current, _write
from tests.integration.test_unified_runtime import minute_inputs

from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import AuditLog, TradingCalendar


class UnexpectedProviderCall(BaseException):
    """Must escape the production method's provider-error fallback."""


class NoProvider:
    def __getattr__(self, name):
        raise UnexpectedProviderCall("unexpected provider/controller access: " + name)


@contextmanager
def _case(tmp_path, *, open_day=True, complete_prefix=True):
    with _current(tmp_path) as chain:
        inputs = minute_inputs(chain)
        with chain.plans._unit_of_work() as work:
            for previous, day in ((FRIDAY, TUESDAY), (TUESDAY, WEDNESDAY)):
                if day == TUESDAY and open_day is None:
                    continue
                work.daily.session.add(TradingCalendar(exchange="SSE", cal_date=day,
                    is_open=open_day if day == TUESDAY else True, previous_trade_date=previous))
            work.history.upsert_minutes(inputs.minute_prefix if complete_prefix
                                        else inputs.minute_prefix[:-1])
            work.history.upsert_five_minute(**inputs.five_minute_bars[0].model_dump())
            work.commit()

        def is_open(day):
            with chain.plans._unit_of_work() as work:
                days = work.references.list_trading_days("SSE", day, day)
                return None if not days else days[0].is_open

        pipeline = SimpleNamespace(_work=chain.plans._unit_of_work,
            _clock=SimpleNamespace(now=lambda: chain.now), provider=NoProvider(),
            _controller=NoProvider(), _daily_basis_cache={}, _runtime_generation=uuid4(),
            _deadline_minute_target=None, _running_deadline=False, is_open_on=is_open)
        yield chain, pipeline, inputs


def _prepare(chain, pipeline, inputs):
    return asyncio.run(ProductionMonitorPipeline.prepare_daily_inputs(
        pipeline, chain.plan, chain.now, None, inputs.minute_prefix))


def _snapshot(chain):
    with chain.plans._unit_of_work() as work:
        return tuple((model.__tablename__, tuple(tuple(row) for row in work.daily.session.execute(
            select(model.__table__).order_by(*model.__table__.primary_key.columns))))
            for model in (DailyRecord, AuditLog))


def _stored_control(chain, kind, *, identity="engineering-control", **changes):
    with chain.plans._unit_of_work() as work:
        bound = next((row for row in work.daily.list(symbol=chain.plan.symbol, kind="FACT")
            if row["payload"]["kind"] == "VOLUME_OR_CANDLE"
            and row["payload"].get("reviewed_fact_target", {}).get("condition_path")
                == "condition.conditions[0]"), None)
    if bound is None:
        bound = _register(chain, 0)
    proof = _command(chain, kind=kind, officialEvidence=official_proof(chain))
    payload = {**bound["payload"], "kind": kind,
        "official_evidence": proof.official_evidence.model_dump(mode="json")}
    payload.update(changes)
    with chain.plans._unit_of_work() as work:
        row = work.daily.save(identity, kind="FACT", symbol=chain.plan.symbol,
            lineage=chain.plan.plan_id, expected_revision=0, payload=payload)
        work.commit()
        return row


@pytest.mark.parametrize("kind", ["TRADABILITY", "FULL_SESSION_SUSPENSION"])
def test_actual_production_preparer_does_not_use_target_marked_control_fact(tmp_path, kind):
    with _case(tmp_path) as (chain, pipeline, inputs):
        stored = _stored_control(chain, kind)
        assert stored["payload"]["reviewed_fact_target"] is not None
        before = _snapshot(chain)
        prepared = _prepare(chain, pipeline, inputs)
        assert prepared.suspended_dates == ()
        assert prepared.quote is not None and prepared.quote.tradable is True
        assert prepared.quote.special_state_verified is False
        assert prepared.quote.liquidity_available is False
        assert prepared.minute_prefix == inputs.minute_prefix
        assert prepared.five_minute_bars == inputs.five_minute_bars
        assert _snapshot(chain) == before


def _official_control(chain, kind, **changes):
    values = dict(factId="official-" + kind, kind=kind,
                  officialEvidence=official_proof(chain))
    return _write(chain, _command(chain, **{**values, **changes}))


@pytest.mark.parametrize("kind", ["TRADABILITY", "FULL_SESSION_SUSPENSION"])
def test_target_free_official_control_keeps_its_original_behavior(tmp_path, kind):
    with _case(tmp_path) as (chain, pipeline, inputs):
        row = _official_control(chain, kind)
        assert "reviewed_fact_target" not in row["payload"]
        prepared = _prepare(chain, pipeline, inputs)
        assert prepared.suspended_dates == (() if kind == "TRADABILITY" else (TUESDAY,))
        assert prepared.quote.tradable is (kind == "TRADABILITY")
        assert prepared.quote.special_state_verified is (kind == "TRADABILITY")
        assert prepared.quote.liquidity_available is (kind == "TRADABILITY")


@pytest.mark.parametrize("kind", ["TRADABILITY", "FULL_SESSION_SUSPENSION"])
@pytest.mark.parametrize("target_first", [False, True])
def test_same_kind_target_never_overrides_or_removes_legal_unbound_control(
        tmp_path, kind, target_first):
    with _case(tmp_path) as (chain, pipeline, inputs):
        if target_first:
            _stored_control(chain, kind)
            chain.now += timedelta(seconds=1)
        _official_control(chain, kind)
        if not target_first:
            chain.now += timedelta(seconds=1)
            _stored_control(chain, kind)
        before = _snapshot(chain)
        prepared = _prepare(chain, pipeline, inputs)
        assert prepared.quote.special_state_verified is (kind == "TRADABILITY")
        assert prepared.quote.tradable is (kind == "TRADABILITY")
        assert prepared.suspended_dates == (() if kind == "TRADABILITY" else (TUESDAY,))
        assert _snapshot(chain) == before


@pytest.mark.parametrize("target_kind", ["TRADABILITY", "FULL_SESSION_SUSPENSION"])
def test_other_target_kind_cannot_contaminate_a_valid_control(tmp_path, target_kind):
    with _case(tmp_path) as (chain, pipeline, inputs):
        _stored_control(chain, target_kind)
        valid_kind = ("FULL_SESSION_SUSPENSION" if target_kind == "TRADABILITY" else "TRADABILITY")
        _official_control(chain, valid_kind)
        prepared = _prepare(chain, pipeline, inputs)
        assert prepared.quote.special_state_verified is (valid_kind == "TRADABILITY")
        assert prepared.quote.tradable is (valid_kind == "TRADABILITY")
        assert prepared.suspended_dates == (() if valid_kind == "TRADABILITY" else (TUESDAY,))


@pytest.mark.parametrize("kind", ["TRADABILITY", "FULL_SESSION_SUSPENSION"])
def test_even_an_incorrect_but_shape_valid_target_is_isolated_by_presence(tmp_path, kind):
    with _case(tmp_path) as (chain, pipeline, inputs):
        row = _stored_control(chain, kind)
        payload = deepcopy(row["payload"])
        payload["reviewed_fact_target"]["target_hash"] = "0" * 64
        with chain.plans._unit_of_work() as work:
            work.daily.save(row["id"], kind="FACT", symbol=chain.plan.symbol,
                lineage=row["lineage"], expected_revision=row["revision"], payload=payload)
            work.commit()
        prepared = _prepare(chain, pipeline, inputs)
        assert prepared.suspended_dates == ()
        assert prepared.quote.tradable is True
        assert prepared.quote.special_state_verified is False


@pytest.mark.parametrize("marker", [None, {}, [], False, {"version": "wrong"}])
def test_invalid_or_empty_marker_is_rejected_by_real_storage_not_force_inserted(tmp_path, marker):
    with _case(tmp_path) as (chain, pipeline, inputs):
        _register(chain, 0)
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _stored_control(chain, "TRADABILITY", reviewed_fact_target=marker)
        assert _snapshot(chain) == before
        assert _prepare(chain, pipeline, inputs).quote.special_state_verified is False


@pytest.mark.parametrize("kind", ["TRADABILITY", "FULL_SESSION_SUSPENSION"])
def test_negative_control_target_is_rejected_by_existing_fact_validator(tmp_path, kind):
    with _case(tmp_path) as (chain, pipeline, inputs):
        _register(chain, 0)
        before = _snapshot(chain)
        with pytest.raises(ValueError, match="negative assertions"):
            _stored_control(chain, kind, satisfied=False)
        assert _snapshot(chain) == before
        assert _prepare(chain, pipeline, inputs).suspended_dates == ()


def test_legitimate_negative_technical_target_cannot_supply_control_truth(tmp_path):
    with _case(tmp_path) as (chain, pipeline, inputs):
        row = _register(chain, 0, satisfied=False)
        assert row["payload"]["satisfied"] is False
        assert row["payload"]["reviewed_fact_target"]
        prepared = _prepare(chain, pipeline, inputs)
        assert prepared.quote.special_state_verified is False
        assert prepared.quote.tradable is True
        assert prepared.suspended_dates == ()


@pytest.mark.parametrize("kind", ["TRADABILITY", "FULL_SESSION_SUSPENSION"])
def test_previous_date_unbound_controls_keep_their_distinct_date_semantics(tmp_path, kind):
    with _case(tmp_path) as (chain, pipeline, inputs):
        _official_control(chain, kind, tradeDate=str(FRIDAY))
        prepared = _prepare(chain, pipeline, inputs)
        assert prepared.quote.special_state_verified is False
        assert prepared.quote.tradable is True
        assert prepared.suspended_dates == (() if kind == "TRADABILITY" else (FRIDAY,))


@pytest.mark.parametrize("open_day", [False, None])
def test_legal_control_does_not_invent_an_open_calendar_day(tmp_path, open_day):
    with _case(tmp_path, open_day=open_day) as (chain, pipeline, inputs):
        _official_control(chain, "TRADABILITY")
        prepared = _prepare(chain, pipeline, inputs)
        assert prepared.quote.special_state_verified is True
        assert prepared.quote.tradable is False
        assert TUESDAY not in prepared.session_dates


def test_missing_persisted_minute_does_not_become_complete_from_control_fact(tmp_path):
    with _case(tmp_path, complete_prefix=False) as (chain, pipeline, inputs):
        _official_control(chain, "TRADABILITY")
        prepared = _prepare(chain, pipeline, inputs)
        assert prepared.minute_prefix == prepared.five_minute_bars == ()
        assert "CURRENT_DAY_MINUTE_PREFIX_MISSING" in prepared.data_blockers


def test_legal_control_does_not_refresh_an_old_quote(tmp_path):
    with _case(tmp_path) as (chain, pipeline, inputs):
        _official_control(chain, "TRADABILITY")
        chain.now += timedelta(minutes=6)
        prepared = _prepare(chain, pipeline, inputs)
        assert prepared.quote is None
        assert "EXECUTION_QUOTE_UNVERIFIED" in prepared.data_blockers


def test_new_active_owner_cannot_use_prior_versions_official_control(tmp_path):
    with _case(tmp_path) as (chain, pipeline, inputs):
        row = _official_control(chain, "TRADABILITY")
        original = chain.version["id"]
        chain.activate(version=2, activation_revision=1)
        assert chain.version["id"] != original
        assert _prepare(chain, pipeline, inputs).quote.special_state_verified is False
        _official_control(chain, "TRADABILITY", factId="new-owner-control")
        assert _prepare(chain, pipeline, inputs).quote.special_state_verified is True
        with chain.plans._unit_of_work() as work:
            assert work.daily.get(row["id"])["payload"]["plan_version_id"] == original


def test_future_control_record_is_rejected_and_rolled_back_by_existing_repository(tmp_path):
    with _case(tmp_path) as (chain, pipeline, inputs):
        _register(chain, 0)
        future = (chain.now + timedelta(minutes=1)).isoformat()
        before = _snapshot(chain)
        with pytest.raises(ValueError, match="not yet available"):
            _stored_control(chain, "TRADABILITY", verified_at=future, available_at=future)
        assert _snapshot(chain) == before
        assert _prepare(chain, pipeline, inputs).quote.special_state_verified is False
