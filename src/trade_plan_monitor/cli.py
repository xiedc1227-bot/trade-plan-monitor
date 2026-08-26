"""Side-effect-free command-line parsing and injected runtime service dispatch."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from decimal import Decimal, InvalidOperation
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
DEFAULT_BACKTEST_MARKET_DATABASE = Path("data/backtest-market.sqlite3")
DEFAULT_BACKTEST_RESULTS_DATABASE = Path("data/backtest-results.sqlite3")
DEFAULT_BACKTEST_REPORT_DIRECTORY = Path("backtest-reports")


class RuntimeCommandService(Protocol):
    """Asynchronous operations supplied by the application composition root."""

    async def validate(self) -> object: ...

    async def once(self) -> object: ...

    async def run(self) -> object: ...

    async def replay(self) -> object: ...

    async def backup(self) -> object: ...


class BacktestCommandService(Protocol):
    """Explicit local/network-separated backtest command surface."""

    async def sync(self, **kwargs: object) -> object: ...

    def verify(self, **kwargs: object) -> object: ...

    def run(self, **kwargs: object) -> object: ...

    def list_runs(self, **kwargs: object) -> object: ...

    def prune(self, **kwargs: object) -> object: ...


RuntimeServiceFactory = Callable[[Path], RuntimeCommandService]
BacktestServiceFactory = Callable[[Path, Path, Path, Path], BacktestCommandService]
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


def _default_backtest_service_factory(
    config_path: Path,
    market_database: Path,
    results_database: Path,
    report_directory: Path,
) -> BacktestCommandService:
    from trade_plan_monitor.backtest.application import BacktestApplicationService

    return BacktestApplicationService(
        config_path=config_path,
        market_database=market_database,
        results_database=results_database,
        report_directory=report_directory,
    )


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


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error


def _decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("value must be a decimal number") from error
    if not parsed.is_finite():
        raise argparse.ArgumentTypeError("value must be finite")
    return parsed


def _add_config_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="application YAML path (default: config/app.yaml)",
    )


def _add_backtest_storage_arguments(parser: argparse.ArgumentParser) -> None:
    _add_config_argument(parser)
    parser.add_argument(
        "--market-db",
        type=Path,
        default=DEFAULT_BACKTEST_MARKET_DATABASE,
        help="isolated historical market SQLite path",
    )
    parser.add_argument(
        "--results-db",
        type=Path,
        default=DEFAULT_BACKTEST_RESULTS_DATABASE,
        help="isolated backtest result SQLite path",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_BACKTEST_REPORT_DIRECTORY,
        help="stable JSON/CSV report directory",
    )


def _add_backtest_scope_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--symbols", nargs="+", required=True, help="1-10 A-share symbols")
    parser.add_argument("--start", type=_iso_date, required=True, help="first replay date")
    parser.add_argument("--end", type=_iso_date, required=True, help="last replay date")
    parser.add_argument(
        "--warmup-start",
        type=_iso_date,
        help="daily-indicator warm-up boundary (default: start minus 400 calendar days)",
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

    backtest_parser = commands.add_parser(
        "backtest",
        help="synchronize and run isolated deterministic historical backtests",
    )
    backtest_commands = backtest_parser.add_subparsers(
        dest="backtest_command",
        title="backtest commands",
        required=True,
    )

    sync_parser = backtest_commands.add_parser(
        "sync",
        help="explicitly download missing historical market facts",
    )
    _add_backtest_storage_arguments(sync_parser)
    _add_backtest_scope_arguments(sync_parser)
    sync_parser.add_argument("--refresh", action="store_true", help="recheck existing heads")
    sync_parser.add_argument(
        "--allow-network",
        action="store_true",
        help="explicitly authorize Tushare/QuickSync network access",
    )
    sync_parser.set_defaults(backtest_operation="sync")

    verify_parser = backtest_commands.add_parser(
        "verify",
        help="locally freeze a content-addressed dataset",
    )
    _add_backtest_storage_arguments(verify_parser)
    _add_backtest_scope_arguments(verify_parser)
    verify_parser.set_defaults(backtest_operation="verify")

    run_parser = backtest_commands.add_parser(
        "run",
        help="run a frozen dataset fully offline",
    )
    _add_backtest_storage_arguments(run_parser)
    run_parser.add_argument("--dataset", required=True, help="verified dataset SHA-256")
    run_parser.add_argument("--plan", type=Path, required=True, help="reviewed YAML/JSON plan")
    run_parser.add_argument(
        "--initial-cash-yuan",
        type=_decimal,
        required=True,
        help="positive initial cash with at most two decimals",
    )
    run_parser.add_argument("--commission-rate", type=_decimal, required=True)
    run_parser.add_argument("--minimum-commission-yuan", type=_decimal, required=True)
    run_parser.add_argument("--stamp-duty-rate", type=_decimal, required=True)
    run_parser.add_argument("--transfer-fee-rate", type=_decimal, required=True)
    run_parser.add_argument("--buy-slippage-bps", type=_decimal, required=True)
    run_parser.add_argument("--sell-slippage-bps", type=_decimal, required=True)
    event_risk = run_parser.add_mutually_exclusive_group(required=True)
    event_risk.add_argument(
        "--no-event-risk",
        dest="manual_event_risk",
        action="store_false",
        help="record the explicit assumption that no material event risk is known",
    )
    event_risk.add_argument(
        "--manual-event-risk",
        dest="manual_event_risk",
        action="store_true",
        help="record an active material event-risk blocker",
    )
    run_parser.set_defaults(backtest_operation="run")

    list_parser = backtest_commands.add_parser("list", help="list retained run summaries")
    _add_backtest_storage_arguments(list_parser)
    list_parser.add_argument("--limit", type=int, default=100)
    list_parser.add_argument("--offset", type=int, default=0)
    list_parser.set_defaults(backtest_operation="list")

    prune_parser = backtest_commands.add_parser(
        "prune",
        help="delete one bounded batch of expired result details",
    )
    _add_backtest_storage_arguments(prune_parser)
    prune_parser.add_argument("--batch-size", type=int, default=1_000)
    prune_parser.set_defaults(backtest_operation="prune")

    return parser


def main(
    argv: Sequence[str] = (),
    *,
    service_factory: RuntimeServiceFactory | None = None,
    backtest_service_factory: BacktestServiceFactory | None = None,
    web_app_factory: WebAppFactory | None = None,
    web_server_runner: WebServerRunner | None = None,
    result_writer: ResultWriter | None = None,
) -> int:
    """Parse a command and dispatch only after an explicit service composition."""

    parser = build_parser()
    arguments = parser.parse_args(list(argv))
    if arguments.command == "backtest":
        factory = backtest_service_factory or _default_backtest_service_factory
        service = factory(
            arguments.config,
            arguments.market_db,
            arguments.results_db,
            arguments.report_dir,
        )
        operation = arguments.backtest_operation
        if operation == "sync":
            result = asyncio.run(
                service.sync(
                    symbols=tuple(arguments.symbols),
                    start=arguments.start,
                    end=arguments.end,
                    warmup_start=arguments.warmup_start,
                    refresh=arguments.refresh,
                    allow_network=arguments.allow_network,
                )
            )
        elif operation == "verify":
            result = service.verify(
                symbols=tuple(arguments.symbols),
                start=arguments.start,
                end=arguments.end,
                warmup_start=arguments.warmup_start,
            )
        elif operation == "run":
            result = service.run(
                dataset_hash=arguments.dataset,
                plan_path=arguments.plan,
                initial_cash_yuan=arguments.initial_cash_yuan,
                commission_rate=arguments.commission_rate,
                minimum_commission_yuan=arguments.minimum_commission_yuan,
                stamp_duty_rate=arguments.stamp_duty_rate,
                transfer_fee_rate=arguments.transfer_fee_rate,
                buy_slippage_bps=arguments.buy_slippage_bps,
                sell_slippage_bps=arguments.sell_slippage_bps,
                manual_event_risk=arguments.manual_event_risk,
            )
        elif operation == "list":
            result = service.list_runs(limit=arguments.limit, offset=arguments.offset)
        else:
            result = service.prune(batch_size=arguments.batch_size)
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
    "BacktestCommandService",
    "BacktestServiceFactory",
    "RuntimeCommandService",
    "RuntimeServiceFactory",
    "WebAppFactory",
    "WebServerRunner",
    "build_parser",
    "console_main",
    "main",
]
