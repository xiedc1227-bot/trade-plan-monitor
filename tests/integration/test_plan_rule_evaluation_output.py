"""Actual ordinary outputs travel through the existing committed owner proof."""

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256

import pytest
from tests.integration.test_runtime_status_projection import _current_status

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.runtime import status_authority
from trade_plan_monitor.runtime.status_authority import condition_completion_matches
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_state_models import DailyEvaluationState


@pytest.fixture
def current(tmp_path, monkeypatch):
    case = _current_status(tmp_path, monkeypatch)
    try:
        yield case
    finally:
        case.close()


def readiness(case):
    return asyncio.run(case.reader.get_plan_readiness(
        version_id=case.result.snapshot["plan_version_id"]))


def test_actual_complete_false_has_no_signal_but_has_exact_owned_rule_output(current):
    snapshot = current.result.snapshot
    rows = snapshot.get("ordinary_evaluations")
    assert rows is not None, "actual producer discarded the evaluated ordinary roots"
    assert {row["rule_id"] for row in rows} == {r.rule_id for r in current.plan.ordinary_rules}
    false = next(row for row in rows if row["rule_id"] == "sell-100")
    assert false["evidence"]["outcome"] == "UNSATISFIED"
    assert not any(signal["rule_id"] == "sell-100" for signal in snapshot["signals"])
    assert false["plan_version_id"] == snapshot["plan_version_id"]
    assert false["review_id"] == snapshot["review_id"]
    assert false["content_hash"] == snapshot["content_hash"]
    assert false["activation_revision"] == snapshot["activation_revision"]
    assert false["evaluated_at"] == snapshot["evaluated_at"]
    assert false["target"] == {"kind": "INTRADAY", "bucket_end": snapshot["minute_target"]}
    assessed = readiness(current)
    rule = next(r for r in assessed.rules if r.facts.owner_id == "sell-100")
    assert rule.state == "CONDITION_FALSE"
    assert rule.facts.root_outcome == "UNSATISFIED"
    assert rule.facts.evaluated_at == current.now
    assert rule.facts.evaluated_target == current.current[0].plans[0].completion.target
    assert rule.facts.leaves[0].condition_path == "condition"
    assert rule.facts.leaves[0].evidence_refs
    assert next(a for a in assessed.axes if a.axis == "DATA_EVALUATION").state == "PASS"
    assert assessed.authority_granted is False
    assert assessed.summary != "READY_FOR_MONITORING"  # channel verification remains pending


def test_full_output_is_in_both_actual_rows_and_the_existing_result_proof(current):
    proof = current.current[0].plans[0].completion
    assert current.result.snapshot.get("ordinary_evaluations")
    with current.sessions() as session, session.begin():
        head = session.get(DailyRecord, "evaluation-head-" + current.plan.symbol)
        original = session.get(DailyRecord, proof.input_stamp.immutable_record_id)
        assert head.payload_json == original.payload_json == canonical(current.result.snapshot)
        assert condition_completion_matches(session, proof=proof,
            snapshot=current.result.snapshot, now=current.now)
        forged = deepcopy(current.result.snapshot)
        forged["ordinary_evaluations"][0]["evidence"]["outcome"] = "UNSATISFIED"
        assert not condition_completion_matches(
            session, proof=proof, snapshot=forged, now=current.now)


def test_old_absent_field_keeps_the_frozen_serialization_and_is_not_initialized():
    from pathlib import Path

    old = json.loads((Path(__file__).parents[1] / "fixtures/pma_legacy_risk_head.json").read_text(
        encoding="utf-8"))["payload"]
    encoded = DailyEvaluationState.model_validate_json(canonical(old)).model_dump_json().encode()
    assert len(encoded) == 2796
    assert sha256(encoded).hexdigest() == (
        "ec8fc2f35c34db4efe2d9b2b4cc85c317e2d7bd2292dc65d3315ff41c6e5acc8")
    assert "ordinary_evaluations" not in json.loads(encoded)


