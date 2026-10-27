"""Real local SINGLE/COMPOSITION commands authenticate explicit immutable reuse.

All sources and provider responses are synthetic local fixtures. No current
authority is mocked and no provider, market data or user database is accessed.
"""

import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import pytest
from tests.integration.preparation_review_current_fixtures import (
    field_source,
    loop_candidate,
    reviewed_mapping,
    single_draft,
)
from tests.integration.test_plan_preparation_review import collection_review_command
from tests.integration.test_plan_preparation_worker import (
    collection_claim,
    collection_update_result,
)
from tests.integration.test_source_coverage_preparation_commit import _NOW
from tests.unit.test_monitor_loop_schedule import at
from tests.unit.test_plan_delta_wire import delta

from trade_plan_monitor.ai.loop_plan_extraction import (
    LoopPlanExtractionOutput,
    OpeningAccountFacts,
    OpeningFact,
)
from trade_plan_monitor.ai.source_derivation_replay import expand_update_with_evidence
from trade_plan_monitor.ai.update_review import context_from_review, materialize_extraction
from trade_plan_monitor.backtest import preparation_current_assurance as current
from trade_plan_monitor.backtest import preparation_lineage_authority as authority
from trade_plan_monitor.backtest.plan_library import (
    compose_reviewed_plans,
    create_single_preparation,
)
from trade_plan_monitor.backtest.preparation_assurance_store import ASSURANCE_TRIGGERS
from trade_plan_monitor.backtest.preparation_lineage_models import PreparationLineage
from trade_plan_monitor.backtest.preparation_lineage_store import lineage
from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    PreparedPlanCompositionInput,
    ReviewedPlanReference,
    SingleSourcePreparationInput,
)
from trade_plan_monitor.backtest.preparation_review import (
    CollectionItemCorrectionCommand,
    collection_item_binding,
    frozen_preparation,
)
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review
from trade_plan_monitor.domain.daily_hash import canonical
from trade_plan_monitor.state.source_coverage_authority import extraction_inputs


def _source(identifier, day=19):
    draft = single_draft()
    text = field_source(draft, tail=("账户记录：当前持仓0股。",))
    return PreparationSource(source_id=identifier, text=text, available_at=at(day),
                             effective_trade_date=at(day).date())


def _finish(store, record, index, result, inputs):
    key = f"{record.preparation_id}-{index}"
    identity = result.request_id if hasattr(result, "request_id") else result.extraction.request_id
    claim = collection_claim(record, index, generation=str(identity)).model_copy(
        update={"claimed_at": _NOW})
    record = store.start_attempt(record.preparation_id, expected_revision=record.revision,
        idempotency_key="start-" + key, work_claim=claim)
    record = store.begin_call(record.preparation_id, generation=claim.generation,
        owner_id=claim.owner_id, expected_revision=record.revision)
    record = store.finish_attempt(record.preparation_id, attempt_id=claim.generation,
        expected_revision=record.revision, idempotency_key="finish-" + key,
        worker_owner_id=claim.owner_id, candidate=result.to_preparation_candidate(), inputs=inputs)
    return store.clear_work_claim(record.preparation_id, generation=claim.generation,
                                   expected_revision=record.revision)


def _root(store, identifier="root", day=19):
    source = _source(identifier + "-source", day)
    record = create_single_preparation(store, SingleSourcePreparationInput(
        preparation_id=identifier, source=source), idempotency_key="create-" + identifier)
    draft, text = single_draft(), source.text
    start = text.index("账户记录")
    output = LoopPlanExtractionOutput(schema_version="monitor-loop-extraction-v1", draft=draft,
        clauses=reviewed_mapping(draft, text).clauses,
        bindings=reviewed_mapping(draft, text).bindings,
        opening_account=OpeningAccountFacts(inventory_quantity=OpeningFact(value=0,
            start=start, end=len(text), excerpt=text[start:]), lots=(), cash_fen=None,
            snapshot_at=None))
    result, inputs = loop_candidate(source, output, uuid4())
    ready = _finish(store, record, 0, result, inputs)
    return store.review_and_freeze(identifier, command=collection_review_command(ready),
                                   idempotency_key="review-" + identifier)


def _reference(record):
    return ReviewedPlanReference(preparation_id=record.preparation_id,
                                 manifest_hash=frozen_preparation(record).manifest_hash)


