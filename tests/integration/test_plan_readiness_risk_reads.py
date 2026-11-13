"""Read actual owned risk comparisons and maintenance through the new consumer."""

import asyncio
import json
from datetime import date, timedelta

import pytest
from tests.integration.test_daily_plan_chain import Chain, official_proof
from tests.integration.test_plan_risk_evaluation_output import MONDAY_CLOSE
from tests.integration.test_plan_risk_evaluation_output import risk_case as risk_case
from tests.integration.test_risk_origin_read_races import fact_plan as fact_plan

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.runtime.status_authority import RuntimeReadAuthority
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.database import create_session_factory
from trade_plan_monitor.state.models import PlanVersionReview
from trade_plan_monitor.web.runtime_status_read_service import RuntimeStatusReadService


@pytest.fixture
def risk_read_configuration(monkeypatch):
    from tests.integration import test_plan_risk_evaluation_output as fixture

    original = fixture.risk_plan

    def plan(options):
        native = original(options)
        if options.get("minute_neighbors"):
            return native
        raw = native.model_dump(mode="json")
        condition = dict(
            type="DAILY_PRICE_COMPARE",
            field="close",
            offset=0,
            comparator="GT",
            reference=dict(
                mode="FIXED", value="7000", unit="FEN", as_of=str(fixture.FRIDAY), source="fixture"
            ),
        )
        for rule in raw["ordinary_rules"]:
            rule.update(
                condition=condition,
                confirmation={"kind": "OFFICIAL_DAILY_CLOSE"},
                execution_window="NEXT_EXCHANGE_SESSION_ONLY",
                independent_signal={"mode": "ONCE_PER_RULE"},
            )
        for alert in raw["alert_rules"]:
            alert.update(condition=condition, confirmation={"kind": "OFFICIAL_DAILY_CLOSE"})
        return load_plan_json(canonical(raw))

    monkeypatch.setattr(fixture, "risk_plan", plan)


@pytest.fixture
def risk_read_case(risk_read_configuration, risk_case):
    from test_persistent_monitor_read_service import _setup

    case = risk_case
    other, _, _, health = _setup(case.tmp_path)
    other.dispose()

    def owner():
        token, configuration, plans = case.pipeline.runtime_status_snapshot()
        return RuntimeReadAuthority(
            token=token,
            lifecycle="RUNNING",
            health=health,
            configuration_revision=configuration,
            plans=plans,
            progress=case.trackers[-1].snapshot(),
        )

    case.latest = case.result
    case.owner = owner
    case.sessions = create_session_factory(case.engine)
    case.reader = RuntimeStatusReadService(case.sessions, owner, clock=case.pipeline._clock.now)
    return case


def read(case):
    return asyncio.run(
        case.reader.get_plan_readiness(version_id=case.latest.snapshot["plan_version_id"])
    )


def branch(result, identity):
    return next(rule for rule in result.rules if rule.facts.owner_id == identity)


def cycle(case, at):
    case.latest = case.run(at)
    assert case.latest is not None and not case.latest.duplicate
    return case.latest


def recover_and_cycle(case, at):
    case.pipeline._clock.current = at
    end = at.replace(minute=at.minute // 5 * 5, second=0)
    if end.hour >= 15:
        end = end.replace(hour=15, minute=0)
    case.sdk.source_time = end - timedelta(minutes=1)

    async def recovered():
        await case.pipeline.refresh_references(at.date())
        await case.pipeline.recover_startup(at.date())

    asyncio.run(recovered())
    case.latest = case.run(at)
    assert case.latest is not None
    assert case.owner().plans[0].completion is not None
    return case.latest


@pytest.mark.parametrize("risk_case", [{"early_activation": True}], indirect=True)
def test_actual_clear_ordinary_close_is_false_without_a_fabricated_root(risk_read_case):
    case = risk_read_case
    actual = branch(read(case), "ordinary-risk")
    assert actual.facts.risk is not None
    assert actual.facts.risk.current.ordinary_close.below is False
    assert actual.state == "CONDITION_FALSE"
    assert actual.facts.root_outcome is None and actual.facts.leaves == ()
    assert actual.facts.risk.maintenance.state == "PASS"
    cycle(case, MONDAY_CLOSE)
    complete = read(case)
    assert next(axis for axis in complete.axes if axis.axis == "DATA_EVALUATION").state == "PASS"


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "severe": "true"}], indirect=True)
def test_current_severe_false_and_old_confirmed_obligation_are_both_visible(risk_read_case):
    case = risk_read_case
    original = next(row for row in case.latest.snapshot["risks"] if row["rule_id"] == "severe-risk")
    case.source.official_closes[MONDAY_CLOSE.date()] = "35.00"
    cycle(case, MONDAY_CLOSE)
    actual = branch(read(case), "severe-risk")
    assert actual.state == "CONDITION_FALSE"
    assert actual.facts.root_outcome == "UNSATISFIED"
    assert actual.facts.risk.obligation.status == "CONFIRMED"
    assert actual.facts.risk.origin.evaluation_id == original["origin_evaluation_id"]
    assert actual.facts.risk.current.evidence.outcome == "UNSATISFIED"


