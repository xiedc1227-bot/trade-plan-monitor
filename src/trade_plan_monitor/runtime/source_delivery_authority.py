"""Read actual source owners for one local send check, never a reusable permit."""

from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from trade_plan_monitor.domain.plan_codec import load_plan_json
from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.events import MonitorEventLog
from trade_plan_monitor.state.repositories import PlanRepository, RepositoryError
from trade_plan_monitor.state.reviewed_fact_authority import fact_evidence_satisfied
from trade_plan_monitor.state.source_action_authority import require_source_action_authority
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
from trade_plan_monitor.state.source_coverage_store import SourceCoverageIntegrityError


def _read_only_identity():
    raise RuntimeError("Delivery source reads cannot generate write identities")


@dataclass(frozen=True, slots=True)
class _DeliveryWork:
    daily: DailyRepository
    plans: PlanRepository


@dataclass(frozen=True, slots=True)
class DeliverySourceContext:
    daily: DailyRepository
    active: object
    details: object
    plan: object
    review: dict
    basis: object | None


def read_delivery_source(session, event, now):
    """Return fresh local owners or deny; stored corruption keeps its error path.

    The caller keeps ``no_autoflush`` around its entire remaining native check.
    This function neither locks nor commits, and its context cannot authorize I/O.
    Ordinary and exception reminders need CURRENT; a real risk cause can retain
    its independently proven historical technical-risk basis. Other reminders
    retain their existing read-only admission without acquiring trade authority.
    """
    def clock():
        return now

    work = _DeliveryWork(DailyRepository(session, clock=clock, id_factory=_read_only_identity),
        PlanRepository(session, clock=clock, id_factory=_read_only_identity,
                       events=MonitorEventLog(session, clock=clock)))
    try:
        with session.no_autoflush:
            reads = ActionOwnerReader(work)
            active = reads.active(event.symbol)
            if (active is None or active.plan_version_id != event.plan_version_id
                    or active.revision != event.activation_revision):
                return None
            details = reads.details(event.plan_version_id)
            if (details is None or details.symbol != event.symbol
                    or details.plan_hash != event.plan_hash
                    or details.plan_id != event.plan_id or details.version != event.plan_version):
                return None
            review = reads.daily("review-" + event.plan_version_id)
            if (review is None or not review["payload"].get("confirmed")
                    or review["payload"].get("review_id") != event.review_id):
                return None
            basis = None
            plan = load_plan_json(details.payload_json)
            if event.signal_type != "REMINDER" or event.alert_kind == "EXCEPTION_REVIEW":
                basis = require_source_action_authority(work, event.plan_version_id,
                    cause_id=None if event.signal_type == "REMINDER" else event.cause_id)
                if (basis.plan_version_id != event.plan_version_id
                        or basis.activation_revision != event.activation_revision):
                    return None
                allowed = {"CURRENT", "HISTORICAL_TECHNICAL_RISK"} if (
                    event.signal_type == "RISK_EXIT") else {"CURRENT"}
                if basis.basis not in allowed:
                    return None
                if event.signal_type != "REMINDER":
                    cause = reads.daily(event.cause_id)
                    expected_kind = "RISK" if event.signal_type == "RISK_EXIT" else "SIGNAL"
                    if cause is None or cause["kind"] != expected_kind:
                        return None
                    payload = cause["payload"]
                    execution = ("earliest_execution_date" if expected_kind == "RISK"
                                 else "execution_date")
                    if (event.confirmed_trade_date is not None and (
                        payload.get("confirmed_trade_date") != str(event.confirmed_trade_date)
                    ) or event.execution_date is not None and (
                        payload.get(execution) != str(event.execution_date)
                    )):
                        return None
                    if expected_kind == "SIGNAL" and (
                        payload.get("side") != event.signal_type
                        or event.rule_id is not None and payload.get("rule_id") != event.rule_id
                    ):
                        return None
            if event.signal_type == "REMINDER":
                if event.alert_kind == "EXCEPTION_REVIEW":
                    from trade_plan_monitor.runtime.market_exceptions import (
                        current_exception_authority,
                    )
                    from trade_plan_monitor.state.market_exception_models import ExceptionCandidate
                    from trade_plan_monitor.state.market_exception_service import (
                        ExceptionAuthorityError,
                    )

                    row = reads.daily(event.cause_id)
                    if row is None:
                        return None
                    try:
                        context = current_exception_authority(work,
                            ExceptionCandidate.model_validate(row["payload"]), now)
                    except ExceptionAuthorityError:
                        return None
                    if context.blockers:
                        return None
                else:
                    head = reads.daily("evaluation-head-" + event.symbol)
                    alert = None if head is None else next((item
                        for item in head["payload"].get("alerts", ())
                        if item.get("cause_id") == event.cause_id
                        and item.get("rule_id") == event.rule_id), None)
                    if alert is None or not fact_evidence_satisfied(work, plan,
                            alert["evidence"], confirmed_trade_date=event.confirmed_trade_date,
                            owner_kind="ALERT_RULE", owner_id=event.rule_id,
                            plan_version_id=event.plan_version_id):
                        return None
            return DeliverySourceContext(work.daily, active, details, plan, review, basis)
    except SourceCoverageAuthorityError as error:
        if error.reason == "SOURCE_COVERAGE_INTEGRITY":
            raise SourceCoverageIntegrityError() from None
        return None
    except SourceCoverageIntegrityError:
        raise
    except (RepositoryError, SQLAlchemyError, ValueError, TypeError, KeyError, AttributeError):
        raise SourceCoverageIntegrityError() from None
    except RecursionError:
        return None
