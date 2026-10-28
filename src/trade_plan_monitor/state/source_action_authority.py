"""Private, transaction-local action source bases, never client-reusable permits.

Callers own the existing symbol/cause writer fence and all execution guards. This
reader performs no writes, commits, migrations or market/provider operations.
"""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from trade_plan_monitor.ai.source_coverage import assess_source_coverage
from trade_plan_monitor.ai.source_coverage_models import COMPLETE_STATES
from trade_plan_monitor.decision.daily_risk import _condition_evidence_ids
from trade_plan_monitor.decision.unified_conditions import UnifiedConditionEvidence
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_validation import load_daily_draft_json
from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.domain.risk_scope import risk_identity
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.state.daily_state_models import DailyFactState, DailyRiskState
from trade_plan_monitor.state.repositories import RepositoryError
from trade_plan_monitor.state.source_coverage_authority import (
    SourceCoverageAuthorityError,
    _verify_supplements,
    read_version_coverage,
    require_current_coverage,
)
from trade_plan_monitor.state.source_coverage_models import CoverageCutoverRow
from trade_plan_monitor.state.source_coverage_store import (
    SourceCoverageIntegrityError,
    SourceCoverageStore,
    SourceCoverageUpgradeRequired,
)


@dataclass(frozen=True, slots=True)
class ActionSourceBasis:
    """Use only in the current fenced call; it is not a coverage COMPLETE label."""

    basis: Literal["CURRENT", "HISTORICAL_TECHNICAL_RISK"]
    plan_version_id: str
    activation_revision: int
    coverage_evidence_hash: str | None
    cutover_evidence_hash: str | None
    risk_rows: tuple[dict, ...]


def _reject(reason="SOURCE_COVERAGE_REQUIRED"):
    raise SourceCoverageAuthorityError(reason)


def _condition_evidence_matches(condition, evidence):
    if canonical(condition.model_dump(mode="json")) != canonical(
        evidence.condition.model_dump(mode="json")
    ):
        return False
    if condition.type not in {"ALL", "ANY"}:
        return not evidence.children and (evidence.outcome != "SATISFIED" or bool(
            evidence.fact_ids if condition.type == "REVIEWED_FACT" else evidence.bar_ids))
    if len(evidence.children) != len(condition.conditions) or not all(
        _condition_evidence_matches(child, proof)
        for child, proof in zip(condition.conditions, evidence.children, strict=True)
    ):
        return False
    statuses = {child.outcome for child in evidence.children}
    decisive, otherwise = (("UNSATISFIED", "SATISFIED") if condition.type == "ALL"
                           else ("SATISFIED", "UNSATISFIED"))
    outcome = (decisive if decisive in statuses else
               "MISSING_INPUT" if "MISSING_INPUT" in statuses else otherwise)
    return evidence.outcome == outcome


def _risk_policy_matches(plan, branch, payload):
    """Compare the original policy, not dynamic status, an ID prefix or SELL text."""
    if risk_identity(branch) != risk_identity(payload):
        return False
    for key in ("kind", "priority", "target_core_qty", "target_tactical_qty", "involves_core",
                "scope_evidence"):
        if key not in payload or canonical(payload[key]) != canonical(getattr(branch, key)):
            return False
    scope = getattr(branch, "holding_scope", None)
    if canonical(payload.get("holding_scope")) != canonical(
        None if scope is None else scope.model_dump(mode="json")
    ):
        return False
    if branch.kind == "ORDINARY_TECHNICAL":
        own = getattr(branch, "risk_line_fen", None)
        line = own if own is not None else (
            None if plan.levels is None else plan.levels.risk_line_fen)
        comparator = (branch.risk_comparison if own is not None else
                      None if plan.levels is None else plan.levels.risk_comparison)
        expected = dict(risk_line_fen=line, risk_comparison=comparator,
                        suspension_confirmation_policy=branch.suspension_confirmation_policy)
        return line is not None and comparator is not None and all(
            key in payload and canonical(payload[key]) == canonical(value)
            for key, value in expected.items())
    evidence = payload.get("technical_evidence", ())
    if not evidence:
        return False
    try:
        rows = tuple(UnifiedConditionEvidence.model_validate(row) for row in evidence)
    except (ValueError, TypeError):
        return False
    return all(row.outcome == "SATISFIED" and _condition_evidence_matches(branch.condition, row)
               for row in rows)


def _risk_dates_match(state, instant):
    """Validate a latched cause's chronology without imposing an ordinary window."""
    confirmed = state.confirmed_trade_date
    if confirmed is None or confirmed > instant.date() or (
        state.earliest_execution_date is not None and state.earliest_execution_date <= confirmed
    ):
        return False
    if state.kind != "ORDINARY_TECHNICAL":
        return True
    breach, second = state.breach_trade_date, state.second_close_date
    return (breach is not None and second is not None and breach < second <= confirmed
            and (state.suspension_confirmation_policy != "RESTART_ADJACENT_PAIR"
                 or second == confirmed))


