"""ML-T12 owns preparation resources on demand and serves one bounded HTTP workflow."""

import asyncio
import time
from threading import Event

import pytest
from tests.integration.test_backtest_single_task import request

from trade_plan_monitor.backtest.composition import create_backtest_composition_factory
from trade_plan_monitor.backtest.jobs import BacktestJobRepository, JobAdmissionError
from trade_plan_monitor.backtest.preparation_models import (
    PreparationSource,
    SinglePlanPreparationInput,
)
from trade_plan_monitor.backtest.preparation_service import PreparationService
from trade_plan_monitor.backtest.preparation_store import PreparationStore
from trade_plan_monitor.backtest.preparation_worker import PreparationExtractor
from trade_plan_monitor.backtest.service_lifecycle import BacktestServiceUnavailable

BASE = "/api/v1/backtest-preparations"
ORIGIN = "http://127.0.0.1:8765"


def api_app(tmp_path, *, ai=None, preparation_path=None):
    from tests.integration.test_backtest_startup_isolation import Runtime

    from trade_plan_monitor.web.app import create_app

    runtime = Runtime()
    factory = create_backtest_composition_factory(
        config_path=tmp_path / "unused.yaml",
        plan_snapshot_reader=None,
        market_database=tmp_path / "market.sqlite3",
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
        preparation_database=preparation_path or tmp_path / "preparation.sqlite3",
    )
    app = create_app(
        runtime_factory=lambda: runtime,
        backtest_lifecycle_factory=factory,
        ai_lifecycle_factory=(lambda: ai) if ai is not None else None,
    )
    return app, runtime


def command():
    return SinglePlanPreparationInput(
        preparation_id="one",
        sources=(PreparationSource(source_id="source-one", text="One supplied original source."),),
    )


def forbidden_ai(*args):
    pytest.fail("Metadata operations must not call AI")


@pytest.mark.parametrize("kind", ["RUN", "SYNC", "VERIFY"])
def test_create_obeys_global_admission_without_a_preparation_record(tmp_path, kind):
    store = PreparationStore(tmp_path / "preparation.sqlite3")
    jobs = BacktestJobRepository(tmp_path / "results.sqlite3")
    jobs.submit(request(kind), "existing", request_id="1" * 32)

    async def scenario():
        service = PreparationService(store, jobs, PreparationExtractor(forbidden_ai))
        try:
            with pytest.raises(JobAdmissionError) as busy:
                await service.create(command(), idempotency_key="create")
            assert busy.value.code == "BACKTEST_BUSY"
            assert store.get("one") is None
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_create_receipt_replays_after_source_edit_while_global_slot_is_busy(tmp_path):
    store = PreparationStore(tmp_path / "preparation.sqlite3")
    jobs = BacktestJobRepository(tmp_path / "results.sqlite3")

    async def scenario():
        service = PreparationService(store, jobs, PreparationExtractor(forbidden_ai))
        try:
            original = await service.create(command(), idempotency_key="create")
            changed = await service.edit_source(
                "one",
                source=original.source.model_copy(update={"text": "Explicit source correction."}),
                expected_revision=original.revision,
                idempotency_key="edit",
            )
            jobs.submit(request("VERIFY"), "existing")
            assert await service.create(command(), idempotency_key="create") == original
            assert store.get("one") == changed
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_preparation_store_is_owned_only_after_explicit_capability_use(tmp_path):
    preparation_path = tmp_path / "preparation.sqlite3"
    factory = create_backtest_composition_factory(
        config_path=tmp_path / "unused.yaml",
        plan_snapshot_reader=None,
        market_database=tmp_path / "market.sqlite3",
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
        preparation_database=preparation_path,
    )
    assert not preparation_path.exists()
    composition = factory()
    assert not preparation_path.exists()

    async def scenario():
        try:
            service = await composition.ensure_preparations()
            assert preparation_path.exists()
            initial = await service.create(command(), idempotency_key="create")
            with pytest.raises(BacktestServiceUnavailable):
                await service.submit_extraction(
                    "one", expected_revision=initial.revision, idempotency_key="extract"
                )
            assert await service.get("one") == initial
            assert not composition._started and composition.authorized_job_ids == frozenset()
        finally:
            await composition.stop()
        assert service.outstanding_work == 0 and composition.outstanding_work == 0

    asyncio.run(scenario())


