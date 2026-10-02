"""Daily candidates reuse immutable plan versions, source provenance and activation fencing."""

from datetime import datetime

from sqlalchemy import select

from trade_plan_monitor.ai.daily_review import DailyMapping, DailyReviewIssue, build_daily_review
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.domain.daily_plan_validation import (
    daily_draft_json,
    daily_draft_sha256,
    load_daily_draft_json,
    obsolete_daily_document,
)
from trade_plan_monitor.state.models import (
    PlanReviewProvenance,
    PlanSource,
    PlanVersion,
    PlanVersionReview,
    StoredPlanExtractionReview,
)
from trade_plan_monitor.state.repositories import (
    DuplicatePlanVersionError,
    PlanReviewOrigin,
    PlanVersionDetailsRecord,
    RepositoryError,
    RevisionConflictError,
    _plan_version_record,
)


def save_daily_draft(work, draft, *, mapping, source_text, clock, extraction_id=None):
    work.daily.lock_symbol(draft.symbol)
    existing = work.daily.session.scalar(
        select(PlanVersion).where(
            PlanVersion.plan_id == draft.plan_id,
            PlanVersion.version == draft.version,
        )
    )
    if existing is not None:
        raise DuplicatePlanVersionError(draft.plan_id, draft.version)
    snapshot = build_daily_review(draft, mapping, source_text)
    if extraction_id is not None:
        extracted = work.daily.get("extraction-" + extraction_id)
        if (
            extracted is None
            or extracted["kind"] != "EXTRACTION"
            or extracted["payload"]["source_text_sha256"] != snapshot.source_hash
            or extracted["symbol"] != draft.symbol
        ):
            raise ValueError("daily extraction provenance was not recorded by the server")
    if mapping.supplements:
        from trade_plan_monitor.domain.daily_hash import daily_hash

        identity = daily_hash(
            "daily-human-supplements-v1",
            {"symbol": draft.symbol, "content_hash": snapshot.content_hash},
        )
        registered = work.daily.get(identity)
        if (
            registered is None
            or registered["kind"] != "DRAFT"
            or registered["payload"].get("source") != "EXPLICIT_HUMAN_OPERATION"
            or registered["payload"].get("supplements")
            != [s.model_dump(mode="json") for s in mapping.supplements]
        ):
            raise ValueError("human supplements require a separate registered human operation")
    repo = work.plans
    now = clock().isoformat()
    source = PlanSource(
        id=repo._id_factory(),
        source_text=source_text,
        source_hash=snapshot.source_hash,
        created_at=now,
    )
    version = PlanVersion(
        id=repo._id_factory(),
        plan_id=draft.plan_id,
        version=draft.version,
        symbol=draft.symbol,
        plan_hash=daily_draft_sha256(draft),
        status="DRAFT",
        payload_json=daily_draft_json(draft),
        source_id=source.id,
        revision=0,
        created_at=now,
    )
    review = PlanVersionReview(plan_version_id=version.id, review_issues_json="[]")
    provenance = PlanReviewProvenance(
        plan_version_id=version.id,
        origin="MANUAL" if extraction_id is None else "AI_EXTRACTION",
        extraction_id=extraction_id,
        source_hash=snapshot.source_hash,
        draft_hash=version.plan_hash,
        confirmed_at=None,
        content_hash=snapshot.content_hash,
        review_evidence_hash=snapshot.evidence_hash,
        mapping_json=canonical(mapping.model_dump(mode="json")),
        required_issues_json=canonical([i.model_dump(mode="json") for i in snapshot.issues]),
        resolutions_json="[]",
        review_id=None,
        review_revision=0,
    )
    repo._session.add(source)
    repo._session.flush()
    repo._session.add(version)
    repo._session.flush()
    repo._session.add_all((review, provenance))
    repo._session.flush()
    work.daily.save(
        "review-" + version.id,
        kind="REVIEW",
        symbol=draft.symbol,
        lineage=draft.plan_id,
        expected_revision=0,
        payload={
            "confirmed": False,
            "content_hash": snapshot.content_hash,
            "source_hash": snapshot.source_hash,
            "evidence_hash": snapshot.evidence_hash,
            "review_id": None,
            "review_revision": 0,
            "plan_version_id": version.id,
        },
    )
    return version.id


def record_daily_extraction(work, result, *, clock):
    identity = "extraction-" + str(result.request_id)
    payload = result.model_dump(mode="json", exclude={"diagnostic"})
    existing = work.daily.get(identity)
    if existing is not None:
        if existing["payload"] != payload:
            raise ValueError("extraction identity was reused")
        return
    work.daily.save(
        identity,
        kind="EXTRACTION",
        symbol=result.draft.symbol,
        lineage=result.draft.plan_id,
        payload=payload,
        expected_revision=0,
    )
    work.plans._session.add(
        StoredPlanExtractionReview(
            id=str(result.request_id),
            provider_id=str(result.provider_id),
            model=result.model,
            prompt_version=result.prompt_version,
            source_hash=result.source_text_sha256,
            draft_hash=daily_draft_sha256(result.draft),
            review_issues_json="[]",
            mapping_json=None,
            content_hash=None,
            review_evidence_hash=None,
            required_issues_json=None,
            completed_at=clock().isoformat(),
        )
    )
    work.plans._session.flush()