def test_corrected_source_at_the_same_target_invalidates_observed_false(current):
    target = current.result.snapshot["minute_target"]
    assert next(r for r in readiness(current).rules if r.facts.owner_id == "sell-100").state == (
        "CONDITION_FALSE")
    with current.work() as work:
        end = current.current[0].plans[0].target.bucket_end
        minute = work.history.list_minutes(current.plan.symbol, start=end, end=end)[0]
        corrected_at = max(minute.received_at, current.now) + timedelta(seconds=1)
        work.history.upsert_minutes((minute.model_copy(update={
            "volume_shares": minute.volume_shares + 1, "received_at": corrected_at}),))
        work.commit()
    current.reader._clock = lambda: corrected_at + timedelta(seconds=1)
    observed = readiness(current)
    assert current.result.snapshot["minute_target"] == target
    assert all(rule.state == "UNKNOWN" for rule in observed.rules)
    assert next(a for a in observed.axes if a.axis == "DATA_EVALUATION").state == "UNKNOWN"


@pytest.mark.parametrize("operator,root", [(None, "MISSING_INPUT"),
                                         ("ALL", "UNSATISFIED"), ("ANY", "SATISFIED")])
def test_actual_missing_leaves_survive_decisive_roots_without_becoming_false(
    tmp_path, monkeypatch, operator, root,
):
    from tests.integration.current_pipeline_fixture import current_three_rule_plan

    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    raw = current_three_rule_plan().model_dump(mode="json")
    missing = {"type": "REVIEWED_FACT", "fact_kind": "TECHNICAL",
               "evidence_requirement": "Human verifies the completed five-minute pattern",
               "validity_scope": "TRADE_DATE"}
    raw["ordinary_rules"] = raw["ordinary_rules"][:1]
    raw["ordinary_rules"][0]["condition"] = missing if operator is None else {
        "type": operator, "conditions": [
            {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5,
             "price_fen": 900 if operator == "ALL" else 1200}, missing]}
    case = _current_status(tmp_path, monkeypatch, plan=UnifiedTradePlan.model_validate(raw))
    try:
        row = case.result.snapshot["ordinary_evaluations"][0]
        assert row["evidence"]["outcome"] == root
        assessed = next(r for r in readiness(case).rules if r.facts.owner_kind == "ORDINARY_RULE")
        assert assessed.facts.root_outcome == root
        assert assessed.state == "MISSING_INPUT"
        assert assessed.reason == "HUMAN_EVIDENCE_REQUIRED"
        assert len(assessed.facts.leaves) == (1 if operator is None else 2)
        assert assessed.facts.leaves[-1].state == "MISSING_INPUT"
        assert assessed.facts.leaves[-1].condition_path == (
            "condition" if operator is None else "condition.conditions[1]")
    finally:
        case.close()


def test_observed_roots_are_the_actual_confirmation_objects_not_a_second_evaluation(
    tmp_path, monkeypatch,
):
    from trade_plan_monitor.runtime import daily_service

    original = daily_service.confirm_signal
    actual = []

    def tapped(plan, rule, **kwargs):
        sink = kwargs.get("_evaluation_observer")
        if sink is not None:
            def delivered(evidence):
                actual.append((rule.rule_id, evidence))
                sink(evidence)
            kwargs["_evaluation_observer"] = delivered
        return original(plan, rule, **kwargs)

    monkeypatch.setattr(daily_service, "confirm_signal", tapped)
    case = _current_status(tmp_path, monkeypatch)
    try:
        rows = case.result.snapshot["ordinary_evaluations"]
        assert len(actual) == len(rows) == 2
        for row, (identity, evidence) in zip(rows, actual, strict=True):
            assert row["rule_id"] == identity
            assert row["evidence"] == evidence.model_dump(mode="json")
    finally:
        case.close()