def test_unused_preparation_capability_is_not_acquired_for_shutdown(tmp_path):
    preparation_path = tmp_path / "preparation.sqlite3"
    composition = create_backtest_composition_factory(
        config_path=tmp_path / "unused.yaml",
        plan_snapshot_reader=None,
        market_database=tmp_path / "market.sqlite3",
        results_database=tmp_path / "results.sqlite3",
        cursor_key_path=tmp_path / "cursor.key",
        preparation_database=preparation_path,
    )()
    asyncio.run(composition.stop())
    assert not preparation_path.exists() and composition.outstanding_work == 0


def test_http_create_read_edit_and_original_receipt(tmp_path):
    from fastapi.testclient import TestClient

    app, runtime = api_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        body = {"input": command().model_dump(mode="json")}
        created = client.post(BASE, json=body, headers={"Idempotency-Key": "create"})
        assert created.status_code == 201
        original = created.json()
        assert original["preparationId"] == "one" and original["status"] == "DRAFT"
        assert created.headers["Location"] == BASE + "/one"
        assert client.get(BASE + "/one").json() == original
        source = {**body["input"]["sources"][0], "text": "An explicit correction."}
        edited = client.put(
            BASE + "/one/source",
            json={"expectedRevision": 1, "source": source},
            headers={"Idempotency-Key": "edit"},
        )
        assert edited.status_code == 200 and edited.json()["sourceRevision"] == 2
        assert (
            client.post(BASE, json=body, headers={"Idempotency-Key": "create"}).json() == original
        )
        assert client.get(BASE + "/one").json() == edited.json()
        assert not runtime.stopped
    assert runtime.stopped


@pytest.mark.parametrize("case", ["empty", "second", "duplicate", "extra", "no-key"])
def test_invalid_create_never_acquires_backtest_resources(tmp_path, case):
    from fastapi.testclient import TestClient

    app, runtime = api_app(tmp_path)
    body = {"input": command().model_dump(mode="json")}
    if case == "empty":
        body["input"]["sources"] = []
    if case in {"second", "duplicate"}:
        second = dict(body["input"]["sources"][0])
        if case == "second":
            second["source_id"] = "source-two"
        body["input"]["sources"].append(second)
    if case == "extra":
        body["approved"] = True
    headers = {} if case == "no-key" else {"Idempotency-Key": "create"}
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.post(BASE, json=body, headers=headers).status_code == 422
        assert app.state.backtest_lifecycle.snapshot.state.value == "NOT_INITIALIZED"
        assert not any(tmp_path.iterdir())
        assert not runtime.stopped


