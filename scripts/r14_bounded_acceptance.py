"""Optional, explicitly authorized R14 loopback acceptance with physical-call guards.

The default invocation is dry-run. This file never copies or prints credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from trade_plan_monitor.ai.prompts import PLAN_EXTRACTION_PROMPT_V4, build_plan_extraction_prompt

APPROVED_MODEL = "deepseek-v4-pro"
AUTHORIZATION = "R14_3_AI_60_MARKET_IN_APP_15MIN"
APPROVED_DATES = frozenset({date(2026, 9, day) for day in (14, 15, 16)})
_ROOT = Path(__file__).resolve().parents[1]
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_INDEXES = frozenset({"000001.SH", "399001.SZ", "399006.SZ", "000688.SH", "399107.SZ"})
_MARKET_CAPS = {
    "trade_cal": 3,
    "stk_limit": 0,
    "daily": 0,
    "rt_min_daily": 3,
    "rt_min": 15,
    "idx_mins": 5,
    "rt_idx_min_daily": 25,
    "index_daily": 5,
}


class BudgetDenied(RuntimeError):
    """Fixed, secret-free failure before a disallowed physical call."""

    def __init__(self) -> None:
        super().__init__("R14 physical-call budget denied")


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class PhysicalAttemptJournal:
    """Durably retain bounded counters and fixed-enum failure metadata."""

    def __init__(
        self,
        path: Path,
        *,
        proposal_id: str,
        run_id: str,
        started_at: str,
    ) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._state: dict[str, object] = {
            "proposalId": proposal_id,
            "runId": run_id,
            "startedAt": started_at,
            "status": "ACTIVE",
            "normalAuditPresent": False,
            "ai": {},
            "market": {},
            "firstMarketFailure": None,
            "referenceFailureCode": None,
        }
        _write_json_atomic(self._path, self._state)

    def record_budget(self, kind: str, snapshot: dict[str, object]) -> None:
        if kind not in {"ai", "market"}:
            raise ValueError("budget kind must be ai or market")
        with self._lock:
            self._state[kind] = snapshot
            _write_json_atomic(self._path, self._state)

    def record_market_failure(self, operation: str, failure: dict[str, object]) -> None:
        allowed = {"code", "failureKind", "httpStatusClass"}
        if set(failure) != allowed:
            raise ValueError("market failure metadata must use the fixed safe schema")
        with self._lock:
            if self._state["firstMarketFailure"] is None:
                self._state["firstMarketFailure"] = {"operation": operation, **failure}
            self._state["status"] = "FAILURE_STOP_REQUESTED"
            _write_json_atomic(self._path, self._state)

    def record_reference_failure(self, code: str) -> None:
        if code not in {
            "REFERENCE_BLOCKED_PERMISSION",
            "REFERENCE_RATE_LIMITED",
            "REFERENCE_TRANSIENT",
            "REFERENCE_TIMEOUT",
            "REFERENCE_INVALID_RESPONSE",
            "REFERENCE_ERROR",
            "REFERENCE_QUEUE_FULL",
            "REFERENCE_CLOSED",
            "REFERENCE_DATA_UNAVAILABLE",
            "REFERENCE_STORAGE_ERROR",
            "REFERENCE_REFRESH_FAILED",
        }:
            raise ValueError("reference failure code is not in the fixed safe set")
        with self._lock:
            self._state["referenceFailureCode"] = code
            self._state["status"] = "FAILURE_STOP_REQUESTED"
            _write_json_atomic(self._path, self._state)

    def complete(self, *, status: str) -> None:
        with self._lock:
            self._state["status"] = status
            self._state["normalAuditPresent"] = True
            _write_json_atomic(self._path, self._state)


class Budget:
    """Thread-safe, pre-call accounting. Failed requests consume one attempt."""

    def __init__(
        self,
        *,
        total: int,
        per_key: Mapping[str, int],
        seconds: int,
        on_denied: Callable[[], None] | None = None,
        on_snapshot: Callable[[dict[str, object]], None] | None = None,
        gate_lock: threading.Lock | None = None,
        stopped: threading.Event | None = None,
    ) -> None:
        self._total = total
        self._caps = dict(per_key)
        self._deadline = monotonic() + seconds
        self._attempts: dict[str, int] = {}
        self._denied = 0
        self._lock = gate_lock if gate_lock is not None else threading.Lock()
        self._stopped = stopped if stopped is not None else threading.Event()
        self._on_denied = on_denied
        self._on_snapshot = on_snapshot

    def admit(self, key: str) -> None:
        journal_failed = False
        with self._lock:
            count = self._attempts.get(key, 0)
            allowed = (
                not self._stopped.is_set()
                and key in self._caps
                and count < self._caps[key]
                and sum(self._attempts.values()) < self._total
                and monotonic() < self._deadline
            )
            if allowed:
                self._attempts[key] = count + 1
                if self._on_snapshot is not None:
                    try:
                        self._on_snapshot(self._snapshot_unlocked())
                    except Exception:
                        if count == 0:
                            self._attempts.pop(key, None)
                        else:
                            self._attempts[key] = count
                        self._denied += 1
                        self._stopped.set()
                        journal_failed = True
                if not journal_failed:
                    return
            else:
                self._denied += 1
                self._stopped.set()
                if self._on_snapshot is not None:
                    try:
                        self._on_snapshot(self._snapshot_unlocked())
                    except Exception:
                        pass
        if self._on_denied is not None:
            self._on_denied()
        raise BudgetDenied

    def reject(self) -> None:
        """Record an unapproved operation without consuming a physical attempt."""

        with self._lock:
            self._denied += 1
            self._stopped.set()
            if self._on_snapshot is not None:
                try:
                    self._on_snapshot(self._snapshot_unlocked())
                except Exception:
                    pass
        if self._on_denied is not None:
            self._on_denied()
        raise BudgetDenied

    def stop(self) -> None:
        """Stop both shared budgets without counting a pre-network denial."""

        with self._lock:
            already_stopped = self._stopped.is_set()
            self._stopped.set()
            if self._on_snapshot is not None:
                try:
                    self._on_snapshot(self._snapshot_unlocked())
                except Exception:
                    pass
        if not already_stopped and self._on_denied is not None:
            self._on_denied()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> dict[str, object]:
        return {
            "totalCap": self._total,
            "perKeyCaps": self._caps.copy(),
            "totalAttempts": sum(self._attempts.values()),
            "attempts": self._attempts.copy(),
            "deniedBeforeNetwork": self._denied,
            "stopped": self._stopped.is_set(),
        }


def approved_sources(
    *, prompt_version: str = PLAN_EXTRACTION_PROMPT_V4
) -> dict[str, tuple[str, str]]:
    literal = json.loads(
        (_ROOT / "tests/fixtures/ai/explicit-plan-literal-source-v3.json").read_text("utf-8")
    )["sourceText"]
    corpus = json.loads(
        (_ROOT / "tests/fixtures/ai/explicit-plan-semantic-acceptance-v2.json").read_text("utf-8")
    )["cases"]
    sources = {"LITERAL": literal}
    for case_id in ("SEM-AMB-01", "SEM-UNS-01"):
        sources[case_id] = next(case["sourceText"] for case in corpus if case["id"] == case_id)
    return {
        case_id: (
            source,
            build_plan_extraction_prompt(source, prompt_version=prompt_version),
        )
        for case_id, source in sources.items()
    }


def _valid_run_id(run_id: str, now: datetime) -> bool:
    """Bind a single date-labelled run name to the proposed exchange-day range."""

    return now.date() in APPROVED_DATES and run_id == f"r14-{now:%Y%m%d}-a"


def _start_window_eligible(now: datetime) -> bool:
    """Allow one proposed open-day session to start in the morning window."""

    return now.date() in APPROVED_DATES and time(10, 10) <= now.time() <= time(11, 0)


def _claim_session(root: Path, run_id: str) -> Path:
    """Atomically consume this local installation's one R14 session slot."""

    root.mkdir(parents=True, exist_ok=True)
    (root / "_session_claimed").mkdir(exist_ok=False)
    folder = root / run_id
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def _session_budgets(
    on_denied: Callable[[], None],
    *,
    market_caps: Mapping[str, int] = _MARKET_CAPS,
    market_total: int = 60,
    wall_seconds: int = 900,
    on_ai_snapshot: Callable[[dict[str, object]], None] | None = None,
    on_market_snapshot: Callable[[dict[str, object]], None] | None = None,
) -> tuple[Budget, Budget]:
    """Use one shared server-stop signal for either physical-call boundary."""

    gate_lock = threading.Lock()
    stopped = threading.Event()
    return (
        Budget(
            total=3,
            per_key={key: 1 for key in approved_sources()},
            seconds=wall_seconds,
            on_denied=on_denied,
            on_snapshot=on_ai_snapshot,
            gate_lock=gate_lock,
            stopped=stopped,
        ),
        Budget(
            total=market_total,
            per_key=market_caps,
            seconds=wall_seconds,
            on_denied=on_denied,
            on_snapshot=on_market_snapshot,
            gate_lock=gate_lock,
            stopped=stopped,
        ),
    )