def _fact_evidence_owned(work, plan, state, instant):
    """Check actual historical FACT owners, without rebasing them to the active plan."""
    roots = state.technical_evidence
    consumed = tuple(dict.fromkeys(identity for root in roots
                                   for identity in _condition_evidence_ids(root)))
    if state.evidence_ids != consumed:
        return False
    owners = {}

    def owned(evidence):
        if evidence.children:
            return all(owned(child) for child in evidence.children)
        condition = evidence.condition
        if condition.type != "REVIEWED_FACT" or evidence.outcome == "MISSING_INPUT":
            # Native market evidence retains its existing evaluator/data owners.
            return True
        if condition.validity_scope != "TRADE_DATE" or not evidence.fact_ids:
            # The current risk wire has no independent SIGNAL identity carrier.
            return False
        for identity in evidence.fact_ids:
            row = work.daily.get(identity)
            if row is None or row["kind"] != "FACT" or row["symbol"] != plan.symbol:
                return False
            fact = DailyFactState.model_validate(row["payload"])
            if fact.plan_version_id not in owners:
                owners[fact.plan_version_id] = work.plans.get_version_details(fact.plan_version_id)
            owner = owners[fact.plan_version_id]
            if (owner is None or owner.symbol != plan.symbol
                    or owner.content_hash != fact.content_hash or fact.kind != condition.fact_kind
                    or fact.trade_date != state.confirmed_trade_date
                    or fact.verified is not True
                    or fact.satisfied != (evidence.outcome == "SATISFIED")
                    or fact.available_at > instant or fact.verified_at > instant):
                return False
        return True

    return all(owned(root) for root in roots)


def _risk_rows(work, plan, cause):
    by_id = {}
    for branch in plan.risk_branches:
        by_id.setdefault(risk_identity(branch), []).append(branch)
    rows = []
    instant = work.daily.clock()
    for row in work.daily.list(symbol=plan.symbol, kind="RISK"):
        payload = row["payload"]
        try:
            state = DailyRiskState.model_validate(payload)
        except (ValueError, TypeError):
            continue  # Uncertain rows remain visible but cannot contribute quantity.
        branches = by_id.get(risk_identity(payload), ())
        identity = daily_hash("daily-risk-obligation-v1", dict(symbol=plan.symbol,
                                                               kind=risk_identity(payload)))
        if (len(branches) == 1 and row["id"] == payload.get("risk_id") == identity
                and payload["status"] == "CONFIRMED"
                and _risk_policy_matches(plan, branches[0], payload)
                and _risk_dates_match(state, instant)
                and (state.kind != "SEVERE_TECHNICAL"
                     or _fact_evidence_owned(work, plan, state, instant))):
            rows.append(row)
    if cause["id"] not in {row["id"] for row in rows}:
        _reject()
    return tuple(rows)


def _actual_binding(work, version_id):
    details = work.plans.get_version_details(version_id)
    if details is None or details.daily_mapping is None:
        _reject()
    active = work.plans.get_active(details.symbol)
    activation = work.plans.get_activation_state(details.symbol)
    if active is None or activation is None:
        _reject()
    if (active.plan_version_id != details.id or details.status != "ACTIVE"
            or activation.plan_version_id != details.id or activation.revision != active.revision
            or activation.changed_at != active.activated_at):
        _reject("SOURCE_COVERAGE_STALE")
    review = work.daily.get("review-" + details.id)
    if review is None or not review["payload"].get("confirmed") or details.review_id is None:
        _reject()
    expected = dict(review_id=details.review_id, review_revision=details.review_revision,
                    content_hash=details.content_hash, source_hash=details.source_hash,
                    evidence_hash=details.review_evidence_hash, plan_version_id=details.id)
    if (details.review_confirmed_at is None or details.review_evidence_hash is None
            or review["kind"] != "REVIEW" or review["symbol"] != details.symbol
            or any(canonical(review["payload"].get(key)) != canonical(value)
                   for key, value in expected.items())):
        _reject("SOURCE_COVERAGE_STALE")
    instant = work.daily.clock()
    if (instant.tzinfo is None or details.review_confirmed_at > instant
            or active.activated_at > instant
            or active.activated_at < details.review_confirmed_at):
        _reject("SOURCE_COVERAGE_INTEGRITY")
    plan = load_plan_json(details.payload_json)
    if not isinstance(plan, UnifiedTradePlan):
        _reject()
    return details, active, plan


def _membership_root(store):
    """Bind a member to the independent installation root, with constant memory."""
    marker = store.installation()
    digest = sha256(b"source-coverage-membership-v1\0[")
    count = 0
    after = None
    while True:
        statement = select(CoverageCutoverRow.plan_version_id, CoverageCutoverRow.plan_hash,
            CoverageCutoverRow.source_hash, CoverageCutoverRow.evidence_hash).order_by(
                CoverageCutoverRow.plan_version_id).limit(100)
        if after is not None:
            statement = statement.where(CoverageCutoverRow.plan_version_id > after)
        page = store.session.execute(statement).all()
        if not page:
            break
        for row in page:
            if count:
                digest.update(b",")
            digest.update(canonical(list(row)).encode("utf-8"))
            count += 1
        after = page[-1][0]
    digest.update(b"]")
    if count != marker.member_count or digest.hexdigest() != marker.membership_hash:
        _reject("SOURCE_COVERAGE_INTEGRITY")


