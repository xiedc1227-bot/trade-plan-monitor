"""Offline actual runtime production from privately registered ordinary targets.

FIELD sources and local temporary SQL are engineering fixtures, not extraction
acceptance. SIGNAL rows in these tests are produced by the actual runtime, never
arranged typed substitutes. No broker or external notification is exercised.
"""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, select
from tests.integration.test_daily_plan_chain import SH, TUESDAY, WEDNESDAY, Chain, official_proof
from tests.integration.test_reviewed_fact_target_authority import _check, _register
from tests.integration.test_reviewed_fact_target_registration import (
    _command,
    _current,
    _plan,
    _write,
)
from tests.integration.test_unified_runtime import minute_inputs, persist_minute_inputs
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.decision.unified_lifecycle import confirm_signal
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.market_data.aggregation import aggregate_five_minute_bar
from trade_plan_monitor.runtime.daily_service import daily_delivery_allowed
from trade_plan_monitor.state.models import FiveMinuteBar as FiveMinuteRow
from trade_plan_monitor.state.models import MinuteBar as MinuteRow
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.state.source_action_authority import require_source_action_authority
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore


def _signals(chain):
    with chain.plans._unit_of_work() as work:
        return work.daily.list(symbol=chain.plan.symbol, kind="SIGNAL")


def _run(chain):
    if chain.plan.ordinary_rules[0].confirmation.kind == "OFFICIAL_DAILY_CLOSE":
        return chain.evaluate(series=chain.series(TUESDAY), official=TUESDAY)
    return chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))


def test_actual_runtime_waits_for_b_then_produces_exact_registered_ordinary_signal(tmp_path):
    with _current(tmp_path, daily=True) as chain:
        a = _register(chain, 0)
        assert _run(chain).snapshot["signals"] == []
        assert _signals(chain) == ()
        b = _register(chain, 1)
        result = _run(chain)
        assert len(result.snapshot["signals"]) == 1
        signal = result.snapshot["signals"][0]
        assert signal["rule_id"] == "low-buy"
        assert [leaf["fact_ids"] for leaf in signal["evidence"][0]["children"]] == [
            [a["id"]], [b["id"]]]
        (row,) = _signals(chain)
        assert row["payload"]["signal_id"] == signal["signal_id"]
        assert _check(chain, row["id"])


@contextmanager
def _case(tmp_path, change=None, *, daily=True):
    raw = _plan(daily=daily).model_dump(mode="json")
    if change is not None:
        change(raw)
    chain = Chain(tmp_path)
    chain.plan = UnifiedTradePlan.model_validate(raw)
    with chain.client:
        chain.activate()
        chain.now = datetime(2026, 9, 22, 16 if daily else 9, 35, 12, tzinfo=SH)
        _run(chain)
        yield chain


def _fact(chain, path, fact_id, **changes):
    return _write(chain, _command(chain, factId=fact_id, **changes),
                  fact_selection=("ORDINARY_RULE", "low-buy", path))


@pytest.mark.parametrize("negative", [0, 1])
@pytest.mark.parametrize("operator", ["ALL", "ANY"])
def test_actual_daily_negative_affects_only_its_corresponding_leaf(tmp_path, negative, operator):
    def change(raw):
        raw["ordinary_rules"][0]["condition"]["type"] = operator

    with _case(tmp_path, change) as chain:
        facts = [_register(chain, index, satisfied=index != negative) for index in range(2)]
        result = _run(chain)
        if operator == "ALL":
            assert result.snapshot["signals"] == []
            _register(chain, negative, satisfied=True, expectedRevision=1)
            result = _run(chain)
        (signal,) = result.snapshot["signals"]
        children = signal["evidence"][0]["children"]
        assert [child["fact_ids"] for child in children] == [[row["id"]] for row in facts]
        assert [child["outcome"] for child in children] == [
            "UNSATISFIED" if operator == "ANY" and i == negative else "SATISFIED"
            for i in range(2)]
        assert _check(chain, signal["signal_id"])


