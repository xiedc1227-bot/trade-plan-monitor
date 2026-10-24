"""Selection persistence and store upgrades do not rewrite existing preparation bytes."""

import sqlite3

import pytest
from tests.unit.test_workbench_selection_context import context, reviewed

from trade_plan_monitor.backtest.preparation_store import PreparationConflictError, PreparationStore
from trade_plan_monitor.backtest.workbench_selection import (
    WorkbenchSelectionCommand,
    WorkbenchSelectionStore,
)


def command():
    return WorkbenchSelectionCommand(
        schema_version="workbench-loop-selection-v1", plan=reviewed().reference, context=context()
    )


def test_freeze_receipt_survives_restart_and_rejects_changed_intent(tmp_path):
    path = tmp_path / "preparation.sqlite"
    store = WorkbenchSelectionStore(PreparationStore(path))
    saved = store.save(command(), reviewed(), "once")
    restarted = WorkbenchSelectionStore(PreparationStore(path))
    assert restarted.get(saved.selection_id) == saved
    assert restarted.replay(command(), "once") == saved
    assert restarted.save(command(), reviewed(), "once") == saved
    altered = command().model_copy(
        update={
            "context": context().model_copy(
                update={"evidence": "A different confirmed historical context."}
            )
        }
    )
    with pytest.raises(PreparationConflictError):
        restarted.replay(altered, "once")


