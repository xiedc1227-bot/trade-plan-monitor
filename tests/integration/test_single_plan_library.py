"""One editable source, immutable approved dependencies and server-side composition."""

from datetime import timedelta

import pytest
from tests.integration.test_plan_preparation_review import (
    collection_review_command,
    ready_collection,
)

from trade_plan_monitor.backtest.preparation_models import (
    PreparedPlanCompositionInput,
    ReviewedPlanReference,
    SingleSourcePreparationInput,
)
from trade_plan_monitor.backtest.preparation_review import frozen_preparation
from trade_plan_monitor.backtest.preparation_store import PreparationConflictError


def approved_single(tmp_path):
    store, ready = ready_collection(tmp_path)
    ready = store._operation(
        "TEST_SINGLE",
        ready.preparation_id,
        {},
        "test-single",
        lambda previous, now: previous.model_copy(
            update={"workflow": "SINGLE", "items": previous.items[:1], "status": "CANDIDATE"}
        ),
    )
    approved = store.review_and_freeze(
        ready.preparation_id,
        command=collection_review_command(ready),
        idempotency_key="approve-single",
    )
    frozen = frozen_preparation(approved)
    ref = ReviewedPlanReference(
        preparation_id=approved.preparation_id, manifest_hash=frozen.manifest_hash
    )
    return store, approved, ref


def test_single_create_and_approved_prefix_are_immutable(tmp_path):
    from trade_plan_monitor.backtest.plan_library import (
        create_single_preparation,
        list_reviewed_plans,
    )

    store, approved, ref = approved_single(tmp_path)
    source = approved.items[0].source.model_copy(
        update={
            "source_id": "next",
            "effective_trade_date": approved.items[0].source.effective_trade_date
            + timedelta(days=1),
        }
    )
    command = SingleSourcePreparationInput(
        preparation_id="next-plan", source=source, reviewed_base=ref
    )
    created = create_single_preparation(store, command, idempotency_key="new-single")
    assert created.items[:-1] == approved.items
    assert created.items[-1].status == "DRAFT"
    assert create_single_preparation(store, command, idempotency_key="new-single") == created
    assert list_reviewed_plans(store, offset=0, limit=20)["total"] == 1
    for record, edited in (
        (approved, approved.items[0].source),
        (created, created.items[0].source),
    ):
        with pytest.raises(PreparationConflictError, match="REVIEWED_PLAN_IMMUTABLE"):
            store.edit_collection(
                record.preparation_id,
                expected_revision=record.revision,
                source=edited,
                idempotency_key="edit-" + record.preparation_id,
            )


def test_rejects_unreviewed_and_stale_base_before_creation(tmp_path):
    from trade_plan_monitor.backtest.plan_library import create_single_preparation

    store, record = ready_collection(tmp_path)
    with pytest.raises(PreparationConflictError, match="REVIEWED_BASE_REQUIRED"):
        create_single_preparation(
            store,
            SingleSourcePreparationInput(
                preparation_id="new",
                source=record.items[1].source,
                reviewed_base=ReviewedPlanReference(
                    preparation_id=record.preparation_id, manifest_hash="0" * 64
                ),
            ),
            idempotency_key="bad-base",
        )
    assert store.get("new") is None


def test_historical_read_is_not_authority_to_reuse_an_outdated_review(tmp_path, monkeypatch):
    from trade_plan_monitor.backtest import preparation_worker
    from trade_plan_monitor.backtest.plan_library import list_reviewed_plans, reviewed_entry

    store, approved, ref = approved_single(tmp_path)
    original = preparation_worker.preparation_candidate_review

    def current_scope_recheck(record, index, *, historical=False):
        if not historical:
            raise ValueError("stored successor differs from its source/base binding")
        return original(record, index, historical=historical)

    monkeypatch.setattr(preparation_worker, 'preparation_candidate_review', current_scope_recheck)
    assert frozen_preparation(approved).manifest_hash == ref.manifest_hash
    assert list_reviewed_plans(store, offset=0, limit=20)['total'] == 1
    with pytest.raises(PreparationConflictError, match='REVIEWED_RISK_SCOPE_RECHECK_REQUIRED'):
        reviewed_entry(store, ref)
    assert store.get(approved.preparation_id) == approved


def test_unreviewed_candidate_cannot_opt_into_historical_validation(tmp_path):
    from trade_plan_monitor.backtest.preparation_worker import preparation_candidate_review

    _store, ready = ready_collection(tmp_path)
    with pytest.raises(ValueError, match='already frozen review'):
        preparation_candidate_review(ready, 0, historical=True)