def test_identical_native_leaves_still_need_two_registered_positions(tmp_path):
    def change(raw):
        root = raw["ordinary_rules"][0]["condition"]
        root["conditions"][1] = deepcopy(root["conditions"][0])

    with _case(tmp_path, change) as chain:
        a = _register(chain, 0)
        assert _run(chain).snapshot["signals"] == []
        b = _register(chain, 1)
        (signal,) = _run(chain).snapshot["signals"]
        assert [child["fact_ids"] for child in signal["evidence"][0]["children"]] == [
            [a["id"]], [b["id"]]]
        assert _check(chain, signal["signal_id"])


@pytest.mark.parametrize("damage", ["path", "hash", "other-owner"])
def test_wrong_target_does_not_enter_current_ordinary_production(tmp_path, damage):
    with _current(tmp_path, daily=True) as chain:
        if damage == "other-owner":
            _write(chain, _command(chain, factId="other-owner"), fact_selection=(
                "ORDINARY_RULE", "sell-other", "condition.conditions[0]"))
        else:
            a = _register(chain, 0)
            payload = deepcopy(a["payload"])
            target = payload["reviewed_fact_target"]
            target["condition_path" if damage == "path" else "target_hash"] = (
                "condition.conditions[1]" if damage == "path" else "0" * 64)
            # Deliberately damaged but shape-valid stored FACT, not a claim
            # that the private registration path accepts this target.
            with chain.plans._unit_of_work() as work:
                work.daily.save(a["id"], kind="FACT", symbol=chain.plan.symbol,
                    lineage=chain.plan.plan_id, expected_revision=1, payload=payload)
                work.commit()
        _register(chain, 1)
        assert _run(chain).snapshot["signals"] == []
        assert _signals(chain) == ()


def test_equal_content_successor_cannot_borrow_the_old_registered_owner(tmp_path):
    with _current(tmp_path, daily=True) as chain:
        old_a = _register(chain, 0)
        old_id, content = chain.version["id"], chain.version["contentHash"]
        chain.activate(version=2, activation_revision=1)
        assert chain.version["id"] != old_id and chain.version["contentHash"] == content
        _run(chain)
        b = _register(chain, 1)
        assert _run(chain).snapshot["signals"] == []
        a = _fact(chain, "condition.conditions[0]", "new-version-a")
        (signal,) = _run(chain).snapshot["signals"]
        assert signal["plan_version_id"] == chain.version["id"]
        assert [child["fact_ids"] for child in signal["evidence"][0]["children"]] == [
            [a["id"]], [b["id"]]]
        assert old_a["id"] != a["id"] and _check(chain, signal["signal_id"])


def test_old_ambiguous_unbound_facts_remain_blocked(tmp_path):
    with _current(tmp_path, daily=True) as chain:
        _write(chain, _command(chain, factId="old-kind-only"))
        assert _run(chain).snapshot["signals"] == []


def test_independent_daily_numeric_any_is_decisive_with_negative_and_missing_manual(tmp_path):
    def change(raw):
        raw["monitoring"] = unified_payload()["monitoring"]
        rule = raw["ordinary_rules"][0]
        manual = rule["condition"]
        manual["type"] = "ANY"
        manual["conditions"].append(dict(type="DAILY_PRICE_IN_RANGE", field="close", offset=0,
                                          range=deepcopy(raw["levels"]["low_buy"])))
        required = deepcopy(manual["conditions"][0])
        rule["condition"] = dict(type="ALL", conditions=[required, manual])

    with _case(tmp_path, change) as chain:
        _fact(chain, "condition.conditions[1].conditions[0]", "negative-a", satisfied=False)
        assert _run(chain).snapshot["signals"] == []
        _fact(chain, "condition.conditions[0]", "required-volume")
        (signal,) = _run(chain).snapshot["signals"]
        children = signal["evidence"][0]["children"][1]["children"]
        assert [child["outcome"] for child in children] == [
            "UNSATISFIED", "MISSING_INPUT", "SATISFIED"]
        assert _check(chain, signal["signal_id"])