def _same_time(value, actual):
    if not isinstance(value, str) or actual is None:
        return False
    parsed = datetime.fromisoformat(value)
    return parsed.tzinfo is not None and parsed == actual


def _historical_identity(work, details, active):
    store = SourceCoverageStore(work.daily.session)
    _membership_root(store)
    member = store.cutover(details.id)
    if member is None:
        _reject()
    old = member.legacy_identity
    if (old.get("status") != "ACTIVE" or old.get("review_id") is None
            or old.get("confirmed_at") is None or old.get("active_revision") is None
            or old.get("activated_at") is None):
        _reject()
    expected = dict(status=details.status, revision=details.revision, review_id=details.review_id,
        review_revision=details.review_revision, review_evidence_hash=details.review_evidence_hash,
        content_hash=details.content_hash, origin=details.review_origin.value,
        active_revision=active.revision)
    if (any(key not in old or canonical(old[key]) != canonical(value)
            for key, value in expected.items())
            or not _same_time(old.get("confirmed_at"), details.review_confirmed_at)
            or not _same_time(old.get("activated_at"), active.activated_at)
            or (member.plan_hash, member.source_hash) != (details.plan_hash, details.source_hash)):
        _reject("SOURCE_COVERAGE_STALE")
    return member


def _risk_meaning_known(work, details):
    stored = read_version_coverage(work, details)
    if stored is None:
        draft = load_daily_draft_json(details.payload_json)
        _verify_supplements(work.daily.session, draft, details.daily_mapping,
                            clock=work.daily.clock)
        proof = assess_source_coverage(draft, details.daily_mapping, details.source_text,
                                       origin="AI_HISTORICAL")
    else:
        proof = stored.assessment
    if any(issue.code == "SOURCE_COVERAGE_LIMIT_EXCEEDED" for issue in proof.issues):
        _reject("SOURCE_COVERAGE_LIMIT_EXCEEDED")
    dangerous = {"UNKNOWN", "PLAN", "RISK"}
    if any(row.scope == "UNKNOWN" or row.scope in dangerous and row.state not in COMPLETE_STATES
           for row in proof.obligations):
        _reject()
    for issue in proof.issues:
        related = [row for row in proof.obligations if any(
            path == issue.path or path.startswith(issue.path + ".")
            or issue.path.startswith(path + ".") or path.startswith(issue.path + "[")
            or issue.path.startswith(path + "[") for path in row.paths)]
        if not related or any(row.scope in dangerous for row in related):
            _reject()


def _require(work, version_id, cause_id):
    details, active, plan = _actual_binding(work, version_id)
    cause = None if cause_id is None else work.daily.get(cause_id)
    if cause_id is not None and (cause is None or cause["symbol"] != details.symbol
                                 or cause["kind"] not in {"SIGNAL", "RISK"}):
        _reject()
    technical = cause is not None and cause["kind"] == "RISK"
    if cause is not None and not technical and (
        cause["payload"].get("plan_version_id") != details.id
        or cause["payload"].get("review_id") != details.review_id
    ):
        _reject("SOURCE_COVERAGE_STALE")
    rows = _risk_rows(work, plan, cause) if technical else ()
    try:
        coverage = require_current_coverage(work, details, require_review=True)
    except SourceCoverageAuthorityError as error:
        if not technical or error.reason != "SOURCE_COVERAGE_REQUIRED":
            raise
        member = _historical_identity(work, details, active)
        _risk_meaning_known(work, details)
        return ActionSourceBasis("HISTORICAL_TECHNICAL_RISK", details.id, active.revision,
                                 None, member.evidence_hash, rows)
    return ActionSourceBasis("CURRENT", details.id, active.revision,
                             coverage.assessment.evidence_hash, None, rows)


def require_source_action_authority(work, version_id, *, cause_id=None):
    """Read real owners in the caller's fence; never use this result as a future token.

    No cause (new producer), ordinary BUY/SELL or exception authority is strict
    current. Only an actual stored RISK can establish the separate original basis.
    Returned risk_rows must replace the unchecked list for quantity recomputation;
    all existing quote/inventory/window/consumption checks still apply afterward.
    """
    try:
        return _require(work, version_id, cause_id)
    except SourceCoverageAuthorityError:
        raise
    except SourceCoverageUpgradeRequired:
        _reject("SOURCE_COVERAGE_UPGRADE_REQUIRED")
    except (SourceCoverageIntegrityError, RepositoryError, SQLAlchemyError):
        _reject("SOURCE_COVERAGE_INTEGRITY")
    except RecursionError:
        _reject("SOURCE_COVERAGE_LIMIT_EXCEEDED")
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        code = ("SOURCE_COVERAGE_LIMIT_EXCEEDED" if "SOURCE_COVERAGE_LIMIT_EXCEEDED" in str(error)
                else "SOURCE_COVERAGE_INTEGRITY")
        _reject(code)