@pytest.mark.parametrize(
    "risk_case", [{"early_activation": True, "line": 6500, "ordinary_only": True}], indirect=True
)
def test_actual_confirmed_ordinary_skip_has_only_current_maintenance(risk_read_case):
    case = risk_read_case
    cycle(case, MONDAY_CLOSE)
    confirmed = branch(read(case), "ordinary-risk")
    assert confirmed.state == "CONDITION_TRUE"
    assert confirmed.facts.root_outcome is None and confirmed.facts.leaves == ()
    cycle(case, MONDAY_CLOSE + timedelta(minutes=1))
    assert not any(
        row["risk_identity"] == "ordinary-risk"
        for row in case.latest.snapshot.get("risk_evaluations", ())
    )
    actual = branch(read(case), "ordinary-risk")
    assert actual.state == "UNKNOWN"
    assert actual.facts.risk.current is None
    assert actual.facts.evaluated_at is None and actual.facts.evaluated_target is None
    assert actual.facts.risk.maintenance.state == "PASS"
    result = read(case)
    # Native risk admission skips ordinary trade confirmation too. Their absent
    # observations remain applicable UNKNOWN; risk maintenance cannot hide them.
    assert any(
        rule.facts.owner_kind == "ORDINARY_RULE"
        and rule.state in {"UNKNOWN", "AWAITING_FIRST_EVALUATION"}
        for rule in result.rules
    )
    assert next(axis for axis in result.axes if axis.axis == "DATA_EVALUATION").state == "UNKNOWN"


@pytest.mark.parametrize(
    "risk_case",
    [{"early_activation": True, "minute_neighbors": True, "severe": "true"}],
    indirect=True,
)
def test_real_minute_recovery_keeps_daily_risk_false_independent_of_old_minute_age(risk_read_case):
    case = risk_read_case
    case.source.official_closes[MONDAY_CLOSE.date()] = "35.00"
    case.pipeline._clock.current = MONDAY_CLOSE
    case.sdk.source_time = MONDAY_CLOSE.replace(hour=15, minute=0) - timedelta(minutes=1)

    async def recovered():
        await case.pipeline.refresh_references(MONDAY_CLOSE.date())
        await case.pipeline.recover_startup(MONDAY_CLOSE.date())

    asyncio.run(recovered())
    case.latest = case.run(MONDAY_CLOSE)
    assert not case.latest.snapshot["data_blockers"]
    assert case.owner().plans[0].completion is not None
    actual = branch(read(case), "severe-risk")
    assert actual.state == "CONDITION_FALSE"
    assert actual.facts.risk.maintenance.state == "PASS"


@pytest.mark.parametrize(
    "risk_case", [{"early_activation": True, "line": 6500, "ordinary_only": True}], indirect=True
)
def test_first_breach_uses_only_the_actual_future_second_close_without_inventing_true(
    risk_read_case,
):
    case = risk_read_case
    actual = branch(read(case), "ordinary-risk")
    assert actual.facts.risk.current.ordinary_close.status_after == "PENDING"
    assert actual.facts.root_outcome is None and actual.facts.leaves == ()
    assert actual.state == "WAITING_OFFICIAL_CONFIRMATION"
    assert actual.facts.expected_confirmation.target.trade_date == MONDAY_CLOSE.date()
    assert actual.facts.expected_confirmation.expected_at > case.pipeline._clock.now()


