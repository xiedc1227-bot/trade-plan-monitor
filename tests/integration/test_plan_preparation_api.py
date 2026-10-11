"""ML-T12 owns preparation resources on demand and serves one bounded HTTP workflow."""

import asyncio
import json
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


def api_app(tmp_path, *, ai=None, preparation_path=None, bind_port=8765):
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
        bind_port=bind_port,
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
        self.ended = Event()
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
        assert not self.entered.is_set() or self.ended.is_set()
        self.stopped = True

    def backtest_extractor(self):
        self.captures += 1
        return PreparationExtractor(self.call)

    def call(self, identity, source, token):
        from tests.unit.test_monitor_loop_extraction import CASES, extract, output_for

        self.calls.append(identity)
        self.entered.set()
        try:
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
        finally:
            self.ended.set()


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
            claim = PreparationStore(tmp_path / "preparation.sqlite3").get("one").work_claim
            for private in (claim.owner_id, claim.admission_key, claim.intent_json):
                assert private not in str(current)
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


@pytest.mark.parametrize(
    "case",
    [
        "path",
        "long-id",
        "query",
        "origin",
        "oversize",
        "revision-bool",
        "revision-string",
        "revision-zero",
        "revision-unsafe",
        "bad-time",
        "time-order",
        "review-empty",
        "source-too-long",
    ],
)
def test_preparation_boundary_rejections_do_not_acquire_resources(tmp_path, case):
    from fastapi.testclient import TestClient

    app, _ = api_app(tmp_path)
    method, path, body, expected = "POST", BASE + "/one/extractions", {"expectedRevision": 1}, 422
    headers = {"Idempotency-Key": "command"}
    if case in {"path", "long-id", "query"}:
        method, body = "GET", None
        path = (
            BASE
            + {"path": "/bad!", "long-id": "/" + "a" * 129, "query": "/one?source=second"}[case]
        )
    if case == "origin":
        headers["Origin"], expected = "https://untrusted.example", 403
    if case == "oversize":
        headers["Content-Length"], expected = str(4 * 1024 * 1024 + 1), 413
    if case.startswith("revision-"):
        body["expectedRevision"] = {
            "revision-bool": True,
            "revision-string": "1",
            "revision-zero": 0,
            "revision-unsafe": 9_007_199_254_740_992,
        }[case]
    if case in {"bad-time", "time-order", "source-too-long"}:
        method, path = "PUT", BASE + "/one/source"
        source = command().sources[0].model_dump(mode="json")
        if case == "bad-time":
            source["available_at"] = "2026-08-20T09:00:00"
        elif case == "time-order":
            source.update(
                authored_at="2026-08-21T09:00:00+08:00", available_at="2026-08-20T09:00:00+08:00"
            )
        else:
            source["text"] = "中" * 150001
        body["source"] = source
    if case == "review-empty":
        path, body = BASE + "/one/reviews", {"review": {}}
    with TestClient(app, base_url=ORIGIN) as client:
        result = client.request(method, path, json=body, headers=headers)
        assert result.status_code == expected
        assert app.state.backtest_lifecycle.snapshot.state.value == "NOT_INITIALIZED"
        assert not any(tmp_path.iterdir())


def test_maximum_source_is_bounded_and_private_claims_are_not_projected(tmp_path):
    from fastapi.testclient import TestClient

    app, _ = api_app(tmp_path)
    body = {"input": command().model_dump(mode="json")}
    body["input"]["sources"][0]["text"] = "中" * 150000
    with TestClient(app, base_url=ORIGIN) as client:
        result = client.post(BASE, json=body, headers={"Idempotency-Key": "create"})
        assert result.status_code == 201 and len(result.content) < 2 * 1024 * 1024
        assert result.json()["source"]["text"] == body["input"]["sources"][0]["text"]
        for private in ("work_claim", "owner_id", "admission_key", "intent_json", "payload_json"):
            assert private not in result.text


