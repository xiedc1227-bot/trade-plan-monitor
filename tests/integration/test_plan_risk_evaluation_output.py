"""Risk observations come from the actual owned producer and admitted SDK input."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from tests.integration import current_pipeline_fixture as fixture
from tests.integration.test_current_condition_plan_authority import OwnedProgress, current_plan
from tests.integration.test_s3_missed_close_kill_restart import CurrentCloseSDK
from tests.unit.test_unified_plan_domain import unified_payload

import trade_plan_monitor.decision.daily_risk as daily_risk
import trade_plan_monitor.runtime.daily_service as daily_service
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.runtime.production import ProductionMonitorPipeline
from trade_plan_monitor.runtime.scheduler import DeadlineKind, MarketDeadline
from trade_plan_monitor.state.daily_state_models import DailyEvaluationState

FRIDAY = fixture.TARGET.date() - timedelta(days=3)
MONDAY_CLOSE = fixture.TARGET.replace(hour=15, minute=21, second=0)
TUESDAY_CLOSE = MONDAY_CLOSE + timedelta(days=1)


def risk_plan(options):
    plan = current_plan(options.get("schema", 5))
    raw = plan.model_dump(mode="json")
    branches = unified_payload()["risk_branches"]
    ordinary = next(row for row in branches if row["kind"] == "ORDINARY_TECHNICAL")
    ordinary.update(
        rule_id="ordinary-risk", risk_line_fen=options.get("line", 5000), risk_comparison="LT"
    )
    siblings = []
    if options.get("reassessment_scope"):
        ordinary["holding_scope"] = {
            "mode": "BEFORE_TRADE_DATE",
            "trade_date": str(FRIDAY + timedelta(days=1)),
        }
        siblings = [
            {
                **ordinary,
                "rule_id": "ordinary-other",
                "risk_line_fen": 6400,
                "target_tactical_qty": 100,
                "holding_scope": None,
            }
        ]
    severe = next(row for row in branches if row["kind"] == "SEVERE_TECHNICAL")
    mode = options.get("severe", "false")
    severe.update(
        rule_id="severe-risk",
        condition=(
            {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 1000}
            if mode == "missing"
            else {
                "type": "DAILY_PRICE_COMPARE",
                "field": "close",
                "offset": 0,
                "comparator": "GT" if mode == "true" else "LT",
                "reference": {
                    "mode": "FIXED",
                    "value": "4000",
                    "unit": "FEN",
                    "as_of": str(FRIDAY),
                    "source": "fixture",
                },
            }
        ),
    )
    if mode == "mixed":
        severe["condition"] = {
            "type": "ALL",
            "conditions": [
                severe["condition"],
                {"type": "MINUTE_CLOSE_BELOW", "timeframe_minutes": 5, "price_fen": 1000},
            ],
        }
    raw.update(
        risk_branches=[ordinary] if options.get("ordinary_only") else [*siblings, ordinary, severe],
        monitoring=unified_payload()["monitoring"],
    )
    return load_plan_json(canonical(raw))


@pytest.fixture
def risk_case(tmp_path, monkeypatch, request):
    options = getattr(request, "param", {})
    plan = risk_plan(options)
    trackers, controllers = [], []

    def owned(**kwargs):
        progress = OwnedProgress(kwargs["runtime_generation"], kwargs["clock"])
        trackers.append(progress.tracker)
        return ProductionMonitorPipeline(
            **kwargs, enable_runtime_status=True, progress_owner=progress
        )

    monkeypatch.setattr(fixture, "ProductionMonitorPipeline", owned)
    activation = (
        fixture.TARGET.replace(day=FRIDAY.day, hour=9, minute=0, second=0)
        if options.get("early_activation")
        else fixture.PREPARED_AT
    )
    engine, work, plan, sdk, build, controller, pipeline, published = (
        fixture.current_pipeline_fixture(
            tmp_path, monkeypatch, current_volume=300, plan=plan, activation_at=activation
        )
    )
    controllers.append(controller)
    source = CurrentCloseSDK(pipeline._clock, (plan.symbol,))

    def daily(**kwargs):
        frame = source.daily(**kwargs)
        return frame.iloc[:0] if options.get("no_series") else frame

    sdk.daily, sdk.adj_factor = daily, source.adj_factor
    calls = []
    native_evaluate = daily_service.evaluate_unified_condition

    def evaluated(condition, series, **kwargs):
        actual = native_evaluate(condition, series, **kwargs)
        calls.append((condition.model_dump(mode="json"), series, kwargs.get("target"), actual))
        return actual

    monkeypatch.setattr(daily_service, "evaluate_unified_condition", evaluated)
    comparisons = []
    native_compare = daily_risk.compare

    def compared(*args):
        comparisons.append(args)
        return native_compare(*args)

    monkeypatch.setattr(daily_risk, "compare", compared)
    case = SimpleNamespace(
        tmp_path=tmp_path,
        engine=engine,
        work=work,
        plan=plan,
        sdk=sdk,
        source=source,
        pipeline=pipeline,
        published=published,
        calls=calls,
        trackers=trackers,
        options=options,
        result=None,
        comparisons=comparisons,
    )

    def run(now=None):
        if now is not None:
            case.pipeline._clock.current = now
        clock = case.pipeline._clock.now()
        official = clock.time() >= datetime.min.time().replace(hour=15, minute=20)
        if not official:
            case.sdk.source_time = clock.replace(
                minute=clock.minute // 5 * 5, second=0
            ) - timedelta(minutes=1)
        deadline = MarketDeadline(
            kind=DeadlineKind.OFFICIAL_CLOSE if official else DeadlineKind.REALTIME_MINUTE,
            trade_date=clock.date(),
            due_at=clock,
            bar_end=None if official else clock.replace(minute=clock.minute // 5 * 5, second=0),
            close_attempt=1 if official else None,
        )

        async def actual_run():
            await case.pipeline.refresh_references(clock.date())
            return await case.pipeline.run_deadline(deadline)

        results = asyncio.run(actual_run())
        return next((item for item in results if item.symbol == case.plan.symbol), None)

    def rebuild():
        current_controller, current_pipeline, current_published = build()
        controllers.append(current_controller)
        case.pipeline, case.published = current_pipeline, current_published
        return current_pipeline

    case.run, case.rebuild = run, rebuild
    try:
        if options.get("initial", True):
            case.result = run(options.get("now"))
            assert case.result is not None
        yield case
    finally:
        for opened in controllers:
            asyncio.run(opened.aclose())
        engine.dispose()


def observations(result):
    rows = result.snapshot.get("risk_evaluations")
    assert rows, "actual owned risk evaluations were discarded"
    return {row["risk_identity"]: row for row in rows}


@pytest.mark.parametrize(
    "risk_case,outcome",
    [
        ({"severe": "true"}, "SATISFIED"),
        ({"severe": "false"}, "UNSATISFIED"),
        ({"severe": "missing"}, "MISSING_INPUT"),
        ({"severe": "mixed"}, "UNSATISFIED"),
    ],
    indirect=["risk_case"],
)
def test_actual_severe_roots_survive_even_when_the_native_cause_stays_clear(risk_case, outcome):
    case = risk_case
    row = observations(case.result)["severe-risk"]
    assert row["evidence"]["outcome"] == outcome
    assert (
        next(risk for risk in case.result.snapshot["risks"] if risk["rule_id"] == "severe-risk")[
            "status"
        ]
        == "CLEAR"
    )
    actual = [entry for entry in case.calls if entry[0] == row["evidence"]["condition"]]
    assert row["evidence"] == actual[-2][3].model_dump(mode="json")
    assert len(actual) == len(case.result.snapshot["daily_evidence"]["bars"]) + 1
    assert row["target"] == {"kind": "OFFICIAL_CLOSE", "trade_date": str(FRIDAY)}
    assert row["ordinary_close"] is None
    if case.options["severe"] == "mixed":
        assert [child["outcome"] for child in row["evidence"]["children"]] == [
            "UNSATISFIED",
            "MISSING_INPUT",
        ]
    assert row["plan_version_id"] == case.result.snapshot["plan_version_id"]
    assert row["review_id"] == case.result.snapshot["review_id"]
    assert row["activation_revision"] == case.result.activation_revision
    assert row["evaluated_at"] == case.result.snapshot["evaluated_at"]
    parsed = DailyEvaluationState.model_validate_json(canonical(case.result.snapshot))
    assert parsed.risk_evaluations[0].kind in {"ORDINARY_TECHNICAL", "SEVERE_TECHNICAL"}
    with case.work() as work:
        original = work.daily.get(case.result.evaluation_id)
        head = work.daily.get("evaluation-head-" + case.plan.symbol)
    assert original["payload"] == head["payload"] == case.result.snapshot
    assert original["kind"] == "EVALUATION" and original["id"] != head["id"]


@pytest.mark.parametrize("risk_case", [{"no_series": True}], indirect=True)
def test_actual_evaluate_none_retains_missing_input_without_a_fabricated_target(risk_case):
    case = risk_case
    assert case.result.snapshot["daily_evidence"] is None
    rows = observations(case.result)
    assert set(rows) == {"severe-risk"}
    assert rows["severe-risk"]["target"] is None
    assert rows["severe-risk"]["evidence"]["outcome"] == "MISSING_INPUT"
    actual = [
        entry for entry in case.calls if entry[0] == rows["severe-risk"]["evidence"]["condition"]
    ]
    assert len(actual) == 1 and actual[0][1] is None and actual[0][2] is None
    assert rows["severe-risk"]["evidence"] == actual[0][3].model_dump(mode="json")
    assert case.comparisons == [] and "risk_births" not in case.result.snapshot


@pytest.mark.parametrize("risk_case", [{"schema": 9}], indirect=True)
def test_existing_p3_family_emits_the_same_exact_risk_owner_binding(risk_case):
    case = risk_case
    assert case.plan.schema_version == 9
    row = observations(case.result)["severe-risk"]
    assert row["evidence"]["outcome"] == "UNSATISFIED"
    assert row["content_hash"] == case.result.snapshot["content_hash"]
    assert row["plan_version_id"] == case.result.snapshot["plan_version_id"]
    assert case.result.snapshot["runtime_generation"] == str(case.pipeline._runtime_generation)


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "severe": "true"}], indirect=True)
def test_current_severe_false_does_not_borrow_latched_true_technical_evidence(risk_case):
    case = risk_case
    old = next(risk for risk in case.result.snapshot["risks"] if risk["rule_id"] == "severe-risk")
    assert old["status"] == "CONFIRMED" and old["technical_evidence"][0]["outcome"] == "SATISFIED"
    case.source.official_closes[MONDAY_CLOSE.date()] = "35.00"
    result = case.run(MONDAY_CLOSE)
    row = observations(result)["severe-risk"]
    current = next(risk for risk in result.snapshot["risks"] if risk["rule_id"] == "severe-risk")
    assert row["evidence"]["outcome"] == "UNSATISFIED"
    assert row["target"]["trade_date"] == str(MONDAY_CLOSE.date())
    assert current["technical_evidence"] == old["technical_evidence"]
    assert current["origin_evaluation_id"] == old["origin_evaluation_id"]
    assert all(
        birth["risk_identity"] != "severe-risk" for birth in result.snapshot.get("risk_births", ())
    )


@pytest.mark.parametrize("risk_case", [{"severe": "missing", "now": MONDAY_CLOSE}], indirect=True)
def test_minute_target_is_only_the_actual_target_passed_to_the_dependent_condition(risk_case):
    case = risk_case
    row = observations(case.result)["severe-risk"]
    assert row["target"]["kind"] == "INTRADAY"
    actual = [entry for entry in case.calls if entry[0] == row["evidence"]["condition"]]
    assert row["target"]["bucket_end"] == actual[-2][2].isoformat()
    assert row["target"]["bucket_end"] == case.result.snapshot["minute_target"]
    assert row["evidence"] == actual[-2][3].model_dump(mode="json")


def test_duplicate_keeps_the_old_snapshot_bytes_and_does_not_run_metadata_evaluators(
    risk_case, monkeypatch
):
    case = risk_case
    service = case.pipeline.daily_evaluations
    inputs = service._current_inputs[case.plan.symbol]
    stable = service.run_inputs(plan=case.plan, inputs=inputs)
    calls, comparisons = len(case.calls), len(case.comparisons)
    assert not case.result.duplicate and case.result.evaluation_id
    with case.work() as work:
        before = work.daily.list(symbol=case.plan.symbol, kind="EVALUATION")
        original = work.daily.get(case.result.evaluation_id)
        assert original is not None and original["kind"] == "EVALUATION"
        assert not original["id"].startswith("evaluation-head-")
        assert original["payload"] == case.result.snapshot

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a duplicate must not save any record")

    from trade_plan_monitor.state.daily_repository import DailyRepository

    monkeypatch.setattr(DailyRepository, "save", forbidden)
    duplicate = service.run_inputs(plan=case.plan, inputs=inputs)
    assert duplicate.duplicate
    assert canonical(duplicate.snapshot) == canonical(stable.snapshot)
    assert len(case.calls) == calls and len(case.comparisons) == comparisons
    with case.work() as work:
        assert work.daily.list(symbol=case.plan.symbol, kind="EVALUATION") == before
        assert work.daily.get(original["id"]) == original
