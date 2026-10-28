"""Current action source authority uses real review rows and the actual SQL cutover."""

import importlib
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import event, insert, inspect, update
from tests.integration.test_live_monitor_projection_migration import _upgrade
from tests.integration.test_market_linkage_review import source_mapping
from tests.integration.test_source_coverage_authority import _command
from tests.integration.test_source_coverage_authority_save import _NOW
from tests.integration.test_source_coverage_authority_save import state as state
from tests.unit.test_source_action_authority import _severe_evidence
from tests.unit.test_source_coverage_baseline import _append_as_context
from tests.unit.test_source_risk_controls import _parent

from trade_plan_monitor.ai.daily_review import build_daily_review
from trade_plan_monitor.decision.daily_risk import _condition_evidence_ids, risk_execution
from trade_plan_monitor.decision.unified_conditions import evaluate_unified_condition
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_validation import daily_draft_json, daily_draft_sha256
from trade_plan_monitor.domain.plan_validation import PlanValidationResult
from trade_plan_monitor.domain.risk_scope import risk_identity
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_review_store import confirm_daily_review, save_daily_draft
from trade_plan_monitor.state.daily_state_models import DailyFactState, DailyRiskState
from trade_plan_monitor.state.database import create_session_factory, create_sqlite_engine
from trade_plan_monitor.state.models import (
    ActivePlan,
    PlanActivationState,
    PlanReviewProvenance,
    PlanSource,
    PlanVersion,
    PlanVersionReview,
)
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
from trade_plan_monitor.state.source_coverage_models import COVERAGE_TRIGGER_SQL, CoverageCutoverRow
from trade_plan_monitor.state.source_coverage_store import SourceCoverageStore
from trade_plan_monitor.state.source_coverage_values import CoverageCutover
from trade_plan_monitor.state.unit_of_work import SqlAlchemyUnitOfWork

_VERSION, _SOURCE, _REVIEW = (str(UUID(int=n)) for n in (801, 802, 803))
_CONFIRMED = _NOW + timedelta(minutes=1)
_ACTIVATED = _NOW + timedelta(minutes=2)


def _draft(*, buy_only_failure=False, expired=False, severe_any=False, parallel_risks=False):
    base, _ = _parent()
    draft = base.draft
    raw = draft.model_dump(mode="json")
    if buy_only_failure:
        raw["ordinary_rules"][0]["condition"] = dict(type="DAILY_PRICE_COMPARE", field="close",
            offset=0, comparator="GT", reference=dict(mode="DYNAMIC", indicator="MA20",
                formula_version="daily-ta-v2", parameters={"period": 21}, offset=0))
    if expired:
        raw["activation"] = dict(mode="DATE_RANGE", start_date="2026-10-20",
                                   end_date="2026-10-26")
    if severe_any:
        raw["risk_branches"][1]["condition"]["type"] = "ANY"
    if parallel_risks:
        first = raw["risk_branches"][0] | dict(rule_id="plan-first", target_tactical_qty=100,
            holding_scope=dict(mode="BEFORE_TRADE_DATE", trade_date="2026-10-26"))
        second = first | dict(rule_id="plan-second",
            holding_scope=dict(mode="FROM_TRADE_DATE", trade_date="2026-10-20"))
        raw["risk_branches"] = [first, second]
    draft = type(draft).model_validate(raw)
    assert draft.to_executable() is not None
    return draft


def _risk_payload(draft, index=0):
    branch = draft.risk_branches[index]
    identity = daily_hash("daily-risk-obligation-v1", dict(symbol=draft.symbol,
                                                           kind=risk_identity(branch)))
    payload = dict(kind=branch.kind, priority=branch.priority, involves_core=branch.involves_core,
        target_core_qty=branch.target_core_qty, target_tactical_qty=branch.target_tactical_qty,
        scope_evidence=branch.scope_evidence, status="CONFIRMED", evidence_ids=[],
        earliest_execution_date="2026-10-27", confirmed_trade_date="2026-10-26",
        breach_trade_date="2026-10-23", second_close_date="2026-10-26", blockers=[],
        risk_id=identity)
    if branch.kind == "ORDINARY_TECHNICAL":
        payload.update(risk_line_fen=draft.levels.risk_line_fen,
            risk_comparison=draft.levels.risk_comparison,
            suspension_confirmation_policy=branch.suspension_confirmation_policy)
    else:
        payload["technical_evidence"] = [_severe_evidence(branch)]
        payload["evidence_ids"] = [identity
            for child in payload["technical_evidence"][0]["children"]
            for identity in child["fact_ids"]]
    for name in ("rule_id", "holding_scope"):
        value = getattr(branch, name, None)
        if value is not None:
            payload[name] = value.model_dump(mode="json") if name == "holding_scope" else value
    return identity, payload