def test_old_identity_is_not_backfilled_and_default_unowned_producer_stays_legacy(
    tmp_path, monkeypatch,
):
    from trade_plan_monitor.runtime import daily_service

    original = daily_service.confirm_signal

    def old_output(*args, **kwargs):
        kwargs.pop("_evaluation_observer", None)
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(daily_service, "confirm_signal", old_output)
        case = _current_status(tmp_path, patch)
    try:
        snapshot = canonical(case.result.snapshot)
        identity = case.result.evaluation_id
        service = case.pipeline.daily_evaluations
        inputs = service._current_inputs[case.plan.symbol]
        duplicate = service.run_inputs(
            plan=case.plan, inputs=inputs, expected_activation_revision=1)
        assert duplicate.duplicate
        assert canonical(duplicate.snapshot) == snapshot
        assert "ordinary_evaluations" not in duplicate.snapshot
        with case.sessions() as session:
            assert session.get(DailyRecord, identity).payload_json == snapshot
        # Default/no current-owner observer is the retained historical profile.
        later = case.now + timedelta(seconds=1)
        case.pipeline._clock.current = later
        unowned = daily_service.DailyRuntimeEvaluationService(case.work).run_inputs(
            plan=case.plan, inputs=inputs.model_copy(update={"evaluated_at": later}),
            expected_activation_revision=1)
        assert not unowned.duplicate and "ordinary_evaluations" not in unowned.snapshot
        later += timedelta(seconds=1)
        case.pipeline._clock.current = later
        fresh = service.run_inputs(plan=case.plan,
            inputs=inputs.model_copy(update={"evaluated_at": later}),
            expected_activation_revision=1)
        assert not fresh.duplicate and fresh.snapshot["ordinary_evaluations"]
        assert fresh.evaluation_id != identity
        assert {s["signal_id"] for s in fresh.snapshot["signals"]} == {
            s["signal_id"] for s in case.result.snapshot["signals"]}
        with case.sessions() as session:
            assert session.get(DailyRecord, identity).payload_json == snapshot
            new = session.get(DailyRecord, fresh.evaluation_id)
            assert new.payload_json == canonical(fresh.snapshot)
    finally:
        case.close()


