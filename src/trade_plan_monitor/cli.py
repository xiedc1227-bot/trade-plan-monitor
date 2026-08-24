"""Side-effect-free command-line parsing and injected runtime service dispatch."""

import argparse
import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

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


RuntimeServiceFactory = Callable[[Path], RuntimeCommandService]


def _return_success(arguments: argparse.Namespace) -> int:
    """Validate the reserved local-only Web declaration before T052 composition."""

    validate_loopback_host(arguments.host)
    validate_web_port(arguments.port)
    return 0


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
    web_parser.set_defaults(handler=_return_success)

    return parser


def main(
    argv: Sequence[str] = (),
    *,
    service_factory: RuntimeServiceFactory | None = None,
) -> int:
    """Parse a command and dispatch only after an explicit service composition."""

    parser = build_parser()
    arguments = parser.parse_args(list(argv))
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
    handler = getattr(arguments, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(arguments)


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "RuntimeCommandService",
    "RuntimeServiceFactory",
    "build_parser",
    "main",
]