def _daily(identity, kind, draft, payload):
    return dict(id=identity, kind=kind, symbol=draft.symbol, lineage=draft.symbol, revision=1,
        payload_json=canonical(payload), created_at=_NOW.isoformat(), updated_at=_NOW.isoformat())


def _signal(draft, version_id, review_id, *, side="SELL", identity="ordinary-cause"):
    return dict(signal_id=identity, rule_id=draft.ordinary_rules[0].rule_id, side=side,
        bucket="TACTICAL", lineage=draft.symbol, state="CONFIRMED", planned_qty=100,
        simulated_qty=0, confirmed_trade_date="2026-10-26", execution_date=None,
        evidence_fingerprint="0" * 64, evidence=[], plan_version_id=version_id,
        review_id=review_id, basis_id="source-action-test", executable_qty=0, blockers=[])


def _historical_fact_owner(connection, draft):
    older = draft.model_copy(update={"plan_id": "historical-risk-fact-owner"})
    source, mapping = source_mapping(older)
    review = build_daily_review(older, mapping, source)
    assert not review.issues
    identity, source_id, review_id = (str(UUID(int=n)) for n in (901, 902, 903))
    connection.execute(insert(PlanSource), dict(id=source_id, source_text=source,
        source_hash=review.source_hash, created_at=(_NOW - timedelta(days=2)).isoformat()))
    connection.execute(insert(PlanVersion), dict(id=identity, plan_id=older.plan_id,
        version=older.version, symbol=older.symbol, plan_hash=daily_draft_sha256(older),
        status="SUPERSEDED", payload_json=daily_draft_json(older), source_id=source_id,
        revision=2, created_at=(_NOW - timedelta(days=2)).isoformat()))
    connection.execute(insert(PlanVersionReview), dict(plan_version_id=identity,
                                                     review_issues_json="[]"))
    connection.execute(insert(PlanReviewProvenance), dict(plan_version_id=identity,
        origin="MANUAL", extraction_id=None, source_hash=review.source_hash,
        draft_hash=daily_draft_sha256(older), confirmed_at=(_NOW - timedelta(days=2)).isoformat(),
        content_hash=review.content_hash, review_evidence_hash=review.evidence_hash,
        mapping_json=canonical(mapping.model_dump(mode="json")), required_issues_json="[]",
        resolutions_json="[]", review_id=review_id, review_revision=1))
    old_daily = _daily("review-" + identity, "REVIEW", older, dict(confirmed=True,
        content_hash=review.content_hash, source_hash=review.source_hash,
        evidence_hash=review.evidence_hash, review_id=review_id, review_revision=1,
        plan_version_id=identity))
    old_daily.update(created_at=(_NOW - timedelta(days=2)).isoformat(),
                     updated_at=(_NOW - timedelta(days=2)).isoformat())
    connection.execute(insert(DailyRecord), old_daily)
    return identity, review.content_hash