@pytest.fixture
def mixed_current(tmp_path, monkeypatch, request):
    from tests.integration import current_pipeline_fixture as pipeline_fixture
    from tests.integration.current_pipeline_fixture import current_three_rule_plan
    from tests.integration.test_explicit_runtime_production import TARGET
    from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK
    from tests.unit.test_unified_plan_domain import unified_payload

    from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan

    raw = current_three_rule_plan().model_dump(mode="json")
    raw["ordinary_rules"][0].update(
        confirmation={"kind": "OFFICIAL_DAILY_CLOSE"},
        execution_window="NEXT_EXCHANGE_SESSION_ONLY",
        condition={"type": "DAILY_PRICE_COMPARE", "field": "close", "offset": 0,
            "comparator": "LT", "reference": {"mode": "FIXED", "value": "4000",
                "unit": "FEN", "as_of": "2026-09-11", "source": "fixture"}})
    raw["monitoring"] = unified_payload()["monitoring"]
    mode = getattr(request, "param", "daily-confirmation")
    if mode in {"daily-reset", "active-risk"}:
        daily_condition = raw["ordinary_rules"][0]["condition"]
        raw["ordinary_rules"][0].update(
            confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
            execution_window="CURRENT_SESSION",
            condition={"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 900})
        if mode == "daily-reset":
            raw["ordinary_rules"][0]["independent_signal"] = {
                "mode": "LATER_CLOSE_RESET_THEN_CONFIRM", "reset_condition": daily_condition}
        else:
            raw["levels"] = unified_payload()["levels"]
            raw["risk_branches"] = [branch for branch in unified_payload()["risk_branches"]
                                    if branch["kind"] == "ORDINARY_TECHNICAL"]
    plan = UnifiedTradePlan.model_validate(raw)
    factory = pipeline_fixture.current_pipeline_fixture
    sources = []

    def activated_before_close_cycle(*args, **kwargs):
        kwargs["activation_at"] = TARGET.replace(day=11, hour=16, minute=0, second=0)
        return factory(*args, **kwargs)

    monkeypatch.setattr(pipeline_fixture, "current_pipeline_fixture", activated_before_close_cycle)

    def configure(sdk, clock, current):
        source = CurrentCloseSDK(clock, (current.symbol,),
                                official_closes={TARGET.date() - timedelta(days=3): "55.00"})
        sdk.daily, sdk.adj_factor = source.daily, source.adj_factor
        sources.append(source)

    case = _current_status(tmp_path, monkeypatch, plan=plan, configure_sdk=configure)
    case.daily_source = sources[0]
    from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService

    def owner():
        token, configuration, plans = case.pipeline.runtime_status_snapshot()
        return replace(case.current[0], token=token, configuration_revision=configuration,
                       plans=plans)

    case.owner = owner
    case.reader = RuntimeStatusReadService(case.sessions, owner,
                                         clock=case.pipeline._clock.now)
    try:
        yield case
    finally:
        case.close()


def test_mixed_targets_match_actual_daily_owner_without_downgrading_pure_minute(mixed_current):
    case = mixed_current
    assert case.current[0].plans[0].completion.target.kind == "INTRADAY"
    result = readiness(case)
    daily = next(r for r in result.rules
                 if r.facts.owner_id == case.plan.ordinary_rules[0].rule_id)
    minute = next(r for r in result.rules if r.facts.owner_kind == "ALERT_RULE")
    assert daily.state == "CONDITION_FALSE"
    assert minute.state == "CONDITION_FALSE"
    assert daily.facts.expected_target == daily.facts.evaluated_target
    assert daily.facts.evaluated_target.kind == "OFFICIAL_CLOSE"
    assert minute.facts.evaluated_target.kind == "INTRADAY"
    row = case.result.snapshot["ordinary_evaluations"][0]
    assert row["target"]["trade_date"] == str(daily.facts.evaluated_target.trade_date)
    assert row["evidence"]["operands"] == ["5500", "4000"]


def test_real_daily_correction_invalidates_only_daily_until_new_evaluation(mixed_current):
    case = mixed_current
    inputs = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol]
    day = inputs.series.bars[-1].trade_date
    case.daily_source.official_closes[day] = "35.00"
    # Force the existing owned acquisition adapter to re-admit the same day's
    # corrected fake-provider data, without running or publishing an evaluation.
    corrected = asyncio.run(case.pipeline.prepare_daily_inputs(
        case.plan, case.now, day, inputs.minute_prefix))
    assert corrected.series is not None
    assert int(corrected.series.bars[-1].close) == 3500
    assert int(inputs.series.bars[-1].close) == 5500
    proof = case.current[0].plans[0].completion
    with case.sessions() as session, session.begin():
        assert condition_completion_matches(session, proof=proof,
            snapshot=case.result.snapshot, now=case.now)
    assert not status_authority.condition_daily_admission_matches(
        proof=proof, snapshot=case.result.snapshot,
        admission=case.owner().plans[0].daily_admission, now=case.now)
    assert asyncio.run(case.reader.get_dashboard()).symbols[0].availability == "CACHED"
    daily = next(r for r in readiness(case).rules
                 if r.facts.owner_id == case.plan.ordinary_rules[0].rule_id)
    assert daily.state == "UNKNOWN"
    assert next(r for r in readiness(case).rules if r.facts.owner_kind == "ALERT_RULE").state == (
        "CONDITION_FALSE")
    fresh = case.pipeline.daily_evaluations.run_inputs(
        plan=case.plan, inputs=corrected, expected_activation_revision=1)
    assert not fresh.duplicate
    latest = case.owner().plans[0]
    assert status_authority.condition_daily_admission_matches(
        proof=latest.completion, snapshot=fresh.snapshot,
        admission=latest.daily_admission, now=case.now)
    assert next(r for r in readiness(case).rules
                if r.facts.owner_id == daily.facts.owner_id).state == "CONDITION_TRUE"


@pytest.mark.parametrize("mixed_current", ["daily-reset", "active-risk"], indirect=True)
def test_indirect_daily_dependencies_match_owner_without_polluting_minute_alerts(mixed_current):
    case = mixed_current
    row = case.result.snapshot["ordinary_evaluations"][0]
    assert row["evidence"]["condition"]["type"] == "MINUTE_CLOSE_BELOW"
    assert row["evidence"]["outcome"] == "UNSATISFIED"
    assessed = readiness(case)
    ordinary = next(rule for rule in assessed.rules if rule.facts.owner_id == row["rule_id"])
    assert ordinary.state == "CONDITION_FALSE"
    assert ordinary.facts.observation.availability == "CURRENT"
    assert next(rule for rule in assessed.rules if rule.facts.owner_kind == "ALERT_RULE").state == (
        "CONDITION_FALSE")


def test_actual_output_model_rejects_cross_owner_time_target_and_duplicate_rows(current):
    from pydantic import ValidationError

    snapshot = current.result.snapshot
    row = snapshot["ordinary_evaluations"][0]
    attacks = (
        {"plan_version_id": "other-version"}, {"review_id": "other-review"},
        {"content_hash": "f" * 64}, {"activation_revision": row["activation_revision"] + 1},
        {"evaluated_at": (current.now + timedelta(seconds=1)).isoformat()},
        {"target": {"kind": "INTRADAY", "bucket_end": (
            current.current[0].plans[0].target.bucket_end + timedelta(minutes=5)).isoformat()}},
    )
    for attack in attacks:
        corrupted = deepcopy(snapshot)
        corrupted["ordinary_evaluations"][0].update(attack)
        with pytest.raises(ValidationError):
            DailyEvaluationState.model_validate_json(canonical(corrupted))
    duplicated = deepcopy(snapshot)
    duplicated["ordinary_evaluations"] = [row, row]
    with pytest.raises(ValidationError):
        DailyEvaluationState.model_validate_json(canonical(duplicated))
    empty = deepcopy(snapshot)
    empty["ordinary_evaluations"] = []
    with pytest.raises(ValidationError):
        DailyEvaluationState.model_validate_json(canonical(empty))


def test_readiness_consumes_actual_output_without_calling_any_condition_evaluator(
    current, monkeypatch,
):
    from trade_plan_monitor.decision import unified_conditions, unified_lifecycle
    from trade_plan_monitor.runtime import daily_service

    def forbidden(*args, **kwargs):
        pytest.fail("readiness must consume committed output, never re-evaluate a condition")

    monkeypatch.setattr(unified_conditions, "evaluate_unified_condition", forbidden)
    monkeypatch.setattr(unified_lifecycle, "evaluate_unified_condition", forbidden)
    monkeypatch.setattr(daily_service, "evaluate_unified_condition", forbidden)
    monkeypatch.setattr(daily_service, "confirm_signal", forbidden)
    assert next(rule for rule in readiness(current).rules
                if rule.facts.owner_id == "sell-100").state == "CONDITION_FALSE"


def prepare_daily(case, *, official=True):
    inputs = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol]
    return asyncio.run(case.pipeline.prepare_daily_inputs(case.plan, case.pipeline._clock.now(),
        inputs.series.bars[-1].trade_date if official else None, inputs.minute_prefix))


