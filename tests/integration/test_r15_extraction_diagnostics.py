"""SIMULATED provider replies through the real local Web extraction entry point."""

from __future__ import annotations

import json
import sqlite3
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.integration.test_explicit_plan_review_api import (
    _EXTRACTION_ID,
    _NOW,
    _confirmation_resolutions,
    _draft_payload,
    _record_extraction,
)
from tests.integration.test_explicit_plan_review_api import (
    _SOURCE as EXPLICIT_SOURCE,
)
from tests.unit.test_ai_plan_extraction_v4 import _SOURCE, _valid_output

from trade_plan_monitor.ai.models import ExplicitPlanDraft
from trade_plan_monitor.ai.review import dump_explicit_plan_draft_json
from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle
from trade_plan_monitor.web.app import create_app, create_production_app
from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

SECRET = "SECRET-Bearer-key-source-response-and-path"


class _Runtime:
    async def start(self) -> dict[str, str]:
        return {"status": "READY"}

    async def stop(self) -> None:
        return None


def _response(
    content: str, *, finish: str = "stop", usage: bool = True, model: str = "SIMULATED-v4"
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish,
                }
            ],
            **(
                {"usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}
                if usage
                else {}
            ),
        },
    )


def _submit(client: TestClient, provider_id: str, source: str, key: str) -> dict[str, object]:
    accepted = client.post(
        "/api/v1/plan-extractions",
        headers={"Idempotency-Key": key},
        json={"providerId": provider_id, "sourceText": source, "expectedRevision": 0},
    )
    assert accepted.status_code == 202, accepted.text
    operation_id = accepted.json()["operationId"]
    for _ in range(100):
        outcome = client.get(f"/api/v1/plan-extractions/{operation_id}")
        assert outcome.status_code == 200
        if outcome.json()["status"] not in {"QUEUED", "RUNNING"}:
            return outcome.json()
    raise AssertionError("extraction never completed")