def test_current_source_review_is_still_required_before_target_production(tmp_path):
    with _current(tmp_path, daily=True) as chain:
        for index in range(2):
            _register(chain, index)
        with chain.plans._unit_of_work() as work:
            store = SourceCoverageStore(work.daily.session)
            old = store.latest(chain.version["id"])
            store.append(chain.version["id"], old.assessment, inputs=old.inputs,
                expected_revision=old.revision, command_id="unreviewed-new-bundle", now=chain.now)
            work.commit()
        assert _run(chain).snapshot["signals"] == []
        assert _signals(chain) == ()


def test_previous_trade_date_target_cannot_confirm_the_new_official_day(tmp_path):
    with _current(tmp_path, daily=True) as chain:
        for index in range(2):
            _register(chain, index)
        chain.now = chain.now.replace(day=23)
        result = chain.evaluate(series=chain.series(WEDNESDAY), official=WEDNESDAY)
        assert all(signal["confirmed_trade_date"] != str(WEDNESDAY)
                   and signal["executable_qty"] == 0 for signal in result.snapshot["signals"])


def _minute_at_current_clock(chain, inputs):
    target = chain.now.replace(second=0, microsecond=0)
    shift = target - inputs.minute_target
    prefix = tuple(bar.model_copy(update={"bar_end": bar.bar_end + shift,
                                          "received_at": chain.now})
                   for bar in inputs.minute_prefix)
    completed = aggregate_five_minute_bar(prefix, bucket_end=target, is_open=True)
    return inputs.model_copy(update={"evaluated_at": chain.now,
        "minute_target": target, "minute_prefix": prefix,
        "five_minute_bars": (completed,),
        "quote": inputs.quote.model_copy(update={"quote_at": target,
            "available_at": chain.now, "evaluated_at": chain.now})})


def _offline_minute_run(chain, inputs, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("minute evaluation attempted network acquisition")

    with monkeypatch.context() as offline:
        offline.setattr("socket.socket", forbidden)
        offline.setattr("socket.create_connection", forbidden)
        return chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)


def _minute_position(chain):
    # Actual calendar prerequisites for the normal inventory command, not a
    # replacement authority callback or an assumed source-review grant.
    with chain.plans._unit_of_work() as work:
        for previous, day in ((TUESDAY - timedelta(days=4), TUESDAY), (TUESDAY, WEDNESDAY)):
            work.daily.session.add(TradingCalendar(exchange="SSE", cal_date=day,
                is_open=True, previous_trade_date=previous))
        work.commit()
    chain.position()


def test_actual_minute_runtime_produces_only_after_both_exact_observed_leaves(
        tmp_path, monkeypatch):
    with _current(tmp_path) as chain:
        inputs = minute_inputs(chain)
        persist_minute_inputs(chain, inputs)  # Normal source setup, never read-time recovery.
        a = _register(chain, 0)
        assert _offline_minute_run(chain, inputs, monkeypatch).snapshot["signals"] == []
        assert _signals(chain) == ()
        b = _register(chain, 1)
        result = _offline_minute_run(chain, inputs, monkeypatch)
        assert len(result.snapshot["signals"]) == 1
        (signal,) = result.snapshot["signals"]
        assert signal["confirmed_at"] == inputs.minute_target.isoformat()
        assert [child["fact_ids"] for child in signal["evidence"][0]["children"]] == [
            [a["id"]], [b["id"]]]
        (stored,) = _signals(chain)
        assert stored["id"] == signal["signal_id"]
        assert _check(chain, stored["id"])