class AIBudgetTransport(httpx.AsyncBaseTransport):
    """Allow only the three exact prompts, selected model, endpoint and output cap."""

    def __init__(
        self,
        budget: Budget,
        *,
        inner: httpx.AsyncBaseTransport | None = None,
        prompt_version: str = PLAN_EXTRACTION_PROMPT_V4,
        max_output_tokens: int = 4096,
    ) -> None:
        self._budget = budget
        self._inner = inner or httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        sources = (
            approved_sources()
            if prompt_version == PLAN_EXTRACTION_PROMPT_V4
            else approved_sources(prompt_version=prompt_version)
        )
        self._prompt_ids = {
            sha256(prompt.encode("utf-8")).hexdigest(): case_id
            for case_id, (_, prompt) in sources.items()
        }
        self._max_output_tokens = max_output_tokens

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if (
            request.method != "POST"
            or url.scheme != "https"
            or url.host != "api.deepseek.com"
            or url.port not in (None, 443)
            or url.path != "/chat/completions"
            or url.query
        ):
            self._budget.reject()
        try:
            body = json.loads(request.content)
            messages = body["messages"]
            prompt = messages[0]["content"]
            case_id = self._prompt_ids[sha256(prompt.encode("utf-8")).hexdigest()]
            valid = (
                body["model"] == APPROVED_MODEL
                and len(messages) == 1
                and messages[0]["role"] == "user"
                and body.get("max_tokens") == self._max_output_tokens
                and body.get("temperature") == 0
                and body.get("thinking") == {"type": "disabled"}
                and body.get("response_format") == {"type": "json_object"}
                and body.get("stream") is False
                and len(prompt.encode("utf-8")) <= 19_000
            )
        except KeyError, IndexError, TypeError, UnicodeError, ValueError:
            self._budget.reject()
        if not valid:
            self._budget.reject()
        self._budget.admit(case_id)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


