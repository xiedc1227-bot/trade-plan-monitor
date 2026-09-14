import asyncio
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from yaml.constructor import ConstructorError

from trade_plan_monitor.ai.command import ConfiguredAICommandService
from trade_plan_monitor.ai.composition import compose_configured_ai_provider
from trade_plan_monitor.ai.configured_secrets import create_configured_secret_store
from trade_plan_monitor.ai.models import AIProviderProfile
from trade_plan_monitor.ai.secrets import InMemorySecretStore
from trade_plan_monitor.cli import build_parser
from trade_plan_monitor.cli import main as run_cli
from trade_plan_monitor.config import load_application_config

PROJECT_ROOT = Path(__file__).parents[2]


def test_empty_yaml_uses_loopback_web_and_unconfigured_credentials(tmp_path: Path) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text("{}\n", encoding="utf-8")

    config = load_application_config(config_path)

    assert config.web.host == "127.0.0.1"
    assert config.web.port == 8765
    assert config.tushare.api_url is None
    assert config.tushare.timeout_seconds == 30
    assert config.tushare.token is None
    assert config.ai.api_key is None
    assert config.ai.profile is AIProviderProfile.DEEPSEEK
    assert str(config.ai.base_url) == "https://api.deepseek.com/"
    assert config.ai.model == "deepseek-flash"


def test_yaml_accepts_direct_credentials(tmp_path: Path) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        """\
tushare:
  api_url: https://api.quicksync.cn
  timeout_seconds: 20
  token: configured-tushare-token
ai:
  profile: OPENAI_COMPATIBLE
  display_name: Private compatible service
  base_url: https://ai.example.com/v1
  model: private-chat-model
  api_key: configured-ai-key
  timeout_seconds: 45
  max_retries: 1
  max_input_chars: 60000
  max_output_tokens: 2048
  temperature: 0.2
""",
        encoding="utf-8",
    )

    config = load_application_config(config_path)

    assert str(config.tushare.api_url) == "https://api.quicksync.cn/"
    assert config.tushare.timeout_seconds == 20
    assert config.tushare.token == "configured-tushare-token"
    assert config.ai.api_key == "configured-ai-key"
    assert config.ai.profile is AIProviderProfile.OPENAI_COMPATIBLE
    assert config.ai.display_name == "Private compatible service"
    assert str(config.ai.base_url) == "https://ai.example.com/v1"
    assert config.ai.model == "private-chat-model"
    assert config.ai.timeout_seconds == 45
    assert config.ai.max_retries == 1
    assert config.ai.max_input_chars == 60_000
    assert config.ai.max_output_tokens == 2_048
    assert config.ai.temperature == 0.2

    provider_config = config.ai.to_provider_config()
    assert provider_config is not None
    assert str(provider_config.base_url) == "https://ai.example.com/v1"
    assert provider_config.model == "private-chat-model"


def test_yaml_accepts_additional_models_with_stable_provider_identities(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        """\
ai:
  profile: DEEPSEEK
  display_name: DeepSeek
  base_url: https://api.deepseek.com
  model: deepseek-v4-flash
  api_key: configured-ai-key
  additional_models:
    - display_name: DeepSeek Pro
      model: deepseek-v4-pro
""",
        encoding="utf-8",
    )

    first_load = load_application_config(config_path).ai.to_provider_configs()
    second_load = load_application_config(config_path).ai.to_provider_configs()

    assert [config.display_name for config in first_load] == [
        "DeepSeek",
        "DeepSeek Pro",
    ]
    assert [config.model for config in first_load] == [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ]
    assert len({config.provider_id for config in first_load}) == 2
    assert [config.provider_id for config in first_load] == [
        config.provider_id for config in second_load
    ]
    assert len({config.secret_ref for config in first_load}) == 1


def test_yaml_rejects_duplicate_additional_model_identifiers(tmp_path: Path) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        """\
ai:
  model: deepseek-v4-flash
  api_key: configured-ai-key
  additional_models:
    - display_name: Duplicate Flash
      model: deepseek-v4-flash
""",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_application_config(config_path)


def test_example_configuration_is_valid_and_contains_direct_placeholders() -> None:
    config = load_application_config(PROJECT_ROOT / "config" / "app.example.yaml")

    assert config.web.host == "127.0.0.1"
    assert config.web.port == 8765
    assert str(config.tushare.api_url) == "https://api.quicksync.cn/"
    assert config.tushare.timeout_seconds == 30
    assert config.tushare.token == "replace-with-your-tushare-token"
    assert config.ai.api_key == "replace-with-your-deepseek-api-key"
    assert config.ai.profile is AIProviderProfile.DEEPSEEK
    assert config.ai.display_name == "DeepSeek"
    assert str(config.ai.base_url) == "https://api.deepseek.com/"
    assert config.ai.model == "deepseek-flash"

    provider_config = config.ai.to_provider_config()
    assert provider_config is not None
    assert provider_config.display_name == "DeepSeek"
    assert str(provider_config.base_url) == "https://api.deepseek.com/"
    assert provider_config.model == "deepseek-flash"
    assert [model.model for model in config.ai.additional_models] == ["deepseek-v4-pro"]