def test_unconfigured_extraction_returns_scoped_error_without_attempt(tmp_path):
    from fastapi.testclient import TestClient

    app, runtime = api_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        original = client.post(
            BASE,
            json={"input": command().model_dump(mode="json")},
            headers={"Idempotency-Key": "create"},
        ).json()
        response = client.post(
            BASE + "/one/extractions",
            json={"expectedRevision": 1},
            headers={"Idempotency-Key": "extract"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert client.get(BASE + "/one").json() == original and not runtime.stopped


class FakeAI:
    def __init__(self, *, blocked=False, unknown=False):
        self.entered, self.release = Event(), Event()
        self.calls, self.captures = [], 0
        self.unknown = unknown
        self.stopped = False
        if not blocked:
            self.release.set()

    @property
    def ai_operation_service(self):
        return self

    @property
    def plan_extraction_service(self):
        return self

    async def start(self):
        return {"configured": True}

    async def stop(self):
        self.stopped = True

    def backtest_extractor(self):
        self.captures += 1
        return PreparationExtractor(self.call)

    def call(self, identity, source, token):
        from tests.unit.test_monitor_loop_extraction import CASES, extract, output_for

        self.calls.append(identity)
        self.entered.set()
        assert self.release.wait(5)
        if self.unknown:
            return None
        result = extract(
            output_for({**CASES[0], "source": source.text}),
            source.text,
            authored_at=source.authored_at,
            available_at=source.available_at,
            effective_trade_date=source.effective_trade_date,
        )
        return result.model_copy(update={"request_id": identity})


def extracted_body():
    from tests.integration.test_plan_preparation_review import AVAILABLE
    from tests.unit.test_monitor_loop_extraction import CASES

    source = PreparationSource(
        source_id="source-1",
        text=CASES[0]["source"].split("参考行情", 1)[0],
        authored_at=AVAILABLE,
        available_at=AVAILABLE,
        effective_trade_date=AVAILABLE.date(),
    )
    return {
        "input": SinglePlanPreparationInput(preparation_id="one", sources=(source,)).model_dump(
            mode="json"
        )
    }


_ANY_PHASE = object()


def wait_view(client, status=None, phase=_ANY_PHASE):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(BASE + "/one")
        if response.status_code == 200:
            value = response.json()
            if (status is None or value["status"] == status) and (
                phase is _ANY_PHASE or value["workPhase"] == phase
            ):
                return value
        time.sleep(0.01)
    pytest.fail("Preparation did not reach the expected durable state")


def test_fake_ai_http_progress_explicit_freeze_source_edit_and_review_replay(tmp_path):
    from fastapi.testclient import TestClient
    from tests.integration.test_plan_preparation_review import review_command

    ai = FakeAI()
    app, _ = api_app(tmp_path, ai=ai)
    with TestClient(app, base_url=ORIGIN) as client:
        created = client.post(BASE, json=extracted_body(), headers={"Idempotency-Key": "create"})
        assert created.status_code == 201
        assert ai.calls == [] and ai.captures == 0
        extracted = client.post(
            BASE + "/one/extractions",
            json={"expectedRevision": 1},
            headers={"Idempotency-Key": "extract"},
        )
        assert extracted.status_code == 202 and extracted.headers["Retry-After"] == "2"
        assert extracted.headers["Location"] == BASE + "/one"
        ready = wait_view(client, status="CANDIDATE", phase=None)
        assert ready["candidate"]["kind"] == "EXTRACTION"
        assert ready["candidate"]["openingAccount"]["cash_fen"] is None
        assert "owner_id" not in str(ready) and "diagnostic" not in str(ready)
        record = PreparationStore(tmp_path / "preparation.sqlite3").get("one")
        declaration = {"review": review_command(record).model_dump(mode="json")}
        reviewed = client.post(
            BASE + "/one/reviews", json=declaration, headers={"Idempotency-Key": "review"}
        )
        assert reviewed.status_code == 200
        frozen = reviewed.json()
        current = client.get(BASE + "/one").json()
        assert current["candidate"]["kind"] == "FROZEN"
        source = {**current["source"], "text": current["source"]["text"] + "更正。"}
        corrected = client.put(
            BASE + "/one/source",
            json={"expectedRevision": current["revision"], "source": source},
            headers={"Idempotency-Key": "edit"},
        )
        assert corrected.status_code == 200 and corrected.json()["candidate"] is None
        assert (
            client.post(
                BASE + "/one/reviews", json=declaration, headers={"Idempotency-Key": "review"}
            ).json()
            == frozen
        )
        assert (
            client.post(
                BASE + "/one/extractions",
                json={"expectedRevision": 1},
                headers={"Idempotency-Key": "extract"},
            ).json()
            == extracted.json()
        )
        assert len(ai.calls) == 1 and ai.captures == 1
        assert not app.state.backtest_lifecycle._instance._started
    assert ai.stopped


@pytest.mark.parametrize("operation", ["edit", "cancel"])
def test_http_mutation_original_receipt_replays_while_other_job_holds_slot(tmp_path, operation):
    from fastapi.testclient import TestClient

    app, _ = api_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        created = client.post(
            BASE,
            json={"input": command().model_dump(mode="json")},
            headers={"Idempotency-Key": "create"},
        ).json()
        body = {"expectedRevision": created["revision"]}
        method, path = client.post, BASE + "/one/cancellations"
        if operation == "edit":
            body["source"] = {**created["source"], "text": "Explicit correction."}
            method, path = client.put, BASE + "/one/source"
        receipt = method(path, json=body, headers={"Idempotency-Key": "mutation"})
        assert receipt.status_code == 200
        jobs = BacktestJobRepository(tmp_path / "results.sqlite3")
        jobs.submit(request("VERIFY"), "other-job")
        replay = method(path, json=body, headers={"Idempotency-Key": "mutation"})
        assert replay.status_code == 200 and replay.json() == receipt.json()
        assert client.get(BASE + "/one").json() == receipt.json()
        assert len(jobs.list_jobs()) == 1


def test_global_busy_rejects_extraction_before_capturing_ai_configuration(tmp_path):
    from fastapi.testclient import TestClient

    ai = FakeAI()
    app, _ = api_app(tmp_path, ai=ai)
    with TestClient(app, base_url=ORIGIN) as client:
        client.post(BASE, json=extracted_body(), headers={"Idempotency-Key": "create"})
        BacktestJobRepository(tmp_path / "results.sqlite3").submit(request("RUN"), "run")
        result = client.post(
            BASE + "/one/extractions",
            json={"expectedRevision": 1},
            headers={"Idempotency-Key": "extract"},
        )
        assert result.status_code == 409
        assert ai.captures == 0 and ai.calls == []
        assert client.get(BASE + "/one").json()["attempts"] == []


def test_malformed_preparation_json_is_rejected_before_resource_acquisition(tmp_path):
    from fastapi.testclient import TestClient

    app, _ = api_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        result = client.post(
            BASE,
            content="{",
            headers={"Content-Type": "application/json", "Idempotency-Key": "create"},
        )
        assert result.status_code == 422
        assert app.state.backtest_lifecycle.snapshot.state.value == "NOT_INITIALIZED"
        assert not any(tmp_path.iterdir())


@pytest.mark.parametrize("operation", ["cancel", "edit"])
def test_http_cancellation_and_source_edit_keep_admission_until_physical_end(tmp_path, operation):
    from fastapi.testclient import TestClient

    ai = FakeAI(blocked=True)
    app, _ = api_app(tmp_path, ai=ai)
    with TestClient(app, base_url=ORIGIN) as client:
        try:
            client.post(BASE, json=extracted_body(), headers={"Idempotency-Key": "create"})
            initial = client.post(
                BASE + "/one/extractions",
                json={"expectedRevision": 1},
                headers={"Idempotency-Key": "extract"},
            )
            assert initial.status_code == 202 and ai.entered.wait(2)
            current = wait_view(client, phase="CALLING")
            body = {"expectedRevision": current["revision"]}
            path, method = BASE + "/one/cancellations", client.post
            if operation == "edit":
                body["source"] = {**current["source"], "text": current["source"]["text"] + "更正。"}
                path, method = BASE + "/one/source", client.put
            pending = method(path, json=body, headers={"Idempotency-Key": "mutation"})
            assert pending.status_code == (202 if operation == "cancel" else 200)
            assert pending.json()["status"] == "CANCEL_REQUESTED"
            assert (
                client.post(
                    BASE + "/one/recoveries",
                    json={
                        "expectedRevision": pending.json()["revision"],
                        "generation": current["generation"],
                        "confirmedEnded": True,
                    },
                    headers={"Idempotency-Key": "recover"},
                ).status_code
                == 409
            )
            other = extracted_body()
            other["input"]["preparation_id"] = "other"
            assert (
                client.post(BASE, json=other, headers={"Idempotency-Key": "other"}).status_code
                == 409
            )
            jobs = BacktestJobRepository(tmp_path / "results.sqlite3")
            for kind in ("RUN", "SYNC", "VERIFY"):
                with pytest.raises(JobAdmissionError):
                    jobs.submit(request(kind), kind, request_id="1" * 32)
            assert len(ai.calls) == 1 and ai.captures == 1
        finally:
            ai.release.set()
        ended = wait_view(
            client, status="CANCELLED" if operation == "cancel" else "DRAFT", phase=None
        )
        assert ended["candidate"] is None
        assert ended["sourceEditPending"] is False
        assert (
            method(path, json=body, headers={"Idempotency-Key": "mutation"}).json()
            == pending.json()
        )
        assert client.get(BASE + "/one").json() == ended
        assert jobs.submit(request("VERIFY"), "after-end").job_id
        manager = app.state.backtest_lifecycle
    assert ai.stopped and manager.snapshot.outstanding_work == 0


def test_unknown_http_outcome_survives_restart_and_requires_explicit_recovery(tmp_path):
    from fastapi.testclient import TestClient

    ai = FakeAI(unknown=True)
    app, _ = api_app(tmp_path, ai=ai)
    with TestClient(app, base_url=ORIGIN) as client:
        client.post(BASE, json=extracted_body(), headers={"Idempotency-Key": "create"})
        receipt = client.post(
            BASE + "/one/extractions",
            json={"expectedRevision": 1},
            headers={"Idempotency-Key": "extract"},
        ).json()
        unknown = wait_view(client, phase="UNKNOWN")
        assert unknown["status"] == "EXTRACTING"
        with pytest.raises(JobAdmissionError):
            BacktestJobRepository(tmp_path / "results.sqlite3").submit(request("VERIFY"), "busy")
    fresh_ai = FakeAI()
    restarted, _ = api_app(tmp_path, ai=fresh_ai)
    with TestClient(restarted, base_url=ORIGIN) as client:
        assert client.get(BASE + "/one").json() == unknown
        assert (
            client.post(
                BASE + "/one/extractions",
                json={"expectedRevision": 1},
                headers={"Idempotency-Key": "extract"},
            ).json()
            == receipt
        )
        recovery = {
            "expectedRevision": unknown["revision"],
            "generation": unknown["generation"],
            "confirmedEnded": True,
        }
        for invalid in (False, 1, "true"):
            assert (
                client.post(
                    BASE + "/one/recoveries",
                    json={**recovery, "confirmedEnded": invalid},
                    headers={"Idempotency-Key": "recover"},
                ).status_code
                == 422
            )
        stale = {**recovery, "generation": "other-generation"}
        assert (
            client.post(
                BASE + "/one/recoveries", json=stale, headers={"Idempotency-Key": "recover"}
            ).status_code
            == 409
        )
        recovered = client.post(
            BASE + "/one/recoveries", json=recovery, headers={"Idempotency-Key": "recover"}
        )
        assert recovered.status_code == 200 and recovered.json()["status"] == "FAILED"
        latest = wait_view(client, status="FAILED", phase=None)
        assert latest["attempts"][-1]["error_code"] == "UNKNOWN_PROVIDER_OUTCOME"
        assert (
            client.post(
                BASE + "/one/recoveries", json=recovery, headers={"Idempotency-Key": "recover"}
            ).json()
            == recovered.json()
        )
        assert fresh_ai.calls == [] and fresh_ai.captures == 0
        client.post(
            BASE + "/one/extractions",
            json={"expectedRevision": latest["revision"]},
            headers={"Idempotency-Key": "explicit-retry"},
        )
        ready = wait_view(client, status="CANDIDATE", phase=None)
        assert len(ready["attempts"]) == 2 and len(fresh_ai.calls) == 1 and fresh_ai.captures == 1


def test_frozen_http_manifest_and_original_review_receipt_survive_restart(tmp_path):
    from fastapi.testclient import TestClient
    from tests.integration.test_plan_preparation_review import review_command

    ai = FakeAI()
    app, _ = api_app(tmp_path, ai=ai)
    with TestClient(app, base_url=ORIGIN) as client:
        client.post(BASE, json=extracted_body(), headers={"Idempotency-Key": "create"})
        client.post(
            BASE + "/one/extractions",
            json={"expectedRevision": 1},
            headers={"Idempotency-Key": "extract"},
        )
        wait_view(client, status="CANDIDATE", phase=None)
        record = PreparationStore(tmp_path / "preparation.sqlite3").get("one")
        body = {"review": review_command(record).model_dump(mode="json")}
        frozen = client.post(
            BASE + "/one/reviews", json=body, headers={"Idempotency-Key": "review"}
        ).json()
        current = client.get(BASE + "/one").json()
    restarted_ai = FakeAI()
    restarted, _ = api_app(tmp_path, ai=restarted_ai)
    with TestClient(restarted, base_url=ORIGIN) as client:
        assert client.get(BASE + "/one").json() == current
        assert (
            client.post(
                BASE + "/one/reviews", json=body, headers={"Idempotency-Key": "review"}
            ).json()
            == frozen
        )
        assert restarted_ai.calls == [] and restarted_ai.captures == 0
        assert not restarted.state.backtest_lifecycle._instance._started