@pytest.mark.parametrize(
    "risk_case", [{"early_activation": True, "line": 6500, "ordinary_only": True}], indirect=True
)
def test_actual_second_close_rebound_remains_false_and_retains_the_old_cause(risk_read_case):
    case = risk_read_case
    case.source.official_closes[MONDAY_CLOSE.date()] = "70.00"
    cycle(case, MONDAY_CLOSE)
    actual = branch(read(case), "ordinary-risk")
    assert actual.facts.risk.current.ordinary_close.confirmation_close_used is True
    assert actual.state == "CONDITION_FALSE"
    assert actual.facts.risk.obligation.status == "OBSERVATION"
    assert actual.facts.root_outcome is None and actual.facts.leaves == ()


@pytest.mark.parametrize("risk_case", [{"early_activation": True}], indirect=True)
def test_exact_current_risk_revision_is_required_for_maintenance(risk_read_case):
    case = risk_read_case
    before = branch(read(case), "ordinary-risk")
    assert before.facts.risk.maintenance.state == "PASS"
    with case.sessions.begin() as session:
        session.get(DailyRecord, before.facts.risk.obligation.risk_id).revision += 1
    after = branch(read(case), "ordinary-risk")
    assert after.state == "CONDITION_FALSE"
    assert after.facts.risk.current is not None
    assert after.facts.risk.maintenance.state == "UNKNOWN"


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "severe": "true"}], indirect=True)
def test_missing_origin_keeps_independently_valid_current_false_and_persisted_obligation(
    risk_read_case,
):
    case = risk_read_case
    case.source.official_closes[MONDAY_CLOSE.date()] = "35.00"
    cycle(case, MONDAY_CLOSE)
    before = branch(read(case), "severe-risk")
    assert before.facts.risk.origin is not None
    with case.sessions.begin() as session:
        row = session.get(DailyRecord, before.facts.risk.obligation.risk_id)
        payload = json.loads(row.payload_json)
        payload.pop("origin_evaluation_id")
        row.payload_json = canonical(payload)
    after = branch(read(case), "severe-risk")
    assert after.state == "CONDITION_FALSE"
    assert after.facts.risk.obligation.status == "CONFIRMED"
    assert after.facts.risk.origin is None and after.facts.risk.maintenance.state == "UNKNOWN"


@pytest.mark.parametrize("risk_case", [{"early_activation": True}], indirect=True)
def test_new_daily_admission_cannot_certify_the_old_risk_comparison(risk_read_case):
    case = risk_read_case
    before = branch(read(case), "ordinary-risk")
    assert before.state == "CONDITION_FALSE"
    inputs = case.pipeline.daily_evaluations._current_inputs[case.plan.symbol]
    day = inputs.series.bars[-1].trade_date
    case.source.official_closes[day] = "70.00"
    result = asyncio.run(
        case.pipeline.prepare_daily_inputs(
            case.plan, case.pipeline._clock.now(), day, inputs.minute_prefix
        )
    )
    assert result.series.bars[-1].close == 7000
    after = branch(read(case), "ordinary-risk")
    assert after.facts.risk.current is None and after.facts.risk.maintenance.state == "UNKNOWN"


@pytest.fixture
def fact_read_case(fact_plan, risk_read_case):
    return risk_read_case


class PausedReevaluation:
    async def reevaluate_version(self, _version):
        return None


def register_structure(case):
    chain = Chain(case.tmp_path)
    chain.plan, chain.now, chain.runtime = (
        case.plan,
        case.pipeline._clock.now(),
        PausedReevaluation(),
    )
    with chain.client:
        return chain.post(
            "plan-facts",
            {
                "planVersionId": case.latest.snapshot["plan_version_id"],
                "contentHash": case.latest.snapshot["content_hash"],
                "factId": "risk-structure",
                "kind": "SEVERE_STRUCTURE",
                "tradeDate": str(case.latest.snapshot["official_trade_date"]),
                "evidence": "Synthetic complete technical failure independently verified",
                "expectedRevision": 0,
            },
        )


