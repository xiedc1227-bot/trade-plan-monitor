"""Contracts for directly configured stock/index live certification."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from trade_plan_monitor.live_certification import (
    LiveCertificationSurface,
    launch_live_certification,
    required_authorization,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


@pytest.mark.parametrize(
    ("surface", "authorization"),
    [
        (LiveCertificationSurface.STOCK, "LPC005_STOCK_LIVE_CERTIFICATION"),
        (LiveCertificationSurface.BOARD_INDEX, "LPC007_BOARD_INDEX_LIVE_CERTIFICATION"),
    ],
)
def test_each_surface_has_a_distinct_exact_authorization(
    surface: LiveCertificationSurface,
    authorization: str,
) -> None:
    assert required_authorization(surface) == authorization


def test_launcher_fails_before_loading_configuration_outside_market_window() -> None:
    calls: list[object] = []

    result = launch_live_certification(
        surface=LiveCertificationSurface.STOCK,
        authorization=required_authorization(LiveCertificationSurface.STOCK),
        config_path=Path("config/app.yaml"),
        now=datetime(2026, 9, 7, 8, 0, tzinfo=SHANGHAI),
        runner=lambda *args: calls.append(args) or 0,
    )

    assert result.outcome == "NOT_RUN_MARKET_WINDOW"
    assert result.return_code == 0
    assert calls == []


def test_stock_launcher_rejects_ambiguous_morning_window_before_configuration() -> None:
    calls: list[object] = []

    result = launch_live_certification(
        surface=LiveCertificationSurface.STOCK,
        authorization=required_authorization(LiveCertificationSurface.STOCK),
        config_path=Path("config/app.yaml"),
        now=datetime(2026, 9, 7, 10, 0, tzinfo=SHANGHAI),
        runner=lambda *args: calls.append(args) or 0,
    )

    assert result.outcome == "NOT_RUN_MARKET_WINDOW"
    assert result.return_code == 0
    assert calls == []


def test_stock_authorization_cannot_start_index_certification() -> None:
    with pytest.raises(ValueError, match="authorization does not match"):
        launch_live_certification(
            surface=LiveCertificationSurface.BOARD_INDEX,
            authorization=required_authorization(LiveCertificationSurface.STOCK),
            config_path=Path("config/app.yaml"),
            now=datetime(2026, 9, 7, 10, 0, tzinfo=SHANGHAI),
            runner=lambda *_args: 0,
        )


def test_launcher_runs_selected_surface_directly_from_application_config(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    config_path = tmp_path / "app.yaml"
    output_directory = tmp_path / "evidence"

    def runner(surface: LiveCertificationSurface, config: Path, output: Path) -> int:
        captured.update(surface=surface, config=config, output=output)
        return 0

    result = launch_live_certification(
        surface=LiveCertificationSurface.BOARD_INDEX,
        authorization=required_authorization(LiveCertificationSurface.BOARD_INDEX),
        config_path=config_path,
        output_directory=output_directory,
        now=datetime(2026, 9, 7, 10, 0, tzinfo=SHANGHAI),
        runner=runner,
    )

    assert result.outcome == "COMPLETED"
    assert result.return_code == 0
    assert captured == {
        "surface": LiveCertificationSurface.BOARD_INDEX,
        "config": config_path,
        "output": output_directory,
    }