def daily_version_details(version, source, review, provenance):
    try:
        if obsolete_daily_document(version.payload_json):
            # Old development documents and their audit binding remain inspectable,
            # but the binding grants no execution under the narrowed contract.
            import json
            from hashlib import sha256

            raw = json.loads(version.payload_json)
            if (
                (raw["plan_id"], raw["version"], raw["symbol"])
                != (version.plan_id, version.version, version.symbol)
                or sha256(version.payload_json.encode()).hexdigest() != version.plan_hash
                or sha256(source.source_text.encode()).hexdigest() != source.source_hash
            ):
                raise ValueError("obsolete daily document identity is invalid")
            return PlanVersionDetailsRecord(
                **_plan_version_record(version).model_dump(mode="python"),
                source_text=source.source_text,
                source_hash=source.source_hash,
                review_origin=PlanReviewOrigin(provenance.origin),
                extraction_id=provenance.extraction_id,
                content_hash=provenance.content_hash,
                review_evidence_hash=provenance.review_evidence_hash,
                review_id=provenance.review_id,
                review_revision=provenance.review_revision,
                review_confirmed_at=None
                if provenance.confirmed_at is None
                else datetime.fromisoformat(provenance.confirmed_at),
                daily_mapping=DailyMapping.model_validate_json(provenance.mapping_json),
                daily_issues=(
                    DailyReviewIssue(
                        issue_id="daily-draft-obsolete",
                        path="draft",
                        code="DAILY_DRAFT_OBSOLETE",
                        reason="Re-extract the preserved source "
                        "and review a new technical-only draft.",
                    ),
                ),
            )
        draft = load_daily_draft_json(version.payload_json)
        mapping = DailyMapping.model_validate_json(provenance.mapping_json)
        snapshot = build_daily_review(draft, mapping, source.source_text)
        issues = canonical([i.model_dump(mode="json") for i in snapshot.issues])
        confirmed = provenance.confirmed_at is not None
        if not all(
            (
                version.id == review.plan_version_id == provenance.plan_version_id,
                version.source_id == source.id,
                version.plan_id == draft.plan_id,
                version.version == draft.version,
                version.symbol == draft.symbol,
                version.payload_json == daily_draft_json(draft),
                version.plan_hash == daily_draft_sha256(draft),
                provenance.draft_hash == version.plan_hash,
                source.source_hash == provenance.source_hash == snapshot.source_hash,
                provenance.content_hash == snapshot.content_hash,
                provenance.review_evidence_hash == snapshot.evidence_hash,
                provenance.mapping_json == canonical(mapping.model_dump(mode="json")),
                provenance.required_issues_json == issues,
                provenance.resolutions_json == "[]",
                confirmed == (provenance.review_id is not None),
                provenance.review_revision == int(confirmed),
                not confirmed or (not snapshot.issues and draft.to_executable() is not None),
            )
        ):
            raise ValueError("daily provenance is inconsistent")
        created = datetime.fromisoformat(version.created_at)
        confirmed_at = None if not confirmed else datetime.fromisoformat(provenance.confirmed_at)
        if created.tzinfo is None or confirmed_at is not None and confirmed_at.tzinfo is None:
            raise ValueError("daily provenance timestamp is naive")
        return PlanVersionDetailsRecord(
            **_plan_version_record(version).model_dump(mode="python"),
            source_text=source.source_text,
            source_hash=source.source_hash,
            review_origin=PlanReviewOrigin(provenance.origin),
            extraction_id=provenance.extraction_id,
            review_confirmed_at=confirmed_at,
            content_hash=snapshot.content_hash,
            review_evidence_hash=snapshot.evidence_hash,
            review_id=provenance.review_id,
            review_revision=provenance.review_revision,
            daily_mapping=mapping,
            daily_issues=snapshot.issues,
        )
    except TypeError, ValueError, RecursionError:
        raise RepositoryError("Stored daily review provenance is invalid") from None


def confirm_daily_review(work, command, *, clock):
    details = work.plans.get_version_details(str(command.plan_version_id))
    if details is None or details.daily_mapping is None:
        raise ValueError("daily candidate was not found")
    work.daily.lock_symbol(details.symbol)
    # Re-read after acquiring the symbol fence, before writing the binding.
    details = work.plans.get_version_details(details.id)
    if (details.content_hash, details.source_hash, details.review_evidence_hash) != (
        command.content_hash,
        command.source_hash,
        command.review_evidence_hash,
    ) or command.resolutions:
        raise ValueError("daily review requires exact current content/source/evidence")
    if details.review_revision != command.expected_revision:
        raise RevisionConflictError(details.review_revision)
    draft = load_daily_draft_json(details.payload_json)
    if details.daily_issues or draft.to_executable() is None:
        raise ValueError("daily review has unresolved parameters or source evidence")
    row = work.plans._session.get(PlanReviewProvenance, details.id)
    row.review_id = work.plans._id_factory()
    row.review_revision = 1
    row.confirmed_at = clock().isoformat()
    binding = work.daily.get("review-" + details.id)
    work.daily.save(
        binding["id"],
        kind="REVIEW",
        symbol=details.symbol,
        lineage=details.plan_id,
        expected_revision=binding["revision"],
        payload={
            **binding["payload"],
            "confirmed": True,
            "review_id": row.review_id,
            "review_revision": 1,
        },
    )
    work.plans._session.flush()
    return work.plans.get_version_details(details.id)