@pytest.fixture
def legacy(tmp_path):
    engines = []

    def create(*, extra=None, confirmed=True, active=True, upgraded=True,
               buy_only_failure=False, expired=False, extra_members=0,
               clock_at=_NOW + timedelta(minutes=3), historical_fact_owner=False,
               severe_any=False, parallel_risks=False):
        engine = create_sqlite_engine(tmp_path / f"action-cutover-{len(engines)}.sqlite3")
        engines.append(engine)
        _upgrade(engine, "0027_simulation_capital")
        draft = _draft(buy_only_failure=buy_only_failure, expired=expired, severe_any=severe_any,
                       parallel_risks=parallel_risks)
        source, mapping = source_mapping(draft)
        if extra is not None:
            source, mapping = _append_as_context(source, mapping, extra,
                semantic_role="COMMENTARY", misclassification=dict(disposition="CONTEXT",
                    paths=[], reason="Old proposed background treatment"))
        snapshot = build_daily_review(draft, mapping, source)
        assert not snapshot.issues
        cause_id, risk = _risk_payload(draft)
        review = dict(confirmed=confirmed, content_hash=snapshot.content_hash,
            source_hash=snapshot.source_hash, evidence_hash=snapshot.evidence_hash,
            plan_version_id=_VERSION, review_id=_REVIEW if confirmed else None,
            review_revision=int(confirmed))
        with engine.begin() as connection:
            fact_owner = (_historical_fact_owner(connection, draft) if historical_fact_owner
                          else (_VERSION, snapshot.content_hash))
            connection.execute(insert(PlanSource), dict(id=_SOURCE, source_text=source,
                source_hash=snapshot.source_hash, created_at=_NOW.isoformat()))
            connection.execute(insert(PlanVersion), dict(id=_VERSION, plan_id=draft.plan_id,
                version=draft.version, symbol=draft.symbol, plan_hash=daily_draft_sha256(draft),
                status="ACTIVE" if active else "DRAFT", payload_json=daily_draft_json(draft),
                source_id=_SOURCE, revision=int(active), created_at=_NOW.isoformat()))
            connection.execute(insert(PlanVersionReview), dict(plan_version_id=_VERSION,
                                                               review_issues_json="[]"))
            connection.execute(insert(PlanReviewProvenance), dict(plan_version_id=_VERSION,
                origin="MANUAL", extraction_id=None, source_hash=snapshot.source_hash,
                draft_hash=daily_draft_sha256(draft),
                confirmed_at=_CONFIRMED.isoformat() if confirmed else None,
                content_hash=snapshot.content_hash,
                review_evidence_hash=snapshot.evidence_hash,
                mapping_json=canonical(mapping.model_dump(mode="json")), required_issues_json="[]",
                resolutions_json="[]", review_id=_REVIEW if confirmed else None,
                review_revision=int(confirmed)))
            connection.execute(insert(DailyRecord), _daily("review-" + _VERSION, "REVIEW", draft,
                                                           review))
            connection.execute(insert(DailyRecord), _daily(cause_id, "RISK", draft, risk))
            if parallel_risks:
                second_id, second = _risk_payload(draft, index=1)
                second_row = _daily(second_id, "RISK", draft, second)
                second_row["created_at"] = (_NOW - timedelta(minutes=1)).isoformat()
                connection.execute(insert(DailyRecord), second_row)
            if active:
                connection.execute(insert(ActivePlan), dict(symbol=draft.symbol,
                    plan_version_id=_VERSION, revision=1, activated_at=_ACTIVATED.isoformat()))
                connection.execute(insert(PlanActivationState), dict(symbol=draft.symbol,
                    plan_version_id=_VERSION, revision=1, changed_at=_ACTIVATED.isoformat()))
            for number in range(extra_members):
                sibling = draft.model_copy(update={"version": number + 2})
                sibling_source, sibling_mapping = source_mapping(sibling)
                sibling_review = build_daily_review(sibling, sibling_mapping, sibling_source)
                source_id = str(UUID(int=1001 + number))
                connection.execute(insert(PlanSource), dict(id=source_id,
                    source_text=sibling_source, source_hash=sibling_review.source_hash,
                    created_at=_NOW.isoformat()))
                connection.execute(insert(PlanVersion), dict(id=str(UUID(int=2001 + number)),
                    plan_id=sibling.plan_id, version=sibling.version, symbol=sibling.symbol,
                    plan_hash=daily_draft_sha256(sibling), status="DRAFT",
                    payload_json=daily_draft_json(sibling), source_id=source_id, revision=0,
                    created_at=_NOW.isoformat()))
        if upgraded:
            _upgrade(engine, "0028_source_coverage")
        sessions = create_session_factory(engine)
        return SimpleNamespace(engine=engine, sessions=sessions, draft=draft, id=_VERSION,
            content_hash=snapshot.content_hash,
            fact_owner_id=fact_owner[0], fact_owner_content_hash=fact_owner[1],
            cause_id=cause_id, risk=risk,
            work=lambda: SqlAlchemyUnitOfWork(sessions, clock=lambda: clock_at))

    try:
        yield create
    finally:
        for engine in engines:
            engine.dispose()


def _resolve(work, version_id, cause_id=None):
    module = importlib.import_module("trade_plan_monitor.state.source_action_authority")
    return module.require_source_action_authority(work, version_id, cause_id=cause_id)


def _rows(engine):
    with engine.connect() as connection:
        names = inspect(connection).get_table_names()
        return {name: connection.exec_driver_sql(f'SELECT * FROM "{name}"').all()
                for name in names if name.startswith(("source_coverage_", "plan_", "active_plan",
                                                       "daily_plan_"))}