def test_update_can_save_unknown_date_but_rejects_duplicate_source_or_earlier_date(tmp_path):
    from trade_plan_monitor.backtest.plan_library import create_single_preparation

    store, approved, ref = approved_single(tmp_path)
    source = approved.items[0].source.model_copy(
        update={
            "source_id": "new-date",
            "effective_trade_date": None,
        }
    )
    command = SingleSourcePreparationInput(
        preparation_id="undated", source=source, reviewed_base=ref
    )
    saved = create_single_preparation(store, command, idempotency_key="undated")
    assert saved.items[-1].source.effective_trade_date is None
    assert saved.items[:-1] == approved.items
    for name, updated, code in (
        (
            "duplicate",
            source.model_copy(update={"source_id": approved.items[0].source.source_id}),
            "SOURCE_ID_CONFLICT",
        ),
        (
            "date",
            source.model_copy(
                update={
                    "effective_trade_date": approved.items[0].source.effective_trade_date,
                }
            ),
            "SOURCE_DATE_CONFLICT",
        ),
    ):
        with pytest.raises(PreparationConflictError, match=code):
            create_single_preparation(
                store,
                command.model_copy(
                    update={
                        "preparation_id": name,
                        "source": updated,
                    }
                ),
                idempotency_key=name,
            )
        assert store.get(name) is None


def test_composition_uses_exact_reviewed_version_and_original_account(tmp_path):
    from trade_plan_monitor.backtest.plan_library import compose_reviewed_plans

    store, approved, ref = approved_single(tmp_path)
    command = PreparedPlanCompositionInput(preparation_id="combined", plans=(ref,))
    combined = compose_reviewed_plans(store, command, idempotency_key="combine")
    frozen = frozen_preparation(combined)
    original = frozen_preparation(approved)
    assert frozen.account == original.account
    assert frozen.schedule == original.schedule
    assert combined.workflow == "COMPOSITION"
    assert compose_reviewed_plans(store, command, idempotency_key="combine") == combined
    with pytest.raises(PreparationConflictError, match="REVIEWED_BASE_CHANGED"):
        compose_reviewed_plans(
            store,
            PreparedPlanCompositionInput(
                preparation_id="stale", plans=(ref.model_copy(update={"manifest_hash": "0" * 64}),)
            ),
            idempotency_key="stale",
        )