def test_ai_composition_selects_the_configured_profile_without_reading_the_secret() -> None:
    settings = load_application_config(PROJECT_ROOT / "config" / "app.example.yaml").ai
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(500)))

    try:
        binding = compose_configured_ai_provider(
            settings=settings,
            client=client,
            secret_store=InMemorySecretStore(),
        )
    finally:
        asyncio.run(client.aclose())

    assert binding is not None
    assert binding.profile is AIProviderProfile.DEEPSEEK
    assert binding.config.model == "deepseek-flash"


def test_direct_ai_key_drives_provider_without_project_secret_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    config_path = config_directory / "app.yaml"
    config_path.write_text(
        """\
ai:
  profile: DEEPSEEK
  base_url: https://api.deepseek.com
  model: deepseek-v4-flash
  api_key: direct-config-test-key
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "wrong-process-value")
    settings = load_application_config(config_path).ai
    store = create_configured_secret_store(settings=settings)
    captured_authorization: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_authorization.append(request.headers.get("Authorization"))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-file-secret",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    async def scenario() -> object:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            binding = compose_configured_ai_provider(
                settings=settings,
                client=client,
                secret_store=store,
            )
            assert binding is not None
            return await binding.provider.test_connection(binding.config)

    result = asyncio.run(scenario())

    assert result.connected is True
    assert captured_authorization == ["Bearer direct-config-test-key"]


@pytest.mark.parametrize(
    "legacy_yaml",
    [
        "tushare:\n  token_ref:\n    environment_variable: TUSHARE_TOKEN\n",
        "ai:\n  api_key_ref:\n    file: ../.env\n    key: DEEPSEEK_API_KEY\n",
    ],
)
def test_yaml_rejects_every_legacy_credential_reference(
    tmp_path: Path,
    legacy_yaml: str,
) -> None:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(legacy_yaml, encoding="utf-8")

    with pytest.raises(ValidationError):
        load_application_config(config_path)


def test_configured_ai_command_fails_before_network_when_secret_is_absent(
    tmp_path: Path,
) -> None:
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    config_path = config_directory / "app.yaml"
    config_path.write_text(
        """\
ai:
  base_url: https://api.deepseek.com
  model: deepseek-v4-flash
""",
        encoding="utf-8",
    )
    service = ConfiguredAICommandService(
        config_path=config_path,
    )

    with pytest.raises(RuntimeError, match="not configured"):
        asyncio.run(service.test_connection())


@pytest.mark.parametrize(
    ("yaml_text", "field_path"),
    [
        ("unexpected: true\n", "unexpected"),
        ("web:\n  host: 0.0.0.0\n", "web.host"),
        ("tushare:\n  api_url: http://api.quicksync.cn\n", "tushare.api_url"),
        ("tushare:\n  api_url: https://user:pass@api.quicksync.cn\n", "tushare.api_url"),
        ("tushare:\n  api_url: https://api.quicksync.cn?token=value\n", "tushare.api_url"),
        ("tushare:\n  api_url: https://api.quicksync.cn#fragment\n", "tushare.api_url"),
    ],
)
def test_yaml_rejects_unknown_and_invalid_url_fields(
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


def test_cli_exposes_configured_ai_test_and_extract_commands(tmp_path: Path) -> None:
    source_path = tmp_path / "plan.txt"
    source_path.write_text("低吸区间为 63.00 元到 64.50 元。", encoding="utf-8")
    calls: list[tuple[str, Path]] = []

    class AICommandService:
        async def test_connection(self) -> dict[str, object]:
            calls.append(("test", Path("config/app.yaml")))
            return {"connected": True}

        async def extract(self, source: Path) -> dict[str, object]:
            calls.append(("extract", source))
            return {"status": "SUCCEEDED"}

    def ai_service_factory(config_path: Path) -> AICommandService:
        assert config_path == Path("config/app.yaml")
        return AICommandService()

    results: list[object] = []

    assert (
        run_cli(
            ["ai", "test"],
            ai_service_factory=ai_service_factory,
            result_writer=results.append,
        )
        == 0
    )
    assert (
        run_cli(
            ["ai", "extract", "--source", str(source_path)],
            ai_service_factory=ai_service_factory,
            result_writer=results.append,
        )
        == 0
    )
    assert calls == [("test", Path("config/app.yaml")), ("extract", source_path)]
    assert results == [{"connected": True}, {"status": "SUCCEEDED"}]


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
    for command in ("validate", "monitor", "web", "replay", "backup", "ai", "backtest"):
        assert command in completed.stdout