def _child(store, parent, identifier="child", day=20, maximum=500, extra=None):
    text = f"position.max_qty = {maximum}"
    if extra is not None:
        text += "\n" + extra
    source = PreparationSource(source_id=identifier + "-source", text=text,
        available_at=at(day), effective_trade_date=at(day).date())
    command = SingleSourcePreparationInput(preparation_id=identifier, source=source,
                                           reviewed_base=_reference(parent))
    return create_single_preparation(store, command, idempotency_key="create-" + identifier)


def _finish_delta(store, record, maximum=500):
    index = len(record.items) - 1
    source = record.items[index].source
    base = preparation_candidate_review(record, index - 1)
    context = context_from_review(base, record.items[index - 1].candidate.candidate_hash)
    _, patch = delta(source.text, values={"max_qty": maximum})
    output, derivation = expand_update_with_evidence(
        json.dumps(patch.model_dump(mode="json")), source, context)
    result = collection_update_result(base, source, output, uuid4(), context).model_copy(
        update={"source_derivation": derivation})
    materialized = materialize_extraction(base, context.base_hash, source, result)
    return _finish(store, record, index, materialized, extraction_inputs(materialized.extraction))


def _review(store, record):
    return store.review_and_freeze(record.preparation_id,
        command=collection_review_command(record, account=None),
        idempotency_key="review-" + record.preparation_id)


def _snapshot(store):
    with closing(sqlite3.connect(store.database_path)) as connection:
        return {table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in ("backtest_preparation", "backtest_preparation_idempotency",
                              "backtest_preparation_assurance")}


def _read(store, record, *, prefix=None, reviewed=False):
    with closing(sqlite3.connect(store.database_path)) as connection:
        changes = connection.total_changes
        if reviewed:
            result = current.require_current_reviewed_preparation(connection, record)
        elif prefix is not None:
            result = current.read_current_assurance_prefix(connection, record, prefix)
        else:
            result = current.read_current_assurance(connection, record)
        assert connection.total_changes == changes
        return result


def _replace_lineage(store, saved, **updates):
    values = {name: getattr(saved, name) for name in type(saved).model_fields
              if name not in {"evidence_key", "evidence_hash"}}
    replacement = PreparationLineage.build(**(values | updates))
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("DROP TRIGGER pma_preparation_assurance_update")
        connection.execute("UPDATE backtest_preparation_assurance SET payload_json=?,"
            "evidence_hash=?,created_at=? WHERE evidence_key=?",
            (canonical(replacement.model_dump(mode="json")), replacement.evidence_hash,
             replacement.created_at.isoformat(), saved.evidence_key))
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_update"])
    return replacement


def _overwrite(store, record):
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("UPDATE backtest_preparation SET document_json=? WHERE preparation_id=?",
                           (record.model_dump_json(), record.preparation_id))


def test_actual_single_creation_registers_lineage_and_rebuilds_original_owner_prefix(tmp_path):
    store = PreparationStore(tmp_path / "lineage.sqlite3", clock=lambda: _NOW)
    parent = _root(store)
    command = SingleSourcePreparationInput(preparation_id="child", source=_source("next", 20),
                                           reviewed_base=_reference(parent))
    child = create_single_preparation(store, command, idempotency_key="create-child")

    with closing(sqlite3.connect(store.database_path)) as connection:
        saved = lineage(connection, child.preparation_id)
        assert saved is not None
        parent_receipt = current.require_current_reviewed_preparation(connection, parent)
        proofs = current.read_current_assurance_prefix(connection, child, 1)
    assert saved.command() == command
    assert len(proofs) == 1 and proofs[0].binding.preparation_id == child.preparation_id
    assert proofs[0].source_assessment == parent_receipt.proofs[0].source_assessment
    assert proofs[0].reuse_ref.original_owner_binding == parent_receipt.proofs[0].binding
    assert proofs[0].reuse_ref.lineage_hash == saved.evidence_hash
    assert create_single_preparation(store, command, idempotency_key="create-child") == child


