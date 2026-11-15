"""Coherent actual-owner reads and bounded evidence pages; no trading authority."""

import base64
import hmac
import json
import secrets
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from trade_plan_monitor.ai.source_coverage_models import NormalizationTrace
from trade_plan_monitor.domain.daily_hash import canonical, daily_hash
from trade_plan_monitor.domain.daily_plan_validation import load_daily_draft_json
from trade_plan_monitor.state.models import PlanVersion
from trade_plan_monitor.state.repositories import PlanVersionDetailsRecord, RepositoryError
from trade_plan_monitor.state.source_action_reads import ActionOwnerReader
from trade_plan_monitor.state.source_coverage_authority import (
    SourceCoverageAuthorityError,
    read_version_coverage,
)
from trade_plan_monitor.state.source_coverage_models import CoverageCutoverRow
from trade_plan_monitor.state.source_coverage_store import (
    SourceCoverageIntegrityError,
    SourceCoverageStore,
    SourceCoverageUpgradeRequired,
)
from trade_plan_monitor.state.source_coverage_values import StoredCoverage
from trade_plan_monitor.web.errors import ApiError, ApiErrorCode
from trade_plan_monitor.web.schemas import ErrorDetail
from trade_plan_monitor.web.source_coverage_schemas import (
    SourceCoverageIssueView,
    SourceCoveragePage,
    SourceCoverageSummaryView,
    SourceHumanSupplementLinkView,
    SourceIssueRow,
    SourceMappingProposalView,
    SourceNormalizationChangeView,
    SourceNormalizationRow,
    SourceObligationRow,
    SourceObligationView,
)

MAX_PAGE_BYTES = 1_048_576
_CURSOR_VERSION = "source-coverage-cursor-v1"


def _error(code, reason):
    return ApiError(code, details=(ErrorDetail(location=("sourceCoverage",), code=reason,
        message="Reload the source coverage evidence and review its current state."),))


def _stale():
    return _error(ApiErrorCode.CONFLICT, "SOURCE_COVERAGE_STALE")


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(value):
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _b64(raw) != value:
        raise ValueError("noncanonical base64")
    return raw


class SourceCoverageCursorCodec:
    """One lifecycle's private HMAC key; pagination is not a durable permission."""

    def __init__(self, *, key=None):
        if key is not None and (type(key) is not bytes or len(key) != 32):
            raise TypeError("source coverage cursor key must contain 32 bytes")
        self.__key = secrets.token_bytes(32) if key is None else key

    def encode(self, version_id, binding, offset):
        raw = canonical(dict(v=_CURSOR_VERSION, planVersionId=version_id,
                             binding=binding, nextOffset=offset)).encode("utf-8")
        token = _b64(raw) + "." + _b64(hmac.digest(self.__key, raw, "sha256"))
        if len(token) > 512:
            raise RuntimeError("source coverage cursor exceeds its owned bound")
        return token

    def decode(self, token, version_id):
        try:
            if type(token) is not str or not 1 <= len(token) <= 512 or not token.isascii():
                raise ValueError("invalid cursor")
            encoded, signature = token.split(".")
            raw, mac = _unb64(encoded), _unb64(signature)
            if not hmac.compare_digest(mac, hmac.digest(self.__key, raw, "sha256")):
                raise ValueError("invalid cursor signature")
            value = json.loads(raw)
            if (type(value) is not dict or set(value) != {
                    "v", "planVersionId", "binding", "nextOffset"}
                    or canonical(value).encode("utf-8") != raw
                    or value["v"] != _CURSOR_VERSION or value["planVersionId"] != version_id
                    or type(value["binding"]) is not str or len(value["binding"]) != 64
                    or any(c not in "0123456789abcdef" for c in value["binding"])
                    or type(value["nextOffset"]) is not int
                    or not 0 <= value["nextOffset"] <= 9_007_199_254_740_991):
                raise ValueError("invalid cursor payload")
            return value["binding"], value["nextOffset"]
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise ApiError(ApiErrorCode.VALIDATION_ERROR) from None


