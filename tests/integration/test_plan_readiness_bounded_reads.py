"""The new readiness poll must not invoke either whole-history state fence."""

from datetime import timedelta

import pytest
from sqlalchemy import event
from tests.integration.test_native_fact_reads import facts as facts
from tests.integration.test_native_fact_reads import state as state
from tests.integration.test_plan_readiness_execution_reads import execution_case as execution_case
from tests.integration.test_plan_readiness_fact_current import (
    assess,
    owner_rule,
    reevaluate,
    register_fact,
)
from tests.integration.test_plan_readiness_fact_current import (
    fact_case as fact_case,
)
from tests.integration.test_plan_readiness_fact_current import (
    fact_configuration as fact_configuration,
)

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.runtime import status_authority
from trade_plan_monitor.state.daily_accounting import DailyAccounting
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.daily_state_models import ReviewedFactObservation
from trade_plan_monitor.state.native_fact_reads import read_native_trade_date_fact_candidates


def test_new_poll_uses_neither_whole_state_nor_all_fact_history(execution_case, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("new readiness must use bounded actual input owners")

    original = DailyRepository.list

    def listed(repository, **kwargs):
        if kwargs["kind"] == "FACT":
            forbidden()
        return original(repository, **kwargs)

    monkeypatch.setattr(status_authority, "_condition_state", forbidden)
    monkeypatch.setattr(DailyAccounting, "evaluation_current", forbidden)
    monkeypatch.setattr(DailyRepository, "list", listed)
    assert owner_rule(assess(execution_case), "sell-100").state == "CONDITION_FALSE"


def test_complete_observation_union_uses_a_prefix_existence_probe(facts):
    facts.add("unobserved")
    observation = ReviewedFactObservation(bar_end=facts.now.replace(minute=0), source_hash="a" * 64)
    facts.add("other-observation", reviewed_fact_observation=observation.model_dump(mode="json"))
    assert tuple(row["id"] for row in facts.read()) == ("unobserved",)
    captured = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if "INDEXED BY ix_daily_fact_trade_date_lookup" in statement:
            captured.append((statement, parameters))

    event.listen(facts.engine, "before_cursor_execute", capture)
    try:
        with facts.work() as work:
            assert (
                read_native_trade_date_fact_candidates(
                    work,
                    target=facts.target,
                    trade_date=facts.day,
                    now=facts.now,
                    require_complete_observation_union=True,
                )
                is None
            )
    finally:
        event.remove(facts.engine, "before_cursor_execute", capture)
    probes = [(sql, values) for sql, values in captured if ")>''" in sql]
    assert probes
    with facts.engine.connect() as connection:
        for sql, values in probes:
            details = " ".join(
                row[3] for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, values)
            )
            assert "SEARCH daily_plan_record USING INDEX ix_daily_fact_trade_date_lookup" in details
            assert "SCAN" not in details and "TEMP B-TREE" not in details


def test_new_fact_and_control_queries_search_indexes_and_do_no_writes(fact_case, monkeypatch):
    case = fact_case
    register_fact(case)
    reevaluate(case)
    captured, writes = [], []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if "INDEXED BY ix_daily_fact_trade_date_lookup" in statement:
            captured.append((statement, parameters))
        if statement.lstrip().split()[0].upper() in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "DROP",
        }:
            writes.append(statement)

    def forbidden(*_args, **_kwargs):
        pytest.fail("readiness attempted evaluation, sizing, acquisition or a historical FACT list")

    original = DailyRepository.list
    monkeypatch.setattr(
        DailyRepository,
        "list",
        lambda owner, **kwargs: (
            forbidden() if kwargs["kind"] == "FACT" else original(owner, **kwargs)
        ),
    )
    monkeypatch.setattr(DailyAccounting, "evaluation_current", forbidden)
    monkeypatch.setattr(status_authority, "_condition_state", forbidden)
    monkeypatch.setattr(
        "trade_plan_monitor.decision.unified_conditions.evaluate_unified_condition", forbidden
    )
    monkeypatch.setattr("trade_plan_monitor.runtime.daily_service.confirm_signal", forbidden)
    monkeypatch.setattr(case.pipeline, "run_deadline", forbidden)
    event.listen(case.engine, "before_cursor_execute", capture)
    try:
        assert (
            owner_rule(assess(case), case.plan.ordinary_rules[0].rule_id).facts.execution.eligible
            is True
        )
    finally:
        event.remove(case.engine, "before_cursor_execute", capture)
    assert captured and not writes
    with case.engine.connect() as connection:
        for sql, values in captured:
            details = " ".join(
                row[3] for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + sql, values)
            )
            assert "SEARCH daily_plan_record USING INDEX ix_daily_fact_trade_date_lookup" in details
            assert "SCAN daily_plan_record" not in details and "TEMP B-TREE" not in details