def test_real_cutover_records_the_original_confirmed_active_grant_before_helper_is_used(legacy):
    case = legacy()
    with case.work() as work:
        member = SourceCoverageStore(work.daily.session).cutover(case.id)
        assert member is not None
        assert member.legacy_identity["status"] == "ACTIVE"
        assert member.legacy_identity["review_id"] == _REVIEW
        assert member.legacy_identity["active_revision"] == 1
        assert SourceCoverageStore(work.daily.session).latest(case.id) is None


def test_legacy_risk_uses_actual_cutover_identity_without_claiming_current_complete(legacy):
    case = legacy()
    before = _rows(case.engine)
    with case.work() as work:
        basis = _resolve(work, case.id, case.cause_id)
        assert basis.basis == "HISTORICAL_TECHNICAL_RISK"
        assert basis.coverage_evidence_hash is None and basis.cutover_evidence_hash
        assert {row["id"] for row in basis.risk_rows} == {case.cause_id}
        assert not hasattr(basis, "coverage_complete") and not hasattr(basis, "model_dump")
    assert _rows(case.engine) == before


def test_source_proven_buy_only_failure_does_not_veto_the_original_independent_risk(legacy):
    case = legacy(buy_only_failure=True)
    with case.work() as work:
        basis = _resolve(work, case.id, case.cause_id)
        assert basis.basis == "HISTORICAL_TECHNICAL_RISK" and len(basis.risk_rows) == 1


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_ordinary_signals_cannot_borrow_a_real_legacy_risk_grant(legacy, side):
    case = legacy()
    with case.engine.begin() as connection:
        connection.execute(insert(DailyRecord), _daily("risk-looking-signal", "SIGNAL", case.draft,
            _signal(case.draft, case.id, _REVIEW, side=side, identity="risk-looking-signal")))
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                             match="SOURCE_COVERAGE_REQUIRED"):
        _resolve(work, case.id, "risk-looking-signal")


@pytest.mark.parametrize("extra", ["所有风险退出必须先等待蓝灯。",
                                   "Only buy when turnover exceeds 3 percent."])
def test_unknown_scope_cannot_be_assumed_independent_of_the_legacy_risk(legacy, extra):
    case = legacy(extra=extra)
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                             match="SOURCE_COVERAGE_REQUIRED"):
        _resolve(work, case.id, case.cause_id)


@pytest.mark.parametrize("options", [dict(confirmed=False), dict(active=False)])
def test_membership_without_original_review_and_active_grant_is_not_authority(legacy, options):
    case = legacy(**options)
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError):
        _resolve(work, case.id, case.cause_id)


def test_runtime_expiry_of_an_ordinary_activation_window_does_not_erase_latched_risk(legacy):
    case = legacy(expired=True)
    with case.work() as work:
        assert _resolve(work, case.id, case.cause_id).basis == "HISTORICAL_TECHNICAL_RISK"


@pytest.mark.parametrize("clock_at", [_NOW, _CONFIRMED + timedelta(seconds=30)])
def test_future_captured_review_or_activation_is_not_a_historical_action_grant(legacy, clock_at):
    case = legacy(clock_at=clock_at)
    with case.work() as work:
        assert SourceCoverageStore(work.daily.session).cutover(case.id) is not None
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
            _resolve(work, case.id, case.cause_id)


@pytest.mark.parametrize("field,value", [
    ("risk_line_fen", 2599), ("risk_comparison", "LTE"), ("target_tactical_qty", 100),
    ("suspension_confirmation_policy", "RESTART_ADJACENT_PAIR"),
    ("holding_scope", {"mode": "BEFORE_TRADE_DATE", "trade_date": "2026-10-09"}),
])
def test_current_persisted_risk_cannot_replace_the_captured_policy(legacy, field, value):
    case = legacy()
    with case.engine.begin() as connection:
        connection.execute(update(DailyRecord).where(DailyRecord.id == case.cause_id).values(
            payload_json=canonical(case.risk | {field: value})))
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                             match="SOURCE_COVERAGE_REQUIRED"):
        _resolve(work, case.id, case.cause_id)


