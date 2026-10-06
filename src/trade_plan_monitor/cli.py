"""Side-effect-free command-line parsing and injected runtime service dispatch."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI

from trade_plan_monitor.web.origin_guard import (
    DEFAULT_WEB_PORT,
    LOOPBACK_HOST,
    validate_loopback_host,
    validate_web_port,
)

DEFAULT_CONFIG_PATH = Path("config/app.yaml")


class RuntimeCommandService(Protocol):
    """Asynchronous operations supplied by the application composition root."""

    async def validate(self) -> object: ...

    async def once(self) -> object: ...

    async def run(self) -> object: ...

    async def replay(self) -> object: ...

    async def backup(self) -> object: ...


class AICommandService(Protocol):
    """Explicit paid-network AI operations selected by the local user."""

    async def test_connection(self) -> object: ...

    async def extract(self, source: Path) -> object: ...


RuntimeServiceFactory = Callable[[Path], RuntimeCommandService]
AIServiceFactory = Callable[[Path], AICommandService]
WebAppFactory = Callable[..., AbstractContextManager[FastAPI]]
WebServerRunner = Callable[..., object]
ResultWriter = Callable[[object], None]


def _default_web_app_factory(
    *,
    config_path: Path,
    bind_host: str,
    bind_port: int,
) -> AbstractContextManager[FastAPI]:
    """Load the installed production application only after Web dispatch."""

    from trade_plan_monitor.web.app import create_production_app

    return create_production_app(
        config_path=config_path,
        bind_host=bind_host,
        bind_port=bind_port,
    )


def _default_web_server_runner(application: FastAPI, *, host: str, port: int) -> object:
    """Run Uvicorn without importing it during CLI parsing or module import."""

    import uvicorn

    return uvicorn.run(application, host=host, port=port)


def _default_ai_service_factory(config_path: Path) -> AICommandService:
    from trade_plan_monitor.ai.command import ConfiguredAICommandService

    return ConfiguredAICommandService(config_path=config_path)


def _loopback_host(value: str) -> str:
    try:
        return validate_loopback_host(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _web_port(value: str) -> int:
    try:
        port = int(value)
        return validate_web_port(port)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="application YAML path (default: config/app.yaml)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the stable top-level command declarations."""

    parser = argparse.ArgumentParser(
        prog="trade-plan-monitor",
        description="Local AI-assisted deterministic trade-plan monitor.",
    )
    commands = parser.add_subparsers(dest="command", title="commands")

    validate_parser = commands.add_parser(
        "validate",
        help="validate configuration and plans",
    )
    _add_config_argument(validate_parser)
    validate_parser.set_defaults(service_operation="validate")

    monitor_parser = commands.add_parser(
        "monitor",
        help="run the headless monitor",
    )
    _add_config_argument(monitor_parser)
    monitor_parser.add_argument("--once", action="store_true", help="run one monitor cycle")
    monitor_parser.set_defaults(service_operation="monitor")

    web_parser = commands.add_parser(
        "web",
        help="serve the local Web application",
    )
    _add_config_argument(web_parser)
    web_parser.add_argument(
        "--host",
        type=_loopback_host,
        default=LOOPBACK_HOST,
        help="loopback-only listener; public/LAN exposure is unsupported",
    )
    web_parser.add_argument(
        "--port",
        type=_web_port,
        default=DEFAULT_WEB_PORT,
        help="local listener port (default: 8765)",
    )

    replay_parser = commands.add_parser(
        "replay",
        help="replay deterministic market fixtures",
    )
    _add_config_argument(replay_parser)
    replay_parser.set_defaults(service_operation="replay")

    backup_parser = commands.add_parser(
        "backup",
        help="create or inspect local backups",
    )
    _add_config_argument(backup_parser)
    backup_parser.set_defaults(service_operation="backup")

    ai_parser = commands.add_parser(
        "ai",
        help="test or use the configured AI provider",
    )
    ai_commands = ai_parser.add_subparsers(
        dest="ai_command",
        title="ai commands",
        required=True,
    )

    ai_test_parser = ai_commands.add_parser(
        "test",
        help="make one paid provider connectivity request",
    )
    _add_config_argument(ai_test_parser)
    ai_test_parser.set_defaults(ai_operation="test_connection")

    ai_extract_parser = ai_commands.add_parser(
        "extract",
        help="extract one review-only plan draft from a UTF-8 text file",
    )
    _add_config_argument(ai_extract_parser)
    ai_extract_parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="UTF-8 natural-language plan source",
    )
    ai_extract_parser.set_defaults(ai_operation="extract")

    return parser


def main(
    argv: Sequence[str] = (),
    *,
    service_factory: RuntimeServiceFactory | None = None,
    ai_service_factory: AIServiceFactory | None = None,
    web_app_factory: WebAppFactory | None = None,
    web_server_runner: WebServerRunner | None = None,
    result_writer: ResultWriter | None = None,
) -> int:
    """Parse a command and dispatch only after an explicit service composition."""

    parser = build_parser()
    arguments = parser.parse_args(list(argv))
    if arguments.command == "ai":
        factory = ai_service_factory or _default_ai_service_factory
        service = factory(arguments.config)
        if arguments.ai_operation == "test_connection":
            result = asyncio.run(service.test_connection())
        else:
            result = asyncio.run(service.extract(arguments.source))
        (result_writer or _write_result)(result)
        return 0
    if arguments.command == "web":
        app_factory = web_app_factory or _default_web_app_factory
        server_runner = web_server_runner or _default_web_server_runner
        with app_factory(
            config_path=arguments.config,
            bind_host=arguments.host,
            bind_port=arguments.port,
        ) as application:
            server_runner(application, host=arguments.host, port=arguments.port)
        return 0
    operation = getattr(arguments, "service_operation", None)
    if operation is not None:
        if service_factory is None:
            raise RuntimeError("runtime service factory is not configured")
        service = service_factory(arguments.config)
        if operation == "monitor":
            operation = "once" if arguments.once else "run"
        handler = getattr(service, operation, None)
        if not callable(handler):
            raise TypeError(f"runtime service does not expose {operation}")
        asyncio.run(handler())
        return 0
    parser.print_help()
    return 0


def _write_result(value: object) -> None:
    model_dump_json = getattr(value, "model_dump_json", None)
    if callable(model_dump_json):
        print(model_dump_json(indent=2))
        return
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def console_main() -> int:
    """Run the installed console entry with the process argument vector."""

    return main(sys.argv[1:])


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "AICommandService",
    "AIServiceFactory",
    "RuntimeCommandService",
    "RuntimeServiceFactory",
    "WebAppFactory",
    "WebServerRunner",
    "build_parser",
    "console_main",
    "main",
]