class MarketBudget:
    """Account for every SDK query before its one-shot HTTPS POST."""

    def __init__(
        self,
        budget: Budget,
        *,
        stop_on_failure_keys: frozenset[str] = frozenset(),
        on_failure: Callable[[str, dict[str, object]], None] | None = None,
    ) -> None:
        self._budget = budget
        self._stop_on_failure_keys = stop_on_failure_keys
        self._on_failure = on_failure

    def call(self, query: Callable[..., Any], name: str, fields: str = "", **kwargs: object) -> Any:
        symbol = kwargs.get("ts_code")
        if name in {"rt_min_daily", "rt_min", "daily"}:
            if symbol != "003043.SZ":
                self._budget.reject()
        elif name in {"idx_mins", "rt_idx_min_daily", "index_daily"}:
            if symbol not in _INDEXES:
                self._budget.reject()
        elif name == "trade_cal":
            if kwargs.get("exchange") not in {"SSE", "SZSE"}:
                self._budget.reject()
        elif name == "stk_limit":
            pass
        else:
            self._budget.reject()
        self._budget.admit(name)
        try:
            return query(name, fields=fields, **kwargs)
        except Exception as error:
            from trade_plan_monitor.market_data.tushare import TushareMarketDataProvider

            failure = TushareMarketDataProvider.safe_failure_metadata(name, error)
            try:
                if self._on_failure is not None:
                    self._on_failure(name, failure)
            finally:
                if name in self._stop_on_failure_keys:
                    self._budget.stop()
            raise


