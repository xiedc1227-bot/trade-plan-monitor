"""Private frozen research observations, separate from live source authorization."""

from datetime import datetime, time
from functools import wraps
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_source_authority import ReplayObservationBasis
from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.models import ActivePlan, PlanActivationState, PlanSource, PlanVersion
from trade_plan_monitor.state.repositories import RepositoryError
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError

_ISSUER = object()


def research_manifest(run_input):
    """A frozen research envelope is never the unavailable original plan source."""
    return canonical_json(dict(kind="FROZEN_REVIEWED_RESEARCH_INPUT", run_input=run_input))


def _reject():
    raise SourceCoverageAuthorityError("SOURCE_COVERAGE_INTEGRITY") from None


def _guarded(method):
    @wraps(method)
    def checked(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except SourceCoverageAuthorityError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError, RecursionError, RepositoryError,
                SQLAlchemyError):
            _reject()
    return checked


class _ResearchSourceAuthority:
    def __init__(self, owner, *, _issuer):
        if _issuer is not _ISSUER:
            _reject()
        self._owner, self._engine, self._input = owner, owner.engine, owner.run_input
        self._bytes = canonical_json(self._input).encode()
        self._hash = sha256(self._bytes).hexdigest()
        self._version_id = str(UUID(self._input.authority_id[:32]))
        self._review_id = str(UUID(sha256(
            (self._input.authority_id + "review").encode()).hexdigest()[:32]))
        self._source_id = str(UUID(sha256(
            (self._input.authority_id + "manifest").encode()).hexdigest()[:32]))

    @_guarded
    def __call__(self, work, version_id, *, cause_id=None):
        owner, sql = self._owner, work.daily.session
        binding = sql.get_bind()
        raw = canonical_json(self._input).encode()
        start = self._input.research_input.started_at
        end = datetime.combine(self._input.end, time.max, start.tzinfo)
        if (owner._closed or owner.run_input is not self._input or owner.engine is not self._engine
                or owner._source_authority_reader is not self
                or getattr(binding, "engine", binding) is not self._engine
                or raw != self._bytes or sha256(raw).hexdigest() != self._hash
                or work.daily.clock() != owner.now
                or not start <= owner.now <= end
                or dump_plan_json(owner.plan) != dump_plan_json(self._input.plan_snapshot)):
            _reject()
        plan = self._input.plan_snapshot
        version = sql.get(PlanVersion, self._version_id, populate_existing=True)
        source = sql.get(PlanSource, self._source_id, populate_existing=True)
        manifest = research_manifest(self._input)
        stamp = start.isoformat()
        if (version_id != self._version_id or version is None or source is None
                or version.source_id != self._source_id or version.plan_id != plan.plan_id
                or version.symbol != plan.symbol or version.version != plan.version
                or version.status != "ACTIVE" or version.revision != 1
                or version.plan_hash != self._input.plan_sha256
                or version.payload_json != dump_plan_json(plan) or version.created_at != stamp
                or source.source_text != manifest or source.created_at != stamp
                or source.source_hash != sha256(manifest.encode()).hexdigest()):
            _reject()
        active = sql.get(ActivePlan, plan.symbol, populate_existing=True)
        state = sql.get(PlanActivationState, plan.symbol, populate_existing=True)
        for view in (active, state, owner.active):
            if (view is None or view.plan_version_id != self._version_id or view.revision != 1):
                _reject()
        if (active.activated_at != stamp or state.changed_at != stamp
                or owner.active.activated_at != start):
            _reject()
        expected_details = dict(id=self._version_id, symbol=plan.symbol, plan_id=plan.plan_id,
            plan_hash=self._input.plan_sha256,
            content_hash=self._input.research_input.review.content_hash,
            payload_json=dump_plan_json(plan), review_id=self._review_id)
        for view in (owner.details, work.plans.get_version_details(version_id)):
            if view is None or any(getattr(view, key, None) != value
                                   for key, value in expected_details.items()):
                _reject()
        repository = DailyRepository(sql, clock=lambda: owner.now,
                                     id_factory=lambda: "unused-read-only")
        row = sql.get(DailyRecord, "review-" + self._version_id, populate_existing=True)
        review = None if row is None else repository._value(row)
        expected = dict(confirmed=True, content_hash=expected_details["content_hash"],
            source_hash=self._input.plan_sha256, evidence_hash=self._input.plan_sha256,
            review_id=self._review_id, review_revision=1, plan_version_id=self._version_id)
        if (review is None or review["kind"] != "REVIEW" or review["symbol"] != plan.symbol
                or review["lineage"] != plan.plan_id or review["revision"] != 1
                or review["created_at"] != stamp or review["updated_at"] != stamp
                or review["payload"] != expected):
            _reject()
        if cause_id is not None:
            row = sql.get(DailyRecord, cause_id, populate_existing=True)
            cause = None if row is None else repository._value(row)
            if (cause is None or cause["symbol"] != plan.symbol
                    or cause["kind"] not in {"SIGNAL", "RISK"}):
                _reject()
            if cause["kind"] == "SIGNAL" and (
                cause["payload"]["plan_version_id"] != self._version_id
                or cause["payload"]["review_id"] != self._review_id
            ):
                _reject()
        statement = select(DailyRecord).where(DailyRecord.symbol == plan.symbol,
            DailyRecord.kind == "RISK").order_by(DailyRecord.created_at, DailyRecord.id)
        risks = tuple(repository._value(row) for row in sql.scalars(
            statement.execution_options(populate_existing=True)))
        return ReplayObservationBasis(self._version_id, 1, risks)


@_guarded
def _issue_research_source_authority(owner):
    from trade_plan_monitor.backtest.research_session import ResearchSession

    if (type(owner) is not ResearchSession or hasattr(owner, "_source_authority_reader")
            or owner._closed or owner.now != owner.run_input.research_input.started_at):
        _reject()
    return _ResearchSourceAuthority(owner, _issuer=_ISSUER)
