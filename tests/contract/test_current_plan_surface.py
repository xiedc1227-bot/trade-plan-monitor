"""Current product capabilities are visible in the formal API contract."""

import pytest

from trade_plan_monitor.web.app import create_app


def test_ai_configuration_is_read_only_in_the_formal_api():
    paths = create_app().openapi()["paths"]
    assert set(paths["/api/v1/ai-providers"]) == {"get"}
    assert "/api/v1/ai-provider-secrets" not in paths
    assert "/api/v1/ai-provider-tests" not in paths
    assert "/api/v1/ai-providers/{provider_id}" not in paths


@pytest.mark.parametrize("contract_version", [1, 2])
def test_current_operations_expose_simulation_without_real_fill_management(contract_version):
    class ReadService:
        monitor_contract_version = 2

    paths = create_app(
        monitor_contract_version=contract_version,
        read_service=ReadService() if contract_version == 2 else None,
    ).openapi()["paths"]
    assert set(paths["/api/v1/position-lots"]) == {"get"}
    for retired in (
        "/api/v1/position-lot-closures",
        "/api/v1/position-inventory-closures",
        "/api/v1/position-inventory-confirmations",
        "/api/v1/manual-event-risk-confirmations",
        "/api/v1/explicit-plan-runtime/{symbol}",
    ):
        assert retired not in paths
    assert "post" in paths["/api/v1/simulated-trades"]
