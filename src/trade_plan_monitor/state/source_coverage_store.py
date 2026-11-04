"""Exact assurance history inside the caller's existing transaction and fence."""

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_content_sha256,
    daily_draft_sha256,
    load_daily_draft_json,
)
from trade_plan_monitor.domain.daily_scope import scope_hash
from trade_plan_monitor.state.models import PlanReviewProvenance, PlanSource, PlanVersion
from trade_plan_monitor.state.repositories import RepositoryError, RevisionConflictError
from trade_plan_monitor.state.source_coverage_models import (
    COVERAGE_TRIGGER_SQL,
    CoverageAssessmentRow,
    CoverageCutoverRow,
    CoverageInputRow,
    CoverageInstallationRow,
    CoverageReviewRow,
)
from trade_plan_monitor.state.source_coverage_values import (
    CoverageCutover,
    CoverageInputs,
    CoverageInstallation,
    CoverageReviewReceipt,
    StoredCoverage,
    coverage_request_hash,
)


class SourceCoverageUpgradeRequired(RepositoryError):
    def __init__(self):
        super().__init__("SOURCE_COVERAGE_UPGRADE_REQUIRED")


class SourceCoverageIntegrityError(RepositoryError):
    def __init__(self):
        super().__init__("Stored source coverage evidence is invalid")


class SourceCoverageCommandConflict(ValueError):
    def __init__(self):
        super().__init__("SOURCE_COVERAGE_COMMAND_CONFLICT")


def _decode(model, raw, evidence_hash):
    try:
        value = model.model_validate_json(raw)
        if canonical(value.model_dump(mode="json")) != raw or value.evidence_hash != evidence_hash:
            raise ValueError("projection mismatch")
        return value
    except (ValueError, TypeError, RecursionError):
        raise SourceCoverageIntegrityError() from None