def _preflight(
    *,
    start_window_eligible: Callable[[datetime], bool] = _start_window_eligible,
    market_caps: Mapping[str, int] = _MARKET_CAPS,
    market_total: int = 60,
    wall_seconds: int = 900,
    bind_port: int = 18765,
    ai_output_tokens: int = 4096,
    prompt_version: str = PLAN_EXTRACTION_PROMPT_V4,
) -> dict[str, object]:
    from trade_plan_monitor.config import load_application_config
    from trade_plan_monitor.live_profiles import load_stock_certification

    path = _ROOT / "config/app.yaml"
    if not path.exists():
        return {"ready": False, "reason": "CONFIG_MISSING"}
    try:
        configuration = load_application_config(path)
    except Exception:
        return {"ready": False, "reason": "CONFIG_INVALID"}
    market = configuration.tushare
    ai = configuration.ai
    market_url = urlsplit(str(market.api_url)) if market.api_url is not None else None
    ai_url = urlsplit(str(ai.base_url))
    profile = (
        load_stock_certification(
            _ROOT / "data/live-certification/tushare-stock-live.json",
            now=datetime.now(_SHANGHAI),
            endpoint_url=str(market.api_url),
        )
        if market.api_url is not None
        else None
    )
    now = datetime.now(_SHANGHAI)
    eligible = start_window_eligible(now)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", bind_port))
        port_available = True
    except OSError:
        port_available = False
    selected = APPROVED_MODEL in {ai.model, *(item.model for item in ai.additional_models)}
    ready = bool(
        market.token
        and market.connect_ip
        and ai.api_key
        and market_url
        and market_url.scheme == "https"
        and market_url.hostname == "api.quicksync.cn"
        and ai_url.scheme == "https"
        and ai_url.hostname == "api.deepseek.com"
        and selected
        and profile is not None
        and profile.ready
        and eligible
        and port_available
    )
    return {
        "ready": ready,
        "timeShanghai": now.isoformat(),
        "weekdayWindowEligible": eligible,
        "isolatedPortAvailable": port_available,
        "exchangeOpenDayConfirmed": False,
        "ai": {
            "profile": ai.profile.value,
            "selectedModelConfigured": selected,
            "model": APPROVED_MODEL,
            "host": ai_url.hostname,
            "keyPresent": bool(ai.api_key),
        },
        "market": {
            "host": market_url.hostname if market_url else None,
            "connectIpPresent": bool(market.connect_ip),
            "tokenPresent": bool(market.token),
            "stockCertificateReady": bool(profile is not None and profile.ready),
        },
        "limits": {
            "aiPhysicalAttempts": 3,
            "aiPerInputAttempts": 1,
            "aiPromptUtf8Bytes": 19_000,
            "aiOutputTokensPerRequest": ai_output_tokens,
            "promptVersion": prompt_version,
            "marketPhysicalAttempts": market_total,
            "marketPerEndpointAttempts": dict(market_caps),
            "wallSeconds": wall_seconds,
            "browserPort": bind_port,
        },
        "mode": "DRY_RUN_NO_NETWORK",
    }


def _bounded_ai_factory(
    config_path: Path,
    plan_lifecycle: object,
    budget: Budget,
    *,
    database: Path | None = None,
    inner_transport: httpx.AsyncBaseTransport | None = None,
    prompt_version: str = PLAN_EXTRACTION_PROMPT_V4,
    max_output_tokens: int = 4096,
):
    from trade_plan_monitor.web.ai_diagnostics import diagnostic_path_for_database
    from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle

    class BoundedAIWebLifecycle(ConfiguredAIWebLifecycle):
        async def start(self) -> dict[str, object]:
            outcome = await super().start()
            if self._diagnostic_sink_available is False:
                raise BudgetDenied
            selected = self._bindings.get(
                next(
                    (
                        identity
                        for identity, binding in self._bindings.items()
                        if binding.config.model == APPROVED_MODEL
                    ),
                    None,
                )
            )
            if selected is None:
                raise BudgetDenied
            bounded = replace(
                selected,
                config=selected.config.model_copy(
                    update={
                        "max_retries": 0,
                        "max_output_tokens": max_output_tokens,
                        "timeout_seconds": 30,
                        "prompt_version": prompt_version,
                    }
                ),
            )
            self._binding = bounded
            self._bindings = {bounded.config.provider_id: bounded}
            return outcome

    return BoundedAIWebLifecycle(
        config_path=config_path,
        client_factory=lambda: httpx.AsyncClient(
            transport=AIBudgetTransport(
                budget,
                inner=inner_transport,
                prompt_version=prompt_version,
                max_output_tokens=max_output_tokens,
            ),
            timeout=httpx.Timeout(30),
            follow_redirects=False,
            trust_env=False,
        ),
        review_store=plan_lifecycle,
        diagnostic_path=(diagnostic_path_for_database(database) if database is not None else None),
    )