@pytest.mark.parametrize("risk_case", [{"early_activation": True}], indirect=True)
def test_actual_missing_fact_and_unconsumed_new_fact_keep_their_distinct_states(fact_read_case):
    case = fact_read_case
    missing = branch(read(case), "severe-risk")
    assert missing.state == "MISSING_INPUT"
    assert missing.facts.risk.current.evidence.outcome == "MISSING_INPUT"
    assert missing.facts.risk.maintenance.state == "UNKNOWN"
    receipt = register_structure(case)
    unconsumed = branch(read(case), "severe-risk")
    assert unconsumed.facts.risk.current is None
    cycle(case, case.pipeline._clock.now() + timedelta(seconds=1))
    confirmed = branch(read(case), "severe-risk")
    assert confirmed.state == "CONDITION_TRUE"
    assert confirmed.facts.risk.origin is not None
    with case.sessions.begin() as session:
        session.delete(session.get(DailyRecord, receipt["id"]))
    after = branch(read(case), "severe-risk")
    assert after.facts.risk.current is None and after.facts.risk.origin is None
    assert after.facts.risk.obligation.status == "CONFIRMED"


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "severe": "true"}], indirect=True)
def test_exhausted_context_clear_retains_history_and_diagnostics_without_model_errors(
    risk_read_case,
):
    from trade_plan_monitor.web.plan_readiness_service import changed_readiness

    before = read(risk_read_case)
    assert branch(before, "severe-risk").facts.risk.origin is not None
    after = changed_readiness(before)
    for actual in after.rules:
        if actual.facts.risk is None:
            continue
        original = branch(before, actual.facts.owner_id)
        assert actual.facts.risk.current is None
        assert actual.facts.risk.obligation == original.facts.risk.obligation
        assert actual.facts.risk.origin is None
        assert actual.facts.risk.maintenance.state == "UNKNOWN"
        assert actual.facts.evaluated_at is None and actual.facts.evaluated_target is None
        assert actual.facts.root_outcome is None


def activate_successor(case):
    chain = Chain(case.tmp_path)
    chain.plan, chain.now, chain.runtime = (
        case.plan,
        case.pipeline._clock.now(),
        PausedReevaluation(),
    )
    with chain.client:
        chain.activate(version=2, activation_revision=1)
        chain.post(
            "plan-facts",
            {
                "planVersionId": chain.version["id"],
                "contentHash": chain.version["contentHash"],
                "factId": "successor-tradability",
                "kind": "TRADABILITY",
                "tradeDate": str(chain.now.date()),
                "evidence": "Synthetic verified current-day tradability and liquidity fixture.",
                "officialEvidence": official_proof(chain),
                "expectedRevision": 0,
            },
        )
    case.rebuild()
    # A newly activated daily plan cannot consume the previous session's close
    # as a fresh current evaluation. Use its first real post-activation close.
    cycle(case, MONDAY_CLOSE)


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "severe": "true"}], indirect=True)
def test_superseded_origin_is_not_rebound_to_the_active_plan_or_trade_input_unknowns(
    risk_read_case,
):
    case = risk_read_case
    original = branch(read(case), "severe-risk").facts.risk.origin
    activate_successor(case)
    result = read(case)
    actual = branch(result, "severe-risk")
    assert actual.facts.risk.origin == original
    assert actual.facts.risk.origin.plan_version_id != str(result.snapshot.context.plan_version_id)
    assert actual.facts.risk.maintenance.state == "PASS"
    assert any(
        rule.facts.side == "BUY" and rule.state in {"UNKNOWN", "AWAITING_FIRST_EVALUATION"}
        for rule in result.rules
    )
    assert actual.facts.execution.eligible is None  # No SELL permission is manufactured.


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "severe": "true"}], indirect=True)
@pytest.mark.parametrize("change", ["risk-revision", "origin-raw-review"])
def test_risk_and_verified_original_raw_bindings_participate_in_the_existing_double_read(
    risk_read_case,
    monkeypatch,
    change,
):
    from trade_plan_monitor.web import plan_readiness_service as projection

    case = risk_read_case
    activate_successor(case)
    before = branch(read(case), "severe-risk")
    original, calls = projection.read_readiness_binding, []

    def changed(*args):
        if not calls:
            with case.sessions.begin() as session:
                if change == "risk-revision":
                    session.get(DailyRecord, before.facts.risk.obligation.risk_id).revision += 1
                else:
                    row = session.get(PlanVersionReview, before.facts.risk.origin.plan_version_id)
                    row.review_issues_json = '["synthetic original raw review metadata"]'
        calls.append(True)
        return original(*args)

    monkeypatch.setattr(projection, "read_readiness_binding", changed)
    after = branch(read(case), "severe-risk")
    assert len(calls) == 2
    assert after.facts.risk.origin == before.facts.risk.origin
    assert after.facts.risk.maintenance.state == (
        "UNKNOWN" if change == "risk-revision" else "PASS"
    )


