import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
from yaml.constructor import ConstructorError

from trade_plan_monitor.cli import build_parser
from trade_plan_monitor.cli import main as run_cli
from trade_plan_monitor.config import load_application_config

PROJECT_ROOT = Path(__file__).parents[2]


def test_empty_yaml_uses_loopback_web_and_secret_reference_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text("{}\n", encoding="utf-8")

    config = load_application_config(config_path)

    assert config.web.host == "127.0.0.1"
    assert config.web.port == 8765
    assert config.tushare.token_ref.environment_variable == "TUSHARE_TOKEN"
    assert config.ai.api_key_ref is None


def test_yaml_accepts_environment_references_without_secret_values(tmp_path: Path) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        """\
tushare:
  token_ref:
    environment_variable: MONITOR_TUSHARE_TOKEN
ai:
  api_key_ref:
    environment_variable: MONITOR_AI_API_KEY
""",
        encoding="utf-8",
    )

    config = load_application_config(config_path)

    assert config.tushare.token_ref.environment_variable == "MONITOR_TUSHARE_TOKEN"
    assert config.ai.api_key_ref is not None
    assert config.ai.api_key_ref.environment_variable == "MONITOR_AI_API_KEY"


def test_example_configuration_is_valid_and_contains_references_only() -> None:
    config = load_application_config(PROJECT_ROOT / "config" / "app.example.yaml")

    assert config.web.host == "127.0.0.1"
    assert config.web.port == 8765
    assert config.tushare.token_ref.environment_variable == "TUSHARE_TOKEN"
    assert config.ai.api_key_ref is not None
    assert config.ai.api_key_ref.environment_variable == "AI_API_KEY"


@pytest.mark.parametrize(
    ("yaml_text", "field_path"),
    [
        ("unexpected: true\n", "unexpected"),
        ("web:\n  host: 0.0.0.0\n", "web.host"),
        ("tushare:\n  token: literal-value\n", "tushare.token"),
        ("ai:\n  api_key: literal-value\n", "ai.api_key"),
    ],
)
def test_yaml_rejects_unknown_and_literal_secret_fields(
    tmp_path: Path,
    yaml_text: str,
    field_path: str,
) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(ValidationError) as error:
        load_application_config(config_path)

    rejected_paths = {".".join(map(str, item["loc"])) for item in error.value.errors()}
    assert field_path in rejected_paths


def test_yaml_safe_loader_rejects_python_object_construction(tmp_path: Path) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        "!!python/object/apply:builtins.str [unsafe]\n",
        encoding="utf-8",
    )

    with pytest.raises(ConstructorError):
        load_application_config(config_path)


def test_cli_declares_inert_commands_and_loopback_web_defaults() -> None:
    parser = build_parser()
    web_args = parser.parse_args(["web"])

    assert web_args.host == "127.0.0.1"
    assert web_args.port == 8765
    for command in ("validate", "monitor", "web", "replay", "backup"):
        assert run_cli([command]) == 0


def test_module_help_lists_every_declared_command() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "trade_plan_monitor", "--help"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    for command in ("validate", "monitor", "web", "replay", "backup"):
        assert command in completed.stdout