class SourceCoverageStore:
    def __init__(self, session):
        self.session = session

    def installation(self):
        tables = {row.__tablename__ for row in (
            CoverageInstallationRow, CoverageCutoverRow, CoverageInputRow,
            CoverageAssessmentRow, CoverageReviewRow,
        )}
        if not tables <= set(inspect(self.session.connection()).get_table_names()):
            raise SourceCoverageUpgradeRequired()
        row = self.session.execute(select(CoverageInstallationRow.__table__)).one_or_none()
        if row is None:
            raise SourceCoverageUpgradeRequired()
        marker = _decode(CoverageInstallation, row.payload_json, row.evidence_hash)
        if row.id != 1 or marker.installation_id != row.installation_id:
            raise SourceCoverageIntegrityError()
        guards = dict(self.session.execute(text(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'pma_seal_%'",
        )).all())
        if any(guards.get(name) != statement for name, statement in COVERAGE_TRIGGER_SQL.items()):
            raise SourceCoverageIntegrityError()
        return marker

    def cutover(self, version_id):
        marker = self.installation()
        row = self.session.execute(select(CoverageCutoverRow.__table__).where(
            CoverageCutoverRow.plan_version_id == version_id,
        )).one_or_none()
        if row is None:
            return None
        value = _decode(CoverageCutover, row.payload_json, row.evidence_hash)
        if (value.plan_version_id, value.installation_id, value.plan_hash, value.source_hash) != (
            row.plan_version_id, marker.installation_id, row.plan_hash, row.source_hash,
        ) or row.installation_id != marker.installation_id:
            raise SourceCoverageIntegrityError()
        identity = self.session.execute(select(PlanVersion.plan_hash, PlanSource.source_hash).join(
            PlanSource, PlanVersion.source_id == PlanSource.id,
        ).where(PlanVersion.id == version_id)).one_or_none()
        if identity is None:
            return None
        if tuple(identity) != (value.plan_hash, value.source_hash):
            raise SourceCoverageIntegrityError()
        return value

    def input(self, extraction_id):
        self.installation()
        row = self.session.execute(select(CoverageInputRow.__table__).where(
            CoverageInputRow.extraction_id == extraction_id,
        )).one_or_none()
        if row is None:
            return None
        value = _decode(CoverageInputs, row.payload_json, row.evidence_hash)
        if value.source_hash != row.source_hash:
            raise SourceCoverageIntegrityError()
        return value

    def save_input(self, extraction_id, value):
        prior = self.input(extraction_id)
        value = CoverageInputs.model_validate_json(value.model_dump_json())
        if prior is not None:
            if prior != value:
                raise SourceCoverageCommandConflict()
            return prior
        self.session.add(CoverageInputRow(extraction_id=extraction_id,
            source_hash=value.source_hash, payload_json=canonical(value.model_dump(mode="json")),
            evidence_hash=value.evidence_hash))
        self._flush()
        return value

    def _record(self, row, *, check_previous=True):
        if row is None:
            return None
        value = _decode(StoredCoverage, row.payload_json, row.evidence_hash)
        if (value.plan_version_id, value.revision, value.command_id, value.request_hash,
            value.created_at.isoformat()) != (row.plan_version_id, row.revision, row.command_id,
                                             row.request_hash, row.created_at):
            raise SourceCoverageIntegrityError()
        if value.revision > 1 and check_previous:
            prior = self.session.execute(select(CoverageAssessmentRow.__table__).where(
                CoverageAssessmentRow.plan_version_id == value.plan_version_id,
                CoverageAssessmentRow.revision == value.revision - 1,
            )).one_or_none()
            if prior is None:
                raise SourceCoverageIntegrityError()
            previous = self._record(prior, check_previous=False)
            if previous.evidence_hash != value.before_hash:
                raise SourceCoverageIntegrityError()
        return value

    def latest(self, version_id):
        self.installation()
        return self._record(self.session.execute(select(CoverageAssessmentRow.__table__).where(
            CoverageAssessmentRow.plan_version_id == version_id,
        ).order_by(CoverageAssessmentRow.revision.desc()).limit(1)).one_or_none())

    def at_revision(self, version_id, revision):
        """Read the receipt's exact assessment and its direct predecessor only."""
        self.installation()
        return self._record(self.session.execute(select(CoverageAssessmentRow.__table__).where(
            CoverageAssessmentRow.plan_version_id == version_id,
            CoverageAssessmentRow.revision == revision,
        )).one_or_none())

    def command(self, command_id):
        self.installation()
        return self._record(self.session.execute(select(CoverageAssessmentRow.__table__).where(
            CoverageAssessmentRow.command_id == command_id,
        )).one_or_none())

    def _bind_plan(self, version_id, assessment):
        rows = self.session.execute(select(PlanVersion, PlanSource).join(
            PlanSource, PlanVersion.source_id == PlanSource.id,
        ).where(PlanVersion.id == version_id)).one_or_none()
        if rows is None:
            raise ValueError("coverage plan version was not found")
        version, source = rows
        try:
            draft = load_daily_draft_json(version.payload_json)
            if (daily_draft_sha256(draft), scope_hash(source.source_text)) != (
                version.plan_hash, source.source_hash,
            ):
                raise ValueError("stored immutable plan differs")
        except (ValueError, TypeError, RecursionError):
            raise SourceCoverageIntegrityError() from None
        if (assessment.content_hash, assessment.source_hash) != (
            daily_draft_content_sha256(draft), source.source_hash,
        ):
            raise ValueError("coverage source/content differs from stored plan")

    def append(self, version_id, assessment, *, inputs=None, expected_revision, command_id, now):
        self.installation()
        self._bind_plan(version_id, assessment)
        request_hash = coverage_request_hash(version_id, expected_revision, assessment, inputs)
        prior = self.command(command_id)
        if prior is not None:
            if prior.request_hash != request_hash:
                raise SourceCoverageCommandConflict()
            return prior
        current = self.latest(version_id)
        actual = 0 if current is None else current.revision
        if actual != expected_revision:
            raise RevisionConflictError(actual)
        value = StoredCoverage.build(plan_version_id=version_id, revision=actual + 1,
            before_hash=None if current is None else current.evidence_hash, command_id=command_id,
            request_hash=request_hash, assessment=assessment, inputs=inputs, created_at=now)
        self.session.add(CoverageAssessmentRow(plan_version_id=version_id, revision=value.revision,
            command_id=command_id, request_hash=request_hash,
            payload_json=canonical(value.model_dump(mode="json")),
            evidence_hash=value.evidence_hash,
            created_at=value.created_at.isoformat()))
        self._flush()
        return value

    def receipt(self, review_id):
        self.installation()
        row = self.session.execute(select(CoverageReviewRow.__table__).where(
            CoverageReviewRow.review_id == review_id,
        )).one_or_none()
        if row is None:
            return None
        value = _decode(CoverageReviewReceipt, row.payload_json, row.evidence_hash)
        if (value.review_id, value.plan_version_id, value.review_revision) != (
            row.review_id, row.plan_version_id, row.review_revision,
        ):
            raise SourceCoverageIntegrityError()
        return value

    def save_receipt(self, receipt):
        prior = self.receipt(receipt.review_id)
        if prior is not None:
            if prior != receipt:
                raise SourceCoverageCommandConflict()
            return prior
        current = self.latest(receipt.plan_version_id)
        original = self.session.get(PlanReviewProvenance, receipt.plan_version_id)
        if current is None or original is None or not current.assessment.coverage_complete:
            raise ValueError("current source coverage and original review are required")
        proof = current.assessment
        if (receipt.coverage_revision, receipt.coverage_bundle_hash,
            receipt.coverage_evidence_hash, receipt.coverage_rules_version, receipt.source_hash,
            receipt.content_hash, receipt.mapping_hash, receipt.review_id, receipt.review_revision,
            receipt.original_review_evidence_hash, receipt.confirmed_at.isoformat()) != (
            current.revision, current.evidence_hash, proof.evidence_hash, proof.rules_version,
            proof.source_hash, proof.content_hash, proof.mapping_hash, original.review_id,
            original.review_revision, original.review_evidence_hash, original.confirmed_at,
        ):
            raise ValueError("coverage receipt differs from current bound review")
        self.session.add(CoverageReviewRow(review_id=receipt.review_id,
            plan_version_id=receipt.plan_version_id, review_revision=receipt.review_revision,
            payload_json=canonical(receipt.model_dump(mode="json")),
            evidence_hash=receipt.evidence_hash))
        self._flush()
        return receipt

    def _flush(self):
        try:
            self.session.flush()
        except IntegrityError:
            raise SourceCoverageCommandConflict() from None