def test_single_child_and_grandchild_use_their_own_delta_and_true_reviewed_parent(tmp_path):
    store = PreparationStore(tmp_path / "chain.sqlite3", clock=lambda: _NOW)
    root = _root(store)
    child = _review(store, _finish_delta(store, _child(store, root)))
    grandchild = _review(store, _finish_delta(store,
        _child(store, child, "grandchild", 21, 600), 600))
    receipt = _read(store, grandchild, reviewed=True)
    original = _read(store, root, reviewed=True).proofs[0]
    assert len(receipt.proofs) == 3
    first, middle, last = receipt.proofs
    assert first.reuse_ref.original_owner_binding == original.binding
    assert first.source_assessment == original.source_assessment
    assert first.reuse_ref.original_assurance_hash == original.evidence_hash
    assert middle.reuse_ref.original_owner_binding.preparation_id == child.preparation_id
    assert middle.reuse_ref.original_owner_binding.item_index == 1
    assert last.reuse_ref is None and last.binding.preparation_id == grandchild.preparation_id
    assert last.parent_hash == middle.evidence_hash
    assert all(proof.coverage_complete for proof in receipt.proofs)
    assert store.get(root.preparation_id) == root and store.get(child.preparation_id) == child


def test_composition_of_independent_roots_authenticates_original_reverse_selection_order(tmp_path):
    store = PreparationStore(tmp_path / "composition.sqlite3", clock=lambda: _NOW)
    first, second = _root(store), _root(store, "second", 20)
    command = PreparedPlanCompositionInput(preparation_id="composed",
        plans=(_reference(second), _reference(first)))
    composed = compose_reviewed_plans(store, command, idempotency_key="compose-roots")
    verified = _read(store, composed, reviewed=True)
    assert verified.kind == "LINEAGE" and verified.lineage.selection_order == (1, 0)
    assert tuple(row.owner_binding.preparation_id for row in verified.lineage.placements) == (
        first.preparation_id, second.preparation_id)
    assert tuple(proof.binding.item_index for proof in verified.proofs) == (0, 1)
    assert all(proof.binding.independent and proof.parent_hash is None for proof in verified.proofs)
    assert verified.proofs[1].reuse_ref.original_owner_binding.item_index == 0
    assert frozen_preparation(composed).manifest_hash == verified.frozen_manifest_hash
    with closing(sqlite3.connect(store.database_path)) as connection:
        count = connection.execute("SELECT count(*) FROM backtest_preparation_assurance "
            "WHERE preparation_id=? AND kind='REVIEW'", (composed.preparation_id,)).fetchone()[0]
        assert count == 0
    assert compose_reviewed_plans(store, command, idempotency_key="compose-roots") == composed


def test_composition_keeps_selected_dependency_leaf_owners_and_original_inner_parents(tmp_path):
    store = PreparationStore(tmp_path / "dependent-compose.sqlite3", clock=lambda: _NOW)
    root = _root(store)
    child = _review(store, _finish_delta(store, _child(store, root)))
    grandchild = _review(store, _finish_delta(store,
        _child(store, child, "grandchild", 21, 600), 600))
    command = PreparedPlanCompositionInput(preparation_id="composed",
        plans=(_reference(grandchild), _reference(root), _reference(child)))
    composed = compose_reviewed_plans(store, command, idempotency_key="compose-chain")
    verified = _read(store, composed, reviewed=True)
    assert verified.lineage.selection_order == (1, 2, 0)
    originals = tuple(_read(store, owner, reviewed=True).proofs[-1]
                      for owner in (root, child, grandchild))
    for alias, original in zip(verified.proofs, originals, strict=True):
        assert alias.source_assessment == original.source_assessment
        assert alias.owners == original.owners
        assert alias.source_refs == original.source_refs
        assert alias.reuse_ref.original_owner_binding == original.binding
    assert verified.proofs[-1].parent_hash == verified.proofs[-2].evidence_hash


def test_prefix_read_never_claims_or_requires_the_consumers_unresolved_future_tail(tmp_path):
    store = PreparationStore(tmp_path / "prefix.sqlite3", clock=lambda: _NOW)
    child = _child(store, _root(store), extra="Everything also depends on the blue lantern.")
    assert _read(store, child, prefix=1)[0].coverage_complete
    ready = _finish_delta(store, child)
    proofs = _read(store, ready)
    assert proofs[0].coverage_complete and not proofs[-1].coverage_complete
    assert _read(store, ready, prefix=1) == proofs[:1]
    with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_REQUIRED"):
        _review(store, ready)