def test_library_http_preserves_single_source_and_rejects_unreviewed_predecessor(tmp_path):
    from fastapi.testclient import TestClient
    from tests.integration.test_plan_preparation_api import ORIGIN, api_app

    app, _ = api_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        body = {
            "preparation_id": "single-http",
            "source": {"source_id": "one", "text": "生效交易日：2026-09-24。等待。"},
        }
        response = client.post(
            "/api/v1/backtest-plan-library/preparations",
            json=body,
            headers={"Idempotency-Key": "single-create"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["workflow"] == "SINGLE"
        assert response.json()["itemCount"] == 1
        assert response.json()["editableSourceId"] == "one"
        assert response.json()["items"][0]["effectiveTradeDate"] == "2026-09-24"
        assert (
            client.post(
                "/api/v1/backtest-plan-library/preparations",
                json=body,
                headers={"Idempotency-Key": "single-create"},
            ).json()
            == response.json()
        )
        assert client.get("/api/v1/backtest-plan-library?offset=0&limit=100").json()["items"] == []
        bad = client.post(
            "/api/v1/backtest-plan-library/preparations",
            json={
                **body,
                "preparation_id": "dependent",
                "reviewed_base": {"preparation_id": "single-http", "manifest_hash": "0" * 64},
            },
            headers={"Idempotency-Key": "unreviewed-base"},
        )
        assert bad.status_code == 409
        assert "REVIEWED_BASE_REQUIRED" in bad.text


def test_composition_of_independent_reviewed_plans_keeps_first_account(tmp_path):
    from tests.unit.test_daily_review import reviewed_mapping

    from trade_plan_monitor.ai.update_review import build_initial_review
    from trade_plan_monitor.backtest.plan_library import compose_reviewed_plans

    store, first, first_ref = approved_single(tmp_path)
    source = first.items[0].source.model_copy(
        update={
            "source_id": "independent",
            "effective_trade_date": first.items[0].source.effective_trade_date + timedelta(days=1),
        }
    )
    item = first.items[0]
    reviewed = build_initial_review(
        frozen_preparation(first).items[0].mapping.draft,
        reviewed_mapping(frozen_preparation(first).items[0].mapping.draft, source.text),
        source,
    )
    candidate = item.candidate.model_copy(
        update={
            **reviewed.to_preparation_candidate().model_dump(),
            "source_hash": source.binding_hash,
        }
    )
    new_item = item.model_copy(
        update={
            "independent": True,
            "source": source,
            "candidate": candidate,
            "attempts": tuple(
                a.model_copy(update={"source_hash": source.binding_hash}) for a in item.attempts
            ),
        }
    )
    second = store._operation(
        "TEST_FULL",
        "second",
        {},
        "make-second",
        lambda old, now: first.model_copy(
            update={
                "preparation_id": "second",
                "revision": 1,
                "status": "CANDIDATE",
                "items": (new_item,),
                "review": None,
                "review_revision": 0,
            }
        ),
    )
    second = store.review_and_freeze(
        "second", command=collection_review_command(second), idempotency_key="approve-second"
    )
    second_ref = ReviewedPlanReference(
        preparation_id="second", manifest_hash=frozen_preparation(second).manifest_hash
    )
    combined = compose_reviewed_plans(
        store,
        PreparedPlanCompositionInput(preparation_id="both", plans=(second_ref, first_ref)),
        idempotency_key="both",
    )
    frozen = frozen_preparation(combined)
    assert [item.source.source_id for item in frozen.items] == ["first", "independent"]
    assert frozen.account == frozen_preparation(first).account
    assert frozen.items[1].base_hash is None


def test_four_single_preparations_link_exact_reviewed_versions_and_compose(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from tests.integration.test_monitor_loop_production_composition import (
        ORIGIN,
        continuity_sources,
        environment,
        post,
        wait,
    )

    from trade_plan_monitor.backtest.preparation_store import PreparationStore

    app, ai, _, _ = environment(tmp_path, monkeypatch, mode="continuity")
    base = "/api/v1/backtest-preparations"
    library = "/api/v1/backtest-plan-library"
    references, frozen_entries = [], []
    with TestClient(app, base_url=ORIGIN) as client:
        for index, source in enumerate(continuity_sources()):
            identity = f"single-{index}"
            created = post(
                client,
                library + "/preparations",
                dict(
                    preparation_id=identity,
                    source=source,
                    reviewed_base=references[-1] if references else None,
                ),
                f"create-{index}",
            )
            assert created.status_code == 201, created.text
            value = created.json()
            assert value["editableSourceId"] == source["source_id"]
            assert (
                post(
                    client,
                    base + f"/{identity}/extractions",
                    dict(
                        schemaVersion="backtest-preparation-v2",
                        expectedRevision=value["revision"],
                        sourceId=source["source_id"],
                        expectedSourceRevision=1,
                        expectedBaseHash=value["items"][-2]["candidateHash"] if index else None,
                    ),
                    f"extract-{index}",
                ).status_code
                == 202
            )
            wait(
                client,
                base + "/" + identity,
                lambda v: v["status"] == "CANDIDATE" and v["workPhase"] is None,
            )
            store = PreparationStore(tmp_path / "preparation.sqlite3")
            record = store.get(identity)
            assert record.items[-1].candidate.validation == "VALID"
            reviewed = post(
                client,
                base + f"/{identity}/reviews",
                dict(
                    schemaVersion="backtest-preparation-v2",
                    kind="CHAIN_REVIEW",
                    review=collection_review_command(record, account=None).model_dump(mode="json"),
                ),
                f"review-{index}",
            )
            assert reviewed.status_code == 200, reviewed.text
            frozen = frozen_preparation(store.get(identity))
            if index:
                assert frozen.items[:-1] == frozen_entries[-1].items
                assert frozen.account == frozen_entries[0].account
            references.append(
                dict(preparation_id=identity, manifest_hash=reviewed.json()["manifestHash"])
            )
            frozen_entries.append(frozen)
        assert ai.source_calls == [0, 1, 2, 3]
        page = client.get(library + "?limit=100").json()
        assert page["total"] == 4 and len(page["items"]) == 4
        denied = post(
            client,
            library + "/compositions",
            dict(preparation_id="missing", plans=references[1:]),
            "missing",
        )
        assert denied.status_code == 409 and "PREDECESSOR_SELECTION_REQUIRED" in denied.text
        command = dict(preparation_id="composed", plans=list(reversed(references)))
        response = post(client, library + "/compositions", command, "combine")
        assert response.status_code == 201, response.text
        assert len(response.json()["versions"]) == 4
        assert post(client, library + "/compositions", command, "combine").json() == response.json()
        assert ai.source_calls == [0, 1, 2, 3]
        frozen = frozen_preparation(
            PreparationStore(tmp_path / "preparation.sqlite3").get("composed")
        )
        assert frozen.items == tuple(entry.items[-1] for entry in frozen_entries)
        assert frozen.account == frozen_entries[0].account
        # Changing an already-reviewed original is forbidden even after restart.
        with pytest.raises(PreparationConflictError, match="REVIEWED_PLAN_IMMUTABLE"):
            store.edit_collection(
                "single-0",
                expected_revision=store.get("single-0").revision,
                source=store.get("single-0").items[0].source,
                idempotency_key="mutate-reviewed",
            )
