"""Latest native TRADE_DATE candidates retain raw evaluator order and complete ties."""

import importlib
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, update
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_source_coverage_authority import _command
from tests.integration.test_source_coverage_authority_save import _NOW
from tests.integration.test_source_coverage_authority_save import state as state
from tests.unit.test_unified_plan_domain import unified_payload

from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.reviewed_fact_targets import list_reviewed_fact_targets
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_review_store import confirm_daily_review, save_daily_draft
from trade_plan_monitor.state.daily_state_models import DailyFactState, ReviewedFactObservation
from trade_plan_monitor.state.native_fact_reads import read_native_trade_date_fact_candidates
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

NOW = _NOW + timedelta(minutes=10)
AVAILABLE = _NOW.replace(minute=5).isoformat()


@pytest.fixture
def facts(state, request):
    variant = getattr(request, "param", "default")
    raw = unified_payload()
    severe = raw["risk_branches"][1]
    if variant == "signal":
        severe["condition"]["conditions"][0]["validity_scope"] = "SIGNAL"
    elif variant == "ambiguous":
        raw["alert_rules"] = [
            {
                "kind": "RISK_ALERT",
                "rule_id": "same-fact-alert",
                "condition": deepcopy(severe["condition"]["conditions"][0]),
                "confirmation": {"kind": "OFFICIAL_DAILY_CLOSE"},
            }
        ]
    elif variant == "minute":
        raw["ordinary_rules"][0].update(
            condition=deepcopy(severe["condition"]["conditions"][0]),
            confirmation={"kind": "COMPLETED_BAR_CLOSE", "timeframe_minutes": 5},
            execution_window="CURRENT_SESSION",
        )
    draft = UnifiedPlanDraft.from_executable(UnifiedTradePlan.model_validate(raw))
    source, mapping = source_mapping(draft)
    with state.work() as work:
        identity = save_daily_draft(
            work, draft, mapping=mapping, source_text=source, clock=lambda: _NOW
        )
        confirm_daily_review(work, _command(work, identity), clock=lambda: _NOW)
        details = work.plans.get_version_details(identity)
        work.commit()
    plan = load_plan_json(details.payload_json)
    targets = list_reviewed_fact_targets(
        plan, plan_version_id=identity, content_hash=details.content_hash
    )
    owner = "ORDINARY_RULE" if variant == "minute" else "RISK_BRANCH"
    target = next(
        value
        for value in targets
        if value.owner_kind == owner
        and (owner != "RISK_BRANCH" or value.condition_path.endswith("[0]"))
    )
    case = SimpleNamespace(
        engine=state.engine,
        sessions=state.sessions,
        plan=plan,
        target=target,
        targets=targets,
        version=identity,
        day=NOW.date(),
        now=NOW,
    )
    case.work = lambda: SqlAlchemyUnitOfWork(state.sessions, clock=lambda: case.now)

    def payload(*, available=AVAILABLE, verified=None, satisfied=True, targeted=True, **changes):
        value = dict(
            plan_version_id=identity,
            content_hash=details.content_hash,
            kind="SEVERE_STRUCTURE",
            trade_date=str(case.day),
            signal_id=None,
            evidence="Synthetic complete technical failure independently verified",
            verified=True,
            satisfied=satisfied,
            available_at=available,
            verified_at=available if verified is None else verified,
            official_evidence=None,
        )
        if targeted:
            value["reviewed_fact_target"] = target.model_dump(mode="json")
        value.update(changes)
        return value

    def add(identity, **values):
        value = payload(**values)
        with case.work() as work:
            work.daily.save(
                identity,
                kind="FACT",
                symbol=plan.symbol,
                lineage=plan.plan_id,
                payload=value,
                expected_revision=0,
            )
            work.commit()
        return value

    def read(*, observation=None, work=None, target=None):
        arguments = dict(
            target=target or case.target, trade_date=case.day, now=case.now, observation=observation
        )
        if work is not None:
            return read_native_trade_date_fact_candidates(work, **arguments)
        with case.work() as transaction:
            return read_native_trade_date_fact_candidates(transaction, **arguments)

    case.payload, case.add, case.read = payload, add, read
    return case