def test_consumer_own_tail_human_correction_keeps_copied_original_provenance(tmp_path):
    store = PreparationStore(tmp_path / "human-tail.sqlite3", clock=lambda: _NOW)
    child = _finish_delta(store, _child(store, _root(store)))
    previous = _read(store, child)
    item = child.items[-1]
    from trade_plan_monitor.ai.update_review import MaterializedUpdateCandidate

    materialized = MaterializedUpdateCandidate.model_validate_json(item.candidate.payload_json)
    output = materialized.extraction.output
    command = CollectionItemCorrectionCommand(expected_revision=child.revision,
        binding=collection_item_binding(item), confirmed=True,
        evidence="Explicit source-bound reassessment of the consumer owned tail.",
        update=output, mapping=output.review(item.source.text).mapping)
    corrected = store.correct_collection_item(child.preparation_id, command=command,
                                               idempotency_key="human-own-tail")
    proofs = _read(store, corrected)
    assert proofs[0] == previous[0]
    assert proofs[-1].source_assessment.origin == "HUMAN"
    assert proofs[-1].source_assessment.automatic_fidelity_verified is False
    assert proofs[-1].parent_hash == proofs[0].evidence_hash
    assert _read(store, _review(store, corrected), reviewed=True).proofs == proofs


def test_missing_parent_current_review_does_not_reuse_historical_zero_issue_freeze(tmp_path):
    store = PreparationStore(tmp_path / "missing-review.sqlite3", clock=lambda: _NOW)
    parent = _root(store)
    before_manifest = frozen_preparation(parent).model_dump_json()
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("DROP TRIGGER pma_preparation_assurance_delete")
        connection.execute("DELETE FROM backtest_preparation_assurance WHERE kind='REVIEW'")
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_delete"])
    before = _snapshot(store)
    with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_REQUIRED"):
        _child(store, parent)
    assert _snapshot(store) == before
    assert frozen_preparation(store.get(parent.preparation_id)).model_dump_json() == before_manifest


def test_detached_advisory_parent_cannot_replace_actual_selected_owner_with_same_value(
    tmp_path, monkeypatch,
):
    from trade_plan_monitor.backtest import plan_library

    store = PreparationStore(tmp_path / "advisory.sqlite3", clock=lambda: _NOW)
    actual, other = _root(store), _root(store, "other", 20)
    assert (actual.items[-1].candidate.candidate_hash != other.items[-1].candidate.candidate_hash)
    before = _snapshot(store)
    monkeypatch.setattr(plan_library, "reviewed_entry",
                        lambda *_: (other, frozen_preparation(actual)))
    with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_STALE"):
        _child(store, actual, day=21)
    assert _snapshot(store) == before


def test_failure_after_lineage_insert_rolls_back_record_command_and_lineage(tmp_path, monkeypatch):
    store = PreparationStore(tmp_path / "rollback.sqlite3", clock=lambda: _NOW)
    parent = _root(store)
    before = _snapshot(store)
    original = authority.save_lineage

    def fail_after_save(connection, value):
        assert connection.in_transaction
        original(connection, value)
        raise PreparationConflictError("TEST_AFTER_LINEAGE")

    monkeypatch.setattr(authority, "save_lineage", fail_after_save)
    with pytest.raises(PreparationConflictError, match="TEST_AFTER_LINEAGE"):
        _child(store, parent)
    assert _snapshot(store) == before


@pytest.mark.parametrize("mutation", ["missing_lineage", "unregistered", "request_hash",
                                      "response_hash", "response_revision", "response_time"])