@dataclass(frozen=True)
class SourceCoverageRead:
    """A single actual read snapshot, reusable by plan projections without rereading."""

    details: PlanVersionDetailsRecord
    summary: SourceCoverageSummaryView
    coverage_reason: str | None
    stored: StoredCoverage | None
    normalization: NormalizationTrace | None

    def binding(self, *, limit):
        return daily_hash("source-coverage-page-binding-v1", dict(
            plan_version_id=self.details.id, summary=self.summary.model_dump(mode="json"),
            plan_revision=self.details.revision, plan_status=self.details.status,
            review_confirmed_at=(None if self.details.review_confirmed_at is None else
                                 self.details.review_confirmed_at.isoformat()),
            limit=limit, stream="OBLIGATION-ISSUE-NORMALIZATION_CHANGE-v1"))

    def row(self, index):
        assessment = self.stored.assessment
        if index < len(assessment.obligations):
            obligation = assessment.obligations[index]
            mapping = self.details.daily_mapping
            clause = next((c for c in mapping.clauses if c.clause_id == obligation.clause_id), None)
            proposal = None if clause is None else SourceMappingProposalView(
                proposed_disposition=clause.disposition, semantic_role=clause.semantic_role,
                reason=clause.reason, proposed_paths=clause.paths)
            value = obligation.model_dump(exclude={"state"})
            return SourceObligationRow(row_index=index, obligation=SourceObligationView(
                **value, server_state=obligation.state, mapping_proposal=proposal,
                human_supplements=_supplement_links(obligation, mapping)))
        offset = index - len(assessment.obligations)
        if offset < len(assessment.issues):
            return SourceIssueRow(row_index=index, issue=SourceCoverageIssueView(
                **assessment.issues[offset].model_dump()))
        offset -= len(assessment.issues)
        trace = self.normalization
        return SourceNormalizationRow(row_index=index, change=SourceNormalizationChangeView(
            **trace.changes[offset].model_dump(), source_hash=trace.source_hash,
            before_hash=trace.before_hash, after_hash=trace.after_hash,
            evidence_hash=trace.evidence_hash, trace_role=("CURRENT_ASSESSMENT"
                if assessment.normalization_hash == trace.evidence_hash else "HISTORICAL_INPUT")))


def _supplement_links(obligation, mapping):
    # A HUMAN origin is not a per-row confirmation. Only an exact core-proven
    # supplement embedded in this obligation can link to an actual saved binding.
    if obligation.state != "MAPPED_WITH_REGISTERED_SUPPLEMENT" or not obligation.semantics_json:
        return ()
    meaning = json.loads(obligation.semantics_json)
    embedded = meaning.get("supplement") if isinstance(meaning, dict) else None
    if not isinstance(embedded, dict):
        return ()
    result = []
    for supplement in mapping.supplements:
        if (canonical(supplement.model_dump(mode="json")) != canonical(embedded)
                or supplement.candidate_content_hash != mapping.candidate_content_hash
                or supplement.path not in obligation.paths):
            continue
        if any(b.origin == "HUMAN_SUPPLEMENT" and b.supplement_id == supplement.supplement_id
               and not b.clause_ids and b.path == supplement.path
               and canonical(b.value) == canonical(supplement.value) for b in mapping.bindings):
            result.append(SourceHumanSupplementLinkView(supplement_id=supplement.supplement_id,
                path=supplement.path, candidate_content_hash=supplement.candidate_content_hash))
    return tuple(result)


def _receipt_matches(details, stored, receipt):
    if receipt is None or not stored.assessment.coverage_complete:
        return False
    assessment = stored.assessment
    return (receipt.plan_version_id, receipt.review_id, receipt.review_revision,
        receipt.original_review_evidence_hash, receipt.confirmed_at,
        receipt.coverage_revision, receipt.coverage_bundle_hash, receipt.coverage_evidence_hash,
        receipt.coverage_rules_version, receipt.source_hash, receipt.content_hash,
        receipt.mapping_hash) == (details.id, details.review_id, details.review_revision,
        details.review_evidence_hash, details.review_confirmed_at,
        stored.revision, stored.evidence_hash, assessment.evidence_hash,
        assessment.rules_version, assessment.source_hash, assessment.content_hash,
        assessment.mapping_hash)


