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
    assert config.tushare.api_url is None
    assert config.tushare.timeout_seconds == 30
    assert config.tushare.token_ref.environment_variable == "TUSHARE_TOKEN"
    assert config.ai.api_key_ref is None


def test_yaml_accepts_environment_references_without_secret_values(tmp_path: Path) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        """\
tushare:
  api_url: https://api.quicksync.cn
  timeout_seconds: 20
  token_ref:
    environment_variable: MONITOR_TUSHARE_TOKEN
ai:
  api_key_ref:
    environment_variable: MONITOR_AI_API_KEY
""",
        encoding="utf-8",
    )

    config = load_application_config(config_path)

    assert str(config.tushare.api_url) == "https://api.quicksync.cn/"
    assert config.tushare.timeout_seconds == 20
    assert config.tushare.token_ref.environment_variable == "MONITOR_TUSHARE_TOKEN"
    assert config.ai.api_key_ref is not None
    assert config.ai.api_key_ref.environment_variable == "MONITOR_AI_API_KEY"


def test_example_configuration_is_valid_and_contains_references_only() -> None:
    config = load_application_config(PROJECT_ROOT / "config" / "app.example.yaml")

    assert config.web.host == "127.0.0.1"
    assert config.web.port == 8765
    assert str(config.tushare.api_url) == "https://api.quicksync.cn/"
    assert config.tushare.timeout_seconds == 30
    assert config.tushare.token_ref.environment_variable == "TUSHARE_TOKEN"
    assert config.ai.api_key_ref is not None
    assert config.ai.api_key_ref.environment_variable == "AI_API_KEY"


@pytest.mark.parametrize(
    ("yaml_text", "field_path"),
    [
        ("unexpected: true\n", "unexpected"),
        ("web:\n  host: 0.0.0.0\n", "web.host"),
        ("tushare:\n  token: literal-value\n", "tushare.token"),
        ("tushare:\n  api_url: http://api.quicksync.cn\n", "tushare.api_url"),
        ("tushare:\n  api_url: https://user:pass@api.quicksync.cn\n", "tushare.api_url"),
        ("tushare:\n  api_url: https://api.quicksync.cn?token=value\n", "tushare.api_url"),
        ("tushare:\n  api_url: https://api.quicksync.cn#fragment\n", "tushare.api_url"),
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


def test_cli_wires_maintenance_commands_and_keeps_loopback_web_defaults() -> None:
    parser = build_parser()
    web_args = parser.parse_args(["web"])

    calls: list[tuple[str, Path]] = []

    class CommandService:
        def __init__(self, config_path: Path) -> None:
            self.config_path = config_path

        async def validate(self) -> None:
            calls.append(("validate", self.config_path))

        async def once(self) -> None:
            calls.append(("once", self.config_path))

        async def run(self) -> None:
            calls.append(("run", self.config_path))

        async def replay(self) -> None:
            calls.append(("replay", self.config_path))

        async def backup(self) -> None:
            calls.append(("backup", self.config_path))

    def service_factory(config_path: Path) -> CommandService:
        return CommandService(config_path)

    assert web_args.host == "127.0.0.1"
    assert web_args.port == 8765
    assert run_cli(["validate"], service_factory=service_factory) == 0
    assert run_cli(["monitor", "--once"], service_factory=service_factory) == 0
    assert run_cli(["monitor"], service_factory=service_factory) == 0
    assert run_cli(["replay"], service_factory=service_factory) == 0
    assert run_cli(["backup"], service_factory=service_factory) == 0
    assert calls == [
        ("validate", Path("config/app.yaml")),
        ("once", Path("config/app.yaml")),
        ("run", Path("config/app.yaml")),
        ("replay", Path("config/app.yaml")),
        ("backup", Path("config/app.yaml")),
    ]

    with pytest.raises(SystemExit):
        parser.parse_args(["web", "--host", "0.0.0.0"])


def test_cli_requires_explicit_runtime_composition_for_service_commands() -> None:
    with pytest.raises(RuntimeError, match="service factory"):
        run_cli(["monitor", "--once"])


def test_cli_import_does_not_start_runtime_work() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import trade_plan_monitor.cli; print('imported')",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "imported"


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