@pytest.mark.parametrize(
    "risk_case",
    [{"early_activation": True, "line": 6500, "ordinary_only": True, "minute_neighbors": True}],
    indirect=True,
)
def test_real_fulfillment_skip_and_new_birth_keep_distinct_original_causes(
    risk_read_case, monkeypatch
):
    case = risk_read_case
    recover_and_cycle(case, MONDAY_CLOSE)
    tuesday = MONDAY_CLOSE + timedelta(days=1)
    morning = tuesday.replace(hour=10, minute=5, second=15)
    chain = Chain(case.tmp_path)
    chain.plan, chain.now, chain.runtime = case.plan, morning, PausedReevaluation()
    with chain.client:
        chain.post(
            "plan-facts",
            {
                "planVersionId": case.latest.snapshot["plan_version_id"],
                "contentHash": case.latest.snapshot["content_hash"],
                "factId": "tuesday-tradability",
                "kind": "TRADABILITY",
                "tradeDate": str(morning.date()),
                "expectedRevision": 0,
                "evidence": "Synthetic verified current-day tradability and liquidity fixture.",
                "officialEvidence": official_proof(chain),
            },
        )
    recover_and_cycle(case, morning)
    action = case.latest.snapshot["risk_action"]
    assert action["status"] == "RISK_EXIT" and action["tactical_qty"] == 100
    with chain.client:
        chain.post(
            "simulated-trades",
            {
                "planVersionId": case.latest.snapshot["plan_version_id"],
                "causeId": action["cause_id"],
                "expectedCauseRevision": action["cause_revision"],
                "expectedInventoryRevision": case.latest.snapshot["inventory"]["revision"],
                "quantity": 100,
            },
        )
    cycle(case, morning + timedelta(seconds=1))
    fulfilled = branch(read(case), "ordinary-risk")
    assert fulfilled.facts.risk.obligation.status == "FULFILLED"
    assert fulfilled.facts.risk.maintenance.state == "UNKNOWN"  # Reused prior-day daily basis.
    assert case.latest.snapshot["daily_evidence"]["adjustment_as_of"] != str(morning.date())
    prepare = case.pipeline.daily_evaluations._prepare

    async def full_daily_inputs(plan, evaluated_at, official_trade_date, minutes):
        # Ask the real composed adapter for its existing full-admission path.
        # The real SDK, collector, commit owner and proof factory remain intact.
        target = official_trade_date or date.fromisoformat(
            case.latest.snapshot["official_trade_date"]
        )
        return await prepare(plan, evaluated_at, target, minutes)

    monkeypatch.setattr(case.pipeline.daily_evaluations, "_prepare", full_daily_inputs)
    # A metadata-only source refresh may remain the native duplicate identity.
    # Register an actual independent control input so the next owned cycle
    # really commits the newly admitted series instead of recycling old bytes.
    chain.now = case.pipeline._clock.now()
    with chain.client:
        chain.post(
            "plan-facts",
            {
                "planVersionId": case.latest.snapshot["plan_version_id"],
                "contentHash": case.latest.snapshot["content_hash"],
                "factId": "current-full-admission-witness",
                "kind": "TRADABILITY",
                "tradeDate": str(morning.date()),
                "expectedRevision": 0,
                "evidence": "Synthetic verified current-day tradability and liquidity fixture.",
                "officialEvidence": official_proof(chain),
            },
        )
    cycle(case, morning + timedelta(seconds=2))
    fulfilled = branch(read(case), "ordinary-risk")
    assert case.latest.snapshot["daily_evidence"]["adjustment_as_of"] == str(morning.date())
    assert fulfilled.facts.risk.current is None and fulfilled.facts.risk.maintenance.state == "PASS"
    old_origin = fulfilled.facts.risk.origin.evaluation_id
    recover_and_cycle(case, tuesday)
    actual = branch(read(case), "ordinary-risk")
    assert actual.facts.risk.obligation.status == "PENDING"
    assert (
        actual.facts.risk.obligation.fulfilled_at is not None
    )  # Actual retained historical field.
    assert actual.facts.risk.current is not None
    assert actual.facts.risk.origin.evaluation_id != old_origin
    assert actual.state == "UNKNOWN"  # No future owned event today after close; no skip exemption.


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "severe": "true"}], indirect=True)
def test_risk_get_has_no_writes_acquisition_evaluation_or_history_scans(
    risk_read_case, monkeypatch
):
    from sqlalchemy import event

    from trade_plan_monitor.runtime import daily_service, status_authority
    from trade_plan_monitor.state.daily_repository import DailyRepository
    from trade_plan_monitor.state.source_action_reads import ActionOwnerReader

    case = risk_read_case
    statements, identities = [], []
    original = ActionOwnerReader.daily

    def point(reader, identity):
        identities.append(identity)
        return original(reader, identity)

    def forbidden(*_args, **_kwargs):
        pytest.fail("risk GET attempted a write, acquisition, evaluation or historical list")

    def capture(_connection, _cursor, sql, _parameters, _context, _many):
        statements.append(sql)

    monkeypatch.setattr(ActionOwnerReader, "daily", point)
    monkeypatch.setattr(DailyRepository, "list", forbidden)
    monkeypatch.setattr(status_authority, "_condition_state", forbidden)
    monkeypatch.setattr(daily_service, "evaluate_unified_condition", forbidden)
    monkeypatch.setattr(daily_service, "advance_daily_risks", forbidden)
    monkeypatch.setattr(case.pipeline, "run_deadline", forbidden)
    monkeypatch.setattr(case.sdk, "daily", forbidden)
    monkeypatch.setattr(case.sdk, "adj_factor", forbidden)
    event.listen(case.engine, "before_cursor_execute", capture)
    try:
        result = read(case)
    finally:
        event.remove(case.engine, "before_cursor_execute", capture)
    assert branch(result, "severe-risk").facts.risk.origin is not None
    assert len(identities) < 40
    assert not any(
        sql.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP"}
        for sql in statements
    )