@pytest.mark.parametrize("change", ["bar", "source"])
def test_actual_minute_producer_requires_fresh_facts_for_changed_observation(
        tmp_path, monkeypatch, change):
    with _current(tmp_path) as chain:
        original = minute_inputs(chain)
        persist_minute_inputs(chain, original)
        old = [_register(chain, i) for i in range(2)]
        chain.now += timedelta(minutes=5) if change == "bar" else timedelta(seconds=1)
        current = _minute_at_current_clock(chain, original)
        if change == "source":
            minutes = list(current.minute_prefix)
            minutes[1] = minutes[1].model_copy(update={"close_fen": 3969})
            current = current.model_copy(update={"minute_prefix": tuple(minutes)})
            assert current.five_minute_bars == original.five_minute_bars
        persist_minute_inputs(chain, current)
        assert _offline_minute_run(chain, current, monkeypatch).snapshot["signals"] == []
        assert _signals(chain) == ()
        fresh = [_fact(chain, f"condition.conditions[{i}]", f"new-{change}-{i}")
                 for i in range(2)]
        assert all(row["payload"]["reviewed_fact_observation"] != old[i]["payload"][
            "reviewed_fact_observation"] for i, row in enumerate(fresh))
        (signal,) = _offline_minute_run(chain, current, monkeypatch).snapshot["signals"]
        assert signal["confirmed_at"] == current.minute_target.isoformat()
        assert [child["fact_ids"] for child in signal["evidence"][0]["children"]] == [
            [row["id"]] for row in fresh]
        assert _check(chain, signal["signal_id"])


def test_equivalent_new_receipts_before_and_after_production_do_not_require_new_facts_or_occurrence(
        tmp_path, monkeypatch):
    with _current(tmp_path) as chain:
        _minute_position(chain)
        original = minute_inputs(chain)
        persist_minute_inputs(chain, original)
        facts = [_register(chain, i) for i in range(2)]
        chain.now += timedelta(seconds=1)
        current = _minute_at_current_clock(chain, original)
        persist_minute_inputs(chain, current)
        first = _offline_minute_run(chain, current, monkeypatch)
        (signal,) = first.snapshot["signals"]
        assert signal["state"] == "READY" and signal["executable_qty"] == 100
        (event_id,) = first.event_ids
        duplicate = _offline_minute_run(chain, current, monkeypatch)
        assert duplicate.duplicate
        assert duplicate.snapshot["signals"][0]["signal_id"] == signal["signal_id"]
        chain.now += timedelta(seconds=1)
        reread = _minute_at_current_clock(chain, original)
        persist_minute_inputs(chain, reread)
        later = _offline_minute_run(chain, reread, monkeypatch)
        assert len(_signals(chain)) == 1
        assert later.snapshot["signals"][0]["signal_id"] == signal["signal_id"]
        assert [child["fact_ids"] for child in signal["evidence"][0]["children"]] == [
            [row["id"]] for row in facts]
        assert _check(chain, signal["signal_id"])
        with chain.plans._unit_of_work() as work:
            event = work.alerts.get(UUID(event_id))
            assert daily_delivery_allowed(work.daily.session, event, chain.now)
            assert work.alerts.is_current_actionable(event, market_date=chain.now.date())


@pytest.mark.parametrize("missing", ["all", "minute", "aggregate"])
def test_actual_produced_confirmation_never_grants_action_when_local_sql_source_is_missing(
        tmp_path, monkeypatch, missing):
    with _current(tmp_path) as chain:
        _minute_position(chain)
        inputs = minute_inputs(chain)
        if missing != "all":
            persist_minute_inputs(chain, inputs)
            with chain.plans._unit_of_work() as work:
                if missing == "minute":
                    work.daily.session.execute(delete(MinuteRow).where(
                        MinuteRow.bar_end == inputs.minute_prefix[0].bar_end.isoformat()))
                else:
                    work.daily.session.execute(delete(FiveMinuteRow))
                work.commit()
        for i in range(2):
            _register(chain, i)
        result = _offline_minute_run(chain, inputs, monkeypatch)
        (signal,) = result.snapshot["signals"]
        assert signal["state"] == "CONFIRMED" and signal["executable_qty"] == 0
        assert "REVIEWED_FACT_REQUIRED" in signal["blockers"]
        assert result.event_ids == ()
        assert not _check(chain, signal["signal_id"])
        with chain.plans._unit_of_work() as work:
            work.daily.lock_symbol(chain.plan.symbol)
            with pytest.raises(SourceCoverageAuthorityError):
                require_source_action_authority(work, chain.version["id"],
                                                cause_id=signal["signal_id"])
            if missing == "all":
                assert work.daily.session.scalar(select(MinuteRow)) is None
                assert work.daily.session.scalar(select(FiveMinuteRow)) is None