def test_simulated_failures_are_durable_sanitized_and_success_remains_review_only(
    tmp_path: Path, capsys
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "ai:\n"
        "  profile: DEEPSEEK\n"
        "  base_url: https://api.deepseek.com\n"
        "  model: simulated-v4-pro\n"
        f"  api_key: {SECRET}\n"
        "  max_retries: 0\n",
        encoding="utf-8",
    )
    database = tmp_path / "isolated/monitor.sqlite3"
    database.parent.mkdir()
    diagnostic_path = database.with_suffix(".ai-extraction-diagnostics.jsonl")
    plans = PersistentPlanWebLifecycle(database_path=database)
    responses = iter(
        [
            _response(json.dumps(_valid_output(), ensure_ascii=False)),
            httpx.Response(401, text=f"Authorization: Bearer {SECRET}"),
            _response("{}", finish="length"),
            _response("{}", finish=SECRET, model=SECRET),
            _response("{"),
            _response('{"draft":1,"draft":2}'),
            _response(json.dumps({**_valid_output(), SECRET: "leak"})),
            _response(json.dumps(_valid_output(), ensure_ascii=False)),
        ]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    def make_ai() -> ConfiguredAIWebLifecycle:
        return ConfiguredAIWebLifecycle(
            config_path=config,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(handler), trust_env=False
            ),
            review_store=plans,
            diagnostic_path=diagnostic_path,
        )

    app = create_app(
        runtime_factory=_Runtime,
        plan_lifecycle_factory=lambda: plans,
        ai_lifecycle_factory=make_ai,
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        provider_id = client.get("/api/v1/ai-runtime").json()["providerId"]
        success = _submit(client, provider_id, _SOURCE, "SIMULATED-success")
        assert success["status"] == "SUCCEEDED"
        assert success["draftPlanJson"] is not None
        outcomes = [
            _submit(client, provider_id, _SOURCE + SECRET, f"SIMULATED-{index}")
            for index in range(7)
        ]
        assert [item["status"] for item in outcomes] == [
            "PROVIDER_ERROR",
            "INVALID_OUTPUT",
            "INVALID_OUTPUT",
            "INVALID_OUTPUT",
            "INVALID_OUTPUT",
            "INVALID_OUTPUT",
            "INVALID_OUTPUT",
        ]
        for outcome in outcomes:
            assert outcome["draftPlanJson"] is None
            assert SECRET not in json.dumps(outcome, ensure_ascii=False)

    lines = [json.loads(line) for line in diagnostic_path.read_text("utf-8").splitlines()]
    assert len(lines) == 8
    assert [line["reason"] for line in lines] == [
        "NONE",
        "PROVIDER_ERROR",
        "FINISH_REASON",
        "FINISH_REASON",
        "JSON_SYNTAX",
        "JSON_DUPLICATE_KEY",
        "SCHEMA",
        "MAPPING",
    ]
    assert lines[1]["providerErrorCode"] == "AUTHENTICATION"
    assert lines[1]["usage"] is None
    assert lines[2]["finishReason"] == "length"
    assert lines[2]["usage"] == {"promptTokens": 11, "completionTokens": 7, "totalTokens": 18}
    assert lines[3]["finishReason"] == "other"
    assert all(
        line["sourceTextSha256"] == sha256((_SOURCE + SECRET).encode()).hexdigest()
        for line in lines[1:]
    )
    assert all(line["model"] == "simulated-v4-pro" for line in lines)
    assert lines[0]["modelMatchesConfigured"] is False
    assert SECRET not in diagnostic_path.read_text("utf-8")
    assert SECRET not in capsys.readouterr().out
    with sqlite3.connect(database) as connection:
        table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
        for table in ("position_inventory_state", "position_lot", "plan_version"):
            if table in table_names:
                assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM plan_extraction_review").fetchone()[0] == 1

    # The public operation cache is gone after shutdown, while diagnostic records remain.
    restarted = make_ai()
    app2 = create_app(runtime_factory=_Runtime, ai_lifecycle_factory=lambda: restarted)
    with TestClient(app2, base_url="http://127.0.0.1:8765") as client:
        assert client.get(f"/api/v1/plan-extractions/{outcomes[0]['id']}").status_code == 404
    assert len(diagnostic_path.read_text("utf-8").splitlines()) == 8


@pytest.mark.parametrize("sink_failure", [False, True])
def test_simulated_production_composition_selects_the_database_sidecar(
    tmp_path: Path, monkeypatch, sink_failure: bool
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "ai:\n"
        "  profile: DEEPSEEK\n"
        "  base_url: https://api.deepseek.com\n"
        "  model: simulated-v4-pro\n"
        "  api_key: offline-only-key\n"
        "  max_retries: 0\n",
        encoding="utf-8",
    )
    database = tmp_path / "production-isolated/monitor.sqlite3"
    created_clients: list[httpx.AsyncClient] = []

    def make_client() -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: _response("{", usage=False)),
            trust_env=False,
        )
        created_clients.append(client)
        return client

    class _Backtest:
        read_service = None
        operation_service = None

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    monkeypatch.setattr("trade_plan_monitor.web.ai_service._default_client", make_client)
    if sink_failure:

        def fail_sink(*_args: object, **_kwargs: object) -> None:
            raise OSError("SIMULATED diagnostic disk denial")

        monkeypatch.setattr("trade_plan_monitor.web.ai_service.ensure_diagnostic_sink", fail_sink)
        monkeypatch.setattr(
            "trade_plan_monitor.web.ai_service.append_extraction_diagnostic", fail_sink
        )
    monkeypatch.setattr(
        "trade_plan_monitor.backtest.composition.create_backtest_composition_factory",
        lambda **_kwargs: _Backtest,
    )
    with create_production_app(monitor_contract_version=1,
        config_path=config,
        database_path=database,
        runtime_factory=_Runtime,
    ) as app:
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            assert app.state.ai_startup["diagnosticAvailable"] is not sink_failure
            provider_id = client.get("/api/v1/ai-runtime").json()["providerId"]
            outcome = _submit(client, provider_id, _SOURCE, "SIMULATED-production-entry")
            assert outcome["status"] == "INVALID_OUTPUT"
            assert outcome["diagnosticStatus"] == ("WRITE_FAILED" if sink_failure else "RECORDED")
    path = database.with_suffix(".ai-extraction-diagnostics.jsonl")
    if sink_failure:
        assert not path.exists()
    else:
        record = json.loads(path.read_text("utf-8"))
        assert record["reason"] == "JSON_SYNTAX"
        assert record["usage"] is None
    assert all(client.is_closed for client in created_clients)


