"""Fresh reads of the exact owners consumed by live action source checks."""

from sqlalchemy import inspect, select

from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_content_sha256,
    load_daily_draft_json,
)
from trade_plan_monitor.state.daily_models import DailyRecord
from trade_plan_monitor.state.models import (
    ActivePlan,
    PlanActivationState,
    PlanReviewProvenance,
    PlanSource,
    PlanVersion,
    PlanVersionReview,
    StoredPlanExtractionReview,
)
from trade_plan_monitor.state.source_coverage_authority import SourceCoverageAuthorityError
from trade_plan_monitor.state.source_coverage_models import (
    CoverageAssessmentRow,
    CoverageCutoverRow,
    CoverageInputRow,
    CoverageInstallationRow,
    CoverageReviewRow,
)

_ABSENT = object()


def _attribute_matches(state, key, expected):
    history = state.attrs[key].history
    values = [state.dict.get(key, _ABSENT), *history.deleted, *history.added]
    if state.identity is not None:
        for index, column in enumerate(state.mapper.primary_key):
            if column.key == key:
                values.append(state.identity[index])
    return expected in values


class ActionOwnerReader:
    """Refresh clean targets only, preserving every unflushed session change.

    The caller must hold its existing writer fence and ``session.no_autoflush``
    for the complete check, including downstream assurance-store reads.
    """

    def __init__(self, work):
        self.work = work
        self.session = work.daily.session

    def _reject_pending(self, model, **criteria):
        for owner in (*self.session.new, *self.session.dirty, *self.session.deleted):
            if not isinstance(owner, model):
                continue
            state = inspect(owner)
            if all(_attribute_matches(state, key, value) for key, value in criteria.items()):
                raise SourceCoverageAuthorityError("SOURCE_COVERAGE_INTEGRITY")

    def _row(self, model, identity):
        primary_key, = inspect(model).primary_key
        self._reject_pending(model, **{primary_key.key: identity})
        return self.session.scalar(select(model).where(primary_key == identity)
            .execution_options(populate_existing=True))

    def _required(self, model, identity):
        row = self._row(model, identity)
        if row is None:
            raise SourceCoverageAuthorityError()
        return row

    def details(self, version_id):
        version = self._required(PlanVersion, version_id)
        self._row(PlanSource, version.source_id)
        self._row(PlanVersionReview, version_id)
        provenance = self._row(PlanReviewProvenance, version_id)
        if provenance is not None and provenance.extraction_id is not None:
            self._row(StoredPlanExtractionReview, provenance.extraction_id)
        return self.work.plans.get_version_details(version_id)

    def coverage(self, details):
        # Historical FACT content owners need fresh identity, not a new source grant.
        if details.extraction_id is not None:
            self._reject_pending(CoverageInputRow, extraction_id=details.extraction_id)
            self._reject_pending(DailyRecord, id="extraction-" + details.extraction_id)
        self._reject_pending(CoverageInstallationRow)
        self._reject_pending(CoverageAssessmentRow, plan_version_id=details.id)
        self._reject_pending(CoverageReviewRow, plan_version_id=details.id)
        if details.review_id is not None:
            self._reject_pending(CoverageReviewRow, review_id=details.review_id)
        if details.daily_mapping is not None and (
            details.daily_mapping.supplements
            or load_daily_draft_json(details.payload_json).schema_version == 10
        ):
            draft = load_daily_draft_json(details.payload_json)
            identity = daily_hash("daily-human-supplements-v1", dict(
                symbol=draft.symbol, content_hash=daily_draft_content_sha256(draft)))
            if details.daily_mapping.supplements:
                self._required(DailyRecord, identity)
            else:
                # Intent-only registration still participates in the exact read
                # snapshot, including pending writes/deletes; absence grants nothing.
                self._row(DailyRecord, identity)

    def active(self, symbol):
        return (None if self._row(ActivePlan, symbol) is None
                else self.work.plans.get_active(symbol))

    def activation(self, symbol):
        return (None if self._row(PlanActivationState, symbol) is None
                else self.work.plans.get_activation_state(symbol))

    def daily(self, identity):
        row = self._row(DailyRecord, identity)
        return None if row is None else self.work.daily._value(row)

    def risks(self, symbol):
        self._reject_pending(DailyRecord, symbol=symbol, kind="RISK")
        statement = select(DailyRecord.id).where(DailyRecord.symbol == symbol,
                                                DailyRecord.kind == "RISK")
        offset = 0
        while True:
            page = self.session.scalars(statement.order_by(DailyRecord.created_at, DailyRecord.id)
                .offset(offset).limit(500)).all()
            for identity in page:
                self._reject_pending(DailyRecord, id=identity)
            if page:
                rows = self.session.scalars(select(DailyRecord).where(DailyRecord.id.in_(page))
                    .order_by(DailyRecord.created_at, DailyRecord.id).limit(500)
                    .execution_options(populate_existing=True)).all()
                if len(rows) != len(page):
                    raise SourceCoverageAuthorityError("SOURCE_COVERAGE_INTEGRITY")
                for row in rows:
                    yield self.work.daily._value(row)
            if len(page) < 500:
                return
            offset += 500

    def historical_root(self):
        # Every cutover member contributes to the independently sealed root.
        self._reject_pending(CoverageCutoverRow)