def _shadow_matches(reader, details, *, confirmed):
    row = reader.daily("review-" + details.id)
    if row is None or row["kind"] != "REVIEW" or row["symbol"] != details.symbol:
        raise SourceCoverageIntegrityError()
    payload = row["payload"]
    from trade_plan_monitor.state.daily_state_models import DailyReviewBinding

    binding = DailyReviewBinding.model_validate(payload)
    receipt = binding.buy_suspension_replacement
    if receipt is not None and (
        receipt.new_plan_id, receipt.new_plan_version, receipt.new_plan_hash, receipt.new_guard,
    ) != (details.plan_id, details.version, details.plan_hash,
          load_daily_draft_json(details.payload_json).to_executable().buy_suspension):
        return False
    return binding.model_dump(mode="json", exclude={
        "buy_suspension_replacement_intent", "buy_suspension_replacement",
    }) == dict(confirmed=confirmed, plan_version_id=details.id,
        content_hash=details.content_hash, source_hash=details.source_hash,
        evidence_hash=details.review_evidence_hash, review_id=details.review_id,
        review_revision=details.review_revision)


def read_source_coverage(work, version_id) -> SourceCoverageRead | None:
    """Fetch fresh owners and recompute evidence in one existing read transaction.

    No writer fence, migration, cutover-root scan, provider or receipt is created.
    Unflushed related changes are rejected and preserved, not discarded or flushed.
    """
    session = work.daily.session
    with session.no_autoflush:
        if session.scalar(select(PlanVersion.id).where(PlanVersion.id == version_id)) is None:
            return None
        reader = ActionOwnerReader(work)
        try:
            details = reader.details(version_id)
            reader.coverage(details)
            reader._reject_pending(CoverageCutoverRow, plan_version_id=version_id)
            stored = read_version_coverage(work, details)
            store = SourceCoverageStore(session)
            legacy = stored is None and store.cutover(version_id) is not None
            receipt = None if details.review_id is None else store.receipt(details.review_id)
        except SourceCoverageUpgradeRequired:
            stored, receipt, legacy = None, None, False
            reason = "SOURCE_COVERAGE_UPGRADE_REQUIRED"
        except SourceCoverageAuthorityError as error:
            if error.reason == "SOURCE_COVERAGE_INTEGRITY":
                raise SourceCoverageIntegrityError() from None
            if error.reason not in {"SOURCE_COVERAGE_STALE", "SOURCE_COVERAGE_REQUIRED"}:
                raise _error(ApiErrorCode.CONFLICT, error.reason) from None
            # General plan views remain readable. No old spans or proof object
            # are represented as current after a legitimate correspondence drift.
            stored, receipt, legacy = None, None, False
            reason = error.reason
        except (RepositoryError, ValueError, TypeError, RecursionError):
            raise SourceCoverageIntegrityError() from None
        else:
            reason = None if stored is not None else "SOURCE_COVERAGE_REQUIRED"

        assessment = None if stored is None else stored.assessment
        normalization = (None if stored is None or stored.inputs is None
                         else stored.inputs.normalization)
        complete = assessment is not None and assessment.coverage_complete
        bound = stored is not None and _receipt_matches(details, stored, receipt)
        if stored is not None and (not complete or (details.review_id is not None and not bound)):
            reason = ("SOURCE_COVERAGE_STALE" if receipt is not None and complete
                      else "SOURCE_COVERAGE_REQUIRED")
        can_confirm = bool(complete and details.status == "DRAFT" and details.review_id is None
            and details.review_revision == 0 and details.review_confirmed_at is None
            and not details.daily_issues and load_daily_draft_json(
                details.payload_json).to_executable() is not None)
        if bound or can_confirm:
            try:
                shadow_matches = _shadow_matches(reader, details, confirmed=bound)
            except (RepositoryError, ValueError, TypeError, RecursionError):
                raise SourceCoverageIntegrityError() from None
            if not shadow_matches:
                bound, can_confirm, reason = False, False, "SOURCE_COVERAGE_STALE"
        counts = (0 if assessment is None else len(assessment.obligations),
                  0 if assessment is None else len(assessment.issues),
                  0 if normalization is None else len(normalization.changes))
        summary = SourceCoverageSummaryView(
            status=(assessment.status if assessment is not None else
                    "LEGACY_UNASSESSED" if legacy else "UNKNOWN"),
            coverage_complete=bool(complete), current_review_bound=bound,
            can_confirm_review=can_confirm, reason=reason,
            review_state=("CURRENT" if bound else "UNCONFIRMED" if can_confirm else
                          "NEEDS_REVIEW" if stored is not None or legacy else "UNKNOWN"),
            source_hash=details.source_hash, candidate_plan_hash=details.plan_hash,
            content_hash=details.content_hash, mapping_hash=(None if assessment is None
                else assessment.mapping_hash), rules_version=(None if assessment is None
                else assessment.rules_version), coverage_evidence_hash=(None if assessment is None
                else assessment.evidence_hash), coverage_revision=(None if stored is None
                else stored.revision), coverage_bundle_hash=(None if stored is None
                else stored.evidence_hash), normalization_hash=(None if assessment is None
                else assessment.normalization_hash),
            original_review_evidence_hash=details.review_evidence_hash,
            review_id=None if details.review_id is None else UUID(details.review_id),
            review_revision=details.review_revision,
            coverage_review_receipt_hash=None if receipt is None else receipt.evidence_hash,
            origin=None if assessment is None else assessment.origin,
            automatic_fidelity_verified=bool(
                assessment and assessment.automatic_fidelity_verified),
            obligation_count=counts[0], issue_count=counts[1],
            normalization_change_count=counts[2], total_rows=sum(counts))
        return SourceCoverageRead(details, summary, reason, stored, normalization)