def test_preparation_store_failure_is_cached_without_blocking_monitor_or_job_reads(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    import trade_plan_monitor.backtest.composition as module

    path = tmp_path / "preparation.sqlite3"
    path.write_bytes(b"corrupt private preparation store")
    attempts = []
    original = module.PreparationStore

    def acquire(*args, **kwargs):
        attempts.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "PreparationStore", acquire)
    app, runtime = api_app(tmp_path)
    with TestClient(app, base_url=ORIGIN) as client:
        for _ in range(2):
            response = client.get(BASE + "/one")
            assert response.status_code == 503 and response.headers["Retry-After"] == "1"
            assert "preparation.sqlite3" not in response.text and "corrupt" not in response.text
        assert len(attempts) == 1 and runtime.started and not runtime.stopped
        assert client.get("/api/v1/backtest-jobs").status_code == 200
        path.write_bytes(b"")  # A controlled repair alone cannot restart failed acquisition.
        assert client.get(BASE + "/one").status_code == 503 and len(attempts) == 1
        capability = app.state.backtest_lifecycle._instance._preparations
        client.portal.call(capability.retry)
        assert client.get(BASE + "/one").status_code == 404 and len(attempts) == 2
        assert not app.state.backtest_lifecycle._instance._started


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "CANCEL_REQUESTED", "EXPIRED"])
@pytest.mark.parametrize("kind", ["RUN", "SYNC", "VERIFY"])
def test_http_new_preparation_mutations_reject_all_unfinished_job_states(tmp_path, state, kind):
    from datetime import datetime, timedelta

    from fastapi.testclient import TestClient
    from tests.integration.test_backtest_jobs import _SHANGHAI, _Clock
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
        current = wait_view(client, status="CANDIDATE", phase=None)
        record = PreparationStore(tmp_path / "preparation.sqlite3").get("one")
        declaration = {"review": review_command(record).model_dump(mode="json")}
        clock = _Clock(datetime(2026, 8, 28, 10, tzinfo=_SHANGHAI))
        jobs = BacktestJobRepository(tmp_path / "results.sqlite3", clock=clock)
        job = jobs.submit(request(kind), "other-job", request_id="1" * 32)
        if state != "QUEUED":
            jobs.claim_next()
        if state == "CANCEL_REQUESTED":
            jobs.request_cancel(job.job_id, "cancel-job")
        if state == "EXPIRED":
            clock.advance(timedelta(seconds=31))
        other = extracted_body()
        other["input"]["preparation_id"] = "other"
        edit = {
            "expectedRevision": current["revision"],
            "source": {**current["source"], "text": current["source"]["text"] + "\n"},
        }
        for method, route, body, key in (
            ("POST", BASE, other, "other"),
            ("PUT", BASE + "/one/source", edit, "edit"),
            ("POST", BASE + "/one/extractions", {"expectedRevision": current["revision"]}, "new"),
            ("POST", BASE + "/one/reviews", declaration, "review"),
            (
                "POST",
                BASE + "/one/cancellations",
                {"expectedRevision": current["revision"]},
                "cancel",
            ),
        ):
            response = client.request(method, route, json=body, headers={"Idempotency-Key": key})
            assert response.status_code == 409
            assert response.json()["error"]["details"][0]["code"] == "BACKTEST_BUSY"
        assert client.get(BASE + "/one").json() == current and ai.captures == 1
        assert len(ai.calls) == 1 and len(jobs.list_jobs()) == 1


def test_acquired_preparation_shutdown_owns_drain_after_inner_observation_timeouts(tmp_path):
    from threading import Timer

    from fastapi.testclient import TestClient

    from trade_plan_monitor.backtest.service_config import BacktestServiceConfig

    ai = FakeAI(blocked=True)
    app, runtime = api_app(tmp_path, ai=ai)
    timer = Timer(0.2, ai.release.set)
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            client.post(BASE, json=extracted_body(), headers={"Idempotency-Key": "create"})
            client.post(
                BASE + "/one/extractions",
                json={"expectedRevision": 1},
                headers={"Idempotency-Key": "extract"},
            )
            assert ai.entered.wait(2)
            manager = app.state.backtest_lifecycle
            nested = manager._instance._preparations
            service = nested._instance.read_service
            nested._config = service._config = BacktestServiceConfig(shutdown_wait_seconds=0.01)
            timer.start()
    finally:
        ai.release.set()
        timer.join(1)
    assert ai.ended.is_set() and ai.stopped and runtime.stopped
    assert manager.snapshot.outstanding_work == 0 and service.outstanding_work == 0
    assert PreparationStore(tmp_path / "preparation.sqlite3").get("one").status == "CANCELLED"