def test_unrelated_fact_history_does_not_add_readiness_history_traversal(fact_case):
    from trade_plan_monitor.web.plan_readiness_service import _load

    case = fact_case
    receipt = register_fact(case)
    reevaluate(case)
    owner, now = case.owner(), case.pipeline._clock.now()
    with case.work() as work:
        original = work.daily.get(receipt["id"])["payload"]
    history = {**original, "trade_date": str(case.now.date() - timedelta(days=1))}
    history.pop("reviewed_fact_observation")

    def insert(identities):
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
                        payload_json=canonical(history),
                        created_at=now.isoformat(),
                        updated_at=now.isoformat(),
                    )
                    for identity in identities
                ],
            )

    def measured():
        with case.sessions() as session:
            raw = session.connection().connection.driver_connection
            steps = []
            raw.set_progress_handler(lambda: steps.append(1) or 0, 1)
            try:
                value = _load(session, owner, case.result.snapshot["plan_version_id"], now)
            finally:
                raw.set_progress_handler(None, 0)
        return value.fact_current, value.quote_controls_current, len(steps)

    insert(["history-initial"])
    measured()
    before = measured()
    insert([f"unrelated-history-{index}" for index in range(3000)])
    after = measured()
    assert before[:2] == after[:2]
    assert after[2] <= before[2] + 100  # B-tree depth may change; no row-count traversal.


@pytest.mark.parametrize("wrong", [False, True])
def test_missing_or_changed_index_cannot_certify_fact_truth_or_execution(fact_case, wrong):
    case = fact_case
    register_fact(case)
    reevaluate(case)
    with case.engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX ix_daily_fact_trade_date_lookup")
        if wrong:
            connection.exec_driver_sql(
                "CREATE INDEX ix_daily_fact_trade_date_lookup ON daily_plan_record (symbol)"
            )
    result = owner_rule(assess(case), case.plan.ordinary_rules[0].rule_id)
    assert result.facts.root_outcome is None and result.facts.execution.eligible is None
    with case.engine.connect() as connection:
        sql = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name='ix_daily_fact_trade_date_lookup'"
        ).scalar()
        assert sql is None if not wrong else sql.endswith("(symbol)")


@pytest.mark.parametrize("limit", ["rows", "bytes"])
def test_control_union_budgets_never_truncate_into_a_positive_witness(execution_case, limit):
    case = execution_case
    with case.work() as work:
        payload = next(
            row["payload"]
            for row in work.daily.list(symbol=case.plan.symbol, kind="FACT")
            if row["payload"]["kind"] == "TRADABILITY"
        )
    if limit == "bytes":
        payload["evidence"] = "Synthetic official tradability review " + "x" * 1900
    count = 512 if limit == "rows" else 400
    with case.engine.begin() as connection:
        connection.execute(
            DailyRecord.__table__.insert(),
            [
                dict(
                    id=f"control-tie-{index}",
                    kind="FACT",
                    symbol=case.plan.symbol,
                    lineage=case.plan.plan_id,
                    revision=1,
                    payload_json=canonical(payload),
                    created_at=case.now.isoformat(),
                    updated_at=case.now.isoformat(),
                )
                for index in range(count)
            ],
        )
    rule = owner_rule(assess(case), case.plan.ordinary_rules[0].rule_id)
    assert rule.facts.execution.eligible is None
    assert owner_rule(assess(case), "sell-100").state == "CONDITION_FALSE"
