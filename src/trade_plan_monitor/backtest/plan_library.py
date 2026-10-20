"""Single-source preparation and composition of immutable reviewed entries."""

import json
from datetime import datetime
from hashlib import sha256

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.loop_input import LoopSourceCollection
from trade_plan_monitor.backtest.plan_schedule import ScheduledLoopSchedule, ScheduledScheduleEntry
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationRecord,
    CollectionPreparationReview,
    PreparationItem,
    PreparationSource,
    PreparedPlanCompositionInput,
    ReviewedPlanReference,
    SingleSourcePreparationInput,
)
from trade_plan_monitor.backtest.preparation_review import (
    FrozenPreparedCollection,
    PreparationSemanticError,
    _collection_review_hash,
    collection_item_binding,
    frozen_preparation,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError


def reviewed_entry(store, reference):
    record = store.get(reference.preparation_id)
    if (
        not isinstance(record, CollectionPreparationRecord)
        or record.workflow != "SINGLE"
        or record.status != "REVIEWED"
        or record.work_claim is not None
    ):
        raise PreparationConflictError("REVIEWED_BASE_REQUIRED")
    frozen = frozen_preparation(record)
    if frozen.manifest_hash != reference.manifest_hash:
        raise PreparationConflictError("REVIEWED_BASE_CHANGED")
    from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review

    try:
        preparation_candidate_review(record, len(record.items) - 1)
    except ValueError:
        raise PreparationConflictError("REVIEWED_RISK_SCOPE_RECHECK_REQUIRED") from None
    return record, frozen


def create_single_preparation(store, command: SingleSourcePreparationInput, *, idempotency_key):
    command = SingleSourcePreparationInput.model_validate_json(command.model_dump_json())

    def change(previous, now):
        if previous is not None:
            raise PreparationConflictError("PREPARATION_EXISTS")
        source = command.source.with_inferred_date()
        prefix, account = (), None
        if command.reviewed_base is not None:
            base, frozen = reviewed_entry(store, command.reviewed_base)
            account = frozen.account
            if (
                source.effective_trade_date is not None
                and source.effective_trade_date <= base.items[-1].source.effective_trade_date
            ):
                raise PreparationConflictError("SOURCE_DATE_CONFLICT")
            prefix = base.items
        sources = tuple(item.source for item in prefix) + (source,)
        _validate_sources(store, sources)
        return CollectionPreparationRecord(
            preparation_id=command.preparation_id,
            revision=1,
            workflow="SINGLE",
            reviewed_base=command.reviewed_base,
            base_account=account,
            items=(*prefix, PreparationItem(source=source, status="DRAFT", independent=not prefix)),
            created_at=now,
            updated_at=now,
        )

    return store._operation(
        "CREATE_SINGLE", command.preparation_id, command, idempotency_key, change
    )


def _validate_sources(store, sources):
    if len({source.source_id for source in sources}) != len(sources):
        raise PreparationConflictError("SOURCE_ID_CONFLICT")
    known_dates = [
        source.effective_trade_date for source in sources if source.effective_trade_date is not None
    ]
    if len(set(known_dates)) != len(known_dates):
        raise PreparationConflictError("SOURCE_DATE_CONFLICT")
    try:
        LoopSourceCollection(sources=sources)
    except ValueError:
        raise PreparationConflictError("SOURCE_COLLECTION_LIMIT") from None
    store.validate_collection_chronology(sources)


def list_reviewed_plans(store, *, offset: int, limit: int):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid library page")
    where = (
        "json_extract(document_json, '$.workflow') = 'SINGLE' "
        "AND json_extract(document_json, '$.status') = 'REVIEWED'"
    )
    with store._connect() as connection:
        total = connection.execute(
            f"SELECT count(*) FROM backtest_preparation WHERE {where}"
        ).fetchone()[0]
        rows = connection.execute(
            f"SELECT preparation_id, document_json FROM backtest_preparation WHERE {where} "
            "ORDER BY json_extract(document_json, '$.updated_at') DESC, "
            "preparation_id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    items = []
    for preparation_id, document in rows:
        # Discovery projects the saved review; reuse still calls reviewed_entry's full checks.
        record = json.loads(document)
        frozen = json.loads(record["review"]["manifest_json"])
        if (
            record["schema_version"] != "backtest-preparation-v2"
            or record["preparation_id"] != preparation_id
            or record.get("work_claim") is not None
            or frozen["schema_version"] != "prepared-loop-plan-v2"
            or frozen["preparation_id"] != preparation_id
            or frozen["revision"] != record["revision"]
            or datetime.fromisoformat(frozen["reviewed_at"])
            != datetime.fromisoformat(record["review"]["reviewed_at"])
            or not frozen["items"]
            or len(frozen["items"]) != len(record["items"])
        ):
            raise PreparationSemanticError("FROZEN_BINDING_CONFLICT")
        last = frozen["items"][-1]
        source = PreparationSource.model_validate_json(json.dumps(last["source"]))
        if source != PreparationSource.model_validate_json(
            json.dumps(record["items"][-1]["source"])
        ):
            raise PreparationSemanticError("FROZEN_BINDING_CONFLICT")
        version = last["version"]
        items.append(
            dict(
                preparation_id=preparation_id,
                manifest_hash=sha256(
                    ("prepared-loop-plan-v2\0" + canonical_json(frozen)).encode()
                ).hexdigest(),
                source_id=source.source_id,
                effective_trade_date=source.effective_trade_date,
                symbol=version["snapshot"]["symbol"],
                name=version["snapshot"]["name"],
                reviewed_base=ReviewedPlanReference.model_validate_json(json.dumps(record["reviewed_base"]))
                if record.get("reviewed_base") is not None else None,
                reviewed_at=version["review"]["reviewed_at"],
                identity=dict(
                    source_hash=source.source_hash,
                    plan_hash=version["plan_hash"],
                    plan_version_id=version["version_id"],
                    reviewed_version_hash=sha256(
                        (
                            "plan-library-reviewed-version-v1\0" + canonical_json(version)
                        ).encode()
                    ).hexdigest(),
                ),
            )
        )
    return dict(items=tuple(items), offset=offset, limit=limit, total=total)


def compose_reviewed_plans(store, command: PreparedPlanCompositionInput, *, idempotency_key):
    command = PreparedPlanCompositionInput.model_validate_json(command.model_dump_json())

    def change(previous, now):
        if previous is not None:
            raise PreparationConflictError("PREPARATION_EXISTS")
        selected = [(ref, *reviewed_entry(store, ref)) for ref in command.plans]
        selected.sort(key=lambda value: value[2].items[-1].source.effective_trade_date)
        prior = None
        for ref, record, _frozen in selected:
            if record.reviewed_base is not None and record.reviewed_base != prior:
                raise PreparationConflictError("PREDECESSOR_SELECTION_REQUIRED")
            prior = ref
        items = tuple(record.items[-1] for _, record, _ in selected)
        _validate_sources(store, tuple(item.source for item in items))
        frozen_items = tuple(frozen.items[-1] for _, _, frozen in selected)
        if (
            len(
                {
                    (item.version.snapshot.symbol, item.version.snapshot.market)
                    for item in frozen_items
                }
            )
            != 1
        ):
            raise PreparationConflictError("SOURCE_ASSET_CONFLICT")
        first = selected[0][2]
        values = dict(
            preparation_id=command.preparation_id,
            revision=1,
            items=frozen_items,
            reused_reviews=True,
            schedule=ScheduledLoopSchedule(
                entries=tuple(
                    ScheduledScheduleEntry(
                        effective_trade_date=item.source.effective_trade_date,
                        version=item.version,
                    )
                    for item in frozen_items
                )
            ),
            account=first.account,
            account_origin=first.account_origin,
            opening_evidence=first.opening_evidence,
            reviewed_at=now,
            schema_version="prepared-loop-plan-v2",
        )
        frozen = FrozenPreparedCollection(**values, review_hash=_collection_review_hash(values))
        return CollectionPreparationRecord(
            preparation_id=command.preparation_id,
            revision=1,
            workflow="COMPOSITION",
            items=items,
            status="REVIEWED",
            review_revision=1,
            created_at=now,
            updated_at=now,
            review=CollectionPreparationReview(
                items=tuple(collection_item_binding(item) for item in items),
                confirmed=True,
                reviewed_at=now,
                manifest_json=canonical_json(frozen),
            ),
        )

    return store._operation(
        "COMPOSE_REVIEWED", command.preparation_id, command, idempotency_key, change
    )