def assert_daily_unknown(case):
    assessed = readiness(case)
    assert assessed.rules[0].state == "UNKNOWN"
    assert next(r for r in assessed.rules if r.facts.owner_kind == "ALERT_RULE").state == (
        "CONDITION_FALSE")
    assert next(a for a in assessed.axes if a.axis == "DATA_EVALUATION").state == "UNKNOWN"
    assert asyncio.run(case.reader.get_dashboard()).symbols[0].availability == "CACHED"


@pytest.mark.parametrize("change", ["historical", "uniform"])
def test_actual_factor_revisions_invalidate_the_consumed_series(mixed_current, monkeypatch, change):
    case = mixed_current
    original = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol].series
    base = case.sdk.adj_factor

    def corrected(**kwargs):
        frame = base(**kwargs)
        mask = (frame["trade_date"] == original.bars[0].trade_date.strftime("%Y%m%d")
                if change == "historical" else frame.index == frame.index)
        frame.loc[mask, "adj_factor"] = "2"
        return frame

    monkeypatch.setattr(case.sdk, "adj_factor", corrected)
    latest = prepare_daily(case).series
    assert latest is not None and latest.bars[-1].close == original.bars[-1].close
    assert (latest.basis_id == original.basis_id) == (change == "historical")
    assert latest.bars[-1].bar_id != original.bars[-1].bar_id
    assert_daily_unknown(case)


@pytest.mark.parametrize("failure", ["raw", "factor", "missing-factor", "permission"])
def test_actual_complete_acquisition_failure_revokes_prior_admission(
    mixed_current, monkeypatch, failure,
):
    from trade_plan_monitor.market_data.tushare import TushareErrorCode, TushareProviderError

    case = mixed_current
    assert case.owner().plans[0].daily_admission is not None
    base = case.sdk.adj_factor

    def failed(**kwargs):
        if failure == "missing-factor":
            return base(**kwargs).iloc[:0]
        if failure == "permission":
            raise TushareProviderError(TushareErrorCode.BLOCKED_PERMISSION, "daily")
        raise RuntimeError("offline source unavailable")

    monkeypatch.setattr(case.sdk, "daily" if failure in {"raw", "permission"}
                        else "adj_factor", failed)
    assert prepare_daily(case).series is None
    assert case.owner().plans[0].daily_admission is None
    assert_daily_unknown(case)