def test_current_reads_require_the_registered_exact_original_creation_response(tmp_path, mutation):
    store = PreparationStore(tmp_path / (mutation + ".sqlite3"), clock=lambda: _NOW)
    child = _child(store, _root(store))
    with closing(sqlite3.connect(store.database_path)) as connection:
        saved = lineage(connection, child.preparation_id)
    if mutation == "unregistered":
        _replace_lineage(store, saved, command_id="self-signed-no-real-command")
    elif mutation == "response_hash":
        _replace_lineage(store, saved, creation_response_hash="0" * 64)
    else:
        with closing(sqlite3.connect(store.database_path)) as connection, connection:
            if mutation == "missing_lineage":
                connection.execute("DROP TRIGGER pma_preparation_assurance_delete")
                connection.execute("DELETE FROM backtest_preparation_assurance "
                                   "WHERE kind='LINEAGE'")
                connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_delete"])
            elif mutation == "request_hash":
                connection.execute("UPDATE backtest_preparation_idempotency SET request_hash=? "
                    "WHERE idempotency_key=?", ("0" * 64, saved.command_id))
            else:
                changed = child.model_dump(mode="json")
                if mutation == "response_revision":
                    changed["revision"] += 1
                else:
                    changed["updated_at"] = _NOW.replace(hour=11).isoformat()
                connection.execute("UPDATE backtest_preparation_idempotency SET response_json=? "
                    "WHERE idempotency_key=?", (json.dumps(changed), saved.command_id))
    before = _snapshot(store)
    code = "SOURCE_COVERAGE_REQUIRED" if mutation in {"missing_lineage", "unregistered"} else (
        "SOURCE_COVERAGE_STALE")
    with pytest.raises(PreparationConflictError, match=code):
        _read(store, child, prefix=1)
    assert _snapshot(store) == before


@pytest.mark.parametrize("mutation", ["direct_proof", "direct_review", "direct_revision",
                                      "leaf_proof", "leaf_review", "leaf_manifest"])
def test_rehashed_placements_cannot_replace_real_owner_or_leaf_evidence(tmp_path, mutation):
    store = PreparationStore(tmp_path / (mutation + ".sqlite3"), clock=lambda: _NOW)
    child = _review(store, _finish_delta(store, _child(store, _root(store))))
    grandchild = _child(store, child, "grandchild", 21, 600)
    with closing(sqlite3.connect(store.database_path)) as connection:
        saved = lineage(connection, grandchild.preparation_id)
    original = saved.placements[0]
    field = {"direct_proof": "owner_proof_hash", "direct_review": "owner_review_hash",
             "direct_revision": "owner_revision", "leaf_proof": "leaf_assurance_hash",
             "leaf_review": "leaf_current_review_hash", "leaf_manifest": "leaf_manifest_hash"}[
                 mutation]
    changed = original.model_copy(update={field: original.owner_revision + 1
                                          if mutation == "direct_revision" else "0" * 64})
    _replace_lineage(store, saved, placements=(changed, *saved.placements[1:]))
    before = _snapshot(store)
    with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_STALE"):
        _read(store, grandchild, prefix=2)
    assert _snapshot(store) == before


@pytest.mark.parametrize("mutation", ["copied_source", "account", "parent"])
def test_current_draft_cannot_replace_immutable_copied_prefix_account_or_parent(tmp_path, mutation):
    store = PreparationStore(tmp_path / (mutation + ".sqlite3"), clock=lambda: _NOW)
    parent, other = _root(store), _root(store, "other")
    child = _child(store, parent)
    if mutation == "copied_source":
        changed = child.model_copy(update={"items": (other.items[0], child.items[-1])})
    elif mutation == "account":
        cash = child.base_account.cash.model_copy(update={"balance_fen": 2_000_000})
        changed = child.model_copy(update={"base_account": child.base_account.model_copy(
            update={"cash": cash})})
    else:
        changed = child.model_copy(update={"reviewed_base": _reference(other)})
    _overwrite(store, changed)
    before = _snapshot(store)
    with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_STALE"):
        _read(store, changed, prefix=1)
    assert _snapshot(store) == before


def test_draft_can_edit_only_its_own_tail_after_registered_creation_and_keep_old_creation(tmp_path):
    store = PreparationStore(tmp_path / "edit-tail.sqlite3", clock=lambda: _NOW)
    child = _child(store, _root(store))
    before = _read(store, child, prefix=1)
    source = child.items[-1].source.model_copy(update={"text": "position.max_qty = 600",
        "available_at": at(21), "effective_trade_date": at(21).date()})
    edited = store.edit_collection(child.preparation_id, expected_revision=child.revision,
        source=source, idempotency_key="edit-own-tail")
    assert edited.items[:-1] == child.items[:-1]
    assert _read(store, edited, prefix=1) == before
    reviewed = _review(store, _finish_delta(store, edited, 600))
    assert _read(store, reviewed, reviewed=True).proofs[-1].coverage_complete
    with closing(sqlite3.connect(store.database_path)) as connection:
        saved = lineage(connection, child.preparation_id)
    assert saved.command().source == child.items[-1].source != source


