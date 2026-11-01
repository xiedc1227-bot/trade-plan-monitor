"""Private minute observation storage/admission, never consumer permission."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256

import pytest
from pydantic import ValidationError
from tests.integration.test_daily_plan_chain import SH
from tests.integration.test_reviewed_fact_target_registration import (
    SELECTION,
    _command,
    _current,
    _identity,
    _seed_bound_fact,
    _snapshot,
    _write,
)
from tests.integration.test_reviewed_fact_target_runtime import _minute_at_current_clock
from tests.integration.test_reviewed_fact_target_storage import (
    LEGACY,
    LEGACY_MODEL_BYTES,
    LEGACY_SQL_BYTES,
    _read,
    _save,
    _schema,
    _targeted,
)
from tests.integration.test_reviewed_fact_target_storage import database as database
from tests.integration.test_unified_runtime import minute_inputs

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.market_data.aggregation import FiveMinuteBar, aggregate_five_minute_bar
from trade_plan_monitor.market_data.models import MinuteBar
from trade_plan_monitor.state.daily_state_models import (
    DailyFactState,
    ReviewedFactObservation,
    reviewed_fact_observation_source_hash,
)
from trade_plan_monitor.state.repositories import RevisionConflictError
from trade_plan_monitor.web.daily_service import _record_fact
from trade_plan_monitor.web.routers.daily_plans import DailyFactCommand

GOLDEN_JSON = (
    '{"aggregate":{"amount_yuan":"5","bar_end":"2026-09-22T09:35:00.000000+08:00",'
    '"close_fen":11,"formula_version":"ta-v1","high_fen":12,"low_fen":9,"open_fen":10,'
    '"symbol":"601021.SH","volume_shares":500},"minutes":['
    '{"amount_yuan":"1","bar_end":"2026-09-22T09:31:00.000000+08:00","close_fen":11,'
    '"high_fen":12,"low_fen":9,"open_fen":10,"symbol":"601021.SH","volume_shares":100},'
    '{"amount_yuan":"1","bar_end":"2026-09-22T09:32:00.000000+08:00","close_fen":11,'
    '"high_fen":12,"low_fen":9,"open_fen":10,"symbol":"601021.SH","volume_shares":100},'
    '{"amount_yuan":"1","bar_end":"2026-09-22T09:33:00.000000+08:00","close_fen":11,'
    '"high_fen":12,"low_fen":9,"open_fen":10,"symbol":"601021.SH","volume_shares":100},'
    '{"amount_yuan":"1","bar_end":"2026-09-22T09:34:00.000000+08:00","close_fen":11,'
    '"high_fen":12,"low_fen":9,"open_fen":10,"symbol":"601021.SH","volume_shares":100},'
    '{"amount_yuan":"1","bar_end":"2026-09-22T09:35:00.000000+08:00","close_fen":11,'
    '"high_fen":12,"low_fen":9,"open_fen":10,"symbol":"601021.SH","volume_shares":100}]}'
)
GOLDEN_HASH = "4879a08e71271a6520b804d53a2b695708afc1874289a124b7ac192b6df8e713"


def _golden_values():
    end = datetime(2026, 9, 22, 9, 35, tzinfo=SH)
    minutes = tuple(MinuteBar(symbol="601021.SH", bar_end=end - timedelta(minutes=4-index),
        open_fen=10, high_fen=12, low_fen=9, close_fen=11, volume_shares=100,
        amount_yuan=Decimal("1.00"), received_at=end + timedelta(seconds=12))
        for index in range(5))
    aggregate = FiveMinuteBar(symbol="601021.SH", bar_end=end, open_fen=10, high_fen=12,
        low_fen=9, close_fen=11, volume_shares=500, amount_yuan=Decimal("5.000"))
    return minutes, aggregate


def _observed_payload(**changes):
    return {**_targeted(), "reviewed_fact_observation": {
        "bar_end": "2026-09-22T09:35:00+08:00", "source_hash": GOLDEN_HASH}, **changes}


def test_real_private_minute_registration_saves_the_actual_completed_observation(tmp_path):
    with _current(tmp_path) as chain:
        row = _write(chain, _command(chain), fact_selection=SELECTION)
        observation = row["payload"].get("reviewed_fact_observation")
        assert observation is not None
        with chain.plans._unit_of_work() as work:
            head = work.daily.get("evaluation-head-" + chain.plan.symbol)["payload"]
            assert observation["bar_end"] == head["minute_target"]
            assert len(observation["source_hash"]) == 64
            assert work.daily.get(row["id"])["payload"]["reviewed_fact_observation"] == observation


def test_independent_literal_preimage_and_fixed_sha256():
    # The expected literal and digest were specified using only standard-library
    # SHA256, before calling this generator; never obtain expected from it.
    preimage = b"reviewed-fact-observation-v1\0" + GOLDEN_JSON.encode("utf-8")
    assert len(preimage) == 1046
    assert sha256(preimage).hexdigest() == GOLDEN_HASH
    minutes, aggregate = _golden_values()
    assert reviewed_fact_observation_source_hash(minutes, aggregate) == GOLDEN_HASH


def test_content_hash_ignores_receipt_scale_order_and_ambient_decimal_context():
    minutes, aggregate = _golden_values()
    equivalent = tuple(value.model_copy(update={"amount_yuan": Decimal("1E0"),
        "received_at": value.received_at + timedelta(minutes=1)}) for value in reversed(minutes))
    with localcontext() as context:
        context.prec = 2
        assert reviewed_fact_observation_source_hash(equivalent,
            aggregate.model_copy(update={"amount_yuan": Decimal("5.0")})) == GOLDEN_HASH


def test_source_correction_changes_hash_even_when_aggregate_does_not_change():
    minutes, aggregate = _golden_values()
    corrected = list(minutes)
    corrected[1] = corrected[1].model_copy(update={"close_fen": 10})
    assert aggregate_five_minute_bar(tuple(corrected), bucket_end=aggregate.bar_end,
                                    is_open=True) == aggregate
    assert reviewed_fact_observation_source_hash(tuple(corrected), aggregate) != GOLDEN_HASH


@pytest.mark.parametrize("damage", ["missing", "duplicate", "aggregate", "foreign", "constructed"])
def test_pure_hash_rejects_incomplete_or_mismatching_typed_market_content(damage):
    minutes, aggregate = _golden_values()
    if damage == "missing":
        minutes = minutes[:-1]
    elif damage == "duplicate":
        minutes = (*minutes[:-1], minutes[0])
    elif damage == "aggregate":
        aggregate = aggregate.model_copy(update={"volume_shares": 501})
    elif damage == "foreign":
        minutes = (minutes[0].model_copy(update={"symbol": "600000.SH"}), *minutes[1:])
    else:
        bad = minutes[0].model_dump(mode="python")
        bad["volume_shares"] = -1
        minutes = (MinuteBar.model_construct(**bad), *minutes[1:])
    with pytest.raises(ValueError):
        reviewed_fact_observation_source_hash(minutes, aggregate)


def test_observation_shape_roundtrips_sql_and_preserves_audit_hash(database):
    payload = _observed_payload()
    schema = _schema(database)
    assert _save(database, payload)["revision"] == 1
    row, raw, hashes = _read(database)
    assert row["payload"] == payload
    assert DailyFactState.model_validate(row["payload"]).model_dump(mode="json") == payload
    assert raw == canonical(payload).encode()
    assert hashes == ((None, sha256(raw).hexdigest()),)
    assert _schema(database) == schema
    # Persistence is shape consistency, not authentication of source_hash.
    bad_claim = _observed_payload(reviewed_fact_observation={
        "bar_end": payload["reviewed_fact_observation"]["bar_end"], "source_hash": "0" * 64})
    assert _save(database, bad_claim, revision=1)["revision"] == 2
    assert _read(database)[0]["payload"] == bad_claim


@pytest.mark.parametrize("observation", [None, {}, [], False,
    {"bar_end": "2026-09-22T09:35:00+08:00"},
    {"bar_end": "2026-09-22T09:35:00+08:00", "source_hash": "A" * 64},
    {"bar_end": "2026-09-22T09:35:00+08:00", "source_hash": " " + "a" * 64},
    {"bar_end": "2026-09-22T09:35:00+08:00", "source_hash": 42},
    {"bar_end": "2026-09-22T09:35:00+08:00", "source_hash": "a" * 64, "extra": True},
    {"bar_end": "2026-09-22T09:36:00+08:00", "source_hash": "a" * 64},
    {"bar_end": "2026-09-22T09:35:00", "source_hash": "a" * 64},
])
def test_invalid_observation_is_rejected_at_actual_sql_save(database, observation):
    _save(database, _targeted())
    before = _read(database)
    with pytest.raises(ValueError):
        _save(database, _observed_payload(reviewed_fact_observation=observation), revision=1)
    assert _read(database) == before


@pytest.mark.parametrize("changes", [
    {"reviewed_fact_target": None}, {"trade_date": "2026-09-18"},
    {"verified_at": "2026-09-22T09:34:00+08:00"},
    {"available_at": "2026-09-22T09:34:00+08:00"},
])
def test_observation_must_have_target_same_date_and_available_verification(changes):
    with pytest.raises(ValueError):
        DailyFactState.model_validate(_observed_payload(**changes))
    payload = _observed_payload()
    payload.pop("reviewed_fact_target")
    with pytest.raises(ValueError):
        DailyFactState.model_validate(payload)


def test_nested_observation_is_revalidated_and_explicit_null_cannot_erase_it():
    value = ReviewedFactObservation.model_construct(
        bar_end=datetime(2026, 9, 22, 9, 35, tzinfo=SH), source_hash="bad")
    with pytest.raises(ValidationError):
        DailyFactState.model_validate(_observed_payload(reviewed_fact_observation=value))
    fact = DailyFactState.model_validate(_observed_payload())
    with pytest.raises(ValueError):
        fact.model_copy(update={"reviewed_fact_observation": None})
    assert fact.reviewed_fact_observation.source_hash == GOLDEN_HASH


@pytest.mark.parametrize("targeted", [False, True])
def test_legacy_model_sql_bytes_hash_and_missing_observation_stay_exact(database, targeted):
    payload = _targeted() if targeted else LEGACY
    expected_model = (canonical(payload).encode() if targeted else LEGACY_MODEL_BYTES)
    model = DailyFactState.model_validate(payload)
    if targeted:
        # Compare fields in their original model order, not repository key order.
        import json
        expected_model = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    assert model.model_dump_json().encode() == expected_model
    assert "reviewed_fact_observation" not in model.model_dump(mode="json")
    _save(database, payload)
    row, raw, hashes = _read(database)
    assert raw == (canonical(payload).encode() if targeted else LEGACY_SQL_BYTES)
    assert hashes == ((None, sha256(raw).hexdigest()),)
    assert "reviewed_fact_observation" not in row["payload"]


def test_same_observation_truth_revision_retains_cas_and_cannot_erase_binding(tmp_path):
    with _current(tmp_path) as chain:
        first = _write(chain, _command(chain), fact_selection=SELECTION)
        command = _command(chain, expectedRevision=1, satisfied=False)
        second = _write(chain, command, fact_selection=SELECTION)
        assert second["revision"] == 2 and second["payload"]["satisfied"] is False
        assert second["payload"]["reviewed_fact_target"] == first["payload"]["reviewed_fact_target"]
        assert second["payload"]["reviewed_fact_observation"] == (
            first["payload"]["reviewed_fact_observation"])
        before = _snapshot(chain)
        with pytest.raises(RevisionConflictError):
            _write(chain, command, fact_selection=SELECTION)
        with pytest.raises(ValueError):
            _write(chain, _command(chain, expectedRevision=2))
        assert _snapshot(chain) == before


def test_receipt_clock_fact_head_and_decimal_scale_changes_do_not_move_observation(tmp_path):
    with _current(tmp_path) as chain:
        first = _write(chain, _command(chain), fact_selection=SELECTION)
        with chain.plans._unit_of_work() as work:
            original = work.daily.get("evaluation-head-" + chain.plan.symbol)["payload"]
        chain.now += timedelta(seconds=10)
        chain.runtime.run_inputs(plan=chain.plan, inputs=minute_inputs(chain))
        with chain.plans._unit_of_work() as work:
            head = work.daily.get("evaluation-head-" + chain.plan.symbol)
            payload = deepcopy(head["payload"])
            assert payload != original  # New receipts, clock and fact revisions are real.
            for minute in payload["minute_prefix"]:
                minute["amount_yuan"] = format(Decimal(minute["amount_yuan"]), ".3f")
            for aggregate in payload["five_minute_bars"]:
                aggregate["amount_yuan"] = format(Decimal(aggregate["amount_yuan"]), ".3f")
            work.daily.save(head["id"], kind="EVALUATION", symbol=head["symbol"],
                lineage=head["lineage"], expected_revision=head["revision"], payload=payload)
            work.commit()
        second = _write(chain, _command(chain, expectedRevision=1), fact_selection=SELECTION)
        assert second["payload"]["reviewed_fact_observation"] == (
            first["payload"]["reviewed_fact_observation"])


def test_observation_binds_only_the_selected_completed_bucket_not_earlier_head_history(tmp_path):
    with _current(tmp_path) as chain:
        earlier = minute_inputs(chain)
        chain.now += timedelta(minutes=5)
        later = _minute_at_current_clock(chain, earlier)
        combined = later.model_copy(update={"minute_prefix": (
            *earlier.minute_prefix, *later.minute_prefix)})
        chain.runtime.run_inputs(plan=chain.plan, inputs=combined)
        first = _write(chain, _command(chain), fact_selection=SELECTION)
        assert first["payload"]["reviewed_fact_observation"]["source_hash"] == (
            reviewed_fact_observation_source_hash(later.minute_prefix, later.five_minute_bars[-1]))
        minutes = list(combined.minute_prefix)
        minutes[1] = minutes[1].model_copy(update={"close_fen": 3969})
        corrected = combined.model_copy(update={"minute_prefix": tuple(minutes)})
        chain.runtime.run_inputs(plan=chain.plan, inputs=corrected)
        second = _write(chain, _command(chain, expectedRevision=1), fact_selection=SELECTION)
        assert second["payload"]["reviewed_fact_observation"] == (
            first["payload"]["reviewed_fact_observation"])


@pytest.mark.parametrize("change", ["bar", "intrabar", "aggregate"])
def test_changed_bar_or_source_requires_a_new_fact_identity(tmp_path, change):
    with _current(tmp_path) as chain:
        first = _write(chain, _command(chain), fact_selection=SELECTION)
        original_inputs = minute_inputs(chain)
        chain.now += timedelta(minutes=5) if change == "bar" else timedelta(seconds=1)
        if change == "bar":
            inputs = _minute_at_current_clock(chain, original_inputs)
        else:
            inputs = minute_inputs(chain)
            minutes = list(inputs.minute_prefix)
            index = 1 if change == "intrabar" else 4
            minutes[index] = minutes[index].model_copy(update={"close_fen": 3969})
            bar = aggregate_five_minute_bar(tuple(minutes), bucket_end=inputs.minute_target,
                                            is_open=True)
            inputs = inputs.model_copy(update={"minute_prefix": tuple(minutes),
                                                "five_minute_bars": (bar,)})
        chain.runtime.run_inputs(plan=chain.plan, inputs=inputs)
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain, expectedRevision=1), fact_selection=SELECTION)
        assert _snapshot(chain) == before
        fresh = _write(chain, _command(chain, factId="fresh-observation"), fact_selection=SELECTION)
        assert fresh["payload"]["reviewed_fact_observation"] != (
            first["payload"]["reviewed_fact_observation"])
        with chain.plans._unit_of_work() as work:
            assert work.daily.get(first["id"])["payload"] == first["payload"]
            assert work.daily.list(symbol=chain.plan.symbol, kind="SIGNAL") == ()


def test_old_target_without_observation_is_readable_but_never_silently_upgraded(tmp_path):
    with _current(tmp_path) as chain:
        old = _seed_bound_fact(chain)
        assert "reviewed_fact_observation" not in old
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain, expectedRevision=1), fact_selection=SELECTION)
        assert _snapshot(chain) == before
        with chain.plans._unit_of_work() as work:
            assert work.daily.get(_identity(chain))["payload"] == old
        fresh = _write(chain, _command(chain, factId="fresh-observation"), fact_selection=SELECTION)
        assert "reviewed_fact_observation" in fresh["payload"]


@pytest.mark.parametrize("damage", ["missing", "aggregate", "future-receipt"])
def test_actual_head_must_still_supply_complete_available_corresponding_source(tmp_path, damage):
    with _current(tmp_path) as chain:
        with chain.plans._unit_of_work() as work:
            head = work.daily.get("evaluation-head-" + chain.plan.symbol)
            payload = deepcopy(head["payload"])
            if damage == "missing":
                payload["minute_prefix"].pop()
            elif damage == "aggregate":
                payload["five_minute_bars"][-1]["volume_shares"] += 1
            else:
                payload["minute_prefix"][0]["received_at"] = (
                    chain.now + timedelta(minutes=1)).isoformat()
            work.daily.save(head["id"], kind="EVALUATION", symbol=head["symbol"],
                lineage=head["lineage"], expected_revision=head["revision"], payload=payload)
            work.commit()
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            _write(chain, _command(chain), fact_selection=SELECTION)
        assert _snapshot(chain) == before


def test_daily_registration_does_not_add_a_minute_observation(tmp_path):
    with _current(tmp_path, daily=True) as chain:
        first = _write(chain, _command(chain), fact_selection=SELECTION)
        assert "reviewed_fact_observation" not in first["payload"]
        second = _write(chain, _command(chain, expectedRevision=1), fact_selection=SELECTION)
        assert "reviewed_fact_observation" not in second["payload"]


def test_actual_save_with_observation_rolls_back_with_the_existing_transaction(tmp_path):
    with _current(tmp_path) as chain:
        before = _snapshot(chain)
        with pytest.raises(RuntimeError, match="observation rollback probe"):
            with chain.plans._unit_of_work() as work:
                details = work.plans.get_version_details(chain.version["id"])
                work.daily.lock_symbol(details.symbol)
                row = _record_fact(
                    work, details, _command(chain), chain.now, fact_selection=SELECTION)
                assert "reviewed_fact_observation" in row["payload"]
                raise RuntimeError("observation rollback probe")
        assert _snapshot(chain) == before


@pytest.mark.parametrize("field", ["reviewed_fact_observation", "reviewedFactObservation"])
def test_public_command_and_real_http_do_not_accept_observation_input(tmp_path, field):
    with _current(tmp_path) as chain:
        payload = {**_command(chain).model_dump(mode="json", by_alias=True),
            field: {"bar_end": "2026-09-22T09:35:00+08:00", "source_hash": GOLDEN_HASH}}
        before = _snapshot(chain)
        with pytest.raises(ValueError):
            DailyFactCommand.model_validate(payload)
        response = chain.client.post("/api/v1/plan-facts", json=payload,
                                     headers={"Idempotency-Key": "no-private-observation"})
        assert response.status_code == 422
        assert _snapshot(chain) == before