def raw_fact(case, identity, payload):
    with case.engine.begin() as connection:
        connection.execute(
            DailyRecord.__table__.insert().values(
                id=identity,
                kind="FACT",
                symbol=case.plan.symbol,
                lineage=case.plan.plan_id,
                revision=1,
                payload_json=canonical(payload),
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            )
        )


def ids(rows):
    return None if rows is None else tuple(row["id"] for row in rows)


def test_native_fact_candidate_reader_has_a_dedicated_entrypoint():
    module = importlib.import_module("trade_plan_monitor.state.native_fact_reads")
    assert callable(module.read_native_trade_date_fact_candidates)


def test_known_empty_is_distinct_from_unknown_and_reads_real_native_rows(facts):
    assert facts.read() == ()
    facts.add("actual-fact")
    assert ids(facts.read()) == ("actual-fact",)


@pytest.mark.parametrize(
    "older,newer",
    [
        ("2026-10-27T10:05:00.000001+08:00", "2026-10-27T10:05:00.000002+08:00"),
        ("2026-10-27T10:05:00+08:00", "2026-10-27T10:05:00.000+08:00"),
        ("2026-10-27T10:05:00.000+08:00", "2026-10-27T10:05:00.000000+08:00"),
        ("2026-10-27T10:05:00.1+08:00", "2026-10-27T10:05:00.100000+08:00"),
    ],
)
def test_microseconds_and_mixed_precision_keep_original_raw_latest_semantics(facts, older, newer):
    before = facts.add("older", available=older, satisfied=True)
    after = facts.add("newer", available=newer, satisfied=False)
    rows = facts.read()
    assert ids(rows) == ("newer",)
    condition = facts.plan.risk_branches[1].condition.conditions[0]
    expected = evaluate_unified_condition(
        condition,
        None,
        facts=[dict(before, id="older"), dict(after, id="newer")],
        target=facts.now,
        _fact_owner=(facts.plan, facts.version, facts.target.owner_kind, facts.target.owner_id),
        _condition_path=facts.target.condition_path,
    )
    actual = evaluate_unified_condition(
        condition,
        None,
        facts=[dict(row["payload"], id=row["id"]) for row in rows],
        target=facts.now,
        _fact_owner=(facts.plan, facts.version, facts.target.owner_kind, facts.target.owner_id),
        _condition_path=facts.target.condition_path,
    )
    assert actual == expected and actual.outcome == "UNSATISFIED"


def test_targeted_and_unbound_groups_merge_all_opposite_ties_without_satisfied_filter(facts):
    facts.add("targeted-positive", satisfied=True)
    facts.add("legacy-negative", satisfied=False, targeted=False)
    facts.add("targeted-second", satisfied=True)
    rows = facts.read()
    assert ids(rows) == ("legacy-negative", "targeted-positive", "targeted-second")
    condition = facts.plan.risk_branches[1].condition.conditions[0]
    result = evaluate_unified_condition(
        condition,
        None,
        facts=[dict(row["payload"], id=row["id"]) for row in rows],
        target=facts.now,
        _fact_owner=(facts.plan, facts.version, facts.target.owner_kind, facts.target.owner_id),
        _condition_path=facts.target.condition_path,
    )
    assert result.outcome == "MISSING_INPUT" and len(result.fact_ids) == 3


@pytest.mark.parametrize(
    "older,newer",
    [
        ("2026-10-27T10:04:59+08:00", "2026-10-27T10:05:00+08:00"),
        ("2026-10-27T10:04:59.000+08:00", "2026-10-27T10:04:59.000000+08:00"),
    ],
)
def test_raw_verified_tuple_breaks_available_ties_and_newer_unbound_wins(facts, older, newer):
    facts.add("older-target", verified=older)
    facts.add("newer-legacy", targeted=False, verified=newer, satisfied=False)
    assert ids(facts.read()) == ("newer-legacy",)


