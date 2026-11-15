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
    from trade_plan_monitor.state.source_coverage_authority import (
        validate_buy_suspension_clarifications,
        validate_buy_suspension_replacement_intent,
    )

    validate_buy_suspension_clarifications(draft, mapping.supplements, source_text)
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
    registered, intent = None, None
    if mapping.supplements or draft.schema_version == 10:
        from trade_plan_monitor.domain.daily_hash import daily_hash

        identity = daily_hash(
            "daily-human-supplements-v1",
            {"symbol": draft.symbol, "content_hash": snapshot.content_hash},
        )
        registered = work.daily.get(identity)
        if mapping.supplements and (
            registered is None
            or registered["kind"] != "DRAFT"
            or registered["payload"].get("source") != "EXPLICIT_HUMAN_OPERATION"
            or registered["payload"].get("supplements")
            != [s.model_dump(mode="json") for s in mapping.supplements]
        ):
            raise ValueError("human supplements require a separate registered human operation")
        if registered is not None:
            intent = registered["payload"].get("buy_suspension_replacement_intent")
            if intent is not None and intent["source_hash"] != snapshot.source_hash:
                # The registry is content-scoped. Another source does not inherit
                # its replacement proposal; the actual source must be reviewed anew.
                intent = None
        if intent is not None:
            from trade_plan_monitor.state.source_coverage_values import (
                BuySuspensionReplacementIntent,
            )

            intent = BuySuspensionReplacementIntent.model_validate(intent)
            validate_buy_suspension_replacement_intent(draft, intent, source_text)
            if registered["payload"]["supplements"] != [
                    s.model_dump(mode="json") for s in mapping.supplements]:
                raise ValueError("replacement intent differs from its registered supplement set")
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
            **({"buy_suspension_replacement_intent": intent.model_dump(mode="json")}
               if intent is not None else {}),
        },
    )
    from trade_plan_monitor.state.source_coverage_authority import save_version_coverage

    save_version_coverage(work, version.id, draft, mapping, source_text,
                          extraction_id=extraction_id, clock=clock)
    return version.id


def record_daily_extraction(work, result, *, clock):
    identity = "extraction-" + str(result.request_id)
    payload = result.model_dump(mode="json", exclude={"diagnostic"})
    existing = work.daily.get(identity)
    from trade_plan_monitor.state.source_coverage_authority import save_extraction_inputs

    if existing is not None:
        if existing["payload"] != payload:
            raise ValueError("extraction identity was reused")
        save_extraction_inputs(work, result, replay=True)
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
    save_extraction_inputs(work, result)


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


def confirm_daily_review(work, command, *, clock, buy_suspension_current=None):
    details = work.plans.get_version_details(str(command.plan_version_id))
    if details is None or details.daily_mapping is None:
        raise ValueError("daily candidate was not found")
    work.daily.lock_symbol(details.symbol)
    # Re-read after acquiring the symbol fence, before writing the binding.
    details = work.plans.get_version_details(details.id)
    from trade_plan_monitor.state.source_coverage_authority import (
        SourceCoverageAuthorityError,
        require_confirmation_coverage,
        save_coverage_receipt,
    )

    if (details.content_hash, details.source_hash, details.review_evidence_hash) != (
        command.content_hash,
        command.source_hash,
        command.review_evidence_hash,
    ):
        raise SourceCoverageAuthorityError("SOURCE_COVERAGE_STALE")
    if command.resolutions:
        raise ValueError("daily review does not accept issue waivers")
    if details.review_revision != command.expected_revision:
        raise RevisionConflictError(details.review_revision)
    coverage = require_confirmation_coverage(work, details, command)
    draft = load_daily_draft_json(details.payload_json)
    if details.daily_issues or draft.to_executable() is None:
        raise ValueError("daily review has unresolved parameters or source evidence")
    row = work.plans._session.get(PlanReviewProvenance, details.id)
    row.review_id = work.plans._id_factory()
    row.review_revision = 1
    row.confirmed_at = clock().isoformat()
    binding = work.daily.get("review-" + details.id)
    receipt = review_buy_suspension_replacement(work, details,
        binding["payload"].get("buy_suspension_replacement_intent"),
        review_id=row.review_id, confirmed_at=datetime.fromisoformat(row.confirmed_at),
        current=buy_suspension_current)
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
            **({"buy_suspension_replacement": receipt.model_dump(mode="json")}
               if receipt is not None else {}),
        },
    )
    work.plans._session.flush()
    confirmed = work.plans.get_version_details(details.id)
    save_coverage_receipt(work, confirmed, coverage)
    return confirmed