def test_concurrent_freeze_publishes_one_selection_and_receipt(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store = WorkbenchSelectionStore(PreparationStore(tmp_path / "preparation.sqlite"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = tuple(pool.map(lambda _: store.save(command(), reviewed(), "same"), range(2)))
    assert values[0] == values[1]
    with sqlite3.connect(tmp_path / "preparation.sqlite") as connection:
        assert connection.execute("SELECT count(*) FROM backtest_plan_selection").fetchone() == (1,)
        assert connection.execute(
            "SELECT count(*) FROM backtest_preparation_idempotency"
        ).fetchone() == (1,)


def test_upgrade_old_preparation_store_preserves_documents_and_receipts(tmp_path):
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
          CREATE TABLE backtest_preparation_metadata(singleton INTEGER PRIMARY KEY,
              domain TEXT NOT NULL,schema_version INTEGER NOT NULL);
          INSERT INTO backtest_preparation_metadata VALUES(1,'backtest-preparation-v1',1);
          CREATE TABLE backtest_preparation(preparation_id TEXT PRIMARY KEY,document_json TEXT);
          INSERT INTO backtest_preparation VALUES('preserved','  {"original":"bytes"}  ');
          CREATE TABLE backtest_preparation_idempotency(idempotency_key TEXT PRIMARY KEY,
              request_hash TEXT,response_json TEXT);
          INSERT INTO backtest_preparation_idempotency VALUES('old-key','old-hash','exact receipt');
        """)
    PreparationStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT document_json FROM backtest_preparation").fetchone() == (
            '  {"original":"bytes"}  ',
        )
        assert connection.execute(
            "SELECT response_json FROM backtest_preparation_idempotency"
        ).fetchone() == ("exact receipt",)
        assert connection.execute("SELECT count(*) FROM backtest_plan_selection").fetchone() == (0,)


@pytest.mark.parametrize("kind", ["single", "collection"])
def test_upgrade_real_prior_formats_preserves_decoding_and_exact_receipts(tmp_path, kind):
    from tests.integration.test_plan_preparation_review import ready_collection, ready_preparation

    store, record = (ready_preparation if kind == "single" else ready_collection)(tmp_path)
    with sqlite3.connect(store.database_path) as connection:
        documents = connection.execute("SELECT * FROM backtest_preparation").fetchall()
        receipts = connection.execute("SELECT * FROM backtest_preparation_idempotency").fetchall()
        connection.execute("DROP TABLE backtest_plan_selection")
        connection.execute("UPDATE backtest_preparation_metadata SET schema_version = 1")
    restored = PreparationStore(store.database_path)
    assert restored.get(record.preparation_id) == record
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("SELECT * FROM backtest_preparation").fetchall() == documents
        assert (
            connection.execute("SELECT * FROM backtest_preparation_idempotency").fetchall()
            == receipts
        )


def test_mounted_selection_is_idempotent_and_recovers_without_live_reader(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from tests.integration.test_web_api import _FakeLifecycle

    from trade_plan_monitor.backtest.composition import create_backtest_composition_factory
    from trade_plan_monitor.web.app import create_app

    class Reader:
        calls = 0

        async def get_plan_version(self, *, version_id):
            raise AssertionError("selection must use the complete reviewed snapshot reader")

        async def get_reviewed_backtest_plan(self, *, version_id):
            self.calls += 1
            assert version_id == str(command().plan.plan_version_id)
            return reviewed()

    reader = Reader()
    factory = create_backtest_composition_factory(
        config_path=tmp_path / "absent.yaml",
        plan_snapshot_reader=reader,
        market_database=tmp_path / "market.sqlite",
        results_database=tmp_path / "result.sqlite",
        preparation_database=tmp_path / "prepare.sqlite",
        cursor_key_path=tmp_path / "cursor.key",
    )
    app = create_app(
        runtime_factory=lambda: _FakeLifecycle(events=[]),
        plan_service=reader,
        backtest_lifecycle_factory=factory,
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        headers = {"Origin": "http://127.0.0.1:8765", "Idempotency-Key": "freeze-once"}
        payload = command().model_dump(mode="json", by_alias=True)
        response = client.post("/api/v1/backtest-plan-selections", json=payload, headers=headers)
        assert response.status_code == 201, response.text
        value = response.json()
        assert value["frozen"]["version"]["snapshot"] == reviewed().version.snapshot.model_dump(
            mode="json"
        )
        assert reader.calls == 1
        response2 = client.post("/api/v1/backtest-plan-selections", json=payload, headers=headers)
        assert response2.json() == value
        assert reader.calls == 1
        fetched = client.get("/api/v1/backtest-plan-selections/" + value["selectionId"])
        assert fetched.json() == value
        assert reader.calls == 1

        def busy(_store, _selection_id):
            error = sqlite3.OperationalError("private locked database path")
            error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise error

        with monkeypatch.context() as patcher:
            patcher.setattr(WorkbenchSelectionStore, "get", busy)
            unavailable = client.get("/api/v1/backtest-plan-selections/" + value["selectionId"])
            assert unavailable.status_code == 503
            assert unavailable.headers["Retry-After"] == "1"
            assert "private locked" not in unavailable.text
        identity = {key: value[key] for key in ("selectionId", "selectionHash")}
        assert (
            client.get(
                "/api/v1/backtest-run-data",
                params=identity
                | {
                    "preparationId": "mixed",
                    "manifestHash": "a" * 64,
                },
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/v1/backtest-run-data",
                params={
                    "selectionId": value["selectionId"],
                    "selectionHash": "a" * 64,
                },
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/backtest-plan-selections",
                json=payload,
                headers=headers | {"Origin": "https://example.com"},
            ).status_code
            == 403
        )
        invalid = payload | {"context": payload["context"] | {"confirmed": 1}}
        assert (
            client.post(
                "/api/v1/backtest-plan-selections", json=invalid, headers=headers
            ).status_code
            == 422
        )
        changed = payload | {"plan": payload["plan"] | {"planHash": "b" * 64}}
        assert (
            client.post(
                "/api/v1/backtest-plan-selections",
                json=changed,
                headers=headers | {"Idempotency-Key": "changed-review"},
            ).status_code
            == 409
        )
        payload["context"]["evidence"] = "Changed research declaration"
        assert (
            client.post(
                "/api/v1/backtest-plan-selections", json=payload, headers=headers
            ).status_code
            == 409
        )


def test_real_workbench_reader_returns_original_inactive_approval(tmp_path):
    from functools import partial

    from fastapi.testclient import TestClient
    from tests.integration.test_current_plan_api import (
        make_app,
        post,
        review_payload,
        reviewed_save,
        simple_plan,
    )

    from trade_plan_monitor.domain.unified_plan_validation import UnifiedPlanDraft

    app = make_app(tmp_path)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        draft = UnifiedPlanDraft.from_executable(simple_plan())
        saved = reviewed_save(client, draft)
        service = app.state.plan_operation_service
        from trade_plan_monitor.state.repositories import PlanSaveBlockedError

        with pytest.raises(PlanSaveBlockedError):
            client.portal.call(partial(service.get_reviewed_backtest_plan, version_id=saved["id"]))
        confirmation = post(client, "plan-review-confirmations", review_payload(saved))
        frozen = client.portal.call(
            partial(service.get_reviewed_backtest_plan, version_id=saved["id"])
        )
        assert str(frozen.reference.review_id) == confirmation["reviewId"]
        assert frozen.reference.review_evidence_hash == saved["reviewEvidenceHash"]
        assert frozen.version.snapshot == simple_plan()
        assert (
            client.get("/api/v1/plan-activation-states/" + saved["symbol"]).json()["active"]
            is False
        )


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("code", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_IOERR])
def test_selection_reader_maps_only_busy_locks_and_preserves_retry_intent(tmp_path, code, wrapped):
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import OperationalError
    from tests.integration.test_web_api import _FakeLifecycle

    from trade_plan_monitor.backtest.composition import create_backtest_composition_factory
    from trade_plan_monitor.web.app import create_app

    class Reader:
        failure = True

        async def get_plan_version(self, *, version_id):
            raise AssertionError("selection must use the complete reviewed snapshot reader")

        async def get_reviewed_backtest_plan(self, *, version_id):
            if self.failure:
                error = sqlite3.OperationalError("private workbench database path")
                error.sqlite_errorcode = code
                if wrapped:
                    raise OperationalError("private SQL", {}, error)
                raise error
            return reviewed()

    reader = Reader()
    factory = create_backtest_composition_factory(
        config_path=tmp_path / "absent.yaml", plan_snapshot_reader=reader,
        market_database=tmp_path / "market.sqlite", results_database=tmp_path / "result.sqlite",
        preparation_database=tmp_path / "prepare.sqlite", cursor_key_path=tmp_path / "cursor.key",
    )
    app = create_app(
        runtime_factory=lambda: _FakeLifecycle(events=[]), plan_service=reader,
        backtest_lifecycle_factory=factory,
    )
    with TestClient(app, base_url="http://127.0.0.1:8765", raise_server_exceptions=False) as client:
        headers = {"Origin": "http://127.0.0.1:8765", "Idempotency-Key": "reader-retry"}
        payload = command().model_dump(mode="json", by_alias=True)
        failed = client.post("/api/v1/backtest-plan-selections", json=payload, headers=headers)
        if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            assert failed.status_code == 503
            assert failed.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
            assert failed.headers["Retry-After"] == "1"
        else:
            assert failed.status_code == 500
            assert "Retry-After" not in failed.headers
        assert "private" not in failed.text
        reader.failure = False
        accepted = client.post("/api/v1/backtest-plan-selections", json=payload, headers=headers)
        assert accepted.status_code == 201, accepted.text
        assert client.post(
            "/api/v1/backtest-plan-selections", json=payload, headers=headers,
        ).json() == accepted.json()


@pytest.mark.parametrize("mode,expected_fills", [("FOLLOW_REMINDERS", 1), ("OBSERVE_ONLY", 0)])
def test_workbench_replay_copies_exact_plan_and_runs_existing_loop(
    tmp_path,
    monkeypatch,
    mode,
    expected_fills,
):
    from functools import partial
    from threading import Event

    from fastapi.testclient import TestClient
    from tests.integration.test_backtest_market_store import PROFILE
    from tests.integration.test_monitor_loop_cycle import frames
    from tests.integration.test_monitor_loop_production_composition import wait
    from tests.integration.test_web_api import _FakeLifecycle
    from tests.unit.test_monitor_loop_input import account
    from tests.unit.test_monitor_loop_schedule import at, calendar

    from trade_plan_monitor.backtest import composition as module
    from trade_plan_monitor.backtest.jobs.maintenance import BacktestJobMaintenance
    from trade_plan_monitor.backtest.jobs.repository import BacktestJobRepository
    from trade_plan_monitor.backtest.loop_input import PositionLimitFunding
    from trade_plan_monitor.backtest.market_store import BacktestMarketStore
    from trade_plan_monitor.web.app import create_app

    now = at(20, 9, 43, 12)
    original = reviewed()
    original = original.model_copy(
        update={
            "version": original.version.model_copy(
                update={
                    "review": original.version.review.model_copy(
                        update={"reviewed_at": at(19, 18)}
                    ),
                }
            )
        }
    )

    class Reader:
        async def get_plan_version(self, **_kwargs):
            raise AssertionError("no legacy reader")

        async def get_reviewed_backtest_plan(self, **_kwargs):
            return original

    market = BacktestMarketStore(tmp_path / "market.sqlite")
    market.record_trading_days(calendar())
    values = tuple(frames())
    market.record_completed_loop_minutes(
        tuple(value.minute for value in values), historical_profile=PROFILE
    )
    market.record_daily_limits(
        (values[0].daily_limit.model_copy(update={"received_at": at(20, 9, 30)}),)
    )
    monkeypatch.setattr(
        module, "BacktestJobRepository", partial(BacktestJobRepository, clock=lambda: now)
    )
    monkeypatch.setattr(module, "PreparationStore", partial(PreparationStore, clock=lambda: now))
    monkeypatch.setattr("trade_plan_monitor.backtest.automatic_data.now", lambda: now)
    maintenance_finished = Event()
    original_prune = BacktestJobMaintenance.prune

    def prune_at_fixture_time(self, *, as_of, batch_size=1_000):
        # Admission, jobs and retention must share the same historical fixture clock.
        assert as_of.tzinfo is not None
        result = original_prune(self, as_of=now, batch_size=batch_size)
        maintenance_finished.set()
        return result

    monkeypatch.setattr(BacktestJobMaintenance, "prune", prune_at_fixture_time)
    reader = Reader()
    factory = module.create_backtest_composition_factory(
        config_path=tmp_path / "absent.yaml",
        plan_snapshot_reader=reader,
        market_database=market.database_path,
        results_database=tmp_path / "results.sqlite",
        preparation_database=tmp_path / "preparation.sqlite",
        cursor_key_path=tmp_path / "cursor",
    )
    app = create_app(
        runtime_factory=lambda: _FakeLifecycle(events=[]),
        plan_service=reader,
        backtest_lifecycle_factory=factory,
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        headers = {"Origin": "http://127.0.0.1:8765", "Idempotency-Key": "selection"}
        body = (
            command()
            .model_copy(
                update={
                    "context": context().model_copy(
                        update={
                            "initial_account": account(lots=(), cash=PositionLimitFunding()),
                        }
                    )
                }
            )
            .model_dump(mode="json", by_alias=True)
        )
        response = client.post("/api/v1/backtest-plan-selections", json=body, headers=headers)
        assert response.status_code == 201, response.text
        selection = response.json()
        identity = {key: selection[key] for key in ("selectionId", "selectionHash")}
        ready = client.get("/api/v1/backtest-run-data", params=identity)
        assert ready.status_code == 200 and ready.json()["ready"], ready.text
        run = identity | {
            "schemaVersion": "workbench-loop-selection-v1",
            "response": {"mode": mode},
            "costs": {
                "commissionRate": "0",
                "minimumCommissionFen": 0,
                "stampDutyRate": "0",
                "transferFeeRate": "0",
                "buySlippageFen": 0,
                "sellSlippageFen": 0,
            },
        }
        response = client.post(
            "/api/v1/backtest-runs", json=run, headers=headers | {"Idempotency-Key": "run"}
        )
        assert response.status_code == 202, response.text
        receipt = response.json()

        async def unavailable(**_kwargs):
            raise AssertionError("live plan reader is unavailable after acceptance")

        reader.get_reviewed_backtest_plan = unavailable
        # Acceptance owns copied inputs; retry and execution no longer require the source DB.
        (tmp_path / "preparation.sqlite").rename(tmp_path / "unavailable-preparation.sqlite")
        repeated = client.post(
            "/api/v1/backtest-runs", json=run, headers=headers | {"Idempotency-Key": "run"}
        )
        assert repeated.status_code == 202, repeated.text
        assert repeated.json()["runId"] == receipt["runId"]
        assert repeated.json()["jobId"] == receipt["jobId"]
        changed = run | {
            "response": {
                "mode": "OBSERVE_ONLY" if mode == "FOLLOW_REMINDERS" else "FOLLOW_REMINDERS"
            }
        }
        assert (
            client.post(
                "/api/v1/backtest-runs", json=changed, headers=headers | {"Idempotency-Key": "run"}
            ).status_code
            == 409
        )
        job = wait(
            client,
            "/api/v1/backtest-jobs/" + receipt["jobId"],
            lambda value: value["status"] == "FAILED" or (
                value["status"] == "COMPLETED" and maintenance_finished.is_set()
            ),
        )
        assert job["status"] == "COMPLETED", job

        # Neither source reader nor the mutable preparation store participates in result reads.
        result = client.get("/api/v1/backtest-runs/" + receipt["runId"])
        assert result.status_code == 200, result.text
        result = result.json()
        assert result["schemaVersion"] == "monitor-loop-result-workbench-v1"
        assert result["fillCount"] == expected_fills
        assert result["provenance"]["planVersionId"] == str(original.reference.plan_version_id)
        fills = client.get("/api/v1/backtest-runs/" + receipt["runId"] + "/fills")
        assert fills.status_code == 200, fills.text

    restarted = create_app(
        runtime_factory=lambda: _FakeLifecycle(events=[]),
        plan_service=reader,
        backtest_lifecycle_factory=factory,
    )
    with TestClient(restarted, base_url="http://127.0.0.1:8765") as client:
        restored = client.get("/api/v1/backtest-runs/" + receipt["runId"])
        assert restored.status_code == 200, restored.text
        assert restored.json() == result
        assert not (tmp_path / "preparation.sqlite").exists()