def test_loopback_http_cancel_edit_review_and_restart_journey(tmp_path):
    import socket
    from contextlib import contextmanager
    from threading import Thread

    import httpx
    import uvicorn
    from tests.integration.test_plan_preparation_review import review_command

    @contextmanager
    def serve(ai):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        app, runtime = api_app(tmp_path, ai=ai, bind_port=port)
        server = uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=port, log_config=None, access_log=False, ws="none"
            )
        )
        thread = Thread(target=lambda: server.run(sockets=[listener]), name="preparation-http-test")
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            with httpx.Client(
                base_url=origin, headers={"Origin": origin}, timeout=5, trust_env=False
            ) as client:
                yield client
        finally:
            ai.release.set()
            server.should_exit = True
            thread.join(5)
            listener.close()
            assert not thread.is_alive() and runtime.stopped and ai.stopped

    ai = FakeAI(blocked=True)
    with serve(ai) as client:
        assert (
            client.post(
                BASE, json=extracted_body(), headers={"Idempotency-Key": "create"}
            ).status_code
            == 201
        )
        assert (
            client.post(
                BASE + "/one/extractions",
                json={"expectedRevision": 1},
                headers={"Idempotency-Key": "extract"},
            ).status_code
            == 202
        )
        assert ai.entered.wait(2)
        calling = wait_view(client, phase="CALLING")
        cancelled = client.post(
            BASE + "/one/cancellations",
            json={"expectedRevision": calling["revision"]},
            headers={"Idempotency-Key": "cancel"},
        )
        assert cancelled.status_code == 202
        ai.release.set()
        ended = wait_view(client, status="CANCELLED", phase=None)
        edit = {
            "expectedRevision": ended["revision"],
            "source": {**ended["source"], "text": ended["source"]["text"] + "\n"},
        }
        changed = client.put(BASE + "/one/source", json=edit, headers={"Idempotency-Key": "edit"})
        assert changed.status_code == 200 and changed.json()["status"] == "DRAFT"
        assert (
            client.post(
                BASE + "/one/extractions",
                json={"expectedRevision": changed.json()["revision"]},
                headers={"Idempotency-Key": "new-extract"},
            ).status_code
            == 202
        )
        wait_view(client, status="CANDIDATE", phase=None)
        record = PreparationStore(tmp_path / "preparation.sqlite3").get("one")
        body = {"review": review_command(record).model_dump(mode="json")}
        review = client.post(
            BASE + "/one/reviews", json=body, headers={"Idempotency-Key": "review"}
        )
        assert review.status_code == 200
        frozen, reviewed = review.json(), client.get(BASE + "/one").json()
    restarted_ai = FakeAI()
    with serve(restarted_ai) as client:
        assert client.get(BASE + "/one").json() == reviewed
        assert (
            client.post(
                BASE + "/one/reviews", json=body, headers={"Idempotency-Key": "review"}
            ).json()
            == frozen
        )
        assert restarted_ai.captures == 0 and restarted_ai.calls == []