def review_buy_suspension_replacement(work, details, intent, *, review_id, confirmed_at,
                                    current=None, observed_at=None):
    """Build a bounded receipt from actual SQL; no state, trade or activation is changed."""
    from trade_plan_monitor.ai.source_treatments import buy_suspension_replacement_proposal
    from trade_plan_monitor.state.activation_history import (
        guard_owner_hash,
        resolve_buy_suspension_context,
        suspension_plan,
    )
    from trade_plan_monitor.state.source_coverage_authority import (
        validate_buy_suspension_replacement_intent,
    )
    from trade_plan_monitor.state.source_coverage_values import (
        BuySuspensionReplacementBinding,
        BuySuspensionReplacementIntent,
    )

    context = resolve_buy_suspension_context(work.plans, details.symbol)
    plan = suspension_plan(details)
    guard = getattr(plan, "buy_suspension", None)
    if intent is None:
        if buy_suspension_replacement_proposal(details.source_text) is not None:
            raise ValueError("replacement source proposal requires its registered human intent")
        if context.owner is not None and guard != suspension_plan(context.owner).buy_suspension:
            raise ValueError("ordinary continuation must retain its original guard and start")
        return None
    intent = BuySuspensionReplacementIntent.model_validate(intent)
    validate_buy_suspension_replacement_intent(load_daily_draft_json(details.payload_json),
                                              intent, details.source_text)
    if context.owner is None or context.predecessor is None:
        raise ValueError("replacement requires a server-resolved actual predecessor guard")
    old, owner = context.predecessor, context.owner
    if details.source_hash in {old.source_hash, owner.source_hash}:
        raise ValueError("replacement requires a new source, not a same-source reimport")
    definition = suspension_plan(owner).buy_suspension
    record = work.daily.get_buy_suspension(symbol=details.symbol, owner_plan_version_id=owner.id)
    unresolved_from, unresolved_through = None, None
    if record is not None:
        state = record["state"]
        if (state.definition, state.content_hash, state.source_hash, state.review_id,
            state.birth_activation_revision) != (definition, owner.content_hash, owner.source_hash,
                owner.review_id, context.birth_revision):
            raise ValueError("guard record differs from its actual original owner")
    verified = (record is not None and (record["state"].trigger is not None
        or callable(current) and current(work, suspension_plan(old),
                                        expected_revision=record["revision"]) is True))
    if not verified:
        from datetime import time

        from trade_plan_monitor.runtime.recovery import buy_suspension_target

        observed_at = observed_at or confirmed_at
        days = work.references.list_trading_days(plan.market,
            observed_at.date(), observed_at.date())
        if days and (not days[0].is_open or observed_at.time() < time(9, 30)):
            days += work.references.list_trading_days(plan.market,
                days[0].previous_trade_date, days[0].previous_trade_date)
        unresolved_from = definition.effective_from
        target = buy_suspension_target(observed_at, days)
        unresolved_through = target if target is not None and target >= unresolved_from else None
    return BuySuspensionReplacementBinding.build(symbol=details.symbol,
        predecessor_plan_version_id=old.id, predecessor_plan_id=old.plan_id,
        predecessor_plan_version=old.version, predecessor_plan_hash=old.plan_hash,
        predecessor_content_hash=old.content_hash, predecessor_source_hash=old.source_hash,
        predecessor_review_id=old.review_id, predecessor_review_revision=old.review_revision,
        predecessor_activation_revision=context.activation_revision, predecessor_guard=definition,
        predecessor_guard_owner_plan_version_id=owner.id,
        predecessor_guard_owner_hash=guard_owner_hash(context),
        predecessor_state_hash=None if record is None else record["state_hash"],
        predecessor_state_revision=0 if record is None else record["revision"],
        predecessor_unresolved_from=unresolved_from,
        predecessor_unresolved_through=unresolved_through,
        new_plan_version_id=details.id, new_plan_id=details.plan_id,
        new_plan_version=details.version, new_plan_hash=details.plan_hash,
        new_content_hash=details.content_hash, new_source_hash=details.source_hash,
        new_review_id=review_id, new_review_revision=1, new_guard=guard,
        intent=intent, confirmed_at=confirmed_at)