def source_coverage_page(read, codec, *, limit=50, cursor=None):
    """Pack only complete rows, measuring the final public UTF-8 envelope."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ApiError(ApiErrorCode.VALIDATION_ERROR)
    if read.summary.reason == "SOURCE_COVERAGE_STALE" and read.stored is None:
        raise _stale()
    version_id, binding = read.details.id, read.binding(limit=limit)
    offset = 0
    if cursor is not None:
        old_binding, offset = codec.decode(cursor, version_id)
        if old_binding != binding:
            raise _stale()
        if not 0 < offset < read.summary.total_rows:
            raise ApiError(ApiErrorCode.VALIDATION_ERROR)
    items, result = [], None
    # Include the exact next cursor in every candidate size calculation.
    for index in range(offset, min(offset + limit, read.summary.total_rows)):
        candidate = _page(read, codec, binding, limit, offset, (*items, read.row(index)))
        if len(candidate.model_dump_json(by_alias=True).encode("utf-8")) > MAX_PAGE_BYTES:
            break
        result = candidate
        items.append(candidate.items[-1])
    if result is not None:
        return result
    if offset < read.summary.total_rows:
        raise _error(ApiErrorCode.VALIDATION_ERROR, "SOURCE_COVERAGE_LIMIT_EXCEEDED")
    return _page(read, codec, binding, limit, offset, ())


def _page(read, codec, binding, limit, offset, items):
    end = offset + len(items)
    return SourceCoveragePage(plan_version_id=UUID(read.details.id), summary=read.summary,
        items=tuple(items), limit=limit, returned_count=len(items),
        total_rows=read.summary.total_rows,
        next_cursor=(codec.encode(read.details.id, binding, end)
                     if end < read.summary.total_rows else None))
