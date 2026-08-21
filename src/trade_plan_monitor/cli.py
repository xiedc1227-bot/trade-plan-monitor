"""No-op command-line declarations for the staged application scaffold."""

import argparse
from collections.abc import Sequence
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("config/app.yaml")


def _return_success(_arguments: argparse.Namespace) -> int:
    """Return successfully without starting any application service."""

    return 0


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

    monitor_parser = commands.add_parser(
        "monitor",
        help="run the headless monitor",
    )
    _add_config_argument(monitor_parser)
    monitor_parser.add_argument("--once", action="store_true", help="run one monitor cycle")

    web_parser = commands.add_parser(
        "web",
        help="serve the local Web application",
    )
    _add_config_argument(web_parser)
    web_parser.add_argument(
        "--host",
        choices=("127.0.0.1",),
        default="127.0.0.1",
        help="local listener address (default: 127.0.0.1)",
    )
    web_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="local listener port (default: 8765)",
    )

    replay_parser = commands.add_parser(
        "replay",
        help="replay deterministic market fixtures",
    )
    _add_config_argument(replay_parser)

    backup_parser = commands.add_parser(
        "backup",
        help="create or inspect local backups",
    )
    _add_config_argument(backup_parser)

    for command_parser in (
        validate_parser,
        monitor_parser,
        web_parser,
        replay_parser,
        backup_parser,
    ):
        command_parser.set_defaults(handler=_return_success)

    return parser


def main(argv: Sequence[str] = ()) -> int:
    """Parse a command and invoke its currently inert declaration."""

    parser = build_parser()
    arguments = parser.parse_args(list(argv))
    handler = getattr(arguments, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(arguments)


__all__ = ["DEFAULT_CONFIG_PATH", "build_parser", "main"]
