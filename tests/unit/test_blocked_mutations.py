"""Only legacy-plan review may write while the monitor is blocked."""

from types import SimpleNamespace

import pytest
from starlette.requests import HTTPConnection

from trade_plan_monitor.runtime.health import RuntimeServiceStatus
from trade_plan_monitor.web.blocked_mutations import enforce_blocked_read_only
from trade_plan_monitor.web.errors import ApiError


@pytest.mark.parametrize("path", (
    "/api/v1/system/legacy-plan-invalidation",
    "/api/v1/plan-deactivations",
))
def test_restart_required_block_rejects_every_http_mutation(path: str) -> None:
    snapshot = SimpleNamespace(
        status=RuntimeServiceStatus.BLOCKED,
        block_reason="NEEDS_RESTART",
    )
    runtime = SimpleNamespace(health=lambda: snapshot)
    app = SimpleNamespace(state=SimpleNamespace(runtime_lifecycle=runtime))
    connection = HTTPConnection({
        "type": "http", "method": "POST", "path": path,
        "scheme": "http", "server": ("127.0.0.1", 8765),
        "app": app, "headers": [],
    })

    with pytest.raises(ApiError):
        enforce_blocked_read_only(connection)