def test_copied_parent_item_cannot_acquire_a_consumer_human_correction_registration(tmp_path):
    from trade_plan_monitor.ai.loop_plan_extraction import LoopPlanExtractionResult
    from trade_plan_monitor.backtest.preparation_human_authority import register_human_correction
    from trade_plan_monitor.backtest.preparation_models import CollectionPreparationCandidate
    from trade_plan_monitor.backtest.preparation_review import correct_collection_candidate
    from trade_plan_monitor.backtest.preparation_store import _request_hash

    store = PreparationStore(tmp_path / "copied-ci.sqlite3", clock=lambda: _NOW)
    child = _child(store, _root(store))
    copied = child.items[0]
    original = LoopPlanExtractionResult.model_validate_json(copied.candidate.payload_json)
    command = CollectionItemCorrectionCommand(expected_revision=child.revision,
        binding=collection_item_binding(copied), confirmed=True, draft=original.draft,
        mapping=original.daily_mapping, evidence="Attempt to re-register copied parent policy.")
    before = _snapshot(store)
    with pytest.raises(PreparationConflictError, match="REVIEWED_PLAN_IMMUTABLE"):
        store.correct_collection_item(child.preparation_id, command=command,
                                       idempotency_key="public-copied-ci")
    _, reviewed = correct_collection_candidate(child, command)
    candidate = CollectionPreparationCandidate(
        **reviewed.to_preparation_candidate().model_dump(mode="python"),
        source_revision=copied.source_revision, source_hash=copied.source.binding_hash,
        base_hash=copied.base_hash)
    proposed = child.model_copy(update={"revision": child.revision + 1,
        "items": (copied.model_copy(update={"candidate": candidate,
            "candidate_revision": copied.candidate_revision + 1}), child.items[-1])})
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_REQUIRED"):
            register_human_correction(connection, child, proposed, command, command_id="copied-ci",
                command_request_hash=_request_hash("CORRECT_ITEM", child.preparation_id, command),
                now=_NOW)
    assert _snapshot(store) == before


def test_composition_immutable_but_original_frozen_and_idempotent_replay_stay_readable(tmp_path):
    store = PreparationStore(tmp_path / "composed-tamper.sqlite3", clock=lambda: _NOW)
    first, second = _root(store), _root(store, "second", 20)
    command = PreparedPlanCompositionInput(preparation_id="composed",
        plans=(_reference(first), _reference(second)))
    composed = compose_reviewed_plans(store, command, idempotency_key="compose-roots")
    before = frozen_preparation(composed).model_dump_json()
    changed = composed.model_copy(update={"updated_at": _NOW.replace(hour=11)})
    _overwrite(store, changed)
    assert frozen_preparation(changed).model_dump_json() == before
    with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_STALE"):
        _read(store, changed, reviewed=True)
    assert compose_reviewed_plans(store, command, idempotency_key="compose-roots") == composed


def test_descendant_read_rechecks_the_real_parent_current_review_command(tmp_path):
    store = PreparationStore(tmp_path / "parent-review.sqlite3", clock=lambda: _NOW)
    parent = _root(store)
    child = _child(store, parent)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("UPDATE backtest_preparation_idempotency SET request_hash=? "
            "WHERE idempotency_key=?", ("0" * 64, "review-" + parent.preparation_id))
    assert frozen_preparation(parent).manifest_hash == _reference(parent).manifest_hash
    with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_STALE"):
        _read(store, child, prefix=1)


def test_shared_ancestors_are_recomputed_once_in_the_same_context(tmp_path, monkeypatch):
    store = PreparationStore(tmp_path / "cached-ancestors.sqlite3", clock=lambda: _NOW)
    root = _root(store)
    child = _review(store, _finish_delta(store, _child(store, root)))
    grandchild = _review(store, _finish_delta(store,
        _child(store, child, "grandchild", 21, 600), 600))
    composed = compose_reviewed_plans(store, PreparedPlanCompositionInput(preparation_id="composed",
        plans=(_reference(grandchild), _reference(child), _reference(root))),
        idempotency_key="compose-chain")
    calls = []
    original = current._initial

    def observe_actual_initial(item, evidence):
        # A transparent observation still executes all real verification and SQL.
        calls.append(item.source.source_id)
        return original(item, evidence)

    monkeypatch.setattr(current, "_initial", observe_actual_initial)
    assert len(_read(store, composed, reviewed=True).proofs) == 3
    assert calls == [root.items[0].source.source_id]