def test_available_cutoff_uses_exact_microseconds(facts):
    facts.now = NOW.replace(minute=5, microsecond=1)
    facts.add("available", available="2026-10-27T10:05:00.000001+08:00")
    # A future candidate is an actual stored row, not yet admitted by this read's cutoff.
    value = facts.payload(available="2026-10-27T10:05:00.000002+08:00")
    raw_fact(facts, "future", value)
    assert ids(facts.read()) == ("available",)


@pytest.mark.parametrize(
    "field,value",
    [
        ("available_at", "2026-10-27T10:04:00.0000001+08:00"),
        ("verified_at", "2026-10-27T10:04:00Z"),
        ("available_at", "2026-02-30T10:04:00+08:00"),
        ("verified_at", "2026-10-27T10:06:00+08:00"),
    ],
)
def test_unsupported_or_inconsistent_time_is_unknown_even_behind_a_newer_good_fact(
    facts, field, value
):
    facts.add("good-newer")
    broken = facts.payload(available="2026-10-27T10:04:00+08:00")
    broken[field] = value
    raw_fact(facts, "unsupported-older", broken)
    assert facts.read() is None


@pytest.mark.parametrize("mutation", ["missing-index", "wrong-index", "invalid-latest"])
def test_missing_or_changed_index_and_invalid_latest_never_fall_back(facts, mutation):
    facts.add("old-good", available="2026-10-27T10:04:00+08:00")
    if mutation == "invalid-latest":
        value = facts.payload()
        value["satisfied"] = "not-a-boolean"
        raw_fact(facts, "invalid-latest", value)
    else:
        with facts.engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX ix_daily_fact_trade_date_lookup")
            if mutation == "wrong-index":
                connection.exec_driver_sql(
                    "CREATE INDEX ix_daily_fact_trade_date_lookup ON daily_plan_record (symbol)"
                )
    assert facts.read() is None


@pytest.mark.parametrize("facts", ["ambiguous"], indirect=True)
def test_legacy_ambiguity_cannot_donate_a_same_kind_fact_to_an_exact_target(facts):
    facts.add("exact")
    facts.add("ambiguous-legacy", targeted=False, available="2026-10-27T10:06:00+08:00")
    assert ids(facts.read()) == ("exact",)


@pytest.mark.parametrize("facts", ["signal"], indirect=True)
def test_signal_leaf_has_no_trade_date_seek(facts):
    assert facts.read() is None


def test_other_owner_content_kind_date_and_target_groups_do_not_contribute(facts):
    facts.add("exact")
    other = facts.payload(available="2026-10-27T10:06:00+08:00")
    other["plan_version_id"] = "00000000-0000-0000-0000-000000000999"
    other["reviewed_fact_target"]["plan_version_id"] = other["plan_version_id"]
    raw_fact(facts, "other-version", other)
    other = facts.payload(available="2026-10-27T10:06:00+08:00")
    other["content_hash"] = "f" * 64
    other["reviewed_fact_target"]["content_hash"] = other["content_hash"]
    raw_fact(facts, "other-content", other)
    other = facts.payload(available="2026-10-27T10:06:00+08:00")
    other["reviewed_fact_target"]["target_hash"] = "e" * 64
    raw_fact(facts, "other-target", other)
    facts.add("other-kind", kind="SEVERE_DETERIORATION", targeted=False)
    facts.add("other-date", trade_date=str(facts.day - timedelta(days=1)))
    assert ids(facts.read()) == ("exact",)


@pytest.mark.parametrize("facts", ["minute"], indirect=True)
def test_exact_observation_candidates_are_scoped_without_claiming_minute_truth(facts):
    observation = ReviewedFactObservation(bar_end=NOW.replace(minute=5), source_hash="a" * 64)
    facts.add("observed", reviewed_fact_observation=observation.model_dump(mode="json"))
    assert facts.read() is None
    assert ids(facts.read(observation=observation)) == ("observed",)
    wrong = observation.model_copy(update={"source_hash": "b" * 64})
    assert facts.read(observation=wrong) == ()  # Only the explicitly requested group is empty.