@pytest.mark.parametrize("damage", ["minute-missing", "aggregate-missing", "source-correction"])
def test_actual_ready_minute_action_and_send_recheck_real_sql_after_production(
        tmp_path, monkeypatch, damage):
    with _current(tmp_path) as chain:
        _minute_position(chain)
        inputs = minute_inputs(chain)
        persist_minute_inputs(chain, inputs)
        for i in range(2):
            _register(chain, i)
        result = _offline_minute_run(chain, inputs, monkeypatch)
        (signal,) = result.snapshot["signals"]
        assert signal["state"] == "READY" and signal["executable_qty"] == 100
        (event_id,) = result.event_ids
        with chain.plans._unit_of_work() as work:
            event = work.alerts.get(UUID(event_id))
            assert event.cause_id == signal["signal_id"]
            assert daily_delivery_allowed(work.daily.session, event, chain.now)
            assert work.alerts.is_current_actionable(event, market_date=chain.now.date())
            work.daily.lock_symbol(chain.plan.symbol)
            assert require_source_action_authority(work, chain.version["id"],
                cause_id=signal["signal_id"]).basis == "CURRENT"
        chain.now += timedelta(seconds=1)
        with chain.plans._unit_of_work() as work:
            if damage == "minute-missing":
                work.daily.session.execute(delete(MinuteRow))
            elif damage == "aggregate-missing":
                work.daily.session.execute(delete(FiveMinuteRow))
            else:
                corrected = [m.model_copy(update={"received_at": chain.now})
                             for m in inputs.minute_prefix]
                corrected[1] = corrected[1].model_copy(update={"close_fen": 3969})
                work.history.upsert_minutes(tuple(corrected))
            work.commit()
        # The head and actual stored READY SIGNAL are deliberately unchanged.
        # Only the real local source is removed/corrected; no b8a mock is used.
        assert not _check(chain, signal["signal_id"])
        with chain.plans._unit_of_work() as work:
            assert not daily_delivery_allowed(work.daily.session, event, chain.now)
            assert not work.alerts.is_current_actionable(event, market_date=chain.now.date())
            work.daily.lock_symbol(chain.plan.symbol)
            with pytest.raises(SourceCoverageAuthorityError):
                require_source_action_authority(work, chain.version["id"],
                                                cause_id=signal["signal_id"])


@pytest.mark.parametrize("manual", ["missing", "negative", "stale"])
def test_actual_minute_numeric_any_remains_decisive_with_unusable_manual_branch(
        tmp_path, monkeypatch, manual):
    def change(raw):
        a, b = raw["ordinary_rules"][0]["condition"]["conditions"]
        raw["ordinary_rules"][0]["condition"] = dict(type="ALL", conditions=[a,
            dict(type="ANY", conditions=[b, dict(type="MINUTE_CLOSE_BELOW",
                                                 timeframe_minutes=5, price_fen=4000)])])

    with _case(tmp_path, change, daily=False) as chain:
        inputs = minute_inputs(chain)
        persist_minute_inputs(chain, inputs)
        if manual != "missing":
            _fact(chain, "condition.conditions[1].conditions[0]", "manual-b", satisfied=False)
        if manual == "stale":
            chain.now += timedelta(seconds=1)
            inputs = _minute_at_current_clock(chain, inputs)
            minutes = list(inputs.minute_prefix)
            minutes[1] = minutes[1].model_copy(update={"close_fen": 3969})
            inputs = inputs.model_copy(update={"minute_prefix": tuple(minutes)})
            persist_minute_inputs(chain, inputs)
        assert _offline_minute_run(chain, inputs, monkeypatch).snapshot["signals"] == []
        a = _fact(chain, "condition.conditions[0]", "required-a")
        (signal,) = _offline_minute_run(chain, inputs, monkeypatch).snapshot["signals"]
        required, independent = signal["evidence"][0]["children"]
        assert required["fact_ids"] == [a["id"]]
        assert [child["outcome"] for child in independent["children"]] == [
            "UNSATISFIED" if manual == "negative" else "MISSING_INPUT", "SATISFIED"]
        assert _check(chain, signal["signal_id"])