def test_private_resolution_cache_cannot_move_verified_owners_to_another_connection(tmp_path):
    store = PreparationStore(tmp_path / "cache-connection.sqlite3", clock=lambda: _NOW)
    root = _root(store)
    context = authority.CurrentAssuranceContext()
    with closing(sqlite3.connect(store.database_path)) as first:
        assert current.require_current_reviewed_preparation(first, root, _context=context)
    with closing(sqlite3.connect(store.database_path)) as second:
        with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_STALE"):
            current.require_current_reviewed_preparation(second, root, _context=context)


@pytest.mark.parametrize("budget", ["depth", "nodes", "cycle"])
def test_owner_resolution_obeys_budgets_and_never_uses_partial_or_cyclic_cache(tmp_path, budget):
    store = PreparationStore(tmp_path / (budget + ".sqlite3"), clock=lambda: _NOW)
    root = _root(store)
    context = authority.CurrentAssuranceContext()
    if budget == "depth":
        context.active[:] = [f"active-{index}" for index in range(256)]
    elif budget == "nodes":
        context.nodes.update(f"resolved-{index}" for index in range(512))
    else:
        context.active.append(root.preparation_id)
    expected = "SOURCE_COVERAGE_INTEGRITY" if budget == "cycle" else (
        "SOURCE_COVERAGE_LIMIT_EXCEEDED")
    before = _snapshot(store)
    with closing(sqlite3.connect(store.database_path)) as connection:
        with pytest.raises(PreparationConflictError, match=expected):
            current.require_current_reviewed_preparation(connection, root, _context=context)
    assert not context.reviewed and _snapshot(store) == before


@pytest.mark.parametrize("damaged", ["document", "manifest", "manifest_schema"])
def test_actual_owner_stored_document_or_manifest_corruption_is_integrity(tmp_path, damaged):
    store = PreparationStore(tmp_path / (damaged + ".sqlite3"), clock=lambda: _NOW)
    parent = _root(store)
    child = _child(store, parent)
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        if damaged == "document":
            payload = "{broken document"
        else:
            payload = parent.model_dump(mode="json")
            payload["review"]["manifest_json"] = ("{broken manifest" if damaged == "manifest"
                else json.dumps({"schema_version": "unsupported-frozen-shape"}))
            payload = json.dumps(payload)
        connection.execute("UPDATE backtest_preparation SET document_json=? WHERE preparation_id=?",
                           (payload, parent.preparation_id))
    before = _snapshot(store)
    with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_INTEGRITY"):
        _read(store, child, prefix=1)
    assert _snapshot(store) == before


def test_owner_missing_frozen_review_remains_required_instead_of_corruption(tmp_path):
    store = PreparationStore(tmp_path / "missing-frozen.sqlite3", clock=lambda: _NOW)
    parent = _root(store)
    child = _child(store, parent)
    missing = parent.model_copy(update={"review": parent.review.model_copy(
        update={"manifest_json": None})})
    _overwrite(store, missing)
    with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_REQUIRED"):
        _read(store, child, prefix=1)


def test_old_composition_without_lineage_keeps_frozen_and_replay_but_not_current(tmp_path):
    store = PreparationStore(tmp_path / "historical-composition.sqlite3", clock=lambda: _NOW)
    root = _root(store)
    command = PreparedPlanCompositionInput(preparation_id="composed", plans=(_reference(root),))
    composed = compose_reviewed_plans(store, command, idempotency_key="compose-root")
    old_manifest = frozen_preparation(composed).model_dump_json()
    with closing(sqlite3.connect(store.database_path)) as connection, connection:
        connection.execute("DROP TRIGGER pma_preparation_assurance_delete")
        connection.execute("DELETE FROM backtest_preparation_assurance WHERE kind='LINEAGE'")
        connection.execute(ASSURANCE_TRIGGERS["pma_preparation_assurance_delete"])
    before = _snapshot(store)
    assert frozen_preparation(store.get(composed.preparation_id)).model_dump_json() == old_manifest
    assert compose_reviewed_plans(store, command, idempotency_key="compose-root") == composed
    with pytest.raises(PreparationConflictError, match="SOURCE_COVERAGE_REQUIRED"):
        _read(store, composed, reviewed=True)
    assert _snapshot(store) == before
