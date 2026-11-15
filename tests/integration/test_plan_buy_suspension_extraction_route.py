"""Use the configured current service with an in-memory HTTP transport only."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from tests.unit.test_plan_buy_suspension_extraction import FIXTURE, suspension_output

from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle
from trade_plan_monitor.web.routers.plans import PlanExtractionCommand
from trade_plan_monitor.web.schemas import MutationContext


@pytest.mark.parametrize("version,wire,expected", [
    (None, 5, "SUCCEEDED"), ("plan-extract-v13", 10, "SUCCEEDED"),
    ("plan-extract-v13", 5, "INVALID_OUTPUT"), (None, 10, "INVALID_OUTPUT"),
])
def test_configured_current_route_is_explicit_and_single_call(tmp_path: Path, version, wire, expected):
    config_path = tmp_path / "offline.yaml"
    config_path.write_text(
        "ai:\n  base_url: http://127.0.0.1:1\n  api_key: offline-placeholder\n"
        "  model: offline-pbs\n  max_retries: 0\n"
        + (f"  prompt_version: {version}\n" if version else ""), encoding="utf-8")
    output = suspension_output(FIXTURE["unresolved"])
    output["draft"]["buy_suspension"] = {"condition": None, "effective_from": None}
    if wire == 5:
        output.pop("contract_version")
        output["draft"].update(schema_version=5, execution_version="condition-plan-v1")
        output["draft"].pop("buy_suspension")
    prompts, recorded = [], []

    def handle(request):
        body = json.loads(request.content)
        prompts.append(str(body["messages"]))
        return httpx.Response(200, json={"id": "offline-pbs", "model": "offline-pbs",
            "object": "chat.completion", "created": 1,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(output)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})

    class Store:
        async def record_plan_extraction(self, result):
            recorded.append(result)

    async def scenario():
        service = ConfiguredAIWebLifecycle(config_path=config_path, review_store=Store(),
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle),
                                                     trust_env=False))
        await service.start()
        try:
            providers = await service.list_ai_providers(offset=0, limit=20)
            receipt = await service.submit_plan_extraction(command=PlanExtractionCommand(
                provider_id=providers.items[0].config.provider_id,
                source_text=FIXTURE["unresolved"], expected_revision=0),
                context=MutationContext(idempotency_key="pbs-route", request_id="a" * 32))
            for _ in range(200):
                view = await service.get_plan_extraction(operation_id=str(receipt.operation_id))
                if view.status.value not in {"QUEUED", "RUNNING"}:
                    break
                await asyncio.sleep(0)
            assert view.status.value == expected
            assert len(prompts) == 1
            assert (version or "plan-extract-v12") in prompts[0]
            assert len(recorded) == (expected == "SUCCEEDED")
            if expected == "SUCCEEDED":
                assert view.prompt_version == (version or "plan-extract-v12")
                assert json.loads(view.draft_plan_json)["schema_version"] == wire
                assert view.validation_issues
                if wire == 10:
                    assert recorded[0].contract_version == "plan-buy-suspension-extraction-v1"
                    assert recorded[0].draft.to_executable() is None
                    assert any(i.path == "buy_suspension.condition" for i in view.validation_issues)
                    assert view.daily_mapping.supplements == ()
        finally:
            await service.stop()

    asyncio.run(scenario())