@pytest.mark.parametrize("risk_case", [{"early_activation": True}], indirect=True)
def test_expired_owner_cannot_keep_a_current_risk_or_maintenance_claim(risk_read_case):
    case = risk_read_case
    assert branch(read(case), "ordinary-risk").facts.risk.current is not None
    case.pipeline._clock.current += timedelta(seconds=91)
    after = branch(read(case), "ordinary-risk")
    assert after.facts.risk.current is None
    assert after.facts.risk.maintenance.state == "UNKNOWN"
    assert after.state == "UNKNOWN"


@pytest.mark.parametrize("risk_case", [{"early_activation": True, "severe": "true"}], indirect=True)
def test_complete_risk_view_still_uses_the_original_utf8_response_bound(
    risk_read_case, monkeypatch
):
    from trade_plan_monitor.web import plan_readiness_service as projection
    from trade_plan_monitor.web.errors import ApiError, ApiErrorCode

    case = risk_read_case
    assert projection.MAX_READINESS_BYTES == 1024 * 1024
    complete = read(case)
    assert len(complete.axes) == 6
    assert len(complete.rules) == len(case.plan.ordinary_rules) + len(case.plan.alert_rules) + len(
        case.plan.risk_branches
    )
    size = len(complete.model_dump_json(by_alias=True).encode("utf-8"))
    monkeypatch.setattr(projection, "MAX_READINESS_BYTES", size - 1)
    with pytest.raises(ApiError) as error:
        read(case)
    assert error.value.code == ApiErrorCode.SERVICE_UNAVAILABLE


@pytest.mark.parametrize(
    "risk_case",
    [{"early_activation": True, "minute_neighbors": True, "severe": "true"}],
    indirect=True,
)
def test_missing_minute_prefix_keeps_the_risk_unverified_without_a_current_owned_proof(
    risk_read_case,
):
    case = risk_read_case
    case.source.official_closes[MONDAY_CLOSE.date()] = "35.00"
    cycle(case, MONDAY_CLOSE)
    assert "CURRENT_DAY_MINUTE_PREFIX_MISSING" in case.latest.snapshot["data_blockers"]
    assert case.owner().plans[0].completion is None
    actual = branch(read(case), "severe-risk")
    assert actual.state == "UNKNOWN" and actual.facts.root_outcome is None
    assert actual.facts.risk.current is None and actual.facts.risk.maintenance.state == "UNKNOWN"