def test_simulated_diagnostic_io_failure_preserves_active_plan_and_extraction_outcomes(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "ai:\n"
        "  profile: DEEPSEEK\n"
        "  base_url: https://api.deepseek.com\n"
        "  model: simulated-v4-pro\n"
        "  api_key: offline-only-key\n"
        "  max_retries: 0\n",
        encoding="utf-8",
    )
    database = tmp_path / "active-isolated/monitor.sqlite3"
    database.parent.mkdir()
    plans = PersistentPlanWebLifecycle(database_path=database, clock=lambda: _NOW)
    responses = iter([_response("{"), _response(json.dumps(_valid_output(), ensure_ascii=False))])

    def fail_diagnostic_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("SIMULATED sidecar write failure")

    monkeypatch.setattr(
        "trade_plan_monitor.web.ai_service.append_extraction_diagnostic",
        fail_diagnostic_write,
    )
    app = create_app(
        runtime_factory=_Runtime,
        plan_lifecycle_factory=lambda: plans,
        ai_lifecycle_factory=lambda: ConfiguredAIWebLifecycle(
            config_path=config,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(lambda _request: next(responses)),
                trust_env=False,
            ),
            review_store=plans,
            diagnostic_path=database.with_suffix(".ai-extraction-diagnostics.jsonl"),
        ),
    )
    draft = ExplicitPlanDraft.model_validate_json(json.dumps(_draft_payload()))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        _record_extraction(plans, draft)
        saved = client.post(
            "/api/v1/plan-drafts",
            headers={"Idempotency-Key": "SIMULATED-existing-draft"},
            json={
                "extractionId": str(_EXTRACTION_ID),
                "planJson": dump_explicit_plan_draft_json(draft),
                "sourceText": EXPLICIT_SOURCE,
                "expectedRevision": 0,
            },
        )
        assert saved.status_code == 200, saved.text
        detail = saved.json()
        reviewed = client.post(
            "/api/v1/plan-review-confirmations",
            headers={"Idempotency-Key": "SIMULATED-existing-review"},
            json={
                "planVersionId": detail["id"],
                "contentHash": detail["contentHash"],
                "sourceHash": detail["sourceHash"],
                "reviewEvidenceHash": detail["reviewEvidenceHash"],
                "expectedRevision": 0,
                "resolutions": _confirmation_resolutions(detail),
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        approved = reviewed.json()
        assert approved["canActivate"] is True
        activation = client.post(
            "/api/v1/plan-activations",
            headers={"Idempotency-Key": "SIMULATED-existing-activation"},
            json={
                "planVersionId": detail["id"],
                "reviewId": approved["reviewId"],
                "contentHash": detail["contentHash"],
                "expectedRevision": 0,
            },
        )
        assert activation.status_code == 200, activation.text
        before = client.get("/api/v1/plan-activation-states/003043.SZ").json()
        provider_id = client.get("/api/v1/ai-runtime").json()["providerId"]
        invalid = _submit(client, provider_id, _SOURCE, "SIMULATED-io-invalid")
        valid = _submit(client, provider_id, _SOURCE, "SIMULATED-io-valid")
        after = client.get("/api/v1/plan-activation-states/003043.SZ").json()
        assert invalid["status"] == "INVALID_OUTPUT"
        assert valid["status"] == "SUCCEEDED"
        assert invalid["diagnosticStatus"] == valid["diagnosticStatus"] == "WRITE_FAILED"
        assert before == after

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM plan_version").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM position_lot").fetchone()[0] == 0
        inventory_count = connection.execute(
            "SELECT COUNT(*) FROM position_inventory_state"
        ).fetchone()[0]
        assert inventory_count == 0
        assert connection.execute("SELECT COUNT(*) FROM plan_extraction_review").fetchone()[0] == 2