def test_same_version_reactivation_is_a_different_grant_and_cannot_use_cutover(legacy):
    case = legacy(clock_at=_NOW + timedelta(hours=2))
    with case.engine.begin() as connection:
        connection.execute(update(ActivePlan).values(revision=2,
            activated_at=(_ACTIVATED + timedelta(hours=1)).isoformat()))
        connection.execute(update(PlanActivationState).values(revision=2,
            changed_at=(_ACTIVATED + timedelta(hours=1)).isoformat()))
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                             match="SOURCE_COVERAGE_STALE"):
        _resolve(work, case.id, case.cause_id)


def test_removed_or_unowned_confirmed_sibling_cannot_donate_its_target_to_risk_quantity(legacy):
    case = legacy()
    ghost = deepcopy(case.risk) | dict(rule_id="removed-risk", risk_id="unowned-sibling")
    with case.engine.begin() as connection:
        connection.execute(insert(DailyRecord),
                           _daily("unowned-sibling", "RISK", case.draft, ghost))
    with case.work() as work:
        basis = _resolve(work, case.id, case.cause_id)
        assert {row["id"] for row in basis.risk_rows} == {case.cause_id}
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_REQUIRED"):
            _resolve(work, case.id, "unowned-sibling")


def test_severe_status_without_full_condition_evidence_is_not_a_liquidation_grant(legacy):
    case = legacy()
    severe_id, severe = _risk_payload(case.draft, index=1)
    severe["technical_evidence"] = []
    with case.engine.begin() as connection:
        connection.execute(insert(DailyRecord), _daily(severe_id, "RISK", case.draft, severe))
    with case.work() as work:
        basis = _resolve(work, case.id, case.cause_id)
        assert {row["id"] for row in basis.risk_rows} == {case.cause_id}
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_REQUIRED"):
            _resolve(work, case.id, severe_id)


def test_missing_installation_or_damaged_seal_never_falls_back_to_legacy(legacy):
    old = legacy(upgraded=False)
    with old.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                            match="SOURCE_COVERAGE_UPGRADE_REQUIRED"):
        _resolve(work, old.id, old.cause_id)
    case = legacy()
    with case.engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER pma_seal_source_coverage_cutover_update")
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                             match="SOURCE_COVERAGE_INTEGRITY"):
        _resolve(work, case.id, case.cause_id)


def test_individually_resigned_member_cannot_forge_the_original_active_grant(legacy):
    case = legacy(active=False)
    with case.work() as work:
        member = SourceCoverageStore(work.daily.session).cutover(case.id)
        assert member.legacy_identity["status"] == "DRAFT"
    old = member.legacy_identity | dict(status="ACTIVE", revision=1, active_revision=1,
                                      activated_at=_ACTIVATED.isoformat())
    forged = CoverageCutover.build(**member.model_dump(mode="python",
        exclude={"evidence_hash", "legacy_identity"}), legacy_identity=old)
    with case.engine.begin() as connection:
        connection.execute(update(PlanVersion).values(status="ACTIVE", revision=1))
        connection.execute(insert(ActivePlan), dict(symbol=case.draft.symbol,
            plan_version_id=case.id, revision=1, activated_at=_ACTIVATED.isoformat()))
        connection.execute(insert(PlanActivationState), dict(symbol=case.draft.symbol,
            plan_version_id=case.id, revision=1, changed_at=_ACTIVATED.isoformat()))
        trigger = "pma_seal_source_coverage_cutover_update"
        connection.exec_driver_sql("DROP TRIGGER " + trigger)
        connection.execute(update(CoverageCutoverRow).values(
            payload_json=canonical(forged.model_dump(mode="json")),
            evidence_hash=forged.evidence_hash))
        connection.exec_driver_sql(COVERAGE_TRIGGER_SQL[trigger])
    with case.work() as work:
        # All individual member self-hashes, projections and SQL seals pass.
        assert SourceCoverageStore(work.daily.session).cutover(case.id) == forged
        with pytest.raises(SourceCoverageAuthorityError, match="SOURCE_COVERAGE_INTEGRITY"):
            _resolve(work, case.id, case.cause_id)