@pytest.mark.parametrize("legacy_review", [False, True])
def test_opaque_legacy_candidates_cannot_expose_raw_payload_or_frozen_authority(
    tmp_path, legacy_review
):
    from fastapi.testclient import TestClient
    from tests.integration.test_plan_preparation_review import review_command

    from trade_plan_monitor.backtest.preparation_models import PreparationCandidateInput

    store = PreparationStore(tmp_path / "preparation.sqlite3")
    created = store.create(
        SinglePlanPreparationInput.model_validate_json(json.dumps(extracted_body()["input"])),
        idempotency_key="create",
    )
    started = store.start_attempt(
        "one", expected_revision=created.revision, idempotency_key="extract"
    )
    record = store.finish_attempt(
        "one",
        expected_revision=started.revision,
        attempt_id=started.attempts[-1].attempt_id,
        idempotency_key="finish",
        candidate=PreparationCandidateInput(
            payload_json='{"private_provider_detail":"hidden-value"}',
            validation="VALID",
            evidence_hash="a" * 64,
        ),
    )
    if legacy_review:
        record = store.record_review(
            "one",
            expected_revision=record.revision,
            expected_source_revision=record.source_revision,
            expected_candidate_revision=record.candidate_revision,
            candidate_hash=record.candidate.candidate_hash,
            evidence_hash=record.candidate.evidence_hash,
            confirmed=True,
            idempotency_key="legacy-review",
        )
    ai = FakeAI()
    app, _ = api_app(tmp_path, ai=ai)
    with TestClient(app, base_url=ORIGIN) as client:
        result = client.get(BASE + "/one")
        assert result.status_code == 200 and "hidden-value" not in result.text
        assert result.json()["candidate"]["kind"] == "UNAVAILABLE"
        assert result.json()["candidate"]["frozen"] is None
        review = client.post(
            BASE + "/one/reviews",
            json={"review": review_command(record).model_dump(mode="json")},
            headers={"Idempotency-Key": "new-review"},
        )
        assert review.status_code == 409 and store.get("one") == record
        assert ai.captures == 0 and ai.calls == []


def test_collection_service_stops_after_unresolved_first_item_without_dispatching_future(tmp_path):
    from tests.integration.test_plan_preparation_worker import loop_extractor
    from tests.unit.test_monitor_loop_extraction import CASES

    from trade_plan_monitor.backtest.preparation_models import PlanCollectionPreparationInput

    store = PreparationStore(tmp_path / "preparation.sqlite3")
    jobs = BacktestJobRepository(tmp_path / "results.sqlite3")
    extractor, calls = loop_extractor()
    command = PlanCollectionPreparationInput(preparation_id="chain", sources=(
        PreparationSource(source_id="first", text=CASES[0]["source"]),
        PreparationSource(source_id="future", text="Future source must not reach this call."),
    ))

    async def scenario():
        service = PreparationService(store, jobs, extractor)
        try:
            initial = await service.create(command, idempotency_key="create-chain")
            submitted = await service.submit_extraction("chain", expected_revision=initial.revision,
                                                        idempotency_key="extract-chain")
            await service.wait_for_drain()
            ended = store.get("chain")
            assert len(calls) == 1
            assert ended.items[0].candidate.validation == "UNRESOLVED"
            assert ended.items[1].status == "WAITING" and not ended.items[1].attempts
            assert ended.work_claim is None and ended.review is None
            assert await service.submit_extraction("chain", expected_revision=initial.revision,
                                                   idempotency_key="extract-chain") == submitted
            assert len(calls) == 1
            assert jobs.submit(request("VERIFY"), "after-collection").job_id
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_collection_service_runs_successors_serially_under_one_reservation(tmp_path):
    from tests.integration.test_plan_preparation_worker import (
        collection_update_result,
        collection_worker_setup,
    )
    from tests.unit.test_monitor_loop_schedule import at
    from tests.unit.test_plan_update_bindings import current_update

    from trade_plan_monitor.ai.plan_update_extraction import PlanUpdateExtractionOutput

    third, third_output = current_update("仅修改最大仓位为400股，其余规则保留。")
    third = third.model_copy(update={"source_id": "third", "authored_at": at(21),
                                    "available_at": at(21), "effective_trade_date": at(21).date()})
    raw = third_output.model_dump(mode="json")
    raw["draft"]["position"]["max_qty"] = 400
    raw["bindings"][0]["value"] = 400
    third_output = PlanUpdateExtractionOutput.model_validate_json(json.dumps(raw))
    store, jobs, prepared, base, second_output = collection_worker_setup(
        tmp_path, future_source=third, start_successor=False,
    )
    calls, reservations = [], []

    def extract(identity, source, token, *, context):
        current = store.get(prepared.preparation_id)
        calls.append((source.source_id, context.snapshot.position.max_qty))
        reservations.append((current.work_claim.admission_key, current.work_claim.intent_hash))
        with pytest.raises(JobAdmissionError):
            jobs.submit(request("VERIFY"), "during-" + source.source_id)
        if source.source_id == "third":
            assert current.items[1].candidate.validation == "VALID"
            assert context.base_hash == current.items[1].candidate.candidate_hash
        return collection_update_result(
            base, source, second_output if source.source_id == "second" else third_output,
            identity, context,
        )

    async def scenario():
        service = PreparationService(store, jobs, PreparationExtractor(extract))
        try:
            submitted = await service.submit_extraction(
                prepared.preparation_id, expected_revision=prepared.revision,
                idempotency_key="resume-chain",
            )
            await service.wait_for_drain()
            ended = store.get(prepared.preparation_id)
            assert calls == [("second", 1000), ("third", 300)]
            assert len(set(reservations)) == 1
            assert ended.status == "CANDIDATE" and ended.review is None
            assert ended.work_claim is None
            assert [len(item.attempts) for item in ended.items] == [1, 1, 1]
            assert ended.items[0] == prepared.items[0]
            payload = json.loads(ended.items[2].candidate.payload_json)
            assert payload["review"]["draft"]["position"]["max_qty"] == 400
            assert await service.submit_extraction(
                prepared.preparation_id, expected_revision=prepared.revision,
                idempotency_key="resume-chain",
            ) == submitted
            assert len(calls) == 2
            assert jobs.submit(request("VERIFY"), "after-chain").job_id
        finally:
            await service.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["authored_at", "available_at", "effective_trade_date"])