def test_actual_minute_numeric_any_does_not_require_manual_observation_or_local_manual_source(
        tmp_path, monkeypatch):
    def change(raw):
        root = raw["ordinary_rules"][0]["condition"]
        root["type"] = "ANY"
        root["conditions"].append(dict(type="MINUTE_CLOSE_BELOW",
                                       timeframe_minutes=5, price_fen=3970))

    with _case(tmp_path, change, daily=False) as chain:
        original = minute_inputs(chain)
        assert _signals(chain) == ()  # Initial numeric leaf is UNSATISFIED.
        for i in range(2):
            _register(chain, i)
        chain.now += timedelta(seconds=1)
        current = _minute_at_current_clock(chain, original)
        minutes = list(current.minute_prefix)
        minutes[-1] = minutes[-1].model_copy(update={"close_fen": 3969})
        aggregate = aggregate_five_minute_bar(tuple(minutes),
            bucket_end=current.minute_target, is_open=True)
        current = current.model_copy(update={"minute_prefix": tuple(minutes),
                                             "five_minute_bars": (aggregate,)})
        # No local market rows are prepared: the recorded numeric branch is
        # independent of both stale manual observations. Action market guards
        # remain separate; this assertion grants no send/trade permission.
        (signal,) = _offline_minute_run(chain, current, monkeypatch).snapshot["signals"]
        assert [child["outcome"] for child in signal["evidence"][0]["children"]] == [
            "MISSING_INPUT", "MISSING_INPUT", "SATISFIED"]
        assert _check(chain, signal["signal_id"])
        with chain.plans._unit_of_work() as work:
            assert work.daily.session.scalar(select(MinuteRow)) is None
            assert work.daily.session.scalar(select(FiveMinuteRow)) is None


@pytest.mark.parametrize("damage", ["path", "hash", "other-owner", "missing-observation"])
def test_actual_minute_targets_need_native_owner_path_digest_and_observation(
        tmp_path, monkeypatch, damage):
    with _current(tmp_path) as chain:
        inputs = minute_inputs(chain)
        persist_minute_inputs(chain, inputs)
        _register(chain, 1)
        if damage == "other-owner":
            _write(chain, _command(chain, factId="other-minute-owner"), fact_selection=(
                "ORDINARY_RULE", "sell-other", "condition.conditions[0]"))
        else:
            a = _register(chain, 0)
            payload = deepcopy(a["payload"])
            if damage == "missing-observation":
                payload.pop("reviewed_fact_observation")
            else:
                target = payload["reviewed_fact_target"]
                target["condition_path" if damage == "path" else "target_hash"] = (
                    "condition.conditions[1]" if damage == "path" else "0" * 64)
            # Explicit malformed attribution/historical shape in real storage;
            # this does not claim the private admission accepts the mutation.
            with chain.plans._unit_of_work() as work:
                work.daily.save(a["id"], kind="FACT", symbol=chain.plan.symbol,
                    lineage=a["lineage"], expected_revision=a["revision"], payload=payload)
                work.commit()
        assert _offline_minute_run(chain, inputs, monkeypatch).snapshot["signals"] == []
        assert _signals(chain) == ()


def test_actual_minute_equal_content_successor_needs_its_own_registered_facts(
        tmp_path, monkeypatch):
    with _current(tmp_path) as chain:
        inputs = minute_inputs(chain)
        persist_minute_inputs(chain, inputs)
        old = [_register(chain, i) for i in range(2)]
        old_id, content = chain.version["id"], chain.version["contentHash"]
        chain.activate(version=2, activation_revision=1, supplement_revision=1)
        assert chain.version["id"] != old_id and chain.version["contentHash"] == content
        assert _offline_minute_run(chain, inputs, monkeypatch).snapshot["signals"] == []
        b = _fact(chain, "condition.conditions[1]", "successor-b")
        assert _offline_minute_run(chain, inputs, monkeypatch).snapshot["signals"] == []
        a = _fact(chain, "condition.conditions[0]", "successor-a")
        (signal,) = _offline_minute_run(chain, inputs, monkeypatch).snapshot["signals"]
        assert signal["plan_version_id"] == chain.version["id"]
        assert [child["fact_ids"] for child in signal["evidence"][0]["children"]] == [
            [a["id"]], [b["id"]]]
        assert not {row["id"] for row in old}.intersection(
            child["fact_ids"][0] for child in signal["evidence"][0]["children"])
        assert _check(chain, signal["signal_id"])