@pytest.mark.parametrize("path", ["head", "anchor-cache", "duplicate"])
def test_historical_reuse_never_renews_actual_daily_admission(mixed_current, path):
    case = mixed_current
    admitted = case.owner().plans[0].daily_admission
    assert admitted is not None
    case.pipeline._clock.current += timedelta(seconds=1)
    if path == "duplicate":
        inputs = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol]
        result = case.pipeline.daily_evaluations.run_inputs(
            plan=case.plan, inputs=inputs, expected_activation_revision=1)
        assert result.duplicate
    else:
        assert prepare_daily(case, official=False).series is not None
        if path == "anchor-cache":
            calls = len(case.daily_source.calls)
            case.pipeline._clock.current += timedelta(seconds=1)
            assert prepare_daily(case, official=False).series is not None
            assert len(case.daily_source.calls) == calls
    assert case.owner().plans[0].daily_admission == admitted


@pytest.mark.parametrize("boundary", ["seconds", "official-close", "midnight"])
def test_daily_admission_uses_the_actual_sdk_completion_context(
    mixed_current, monkeypatch, boundary,
):
    case = mixed_current
    assert case.owner().plans[0].daily_admission is not None
    if boundary != "seconds":
        case.pipeline._clock.current = case.now.replace(
            hour=14 if boundary == "official-close" else 23, minute=59, second=59)
    started = case.pipeline._clock.now()
    original = case.sdk.adj_factor

    def completes_later(**kwargs):
        frame = original(**kwargs)
        case.pipeline._clock.current += timedelta(seconds=3)
        return frame

    monkeypatch.setattr(case.sdk, "adj_factor", completes_later)
    inputs = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol]
    prepared = asyncio.run(case.pipeline.prepare_daily_inputs(case.plan, started,
        started.date() if boundary == "midnight" else inputs.series.bars[-1].trade_date,
        inputs.minute_prefix))
    admission = case.owner().plans[0].daily_admission
    if boundary == "seconds":
        assert admission is not None
        assert admission.accepted_at == case.pipeline._clock.now() > started
        assert prepared.series.cutoff == admission.accepted_at
    else:
        assert admission is None
        assert readiness(case).rules[0].state == "UNKNOWN"
        # This deliberately advanced fixture has no new healthy progress/health frame.
        from trade_plan_monitor.web.errors import ApiError

        with pytest.raises(ApiError, match="SERVICE_UNAVAILABLE"):
            asyncio.run(case.reader.get_dashboard())


def test_real_legacy_capture_keeps_daily_unknown_without_losing_minute(
    mixed_current, monkeypatch,
):
    case = mixed_current
    original = status_authority.capture_completion_proof

    def legacy_capture(*args, **kwargs):
        kwargs.pop("daily_admission", None)
        return original(*args, **kwargs)

    monkeypatch.setattr(status_authority, "capture_completion_proof", legacy_capture)
    case.pipeline._clock.current += timedelta(seconds=1)
    inputs = prepare_daily(case)
    result = case.pipeline.daily_evaluations.run_inputs(
        plan=case.plan, inputs=inputs, expected_activation_revision=1)
    assert not result.duplicate
    owner = case.owner().plans[0]
    assert owner.daily_admission is not None
    assert owner.completion.input_stamp.daily_admission is None
    assert_daily_unknown(case)