def test_collection_creation_rejects_contradictory_known_source_order_before_persistence(
    tmp_path, field,
):
    from tests.unit.test_monitor_loop_schedule import at

    from trade_plan_monitor.backtest.preparation_models import PlanCollectionPreparationInput
    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store = PreparationStore(tmp_path / "chronology.sqlite3")
    jobs = BacktestJobRepository(tmp_path / "jobs.sqlite3")
    later = at(21).date() if field == "effective_trade_date" else at(21)
    earlier = at(20).date() if field == "effective_trade_date" else at(20)
    sources = tuple(PreparationSource(source_id=identity, text="Original source.", **{field: value})
                    for identity, value in (("first", later), ("second", earlier)))
    value = PlanCollectionPreparationInput(preparation_id="chronology", sources=sources)

    async def scenario():
        service = PreparationService(store, jobs, PreparationExtractor(forbidden_ai))
        try:
            with pytest.raises(PreparationConflictError, match="SOURCE_CHRONOLOGY_CONFLICT"):
                await service.create(value, idempotency_key="create-chronology")
            assert store.get("chronology") is None
            assert jobs.submit(request("VERIFY"), "after-rejection").job_id
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_collection_source_edit_replays_exact_receipt_while_other_task_is_busy(tmp_path):
    from tests.integration.test_plan_preparation_store import collection_input

    from trade_plan_monitor.backtest.preparation_store import PreparationConflictError

    store = PreparationStore(tmp_path / "edit.sqlite3")
    jobs = BacktestJobRepository(tmp_path / "jobs.sqlite3")

    async def scenario():
        service = PreparationService(store, jobs, PreparationExtractor(forbidden_ai))
        try:
            created = await service.create(collection_input(), idempotency_key="create-edit")
            order = tuple(reversed([i.source.source_id for i in created.items]))
            edited = await service.edit_collection(
                created.preparation_id, expected_revision=created.revision,
                idempotency_key="edit-order", source_order=order,
            )
            assert tuple(i.source.source_id for i in edited.items) == order
            jobs.submit(request("VERIFY"), "busy")
            assert await service.edit_collection(
                created.preparation_id, expected_revision=created.revision,
                idempotency_key="edit-order", source_order=order,
            ) == edited
            with pytest.raises(JobAdmissionError):
                await service.edit_collection(
                    created.preparation_id, expected_revision=edited.revision,
                    idempotency_key="new-edit", source=edited.items[0].source.model_copy(
                        update={"text": "Changed source while another task is busy."}),
                )
            with pytest.raises(PreparationConflictError, match="IDEMPOTENCY_CONFLICT"):
                await service.edit_collection(
                    created.preparation_id, expected_revision=created.revision,
                    idempotency_key="edit-order", source_order=tuple(reversed(order)),
                )
            assert store.get(created.preparation_id) == edited
        finally:
            await service.stop()

    asyncio.run(scenario())