def test_default_pure_minute_entry_does_not_gain_target_permission(tmp_path):
    with _current(tmp_path) as chain:
        rows = [_register(chain, i) for i in range(2)]
        inputs = minute_inputs(chain)
        with chain.plans._unit_of_work() as work:
            review = work.plans.get_version_details(chain.version["id"]).review_id
        assert confirm_signal(chain.plan, chain.plan.ordinary_rules[0], series=None,
            facts=tuple({"id": row["id"], **row["payload"]} for row in rows), previous=(),
            session_dates=inputs.session_dates, plan_version_id=chain.version["id"],
            review_id=review,
            bars=inputs.five_minute_bars, target=inputs.minute_target,
            trading_calendar=inputs.trading_calendar) is None


def test_old_minute_targets_without_observation_stay_blocked_at_original_and_actual_later_bar(
        tmp_path):
    with _current(tmp_path) as chain:
        for index in range(2):
            row = _register(chain, index)
            # Readable historical target shape, before observation admission;
            # not a null bypass or an implicitly upgraded registration.
            payload = {key: value for key, value in row["payload"].items()
                       if key != "reviewed_fact_observation"}
            with chain.plans._unit_of_work() as work:
                work.daily.save(row["id"], kind="FACT", symbol=chain.plan.symbol,
                    lineage=row["lineage"], expected_revision=row["revision"], payload=payload)
                work.commit()
        assert _run(chain).snapshot["signals"] == []
        original = minute_inputs(chain)
        chain.now += timedelta(minutes=5)
        inputs = _minute_at_current_clock(chain, original)
        assert inputs.minute_target.isoformat() == "2026-09-22T09:40:00+08:00"
        result = chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        assert result.snapshot["signals"] == []
        with chain.plans._unit_of_work() as work:
            head = work.daily.get("evaluation-head-" + chain.plan.symbol)["payload"]
            assert head["minute_target"] == inputs.minute_target.isoformat()


def test_stored_tradability_target_marker_cannot_restore_quote_control(tmp_path):
    with _current(tmp_path, daily=True) as chain:
        a = _register(chain, 0)
        _register(chain, 1)
        proof = _command(chain, kind="TRADABILITY", officialEvidence=official_proof(chain))
        # Engineering stored FACT only: storage permits a shaped target before
        # semantic admission. Native TRADABILITY condition review was rejected
        # by real source coverage, so do not claim private admission of it.
        with chain.plans._unit_of_work() as work:
            work.daily.save("stored-control-marker", kind="FACT", symbol=chain.plan.symbol,
                lineage=chain.plan.plan_id, expected_revision=0,
                payload={**a["payload"], "kind": "TRADABILITY",
                    "official_evidence": proof.official_evidence.model_dump(mode="json")})
            work.commit()
        # Save a real certified observation with a quote, then recover it
        # through the actual async runtime path. Only A/B supply ordinary leaf
        # testimony; the engineering control marker has no such authority.
        first = chain.evaluate(series=chain.series(TUESDAY), official=TUESDAY, price=3970)
        (signal,) = first.snapshot["signals"]
        assert _check(chain, signal["signal_id"])
        with chain.plans._unit_of_work() as work:
            work.daily.session.add(TradingCalendar(exchange="SSE", cal_date=TUESDAY,
                is_open=True, previous_trade_date=TUESDAY - timedelta(days=4)))
            work.daily.session.add(TradingCalendar(exchange="SSE", cal_date=WEDNESDAY,
                is_open=True, previous_trade_date=TUESDAY))
            work.commit()
        asyncio.run(chain.runtime.reevaluate_version(chain.version["id"]))
        with chain.plans._unit_of_work() as work:
            head = work.daily.get("evaluation-head-" + chain.plan.symbol)["payload"]
            assert head["quote"]["special_state_verified"] is False
        # Existing legitimate target-free official control facts still work.
        _write(chain, _command(chain, factId="unbound-official-control", kind="TRADABILITY",
                               officialEvidence=official_proof(chain)))
        asyncio.run(chain.runtime.reevaluate_version(chain.version["id"]))
        with chain.plans._unit_of_work() as work:
            head = work.daily.get("evaluation-head-" + chain.plan.symbol)["payload"]
            assert head["quote"]["special_state_verified"] is True