def test_daily_owner_get_does_not_acquire_or_write(mixed_current, monkeypatch):
    from sqlalchemy import event

    case = mixed_current
    admitted = case.owner().plans[0].daily_admission
    calls = len(case.daily_source.calls)

    def forbidden(**kwargs):
        pytest.fail("a GET cannot acquire or renew daily data")

    monkeypatch.setattr(case.sdk, "daily", forbidden)
    monkeypatch.setattr(case.sdk, "adj_factor", forbidden)

    def read_only(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().split()[0].upper() not in {
            "INSERT", "UPDATE", "DELETE", "REPLACE"}

    event.listen(case.engine, "before_cursor_execute", read_only)
    try:
        assert readiness(case).rules[0].state == "CONDITION_FALSE"
        assert asyncio.run(case.reader.get_dashboard()).symbols[0].availability == "CURRENT"
        assert case.owner().plans[0].daily_admission == admitted
        assert len(case.daily_source.calls) == calls
    finally:
        event.remove(case.engine, "before_cursor_execute", read_only)


def test_same_label_client_replacement_is_detected_during_the_read(mixed_current):
    from sqlalchemy import event
    from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK

    case = mixed_current
    replacement = CurrentCloseSDK(case.pipeline._clock, (case.plan.symbol,))
    switched = []

    def change_source(connection, cursor, statement, parameters, context, executemany):
        if not switched and "source_coverage" in statement.lower():
            switched.append(True)
            case.pipeline.provider._client._client = replacement

    event.listen(case.engine, "before_cursor_execute", change_source)
    try:
        assert_daily_unknown(case)
        assert case.owner().plans[0].daily_admission is None
        assert switched
    finally:
        event.remove(case.engine, "before_cursor_execute", change_source)


@pytest.mark.parametrize("late", ["success", "failure", "anchor-failure"])
def test_actual_late_sdk_request_cannot_replace_or_revoke_new_admission(
    mixed_current, monkeypatch, late,
):
    from threading import Event

    from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK

    from trade_plan_monitor.runtime.request_control import TushareRequestController

    case = mixed_current
    entered, release = Event(), Event()
    physical = []
    original_daily, original_factor = case.sdk.daily, case.sdk.adj_factor
    replacement = CurrentCloseSDK(case.pipeline._clock, (case.plan.symbol,),
        official_closes={case.now.date() - timedelta(days=3): "35.00"})

    def blocked(**kwargs):
        if late == "anchor-failure" and physical:
            return original_factor(**kwargs)
        physical.append("old-sdk")
        entered.set()
        assert release.wait(8), "bounded real SDK gate"
        if late != "success":
            raise RuntimeError("obsolete source failed")
        return original_daily(**kwargs)

    monkeypatch.setattr(case.sdk, "adj_factor" if late == "anchor-failure" else "daily", blocked)
    # Isolated engineering race profile; installed production stays at 1/1.
    controller = TushareRequestController(clock=case.pipeline._clock,
        executor_workers=2, max_concurrency=2, min_interval=timedelta(0),
        jitter=timedelta(0), timeout_seconds=6, in_cycle_retries=0)
    installed = case.pipeline._controller
    case.pipeline._controller = controller
    inputs = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol]

    async def run():
        task = asyncio.create_task(case.pipeline.prepare_daily_inputs(
            case.plan, case.now, None if late == "anchor-failure"
                else inputs.series.bars[-1].trade_date, inputs.minute_prefix))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            if late == "anchor-failure":
                case.daily_source.official_closes[inputs.series.bars[-1].trade_date] = "35.00"
            else:
                case.pipeline.provider._client._client = replacement
            fresh = await asyncio.wait_for(case.pipeline.prepare_daily_inputs(
                case.plan, case.now, inputs.series.bars[-1].trade_date, inputs.minute_prefix), 4)
            assert fresh.series.bars[-1].close == 3500
            admitted = case.owner().plans[0].daily_admission
            assert admitted is not None
            release.set()
            await asyncio.wait_for(task, 4)
            assert case.owner().plans[0].daily_admission == admitted
            assert physical == ["old-sdk"]
            if late != "anchor-failure":
                assert [name for name, _ in replacement.calls].count("daily") == 1
                assert [name for name, _ in replacement.calls].count("adj_factor") >= 1
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await controller.aclose()

    try:
        asyncio.run(run())
    finally:
        case.pipeline._controller = installed


def test_same_context_keeps_installed_controller_keys_and_physical_policy(
    mixed_current, monkeypatch,
):
    case = mixed_current
    original = type(case.pipeline._controller).execute
    keys = []

    async def observed(controller, operation, call, **kwargs):
        if controller is case.pipeline._controller:
            keys.append(kwargs["work_key"])
        return await original(controller, operation, call, **kwargs)

    monkeypatch.setattr(type(case.pipeline._controller), "execute", observed)
    before = len(case.daily_source.calls)
    prepare_daily(case)
    prepare_daily(case)
    # execute has no shared-result flight: two complete requests are four SDK calls.
    assert len(case.daily_source.calls) - before == 4
    assert len(keys) == 4 and keys[:2] == keys[2:]