def test_installation_membership_is_paged_once_per_call_even_with_multiple_risks(legacy):
    case = legacy(extra_members=100)
    other_id, _ = _install_severe(case)
    statements = []

    def trace(_connection, _cursor, statement, _parameters, _context, _executemany):
        if "source_coverage_cutover.plan_version_id" in statement and "LIMIT" in statement:
            statements.append(statement)

    event.listen(case.engine, "before_cursor_execute", trace)
    try:
        with case.work() as work:
            assert SourceCoverageStore(work.daily.session).installation().member_count == 101
            basis = _resolve(work, case.id, case.cause_id)
            assert basis.basis == "HISTORICAL_TECHNICAL_RISK"
            assert {row["id"] for row in basis.risk_rows} == {case.cause_id, other_id}
    finally:
        event.remove(case.engine, "before_cursor_execute", trace)
    assert len(statements) == 3  # 100 + 1 + empty keyset page, no per-sibling scan.
    assert all("ORDER BY" in statement and "LIMIT" in statement for statement in statements)


def _current_version(state, kind, *, draft=None):
    draft = _draft() if draft is None else draft
    source, mapping = source_mapping(draft)
    with state.work() as work:
        identity = save_daily_draft(work, draft, mapping=mapping, source_text=source,
                                    clock=lambda: _NOW)
        work.commit()
    with SqlAlchemyUnitOfWork(state.sessions, clock=lambda: _ACTIVATED) as work:
        confirm_daily_review(work, _command(work, identity), clock=lambda: _CONFIRMED)
        work.plans.activate(draft.to_executable(), expected_revision=0,
                            validation=PlanValidationResult(issues=()))
        if kind == "RISK":
            cause_id, payload = _risk_payload(draft)
        else:
            cause_id = "ordinary-cause"
            payload = _signal(draft, identity, work.plans.get_version_details(identity).review_id)
        if kind is not None:
            work.daily.save(cause_id, kind=kind, symbol=draft.symbol, lineage=draft.symbol,
                            payload=payload, expected_revision=0)
        work.commit()
    return identity, cause_id if kind is not None else None


@pytest.mark.parametrize("kind", [None, "SIGNAL", "RISK"])
def test_current_complete_review_and_real_active_binding_support_the_current_basis(state, kind):
    identity, cause_id = _current_version(state, kind)
    with SqlAlchemyUnitOfWork(state.sessions, clock=lambda: _NOW + timedelta(minutes=3)) as work:
        basis = _resolve(work, identity, cause_id)
        assert basis.basis == "CURRENT" and basis.coverage_evidence_hash
        assert basis.cutover_evidence_hash is None


def test_future_current_review_is_not_a_current_action_grant(state):
    identity, cause_id = _current_version(state, "RISK")
    with state.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                            match="SOURCE_COVERAGE_INTEGRITY"):
        _resolve(work, identity, cause_id)


@pytest.mark.parametrize("change", [
    dict(confirmed_trade_date="2026-10-29", second_close_date="2026-10-29"),
    dict(earliest_execution_date="2026-10-26"),
    dict(breach_trade_date="2026-10-26"),
    dict(second_close_date="2026-10-23"),
    dict(second_close_date="2026-10-27"),
    dict(breach_trade_date=None),
    dict(second_close_date=None),
])
def test_latent_risk_confirmation_dates_cannot_invent_a_present_exit_grant(legacy, change):
    case = legacy()
    payload = case.risk | change
    # The historical wire codec accepts this shape; current authority must not.
    DailyRiskState.model_validate(payload)
    with case.engine.begin() as connection:
        connection.execute(update(DailyRecord).where(DailyRecord.id == case.cause_id).values(
            payload_json=canonical(payload)))
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                             match="SOURCE_COVERAGE_REQUIRED"):
        _resolve(work, case.id, case.cause_id)


def _install_severe(case, *, facts=True, negative_kind=None, missing_kind=None):
    identity, risk = _risk_payload(case.draft, index=1)
    actual_facts = []
    with case.engine.begin() as connection:
        connection.execute(insert(DailyRecord), _daily(identity, "RISK", case.draft, risk))
        if facts:
            for child in risk["technical_evidence"][0]["children"]:
                if child["condition"]["fact_kind"] == missing_kind:
                    continue
                fact = dict(plan_version_id=case.fact_owner_id,
                    content_hash=case.fact_owner_content_hash,
                    kind=child["condition"]["fact_kind"], trade_date="2026-10-26", signal_id=None,
                    evidence=child["condition"]["evidence_requirement"], verified=True,
                    satisfied=child["condition"]["fact_kind"] != negative_kind,
                    verified_at="2026-10-26T15:00:00+08:00",
                    available_at="2026-10-26T15:00:00+08:00", official_evidence=None)
                DailyFactState.model_validate(fact)
                connection.execute(insert(DailyRecord), _daily(child["fact_ids"][0], "FACT",
                                                               case.draft, fact))
                actual_facts.append(dict(id=child["fact_ids"][0], **fact))
            evidence = evaluate_unified_condition(case.draft.risk_branches[1].condition, None,
                facts=actual_facts, target=_NOW.replace(day=26, hour=15, minute=0))
            assert evidence.outcome == "SATISFIED"
            risk["technical_evidence"] = [evidence.model_dump(mode="json")]
            risk["evidence_ids"] = _condition_evidence_ids(evidence)
            connection.execute(update(DailyRecord).where(DailyRecord.id == identity).values(
                payload_json=canonical(risk)))
    return identity, risk