def _guarded_market_factory(original_factory: Callable[[object], object], guard: MarketBudget):
    """Install the same pre-query guard on each production-owned SDK instance."""

    def guarded_factory(settings: object) -> object:
        client = original_factory(settings)
        query = client.query
        client.query = lambda name, fields="", **kwargs: guard.call(query, name, fields, **kwargs)
        return client

    return guarded_factory


def _create_guarded_app(
    *,
    config_path: Path,
    database: Path,
    plan_lifecycle: object,
    ai_budget: Budget,
    static_directory: Path,
    ai_inner_transport: httpx.AsyncBaseTransport | None = None,
    bind_port: int = 18765,
    prompt_version: str = PLAN_EXTRACTION_PROMPT_V4,
    ai_output_tokens: int = 4096,
    on_reference_failure: Callable[[str], None] | None = None,
):
    from trade_plan_monitor.web.app import create_app
    from trade_plan_monitor.web.monitor_composition import create_monitor_composition_factory

    return create_app(
        runtime_factory=create_monitor_composition_factory(
            config_path=config_path,
            database_path=database,
            on_reference_failure=on_reference_failure,
        ),
        plan_lifecycle_factory=lambda: plan_lifecycle,
        ai_lifecycle_factory=lambda: _bounded_ai_factory(
            config_path,
            plan_lifecycle,
            ai_budget,
            database=database,
            inner_transport=ai_inner_transport,
            prompt_version=prompt_version,
            max_output_tokens=ai_output_tokens,
        ),
        bind_host="127.0.0.1",
        bind_port=bind_port,
        static_directory=static_directory,
    )


async def _deactivate_isolated_plan(database: Path) -> str:
    """Leave a test-owned plan inactive even if the browser session ended early."""

    if not database.exists():
        return "NO_DATABASE"
    from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
    from trade_plan_monitor.web.routers.plans import PlanDeactivationCommand
    from trade_plan_monitor.web.schemas import MutationContext

    plans = PersistentPlanWebLifecycle(
        database_path=database, clock=lambda: datetime.now(_SHANGHAI)
    )
    await plans.start()
    try:
        state = await plans.get_plan_activation_state(symbol="003043.SZ")
        if state is None or not state.active:
            return "INACTIVE"
        await plans.deactivate_plan(
            command=PlanDeactivationCommand(symbol="003043.SZ", expected_revision=state.revision),
            context=MutationContext(idempotency_key=uuid4().hex, request_id=uuid4().hex),
        )
        return "DEACTIVATED"
    finally:
        await plans.stop()


async def _recover_activated_symbol(runtime: object, trade_date: date) -> dict[str, object]:
    """Use the existing production recovery service once after UI activation."""

    pipeline = runtime._runtime._run_deadline.__self__._pipeline
    if pipeline is None:
        return {"status": "NOT_RUN_PIPELINE_UNAVAILABLE"}
    result = await pipeline.recovery.recover_startup(trade_date=trade_date)
    return {
        "mode": "TEST_TRIGGERED_PRODUCTION_RECOVERY",
        "attemptedSymbols": list(result.attempted_symbols),
        "persistedMinuteBars": result.persisted_bar_count,
        "yieldedToRealtime": result.yielded_to_realtime,
        "errorCodes": [
            None if item.error_code is None else item.error_code.value for item in result.results
        ],
    }


