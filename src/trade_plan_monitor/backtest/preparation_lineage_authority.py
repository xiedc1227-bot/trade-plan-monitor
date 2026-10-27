"""Authenticate explicit reuse against actual commands and current parent reviews.

All reads use the caller's connection. Creation stages LINEAGE before the original
record and idempotency response are committed by the existing operation boundary.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field

from trade_plan_monitor.ai.source_candidate_models import PrefixAssuranceRef
from trade_plan_monitor.ai.source_reuse_assurance import build_reuse_alias
from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.preparation_lineage_models import (
    LineagePlacement,
    PreparationLineage,
)
from trade_plan_monitor.backtest.preparation_lineage_store import lineage, save_lineage
from trade_plan_monitor.backtest.preparation_models import (
    CollectionPreparationRecord,
    decode_preparation_record_json,
)
from trade_plan_monitor.backtest.preparation_review import (
    PreparationSemanticError,
    frozen_preparation,
)
from trade_plan_monitor.domain.daily_hash import daily_hash

CREATION_RESPONSE_DOMAIN = "preparation-lineage-creation-response-v1"


def _conflict(code="SOURCE_COVERAGE_REQUIRED"):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    return PreparationConflictError(code)


@dataclass
class CurrentAssuranceContext:
    """Transaction-local verified owners, with bounded recursion and no global cache."""

    reviewed: dict = field(default_factory=dict, init=False)
    active: list = field(default_factory=list, init=False)
    nodes: set = field(default_factory=set, init=False)
    _connection: object = field(default=None, init=False, repr=False)
    _state: tuple | None = field(default=None, init=False, repr=False)

    def bind(self, connection):
        try:
            state = (connection.in_transaction, connection.total_changes,
                connection.execute("PRAGMA data_version").fetchone()[0],
                connection.execute("PRAGMA schema_version").fetchone()[0])
        except sqlite3.DatabaseError:
            raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None
        if self._connection is None:
            self._connection = connection
            self._state = state
        elif self._connection is not connection or self._state != state:
            raise _conflict("SOURCE_COVERAGE_STALE")

    @contextmanager
    def visiting(self, record):
        identity = record.preparation_id
        if identity in self.active:
            raise _conflict("SOURCE_COVERAGE_INTEGRITY")
        if len(self.active) >= 256 or identity not in self.nodes and len(self.nodes) >= 512:
            raise _conflict("SOURCE_COVERAGE_LIMIT_EXCEEDED")
        self.nodes.add(identity)
        self.active.append(identity)
        try:
            yield
        finally:
            self.active.pop()


def assurance_context(connection, context=None):
    context = CurrentAssuranceContext() if context is None else context
    if not isinstance(context, CurrentAssuranceContext):
        raise _conflict("SOURCE_COVERAGE_STALE")
    context.bind(connection)
    return context


@dataclass(frozen=True)
class VerifiedLineage:
    """A real reuse command, never a fabricated revision-zero human REVIEW."""

    lineage: PreparationLineage
    creation_response: CollectionPreparationRecord
    proofs: tuple
    reviews: tuple

    @property
    def evidence_hash(self):
        return self.lineage.evidence_hash

    @property
    def kind(self):
        return "LINEAGE"

    @property
    def frozen_manifest_hash(self):
        return frozen_preparation(self.creation_response).manifest_hash


def _selected(connection, command, operation, context):
    from trade_plan_monitor.backtest import preparation_current_assurance as current
    from trade_plan_monitor.backtest.preparation_store import PreparationStore

    references = ((command.reviewed_base,) if operation == "CREATE_SINGLE" else command.plans)
    selected = []
    for original_index, reference in enumerate(references):
        if reference is None:
            raise _conflict()
        try:
            record = PreparationStore._read(connection, reference.preparation_id)
        except (ValueError, TypeError, KeyError):
            raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None
        if (not isinstance(record, CollectionPreparationRecord) or record.workflow != "SINGLE"
                or record.status != "REVIEWED" or record.work_claim is not None):
            raise _conflict()
        try:
            manifest = frozen_preparation(record)
        except PreparationSemanticError as error:
            code = ("SOURCE_COVERAGE_INTEGRITY" if error.code == "FROZEN_BINDING_CONFLICT"
                    else "SOURCE_COVERAGE_REQUIRED")
            raise _conflict(code) from None
        except (ValueError, TypeError, KeyError):
            raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None
        if manifest.manifest_hash != reference.manifest_hash:
            raise _conflict("SOURCE_COVERAGE_STALE")
        receipt = current.require_current_reviewed_preparation(connection, record, _context=context)
        if len(receipt.proofs) != len(record.items):
            raise _conflict("SOURCE_COVERAGE_STALE")
        selected.append((reference, record, manifest, receipt, original_index))
    return sorted(selected, key=lambda row: row[1].items[-1].source.effective_trade_date)


def _creation(store, command, operation, selected, now):
    from trade_plan_monitor.backtest.plan_library import _composition_record, _single_record

    if operation == "CREATE_SINGLE":
        return _single_record(store, command, now, (selected[0][1], selected[0][2]))
    return _composition_record(store, command, now,
        [(ref, record, manifest) for ref, record, manifest, _, _ in selected])


def _placements(operation, selected):
    placements = []
    for _, record, manifest, receipt, _ in selected:
        indexes = range(len(record.items)) if operation == "CREATE_SINGLE" else (
            len(record.items) - 1,)
        for index in indexes:
            proof = receipt.proofs[index]
            item = record.items[index]
            if (proof.binding.preparation_id, proof.binding.item_index,
                proof.binding.source_id, proof.binding.source_revision,
                proof.binding.source_binding_hash, proof.binding.candidate_revision,
                proof.binding.candidate_hash) != (
                record.preparation_id, index, item.source.source_id, item.source_revision,
                item.source.binding_hash, item.candidate_revision, item.candidate.candidate_hash,
            ):
                raise _conflict("SOURCE_COVERAGE_STALE")
            leaf = proof.reuse_ref
            placements.append(LineagePlacement(consumer_item_index=len(placements),
                owner_binding=proof.binding, owner_revision=record.revision,
                owner_review_revision=record.review_revision,
                owner_review_hash=receipt.evidence_hash,
                owner_manifest_hash=manifest.manifest_hash, owner_proof_hash=proof.evidence_hash,
                leaf_owner_binding=proof.binding if leaf is None else leaf.original_owner_binding,
                leaf_assurance_hash=(proof.evidence_hash if leaf is None else
                                     leaf.original_assurance_hash),
                leaf_current_review_hash=(receipt.evidence_hash if leaf is None else
                                          leaf.original_current_review_hash),
                leaf_manifest_hash=(manifest.manifest_hash if leaf is None else
                                    leaf.original_manifest_hash)))
    return tuple(placements)


def _evidence(command, operation, response, selected, command_id, now):
    from trade_plan_monitor.backtest.preparation_store import _request_hash

    return PreparationLineage.build(operation=operation, preparation_id=response.preparation_id,
        command_id=command_id, command_request_hash=_request_hash(
            operation, response.preparation_id, command), command_json=canonical_json(command),
        creation_response_hash=daily_hash(CREATION_RESPONSE_DOMAIN,
                                          response.model_dump(mode="json")),
        selection_order=tuple(row[4] for row in selected),
        placements=_placements(operation, selected),
        created_at=now)


def _register_creation_lineage(connection, previous, proposed, command, *, operation,
                               command_id, now, store):
    if previous is not None or proposed.preparation_id != command.preparation_id:
        raise _conflict("SOURCE_COVERAGE_STALE")
    context = assurance_context(connection)
    selected = _selected(connection, command, operation, context)
    if proposed != _creation(store, command, operation, selected, now):
        raise _conflict("SOURCE_COVERAGE_STALE")
    return save_lineage(connection, _evidence(
        command, operation, proposed, selected, command_id, now))


def _registered_creation(connection, saved):
    from trade_plan_monitor.backtest.preparation_store import _request_hash

    command = saved.command()
    row = connection.execute(
        "SELECT request_hash,response_json FROM backtest_preparation_idempotency "
        "WHERE idempotency_key=?", (saved.command_id,),
    ).fetchone()
    expected = _request_hash(saved.operation, saved.preparation_id, command)
    if row is None:
        raise _conflict()
    if row[0] != expected or expected != saved.command_request_hash:
        raise _conflict("SOURCE_COVERAGE_STALE")
    try:
        response = decode_preparation_record_json(row[1])
    except (ValueError, TypeError, KeyError, RecursionError):
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None
    if (not isinstance(response, CollectionPreparationRecord)
            or response.preparation_id != saved.preparation_id
            or response.revision != saved.created_revision
            or (response.created_at, response.updated_at) != (saved.created_at, saved.created_at)
            or daily_hash(CREATION_RESPONSE_DOMAIN, response.model_dump(mode="json"))
            != saved.creation_response_hash):
        raise _conflict("SOURCE_COVERAGE_STALE")
    return command, response


def _current_copy(record, response, copied):
    if response.workflow == "COMPOSITION":
        if record != response:
            raise _conflict("SOURCE_COVERAGE_STALE")
        return
    if (record.workflow != "SINGLE" or record.reviewed_base != response.reviewed_base
            or record.base_account != response.base_account
            or record.created_at != response.created_at
            or record.preparation_id != response.preparation_id
            or record.revision < response.revision
            or len(record.items) != len(response.items) or len(record.items) != copied + 1
            or record.items[:copied] != response.items[:copied]
            or record.items[-1].independent):
        raise _conflict("SOURCE_COVERAGE_STALE")


def _resolve_creation_lineage(connection, record, *, context):
    from trade_plan_monitor.backtest.preparation_store import PreparationStore
    from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review

    saved = lineage(connection, record.preparation_id)
    if saved is None:
        if record.reviewed_base is not None or record.workflow == "COMPOSITION":
            raise _conflict()
        return None
    command, response = _registered_creation(connection, saved)
    selected = _selected(connection, command, saved.operation, context)
    expected_response = _creation(PreparationStore, command, saved.operation, selected,
                                  saved.created_at)
    if response != expected_response or saved != _evidence(
        command, saved.operation, response, selected, saved.command_id, saved.created_at,
    ):
        raise _conflict("SOURCE_COVERAGE_STALE")
    _current_copy(record, response, len(saved.placements))
    proofs, reviews = [], []
    for placement in saved.placements:
        # The sealed placement names the exact selected owner. Never search by content/hash.
        owner = next(row for row in selected
                     if row[1].preparation_id == placement.owner_binding.preparation_id)
        _, owner_record, manifest, receipt, _ = owner
        original = receipt.proofs[placement.owner_binding.item_index]
        index = placement.consumer_item_index
        binding = original.binding.model_copy(update={
            "preparation_id": record.preparation_id, "item_index": index})
        prefix = tuple(PrefixAssuranceRef(binding=proof.binding,
            assurance_hash=proof.evidence_hash) for proof in proofs)
        alias = build_reuse_alias(original, binding=binding, prefix=prefix,
            lineage_hash=saved.evidence_hash, current_review_hash=receipt.evidence_hash,
            manifest_hash=manifest.manifest_hash)
        if (alias.reuse_ref.original_owner_binding, alias.reuse_ref.original_assurance_hash,
            alias.reuse_ref.original_current_review_hash,
            alias.reuse_ref.original_manifest_hash) != (
            placement.leaf_owner_binding, placement.leaf_assurance_hash,
            placement.leaf_current_review_hash, placement.leaf_manifest_hash,
        ):
            raise _conflict("SOURCE_COVERAGE_STALE")
        proofs.append(alias)
        reviews.append(preparation_candidate_review(
            owner_record, placement.owner_binding.item_index))
    return VerifiedLineage(saved, response, tuple(proofs), tuple(reviews))


def _guard(function, *args, **kwargs):
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    try:
        return function(*args, **kwargs)
    except PreparationConflictError:
        raise
    except sqlite3.DatabaseError:
        raise _conflict("SOURCE_COVERAGE_INTEGRITY") from None
    except RecursionError:
        raise _conflict("SOURCE_COVERAGE_LIMIT_EXCEEDED") from None
    except (ValueError, TypeError, KeyError, IndexError, StopIteration) as error:
        code = ("SOURCE_COVERAGE_LIMIT_EXCEEDED" if "SOURCE_COVERAGE_LIMIT_EXCEEDED" in str(error)
                else "SOURCE_COVERAGE_STALE")
        raise _conflict(code) from None


def register_creation_lineage(connection, previous, proposed, command, *, operation,
                              command_id, now, store):
    """Authenticate and stage reuse in the caller's existing BEGIN IMMEDIATE."""
    return _guard(_register_creation_lineage, connection, previous, proposed, command,
        operation=operation, command_id=command_id, now=now, store=store)


def resolve_creation_lineage(connection, record, *, context=None):
    """Rebuild aliases only after the actual creation response and parents match."""
    return _guard(_resolve_creation_lineage, connection, record,
                  context=assurance_context(connection, context))


def require_owned_item(connection, record, index, *, context=None):
    """Copied prefix items never acquire new consumer INPUT/HUMAN registrations."""
    resolved = resolve_creation_lineage(connection, record, context=context)
    if resolved is not None and index < len(resolved.proofs):
        raise _conflict()