def test_severe_fact_references_need_real_same_session_fact_owners(legacy):
    case = legacy()
    identity, risk = _install_severe(case, facts=False)
    assert risk["evidence_ids"] and all(risk["technical_evidence"][0]["children"])
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                            match="SOURCE_COVERAGE_REQUIRED"):
        _resolve(work, case.id, identity)


def test_severe_full_tree_with_real_original_fact_records_retains_the_latched_grant(legacy):
    case = legacy(historical_fact_owner=True)
    identity, _ = _install_severe(case)
    with case.work() as work:
        owner = work.plans.get_version_details(case.fact_owner_id)
        assert owner.id != case.id and owner.status == "SUPERSEDED"
        basis = _resolve(work, case.id, identity)
        assert basis.basis == "HISTORICAL_TECHNICAL_RISK"
        assert identity in {row["id"] for row in basis.risk_rows}


@pytest.mark.parametrize("change", [
    dict(kind="SEVERE_DETERIORATION"), dict(trade_date="2026-10-25"),
    dict(satisfied=False), dict(plan_version_id=str(UUID(int=99999))),
    dict(content_hash="0" * 64), dict(verified=False),
    dict(verified_at="2026-10-29T15:00:00+08:00", available_at="2026-10-29T15:00:00+08:00"),
])
def test_real_severe_fact_record_must_match_its_historical_leaf_and_owner(legacy, change):
    case = legacy()
    identity, risk = _install_severe(case)
    fact_id = risk["evidence_ids"][0]
    with case.work() as work:
        original = work.daily.get(fact_id)["payload"]
    with case.engine.begin() as connection:
        connection.execute(update(DailyRecord).where(DailyRecord.id == fact_id).values(
            payload_json=canonical(original | change)))
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
            match="SOURCE_COVERAGE_(?:REQUIRED|INTEGRITY)"):
        _resolve(work, case.id, identity)


def test_a_fact_from_another_security_cannot_prove_the_severe_leaf(legacy):
    case = legacy()
    identity, risk = _install_severe(case)
    with case.engine.begin() as connection:
        connection.execute(update(DailyRecord).where(DailyRecord.id == risk["evidence_ids"][0])
                           .values(symbol="000001.SZ"))
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                            match="SOURCE_COVERAGE_REQUIRED"):
        _resolve(work, case.id, identity)


@pytest.mark.parametrize("mutation", ["omitted_consumed_ids", "self_consistent_dangling_id"])
def test_severe_self_consistent_proof_or_consumed_id_list_is_not_a_fact_owner(legacy, mutation):
    case = legacy()
    identity, risk = _install_severe(case)
    if mutation == "omitted_consumed_ids":
        risk["evidence_ids"] = []
    else:
        risk["technical_evidence"][0]["children"][0]["fact_ids"] = ["no-such-fact"]
        risk["evidence_ids"][0] = "no-such-fact"
    DailyRiskState.model_validate(risk)
    with case.engine.begin() as connection:
        connection.execute(update(DailyRecord).where(DailyRecord.id == identity).values(
            payload_json=canonical(risk)))
    with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                            match="SOURCE_COVERAGE_REQUIRED"):
        _resolve(work, case.id, identity)


@pytest.mark.parametrize("earliest", [None, "2026-10-29"])
def test_known_latched_risk_may_wait_for_a_future_or_missing_execution_session(legacy, earliest):
    case = legacy(expired=True)
    with case.engine.begin() as connection:
        connection.execute(update(DailyRecord).where(DailyRecord.id == case.cause_id).values(
            payload_json=canonical(case.risk | dict(earliest_execution_date=earliest))))
    with case.work() as work:
        assert _resolve(work, case.id, case.cause_id).basis == "HISTORICAL_TECHNICAL_RISK"