def test_default_pure_entry_does_not_gain_target_permission(tmp_path):
    with _current(tmp_path, daily=True) as chain:
        rows = [_register(chain, index) for index in range(2)]
        with chain.plans._unit_of_work() as work:
            review = work.plans.get_version_details(chain.version["id"]).review_id
        assert confirm_signal(chain.plan, chain.plan.ordinary_rules[0],
            series=chain.series(TUESDAY),
            facts=tuple({"id": r["id"], **r["payload"]} for r in rows),
            previous=(), session_dates=(TUESDAY, WEDNESDAY),
            plan_version_id=chain.version["id"], review_id=review) is None


def test_same_time_conflict_stays_local_and_blocks_the_dependent_all(tmp_path):
    with _current(tmp_path, daily=True) as chain:
        for index in range(2):
            _register(chain, index)
        _fact(chain, "condition.conditions[0]", "conflicting-a", satisfied=False)
        assert _run(chain).snapshot["signals"] == []
        assert _signals(chain) == ()


def test_daily_mixed_condition_without_completed_minute_inputs_stays_blocked(tmp_path):
    def change(raw):
        raw["ordinary_rules"][0]["condition"]["conditions"].append(dict(
            type="MINUTE_CLOSE_BELOW", timeframe_minutes=5, price_fen=4000))

    with _case(tmp_path, change) as chain:
        for index in range(2):
            _register(chain, index)
        assert _run(chain).snapshot["signals"] == []


def test_new_ordinary_targets_cannot_supply_reset_or_reminder_facts(tmp_path):
    def change(raw):
        raw["alert_rules"] = [dict(kind="RISK_ALERT", rule_id="same-kind-reminder",
            condition=deepcopy(raw["ordinary_rules"][0]["condition"]),
            confirmation={"kind": "OFFICIAL_DAILY_CLOSE"})]

    with _case(tmp_path, change) as chain:
        for index in range(2):
            _register(chain, index)
        first = _run(chain)
        (signal,) = first.snapshot["signals"]
        assert len(first.snapshot["alerts"]) == 1
        assert first.snapshot["alerts"][0]["outcome"] == "MISSING_INPUT"
        chain.now = chain.now.replace(day=23)
        chain.evaluate(series=chain.series(WEDNESDAY), official=WEDNESDAY)
        for index in range(2):
            _fact(chain, f"condition.conditions[{index}]", f"new-day-{index}",
                  tradeDate=str(WEDNESDAY))
        current = chain.evaluate(series=chain.series(WEDNESDAY), official=WEDNESDAY)
        assert len(current.snapshot["alerts"]) == 1
        assert current.snapshot["alerts"][0]["outcome"] == "MISSING_INPUT"
        with chain.plans._unit_of_work() as work:
            assert work.daily.get(signal["signal_id"])["payload"].get("reset_trade_date") is None


def test_engineering_reference_source_gate_is_not_waived(tmp_path):
    def change(raw):
        raw["monitoring"] = unified_payload()["monitoring"]
        raw["ordinary_rules"][0]["condition"]["conditions"].append(dict(
            type="DAILY_PRICE_COMPARE", field="close", offset=0, comparator="GT",
            reference=dict(mode="FIXED", value="1", unit="FEN", as_of="2026-09-18",
                           source="Synthetic explicit numeric threshold")))

    with pytest.raises(AssertionError, match="SOURCE_COVERAGE_REQUIRED"), _case(tmp_path, change):
        pytest.fail("the current source gate must remain intact pending semantic review")