async def _serve(
    run_id: str,
    *,
    session_root: Path | None = None,
    market_caps: Mapping[str, int] = _MARKET_CAPS,
    market_total: int = 60,
    wall_seconds: int = 900,
    proposal_id: str = "R14",
    bind_port: int = 18765,
    prompt_version: str = PLAN_EXTRACTION_PROMPT_V4,
    ai_output_tokens: int = 4096,
    stop_on_market_failure_keys: frozenset[str] = frozenset(),
    stop_on_reference_failure: bool = False,
) -> int:
    import uvicorn

    from trade_plan_monitor.config import load_application_config
    from trade_plan_monitor.runtime import production
    from trade_plan_monitor.web.app import installed_web_assets
    from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", bind_port))
        listener.listen(128)
        listener.setblocking(False)
    except OSError:
        listener.close()
        raise BudgetDenied from None
    root = session_root if session_root is not None else _ROOT / "data/r14-acceptance"
    try:
        folder = _claim_session(root, run_id)
    except BaseException:
        listener.close()
        raise
    database = folder / "monitor.sqlite3"
    config_path = _ROOT / "config/app.yaml"
    try:
        configuration = load_application_config(config_path)
        if configuration.tushare.connect_ip is None:
            raise BudgetDenied
    except BaseException:
        listener.close()
        raise
    server: uvicorn.Server | None = None
    task: asyncio.Task[None] | None = None
    started_at = datetime.now(_SHANGHAI).isoformat()
    try:
        journal = PhysicalAttemptJournal(
            folder / "physical-attempts.json",
            proposal_id=proposal_id,
            run_id=run_id,
            started_at=started_at,
        )
    except OSError:
        listener.close()
        raise BudgetDenied from None
    first_market_failure: dict[str, object] | None = None
    reference_failure_code: str | None = None
    failure_lock = threading.Lock()

    def stop_server() -> None:
        if server is not None:
            server.should_exit = True

    def record_market_failure(operation: str, failure: dict[str, object]) -> None:
        nonlocal first_market_failure
        safe_failure = {"operation": operation, **failure}
        with failure_lock:
            if first_market_failure is None:
                first_market_failure = safe_failure
        journal.record_market_failure(operation, failure)

    ai_budget, market_budget = _session_budgets(
        stop_server,
        market_caps=market_caps,
        market_total=market_total,
        wall_seconds=wall_seconds,
        on_ai_snapshot=lambda snapshot: journal.record_budget("ai", snapshot),
        on_market_snapshot=lambda snapshot: journal.record_budget("market", snapshot),
    )
    try:
        journal.record_budget("ai", ai_budget.snapshot())
        journal.record_budget("market", market_budget.snapshot())
    except OSError:
        listener.close()
        raise BudgetDenied from None

    def record_reference_failure(code: str) -> None:
        nonlocal reference_failure_code
        if not stop_on_reference_failure:
            return
        with failure_lock:
            if reference_failure_code is None:
                reference_failure_code = code
        try:
            journal.record_reference_failure(code)
        finally:
            market_budget.stop()

    market_guard = MarketBudget(
        market_budget,
        stop_on_failure_keys=stop_on_market_failure_keys,
        on_failure=record_market_failure,
    )
    original_factory = production.create_tushare_client

    production.create_tushare_client = _guarded_market_factory(original_factory, market_guard)
    audit: dict[str, object] = {
        "proposalId": proposal_id,
        "runId": run_id,
        "startedAt": started_at,
        "database": "monitor.sqlite3",
        "channel": "IN_APP_ONLY",
        "aiModel": APPROVED_MODEL,
        "status": "STARTED",
        "activationRecovery": "NOT_RUN_NO_ACTIVE_PLAN",
    }
    try:
        plan_lifecycle = PersistentPlanWebLifecycle(
            database_path=database, clock=lambda: datetime.now(_SHANGHAI)
        )
        with installed_web_assets() as static_directory:
            app = _create_guarded_app(
                config_path=config_path,
                database=database,
                plan_lifecycle=plan_lifecycle,
                ai_budget=ai_budget,
                static_directory=static_directory,
                bind_port=bind_port,
                prompt_version=prompt_version,
                ai_output_tokens=ai_output_tokens,
                on_reference_failure=record_reference_failure,
            )
            server = uvicorn.Server(
                uvicorn.Config(
                    app, host="127.0.0.1", port=bind_port, log_level="warning", access_log=False
                )
            )

            async def recover_after_activation() -> None:
                while not server.should_exit:
                    if getattr(app.state, "plan_web_lifecycle", None) is plan_lifecycle:
                        state = await plan_lifecycle.get_plan_activation_state(symbol="003043.SZ")
                        if state is not None and state.active:
                            runtime = app.state.runtime_lifecycle
                            try:
                                audit["activationRecovery"] = await _recover_activated_symbol(
                                    runtime, datetime.now(_SHANGHAI).date()
                                )
                            except Exception as error:
                                audit["activationRecovery"] = "FAILED"
                                audit["activationRecoveryErrorType"] = type(error).__name__
                            return
                    await asyncio.sleep(1)

            print(
                json.dumps(
                    {"status": "STARTING_BROWSER", "url": f"http://127.0.0.1:{bind_port}"}
                ),
                flush=True,
            )
            task = asyncio.create_task(server.serve(sockets=[listener]))
            recovery_task = asyncio.create_task(recover_after_activation())
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=wall_seconds)
            except TimeoutError:
                audit["status"] = "WALL_LIMIT_REACHED"
                server.should_exit = True
            else:
                with failure_lock:
                    observed_failure = (
                        None if first_market_failure is None else dict(first_market_failure)
                    )
                    observed_reference_code = reference_failure_code
                if observed_reference_code is not None:
                    audit["status"] = "REFERENCE_FAILED"
                    audit["referenceFailureCode"] = observed_reference_code
                    if observed_failure is not None:
                        audit["firstMarketFailure"] = observed_failure
                elif observed_failure is not None:
                    audit["status"] = "MARKET_FAILED"
                    audit["firstMarketFailure"] = observed_failure
                else:
                    audit["status"] = "STOPPED" if server.started else "STARTUP_FAILED"
            finally:
                recovery_task.cancel()
                await asyncio.gather(recovery_task, return_exceptions=True)
    except BaseException as error:
        audit["status"] = "FAILED"
        audit["errorType"] = type(error).__name__
        return_code = 1
    else:
        return_code = (
            1
            if audit["status"] in {"STARTUP_FAILED", "REFERENCE_FAILED", "MARKET_FAILED"}
            else 0
        )
    finally:
        cleanup_deadline = monotonic() + 20
        if server is not None:
            server.should_exit = True
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(task), timeout=max(0, cleanup_deadline - monotonic())
                )
            except BaseException:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                audit["status"] = "SHUTDOWN_FAILED"
                return_code = 1
        listener.close()
        production.create_tushare_client = original_factory
        try:
            audit["isolatedPlanCleanup"] = await asyncio.wait_for(
                _deactivate_isolated_plan(database),
                timeout=max(0, cleanup_deadline - monotonic()),
            )
        except Exception as error:
            audit["isolatedPlanCleanup"] = "FAILED"
            audit["cleanupErrorType"] = type(error).__name__
            return_code = 1
        audit["finishedAt"] = datetime.now(_SHANGHAI).isoformat()
        audit["ai"] = ai_budget.snapshot()
        audit["market"] = market_budget.snapshot()
        if audit["ai"]["deniedBeforeNetwork"] > 0 or audit["market"]["deniedBeforeNetwork"] > 0:
            audit["status"] = "BUDGET_DENIED"
            return_code = 1
        _write_json_atomic(folder / "audit.json", audit)
        journal.complete(status=str(audit["status"]))
        print(json.dumps(audit, sort_keys=True), flush=True)
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorize", default="")
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    preflight = _preflight()
    if not args.execute:
        print(json.dumps(preflight, ensure_ascii=False, sort_keys=True))
        return 0
    if args.authorize != AUTHORIZATION or not preflight.get("ready"):
        print(json.dumps({"status": "NOT_RUN_AUTHORIZATION_OR_PREFLIGHT"}))
        return 2
    if not _valid_run_id(args.run_id, datetime.now(_SHANGHAI)):
        print(json.dumps({"status": "NOT_RUN_INVALID_ID"}))
        return 2
    try:
        return asyncio.run(_serve(args.run_id))
    except FileExistsError:
        print(json.dumps({"status": "NOT_RUN_SESSION_ALREADY_CLAIMED"}))
        return 2
    except BudgetDenied:
        print(json.dumps({"status": "NOT_RUN_PRECONDITION_DENIED"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
