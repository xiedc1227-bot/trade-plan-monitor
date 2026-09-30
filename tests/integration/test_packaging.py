from __future__ import annotations

import json
import tomllib
from contextlib import nullcontext
from importlib import metadata, resources
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from trade_plan_monitor.cli import main as run_cli
from trade_plan_monitor.web.app import (
    ProductionAssetError,
    create_production_app,
    installed_web_assets,
)


class _Lifecycle:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def start(self) -> str:
        self._events.append("start")
        return "DEGRADED"

    async def stop(self) -> None:
        self._events.append("stop")


class _WebSocketService:
    async def serve(self, websocket, *, after: int) -> None:
        await websocket.accept()
        await websocket.send_json({"type": "heartbeat", "sequence": after})
        await websocket.close(code=1000)


class _BacktestLifecycle:
    read_service = object()
    operation_service = object()

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class _AIService:
    """Explicit inert service keeps this packaging-only test free of project config I/O."""

    pass


def _write_distribution(directory: Path) -> None:
    assets = directory / "assets"
    assets.mkdir(parents=True)
    (directory / "index.html").write_text(
        "<!doctype html><script type='module' src='/assets/app.js'></script>",
        encoding="utf-8",
    )
    (assets / "app.js").write_text("export {};", encoding="utf-8")


def test_installed_console_entry_loads_the_production_cli() -> None:
    distribution = metadata.distribution("trade-plan-monitor")
    entry_point = next(
        entry
        for entry in distribution.entry_points
        if entry.group == "console_scripts" and entry.name == "trade-plan-monitor"
    )

    assert entry_point.value == "trade_plan_monitor.cli:console_main"
    assert entry_point.load().__name__ == "console_main"


def test_production_dependencies_include_a_websocket_protocol_implementation() -> None:
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]

    assert "websockets==17.1" in project["dependencies"]


def test_built_vue_distribution_is_discoverable_as_package_data() -> None:
    with installed_web_assets() as directory:
        index = directory / "index.html"
        assets = tuple((directory / "assets").iterdir())

        assert index.is_file()
        assert assets
        assert json.loads((directory / "monitor-contract.json").read_text("utf-8")) == {
            "monitorContractVersion": 2,
        }
        pyproject = Path(__file__).parents[2] / "pyproject.toml"
        package_data = tomllib.loads(pyproject.read_text("utf-8"))["tool"]["setuptools"][
            "package-data"
        ]["trade_plan_monitor.web"]
        assert "dist/monitor-contract.json" in package_data
        html = index.read_text(encoding="utf-8")
        assert "http://" not in html
        assert "https://" not in html


@pytest.mark.parametrize("layout", ["missing", "index-only", "empty-assets"])
def test_incomplete_installed_build_uses_one_safe_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    layout: str,
) -> None:
    distribution = tmp_path / "dist"
    if layout != "missing":
        distribution.mkdir()
        (distribution / "index.html").write_text("spa", encoding="utf-8")
    if layout == "empty-assets":
        (distribution / "assets").mkdir()
    monkeypatch.setattr(resources, "files", lambda _package: tmp_path)

    with pytest.raises(ProductionAssetError) as captured:
        with installed_web_assets():
            pytest.fail("missing assets must not yield a directory")

    assert str(captured.value) == "Installed Web assets are unavailable."
    assert str(tmp_path) not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_resource_discovery_failure_cannot_escape_its_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_discovery(_package: str):
        raise OSError(str(tmp_path))

    monkeypatch.setattr(resources, "files", fail_discovery)

    with pytest.raises(ProductionAssetError) as captured:
        with installed_web_assets():
            pytest.fail("failed discovery must not yield a directory")

    assert str(captured.value) == "Installed Web assets are unavailable."
    assert str(tmp_path) not in repr(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_production_app_keeps_api_websocket_and_spa_routes_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution = tmp_path / "dist"
    _write_distribution(distribution)
    monkeypatch.setattr(resources, "files", lambda _package: tmp_path)
    events: list[str] = []

    with create_production_app(monitor_contract_version=1,
        ai_service=_AIService(),
        database_path=tmp_path / "monitor.sqlite3",
        runtime_factory=lambda: _Lifecycle(events),
        websocket_service=_WebSocketService(),
        backtest_lifecycle_factory=_BacktestLifecycle,
    ) as app:
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            root = client.get("/")
            asset = client.get("/assets/app.js")
            api = client.get("/api/v1/missing")
            with client.websocket_connect("/ws/v1/monitor?after=0") as websocket:
                heartbeat = websocket.receive_json()
                with pytest.raises(WebSocketDisconnect) as closed:
                    websocket.receive_json()

    assert root.status_code == 200
    assert asset.status_code == 200
    assert api.status_code == 404
    assert api.json()["error"]["code"] == "NOT_FOUND"
    assert heartbeat == {"type": "heartbeat", "sequence": 0}
    assert closed.value.code == 1000
    assert events == ["start", "stop"]


def test_web_command_runs_one_packaged_app_on_the_exact_loopback_default() -> None:
    app = FastAPI()
    app_calls: list[tuple[Path, str, int]] = []
    server_calls: list[tuple[FastAPI, str, int]] = []

    def app_factory(*, config_path: Path, bind_host: str, bind_port: int):
        app_calls.append((config_path, bind_host, bind_port))
        return nullcontext(app)

    def server_runner(application: FastAPI, *, host: str, port: int) -> None:
        server_calls.append((application, host, port))

    assert (
        run_cli(
            ["web"],
            web_app_factory=app_factory,
            web_server_runner=server_runner,
        )
        == 0
    )
    assert app_calls == [(Path("config/app.yaml"), "127.0.0.1", 8765)]
    assert server_calls == [(app, "127.0.0.1", 8765)]


@pytest.mark.parametrize("host", ["0.0.0.0", "localhost", "::1"])
def test_web_command_has_no_remote_or_alias_bind_path(host: str) -> None:
    with pytest.raises(SystemExit):
        run_cli(
            ["web", "--host", host],
            web_app_factory=lambda **_kwargs: nullcontext(FastAPI()),
            web_server_runner=lambda *_args, **_kwargs: None,
        )
