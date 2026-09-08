"""Direct application-config live-certification runner contracts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import trade_plan_monitor.live_certification_runner as runner_module
from trade_plan_monitor.config import TushareConfiguration
from trade_plan_monitor.live_certification import LiveCertificationSurface
from trade_plan_monitor.live_certification_runner import run_configured_certification


class _Controller:
    async def aclose(self) -> None:
        return None


def test_runner_reads_tushare_token_directly_from_application_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        """\
tushare:
  api_url: https://api.quicksync.cn
  token: configured-live-token
""",
        encoding="utf-8",
    )
    observed: dict[str, object] = {}

    def create_client(configuration: TushareConfiguration) -> object:
        observed["token"] = configuration.token
        return object()

    async def certify_stock(**kwargs: object) -> object:
        observed["client"] = kwargs["client"]
        observed["output_path"] = kwargs["output_path"]
        return SimpleNamespace(ready=True, profile_id="tushare-stock-live-v1")

    monkeypatch.setattr(runner_module, "create_tushare_client", create_client)
    monkeypatch.setattr(
        runner_module,
        "create_live_tushare_request_controller",
        lambda **_kwargs: _Controller(),
    )
    monkeypatch.setattr(runner_module, "certify_stock", certify_stock)

    result = run_configured_certification(
        LiveCertificationSurface.STOCK,
        config_path,
        tmp_path / "evidence",
    )

    assert result == 0
    assert observed["token"] == "configured-live-token"
    assert observed["output_path"] == tmp_path / "evidence" / "tushare-stock-live.json"
    assert '"outcome": "CERTIFIED"' in capsys.readouterr().out


def test_runner_fails_before_provider_call_when_config_has_no_token(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        "tushare:\n  api_url: https://api.quicksync.cn\n",
        encoding="utf-8",
    )

    result = run_configured_certification(
        LiveCertificationSurface.STOCK,
        config_path,
        tmp_path / "evidence",
    )

    assert result == 2
    assert '"outcome": "NOT_RUN_CONFIG_UNAVAILABLE"' in capsys.readouterr().out


def test_runner_reports_permission_block_without_failing_the_certification_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        """\
tushare:
  api_url: https://api.quicksync.cn
  token: configured-live-token
""",
        encoding="utf-8",
    )

    async def certify_board_indexes(**_kwargs: object) -> object:
        return SimpleNamespace(
            ready_indexes=frozenset(),
            profile_id="tushare-board-index-live-v1",
        )

    monkeypatch.setattr(runner_module, "create_tushare_client", lambda _config: object())
    monkeypatch.setattr(
        runner_module,
        "create_live_tushare_request_controller",
        lambda **_kwargs: _Controller(),
    )
    monkeypatch.setattr(
        runner_module,
        "certify_board_indexes",
        certify_board_indexes,
    )

    result = run_configured_certification(
        LiveCertificationSurface.BOARD_INDEX,
        config_path,
        tmp_path / "evidence",
    )

    output = capsys.readouterr().out
    assert result == 0
    assert '"outcome": "CERTIFIED_VISIBLE_BLOCK"' in output
    assert '"readyIndexCount": 0' in output
