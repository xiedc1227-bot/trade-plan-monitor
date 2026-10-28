"""Session-owned frozen observation evidence, never live source completeness."""

from dataclasses import dataclass, field
from datetime import datetime, time
from functools import wraps
from hashlib import sha256
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_input import ScheduledLoopInput
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.plan_codec import dump_plan_json
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.daily_repository import DailyRepository
from trade_plan_monitor.state.models import ActivePlan, PlanActivationState, PlanSource, PlanVersion
from trade_plan_monitor.state.repositories import RepositoryError
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError

_ISSUER = object()


def _reject():
    raise SourceCoverageAuthorityError("SOURCE_COVERAGE_INTEGRITY") from None


def _guarded(method):
    @wraps(method)
    def checked(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except SourceCoverageAuthorityError:
            raise
        except (AttributeError, TypeError, ValueError, RecursionError, RepositoryError,
                SQLAlchemyError):
            _reject()
    return checked


@dataclass(frozen=True, slots=True)
class ReplayObservationBasis:
    plan_version_id: str
    activation_revision: int
    risk_rows: tuple[dict, ...]
    basis: Literal["REPLAY_OBSERVATION"] = field(default="REPLAY_OBSERVATION", init=False)


class _LoopSourceAuthority:
    """Bound to one preflighted input, fresh engine and actual replay lifecycle."""

    def __init__(self, owner, *, _issuer):
        if _issuer is not _ISSUER:
            _reject()
        self._owner, self._engine, self._input = owner, owner.engine, owner.run_input
        self._bytes = canonical_json(self._input).encode()
        self._hash = sha256(self._bytes).hexdigest()

    def _owner_binding(self, session):
        owner = self._owner
        binding = session.get_bind()
        raw = canonical_json(self._input).encode()
        if (owner._closed or owner.run_input is not self._input or owner.engine is not self._engine
                or owner._source_authority_reader is not self
                or getattr(binding, "engine", binding) is not self._engine
                or raw != self._bytes or sha256(raw).hexdigest() != self._hash
                or not self._input.boundary.started_at <= owner.now
                    <= self._input.boundary.evidence_cutoff):
            _reject()
        return owner

    def _chain(self, at):
        schedule = self._input.schedule
        chain = [schedule.select(self._input.boundary.started_at)]
        for row in schedule.entries:
            point = max(datetime.combine(row.effective_trade_date, time.min, at.tzinfo),
                        row.version.available_at)
            if not self._input.boundary.started_at < point <= at:
                continue
            selected = schedule.select(point)
            if selected is not None and selected.authority_id != chain[-1].authority_id:
                chain.append(selected)
        return tuple(chain)

    def _identity(self, selected, namespace):
        authority = (selected.version.causal_hash if isinstance(self._input, ScheduledLoopInput)
                     else selected.authority_id)
        return str(UUID(sha256(canonical_json(dict(authority=authority, namespace=namespace,
            key="")).encode()).hexdigest()[:32]))

    @staticmethod
    def _same_selection(actual, expected):
        return (actual.authority_id == expected.authority_id and actual.version == expected.version
                and actual.effective_trade_date == expected.effective_trade_date
                and actual.activated_at == expected.activated_at)

    def _selected(self, owner, chain):
        selected = chain[-1]
        current = self._input.schedule.select(owner.now)
        if (not self._same_selection(owner.selection, selected)
                or current is not None and not self._same_selection(current, selected)
                or isinstance(self._input, ScheduledLoopInput)
                    and owner._authority_available != (current is not None)
                or dump_plan_json(owner.plan) != dump_plan_json(selected.version.snapshot)):
            _reject()
        return selected, current

    def _row_revision(self, selected, chain):
        identity = self._identity(selected, "version")
        return 1 + sum(self._identity(row, "version") == identity for row in chain[1:]) + sum(
            self._identity(row, "version") == identity for row in chain[:-1])

    def _registration_time(self, selected):
        identity = self._identity(selected, "version")
        for index, row in enumerate(self._chain(self._owner.now)):
            if self._identity(row, "version") == identity:
                return (self._input.boundary.started_at if index == 0
                        else row.activated_at).isoformat()
        _reject()

    def _version(self, session, selected, *, status, revision):
        plan = selected.version.snapshot
        identity, source_id = (self._identity(selected, key) for key in ("version", "manifest"))
        row = session.get(PlanVersion, identity, populate_existing=True)
        source = session.get(PlanSource, source_id, populate_existing=True)
        manifest = canonical_json(dict(kind="FROZEN_REVIEWED_LOOP_VERSION",
                                       version=selected.version.model_dump(mode="json")))
        registered_at = self._registration_time(selected)
        if (row is None or source is None or row.source_id != source_id
                or row.symbol != plan.symbol or row.version != plan.version
                or row.plan_id != (identity if isinstance(self._input, ScheduledLoopInput)
                                   else plan.plan_id)
                or row.status != status or row.revision != revision
                or row.plan_hash != selected.version.plan_hash
                or row.created_at != registered_at or source.created_at != registered_at
                or row.payload_json != dump_plan_json(plan)
                or source.source_text != manifest
                or source.source_hash != sha256(manifest.encode()).hexdigest()):
            _reject()
        repository = DailyRepository(session, clock=lambda: self._owner.now,
                                     id_factory=lambda: "unused-read-only")
        review_row = session.get(DailyRecord, "review-" + identity, populate_existing=True)
        review = None if review_row is None else repository._value(review_row)
        expected = dict(confirmed=True, content_hash=selected.version.review.content_hash,
            source_hash=daily_hash("monitor-loop-source-binding-v1",
                                   dict(source_hashes=selected.version.source_hashes)),
            evidence_hash=selected.version.evidence_hash,
            review_id=self._identity(selected, "review"),
            review_revision=1, plan_version_id=identity)
        if (review is None or review["kind"] != "REVIEW" or review["revision"] != 1
                or review["symbol"] != plan.symbol or review["lineage"] != plan.plan_id
                or review["created_at"] != registered_at or review["updated_at"] != registered_at
                or review["payload"] != expected):
            _reject()
        return row, expected

    def _active(self, session, chain):
        selected = chain[-1]
        row, review = self._version(session, selected, status="ACTIVE",
                                     revision=self._row_revision(selected, chain))
        active = session.get(ActivePlan, row.symbol, populate_existing=True)
        if (active is None or active.plan_version_id != row.id or active.revision != len(chain)
                or active.activated_at != selected.activated_at.isoformat()):
            _reject()
        state = session.get(PlanActivationState, row.symbol, populate_existing=True)
        if isinstance(self._input, ScheduledLoopInput) and (
            state is None or state.plan_version_id != row.id or state.revision != active.revision
            or state.changed_at != active.activated_at
        ):
            _reject()
        return row, review, active

    @_guarded
    def __call__(self, work, version_id, *, cause_id=None):
        owner = self._owner_binding(work.daily.session)
        if work.daily.clock() != owner.now:
            _reject()
        chain = self._chain(owner.now)
        selected, current = self._selected(owner, chain)
        row, review, active = self._active(work.daily.session, chain)
        details = work.plans.get_version_details(version_id)
        expected = dict(id=row.id, plan_id=selected.version.snapshot.plan_id, symbol=row.symbol,
            plan_hash=row.plan_hash, content_hash=review["content_hash"],
            review_id=review["review_id"], payload_json=row.payload_json)
        if (version_id != row.id or details is None or any(
            getattr(view, name, None) != value for view in (details, owner.details)
            for name, value in expected.items())):
            _reject()
        if cause_id is not None:
            cause_row = work.daily.session.get(DailyRecord, cause_id, populate_existing=True)
            cause = None if cause_row is None else work.daily._value(cause_row)
            if (cause is None or cause["symbol"] != row.symbol
                    or cause["kind"] not in {"SIGNAL", "RISK"}):
                _reject()
            if cause["kind"] == "SIGNAL" and (current is None or not owner._authority_available
                    or cause["payload"]["plan_version_id"] != row.id
                    or cause["payload"]["review_id"] != review["review_id"]):
                _reject()
        statement = select(DailyRecord).where(DailyRecord.symbol == row.symbol,
            DailyRecord.kind == "RISK").order_by(DailyRecord.created_at, DailyRecord.id)
        risk_rows = tuple(work.daily._value(record) for record in work.daily.session.scalars(
            statement.execution_options(populate_existing=True)))
        return ReplayObservationBasis(row.id, active.revision, risk_rows)

    @_guarded
    def require_activation(self, session, target_id):
        """Validate a staged frozen successor before the shared activation writes."""
        owner = self._owner_binding(session)
        chain = self._chain(owner.now)
        selected = chain[-1]
        if (not isinstance(self._input, ScheduledLoopInput) or len(chain) < 2
                or not self._same_selection(owner.selection, selected)
                or owner.now != selected.activated_at or target_id != self._identity(
                    selected, "version")):
            _reject()
        self._active(session, chain[:-1])
        earlier = {self._identity(row, "version") for row in chain[:-1]}
        self._version(session, selected,
            status="SUPERSEDED" if target_id in earlier else "DRAFT",
            revision=self._row_revision(selected, chain[:-1]))


@_guarded
def _issue_loop_source_authority(owner):
    """Called only after LoopSession decoded/preflighted and seeded its fresh engine."""
    from trade_plan_monitor.backtest.loop_session import LoopSession

    if (type(owner) is not LoopSession or hasattr(owner, "_source_authority_reader")
            or owner.now != owner.run_input.boundary.started_at):
        _reject()
    return _LoopSourceAuthority(owner, _issuer=_ISSUER)
