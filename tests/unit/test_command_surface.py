"""Application launch commands do not expose the removed backtest interface."""

import pytest

from trade_plan_monitor.cli import build_parser, main


def test_help_excludes_backtest_and_keeps_web_startup() -> None:
    parser = build_parser()

    assert "backtest" not in parser.format_help()
    arguments = parser.parse_args(["web", "--host", "127.0.0.1", "--port", "8765"])
    assert arguments.command == "web"
    assert arguments.host == "127.0.0.1"
    assert arguments.port == 8765


@pytest.mark.parametrize("operation", ["sync", "verify", "run", "list", "prune"])
def test_removed_backtest_commands_reject_before_creating_files(
    operation, tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as stopped:
        main(["backtest", operation])

    assert stopped.value.code == 2
    assert "invalid choice: 'backtest'" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