def test_exact_queries_use_native_index_without_temp_sorting(facts):
    facts.add("indexed")
    captured = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if "INDEXED BY ix_daily_fact_trade_date_lookup" in statement:
            captured.append((statement, parameters))

    event.listen(facts.engine, "before_cursor_execute", capture)
    try:
        assert ids(facts.read()) == ("indexed",)
    finally:
        event.remove(facts.engine, "before_cursor_execute", capture)
    assert captured
    with facts.engine.connect() as connection:
        for statement, parameters in captured:
            details = " ".join(
                row[3]
                for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters)
            )
            assert "SEARCH daily_plan_record USING INDEX ix_daily_fact_trade_date_lookup" in details
            assert "TEMP B-TREE" not in details and "SCAN daily_plan_record" not in details


def insert_many(case, payload, identities):
    DailyFactState.model_validate_json(canonical(payload))
    with case.engine.begin() as connection:
        connection.execute(
            DailyRecord.__table__.insert(),
            [
                dict(
                    id=identity,
                    kind="FACT",
                    symbol=case.plan.symbol,
                    lineage=case.plan.plan_id,
                    revision=1,
                    payload_json=canonical(payload),
                    created_at=NOW.isoformat(),
                    updated_at=NOW.isoformat(),
                )
                for identity in identities
            ],
        )


def test_unrelated_history_does_not_increase_sqlite_evaluation_traversal(facts):
    facts.add("exact")
    history = facts.payload(trade_date=str(facts.day - timedelta(days=1)))
    insert_many(facts, history, ("history-initial",))
    assert ids(facts.read()) == ("exact",)  # Warm the same native queries before both measurements.

    def measured():
        with facts.work() as work:
            raw = work.daily.session.connection().connection.driver_connection
            steps = []
            raw.set_progress_handler(lambda: steps.append(1) or 0, 1)
            try:
                result = facts.read(work=work)
            finally:
                raw.set_progress_handler(None, 0)
        return ids(result), len(steps)

    before, steps = measured()
    insert_many(facts, history, (f"history-{index}" for index in range(3000)))
    after, expanded_steps = measured()
    assert before == after == ("exact",)
    assert expanded_steps == steps


def test_complete_ties_obey_existing_row_budget_without_silent_truncation(facts):
    value = facts.payload()
    insert_many(facts, value, (f"tie-{index:04d}" for index in range(512)))
    assert len(facts.read()) == 512
    insert_many(facts, value, ("tie-over-budget",))
    assert facts.read() is None


def test_complete_ties_obey_existing_byte_budget(facts):
    value = facts.payload(evidence="Synthetic technical evidence " + "x" * 1950)
    insert_many(facts, value, (f"large-{index:04d}" for index in range(400)))
    assert facts.read() is None


def test_read_is_zero_write_and_keeps_pending_edits(facts):
    facts.add("exact")
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    with facts.work() as work:
        session = work.daily.session
        held = session.get(DailyRecord, "exact")
        held.revision += 1
        dirty = set(session.dirty)

        def forbidden(*_args):
            raise AssertionError("candidate lookup must never autoflush")

        event.listen(session, "before_flush", forbidden)
        event.listen(facts.engine, "before_cursor_execute", capture)
        try:
            assert facts.read(work=work) is None
            assert set(session.dirty) == dirty and held.revision == 2
        finally:
            event.remove(session, "before_flush", forbidden)
            event.remove(facts.engine, "before_cursor_execute", capture)
    assert not any(
        sql.lstrip().startswith(("insert", "update", "delete", "create", "alter"))
        for sql in statements
    )


@pytest.mark.parametrize("shape", ["malformed-json", "explicit-null-target", "bad-observation"])
def test_old_unknown_shapes_are_not_silently_omitted(facts, shape):
    facts.add("good")
    value = facts.payload(available="2026-10-27T10:04:00+08:00")
    if shape == "explicit-null-target":
        value["reviewed_fact_target"] = None
    elif shape == "bad-observation":
        value["reviewed_fact_observation"] = {"bar_end": AVAILABLE, "source_hash": "invalid"}
    raw_fact(facts, "unknown-old", value)
    if shape == "malformed-json":
        with facts.engine.begin() as connection:
            connection.execute(
                update(DailyRecord)
                .where(DailyRecord.id == "unknown-old")
                .values(payload_json="{unsupported legacy JSON")
            )
    assert facts.read() is None