def test_resume_first_close_retains_the_earlier_expected_second_session(legacy):
    case = legacy(expired=True)
    changed = case.risk | dict(breach_trade_date="2026-10-22", second_close_date="2026-10-23")
    with case.engine.begin() as connection:
        connection.execute(update(DailyRecord).where(DailyRecord.id == case.cause_id).values(
            payload_json=canonical(changed)))
    with case.work() as work:
        assert _resolve(work, case.id, case.cause_id).basis == "HISTORICAL_TECHNICAL_RISK"


@pytest.mark.parametrize("missing", [False, True])
def test_severe_any_keeps_a_decisive_real_sat_fact_and_nondecisive_unsat_or_missing(
    legacy, missing,
):
    case = legacy(severe_any=True)
    options = {"missing_kind" if missing else "negative_kind": "SEVERE_DETERIORATION"}
    identity, risk = _install_severe(case, **options)
    outcomes = [child["outcome"] for child in risk["technical_evidence"][0]["children"]]
    assert outcomes == ["SATISFIED", "MISSING_INPUT" if missing else "UNSATISFIED"]
    with case.work() as work:
        assert _resolve(work, case.id, identity).basis == "HISTORICAL_TECHNICAL_RISK"
    if not missing:
        with case.work() as work:
            actual = work.daily.get(risk["evidence_ids"][1])["payload"]
        with case.engine.begin() as connection:
            connection.execute(update(DailyRecord).where(DailyRecord.id == risk["evidence_ids"][1])
                               .values(payload_json=canonical(actual | dict(satisfied=True))))
        with case.work() as work, pytest.raises(SourceCoverageAuthorityError,
                                                match="SOURCE_COVERAGE_REQUIRED"):
            _resolve(work, case.id, identity)


@pytest.mark.parametrize("expected_basis", ["CURRENT", "HISTORICAL_TECHNICAL_RISK"])
def test_verified_same_priority_cohorts_keep_the_original_plan_order_instead_of_database_order(
    legacy, state, expected_basis,
):
    if expected_basis == "HISTORICAL_TECHNICAL_RISK":
        case = legacy(parallel_risks=True)
    else:
        draft = _draft(parallel_risks=True)
        identity, cause_id = _current_version(state, "RISK", draft=draft)
        second_id, second = _risk_payload(draft, index=1)
        second_row = _daily(second_id, "RISK", draft, second)
        second_row["created_at"] = (_NOW - timedelta(minutes=1)).isoformat()
        with state.engine.begin() as connection:
            connection.execute(insert(DailyRecord), second_row)
        case = SimpleNamespace(id=identity, cause_id=cause_id, draft=draft,
            work=lambda: SqlAlchemyUnitOfWork(state.sessions,
                                             clock=lambda: _NOW + timedelta(minutes=3)))
    plan = case.draft.to_executable()
    inventory = dict(symbol=plan.symbol, known=True, core_qty=0, tactical_qty=300,
        total_qty=300, sellable_core=0, sellable_tactical=300)
    lots = tuple(dict(id=identity, bucket="TACTICAL", quantity=100, sellable_quantity=100,
                      acquired_trade_date=day) for identity, day in (
        ("a-old", "2026-10-15"), ("b-overlap", "2026-10-22"), ("c-new", "2026-10-26")))
    with case.work() as work:
        stored = work.daily.list(symbol=plan.symbol, kind="RISK")
        assert [row["payload"]["rule_id"] for row in stored] == ["plan-second", "plan-first"]
        by_id = {row["payload"]["rule_id"]: row for row in stored}
        original = tuple(by_id[risk_identity(branch)] for branch in sorted(
            plan.risk_branches, key=lambda branch: branch.priority))
        basis = _resolve(work, case.id, case.cause_id)
        assert basis.basis == expected_basis

        def action(rows):
            return risk_execution(tuple(row["payload"] | dict(revision=row["revision"])
                for row in rows), plan=plan, inventory=inventory, evaluated_at=work.daily.clock(),
                tradable=True, lots=lots)

        expected, actual = action(original), action(basis.risk_rows)
        assert expected["cause_id"] == case.cause_id and expected["tactical_qty"] == 100
        assert expected["lot_allocations"] == [
            dict(id="b-overlap", bucket="TACTICAL", quantity=100)]
        assert actual == expected, (
            f"Plan-order action: {expected!r}; helper-order action: {actual!r}")