def test_cancelled_actual_acquisition_revokes_admission(mixed_current, monkeypatch):
    from threading import Event

    case = mixed_current
    entered, release = Event(), Event()
    original = case.sdk.daily

    def blocked(**kwargs):
        entered.set()
        assert release.wait(5)
        return original(**kwargs)

    monkeypatch.setattr(case.sdk, "daily", blocked)
    inputs = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol]

    async def run():
        task = asyncio.create_task(case.pipeline.prepare_daily_inputs(
            case.plan, case.now, inputs.series.bars[-1].trade_date, inputs.minute_prefix))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert case.owner().plans[0].daily_admission is None
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())


def test_owner_completion_time_does_not_retime_the_market_cutoff(mixed_current, monkeypatch):
    from trade_plan_monitor.runtime import production

    case = mixed_current
    case.pipeline._clock.current += timedelta(seconds=1)
    original = production.admit_qfq_daily

    def completes_later(**kwargs):
        actual = original(**kwargs)
        case.pipeline._clock.current += timedelta(seconds=2)
        return actual

    monkeypatch.setattr(production, "admit_qfq_daily", completes_later)
    prepared = prepare_daily(case)
    admitted = case.owner().plans[0].daily_admission
    assert admitted.accepted_at == case.pipeline._clock.now()
    assert prepared.evaluated_at == prepared.series.cutoff < admitted.accepted_at
    fresh = case.pipeline.daily_evaluations.run_inputs(
        plan=case.plan, inputs=prepared, expected_activation_revision=1)
    assert not fresh.duplicate
    owner = case.owner().plans[0]
    assert owner.completion.input_stamp.daily_admission == admitted
    assert status_authority.condition_daily_admission_matches(proof=owner.completion,
        snapshot=fresh.snapshot, admission=admitted, now=case.pipeline._clock.now())


@pytest.mark.parametrize("cache_result", ["success", "failure"])
def test_cache_during_full_acquisition_cannot_hide_a_new_admission(
    mixed_current, monkeypatch, cache_result,
):
    from threading import Event

    from trade_plan_monitor.runtime.request_control import TushareRequestController

    case = mixed_current
    if cache_result == "success":
        prepare_daily(case, official=False)  # Real anchor cache, not a synthetic receipt.
    entered, release = Event(), Event()
    original_daily, original_factor = case.sdk.daily, case.sdk.adj_factor
    inputs = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol]
    case.daily_source.official_closes[inputs.series.bars[-1].trade_date] = "35.00"

    def full(**kwargs):
        entered.set()
        assert release.wait(7)
        return original_daily(**kwargs)

    def factor(**kwargs):
        if cache_result == "failure" and not release.is_set():
            raise RuntimeError("anchor observation failed")
        return original_factor(**kwargs)

    monkeypatch.setattr(case.sdk, "daily", full)
    monkeypatch.setattr(case.sdk, "adj_factor", factor)
    controller = TushareRequestController(clock=case.pipeline._clock,
        executor_workers=2, max_concurrency=2, min_interval=timedelta(0),
        jitter=timedelta(0), timeout_seconds=6, in_cycle_retries=0)
    installed = case.pipeline._controller
    case.pipeline._controller = controller

    async def run():
        task = asyncio.create_task(case.pipeline.prepare_daily_inputs(
            case.plan, case.now, inputs.series.bars[-1].trade_date, inputs.minute_prefix))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            cached = await case.pipeline.prepare_daily_inputs(
                case.plan, case.now, None, inputs.minute_prefix)
            assert (cached.series is not None) == (cache_result == "success")
            release.set()
            latest = await asyncio.wait_for(task, 4)
            assert latest.series.bars[-1].close == 3500
            admission = case.owner().plans[0].daily_admission
            if cache_result == "failure":
                assert admission is None  # A later real revocation fences old A.
            else:
                assert admission.series_fingerprint == status_authority._fingerprint(
                    "condition-daily-source-v1", latest.series)
                assessed = await case.reader.get_plan_readiness(
                    version_id=case.result.snapshot["plan_version_id"])
                assert assessed.rules[0].state == "UNKNOWN"
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await controller.aclose()

    try:
        asyncio.run(run())
    finally:
        case.pipeline._controller = installed
