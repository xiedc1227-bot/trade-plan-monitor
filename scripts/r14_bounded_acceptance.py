"""Optional, explicitly authorized R14 loopback acceptance with physical-call guards.

The default invocation is dry-run. This file never copies or prints credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
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
AUTHORIZATION = "R14_3_AI_30_MARKET_IN_APP_15MIN"
_ROOT = Path(__file__).resolve().parents[1]
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_INDEXES = frozenset({"000001.SH", "399001.SZ", "399006.SZ", "000688.SH", "399107.SZ"})
_MARKET_CAPS = {
    "trade_cal": 2,
    "stk_limit": 0,
    "daily": 0,
    "rt_min_daily": 3,
    "rt_min": 4,
    "idx_mins": 5,
    "rt_idx_min_daily": 12,
    "index_daily": 5,
}


class BudgetDenied(RuntimeError):
    """Fixed, secret-free failure before a disallowed physical call."""

    def __init__(self) -> None:
        super().__init__("R14 physical-call budget denied")


class Budget:
    """Thread-safe, pre-call accounting. Failed requests consume one attempt."""

    def __init__(
        self,
        *,
        total: int,
        per_key: Mapping[str, int],
        seconds: int,
        on_denied: Callable[[], None] | None = None,
    ) -> None:
        self._total = total
        self._caps = dict(per_key)
        self._deadline = monotonic() + seconds
        self._attempts: dict[str, int] = {}
        self._denied = 0
        self._lock = threading.Lock()
        self._on_denied = on_denied

    def admit(self, key: str) -> None:
        with self._lock:
            count = self._attempts.get(key, 0)
            allowed = (
                key in self._caps
                and count < self._caps[key]
                and sum(self._attempts.values()) < self._total
                and monotonic() < self._deadline
            )
            if allowed:
                self._attempts[key] = count + 1
                return
            self._denied += 1
        if self._on_denied is not None:
            self._on_denied()
        raise BudgetDenied

    def reject(self) -> None:
        """Record an unapproved operation without consuming a physical attempt."""

        with self._lock:
            self._denied += 1
        if self._on_denied is not None:
            self._on_denied()
        raise BudgetDenied

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "totalCap": self._total,
                "perKeyCaps": self._caps.copy(),
                "totalAttempts": sum(self._attempts.values()),
                "attempts": self._attempts.copy(),
                "deniedBeforeNetwork": self._denied,
            }


def approved_sources() -> dict[str, tuple[str, str]]:
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
            build_plan_extraction_prompt(source, prompt_version=PLAN_EXTRACTION_PROMPT_V4),
        )
        for case_id, source in sources.items()
    }


class AIBudgetTransport(httpx.AsyncBaseTransport):
    """Allow only the three exact prompts, selected model, endpoint and output cap."""

    def __init__(self, budget: Budget, *, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self._budget = budget
        self._inner = inner or httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        self._prompt_ids = {
            sha256(prompt.encode("utf-8")).hexdigest(): case_id
            for case_id, (_, prompt) in approved_sources().items()
        }

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
                and body.get("max_tokens") == 4096
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

    def __init__(self, budget: Budget) -> None:
        self._budget = budget

    def call(self, query: Callable[..., Any], name: str, fields: str = "", **kwargs: object) -> Any:
        symbol = kwargs.get("ts_code")
        if name in {"rt_min_daily", "rt_min", "daily"}:
            if symbol != "003043.SZ":
                self._budget.reject()
        elif name in {"idx_mins", "rt_idx_min_daily", "index_daily"}:
            if symbol not in _INDEXES:
                self._budget.reject()
        elif name in {"trade_cal", "stk_limit"}:
            pass
        else:
            self._budget.reject()
        self._budget.admit(name)
        return query(name, fields=fields, **kwargs)


def _preflight() -> dict[str, object]:
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
    eligible = now.weekday() < 5 and time(13, 10) <= now.time() <= time(14, 30)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 18765))
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
            "aiOutputTokensPerRequest": 4_096,
            "marketPhysicalAttempts": 30,
            "marketPerEndpointAttempts": _MARKET_CAPS,
            "wallSeconds": 900,
            "browserPort": 18765,
        },
        "mode": "DRY_RUN_NO_NETWORK",
    }


def _bounded_ai_factory(config_path: Path, plan_lifecycle: object, budget: Budget):
    from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle

    class BoundedAIWebLifecycle(ConfiguredAIWebLifecycle):
        async def start(self) -> dict[str, object]:
            outcome = await super().start()
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
                    update={"max_retries": 0, "max_output_tokens": 4096}
                ),
            )
            self._binding = bounded
            self._bindings = {bounded.config.provider_id: bounded}
            return outcome

    return BoundedAIWebLifecycle(
        config_path=config_path,
        client_factory=lambda: httpx.AsyncClient(
            transport=AIBudgetTransport(budget),
            timeout=httpx.Timeout(30),
            follow_redirects=False,
            trust_env=False,
        ),
        review_store=plan_lifecycle,
    )


async def _deactivate_isolated_plan(database: Path) -> str:
    """Leave a test-owned plan inactive even if the browser session ended early."""

    if not database.exists():
        return "NO_DATABASE"
    from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle
    from trade_plan_monitor.web.routers.plans import PlanDeactivationCommand
    from trade_plan_monitor.web.schemas import MutationContext

    plans = PersistentPlanWebLifecycle(database_path=database)
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


async def _serve(run_id: str) -> int:
    import uvicorn

    from trade_plan_monitor.config import load_application_config
    from trade_plan_monitor.runtime import production
    from trade_plan_monitor.web.app import create_app, installed_web_assets
    from trade_plan_monitor.web.monitor_composition import create_monitor_composition_factory
    from trade_plan_monitor.web.plan_service import PersistentPlanWebLifecycle

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 18765))
        listener.listen(128)
        listener.setblocking(False)
    except OSError:
        listener.close()
        raise BudgetDenied from None
    folder = _ROOT / "data/r14-acceptance" / run_id
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except BaseException:
        listener.close()
        raise
    database = folder / "monitor.sqlite3"
    config_path = _ROOT / "config/app.yaml"
    configuration = load_application_config(config_path)
    if configuration.tushare.connect_ip is None:
        raise BudgetDenied
    server: uvicorn.Server | None = None
    task: asyncio.Task[None] | None = None

    def stop_server() -> None:
        if server is not None:
            server.should_exit = True

    ai_budget = Budget(
        total=3, per_key={key: 1 for key in approved_sources()}, seconds=900, on_denied=stop_server
    )
    market_budget = Budget(total=30, per_key=_MARKET_CAPS, seconds=900, on_denied=stop_server)
    market_guard = MarketBudget(market_budget)
    original_factory = production.create_tushare_client

    def guarded_factory(settings: object) -> object:
        client = original_factory(settings)
        query = client.query
        client.query = lambda name, fields="", **kwargs: market_guard.call(
            query, name, fields, **kwargs
        )
        return client

    production.create_tushare_client = guarded_factory
    audit: dict[str, object] = {
        "runId": run_id,
        "startedAt": datetime.now(_SHANGHAI).isoformat(),
        "database": "monitor.sqlite3",
        "channel": "IN_APP_ONLY",
        "aiModel": APPROVED_MODEL,
        "status": "STARTED",
        "activationRecovery": "NOT_RUN_NO_ACTIVE_PLAN",
    }
    try:
        plan_lifecycle = PersistentPlanWebLifecycle(database_path=database)
        with installed_web_assets() as static_directory:
            app = create_app(
                runtime_factory=create_monitor_composition_factory(
                    config_path=config_path, database_path=database
                ),
                plan_lifecycle_factory=lambda: plan_lifecycle,
                ai_lifecycle_factory=lambda: _bounded_ai_factory(
                    config_path, plan_lifecycle, ai_budget
                ),
                bind_host="127.0.0.1",
                bind_port=18765,
                static_directory=static_directory,
            )
            server = uvicorn.Server(
                uvicorn.Config(
                    app, host="127.0.0.1", port=18765, log_level="warning", access_log=False
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
                json.dumps({"status": "STARTING_BROWSER", "url": "http://127.0.0.1:18765"}),
                flush=True,
            )
            task = asyncio.create_task(server.serve(sockets=[listener]))
            recovery_task = asyncio.create_task(recover_after_activation())
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=900)
            except TimeoutError:
                audit["status"] = "WALL_LIMIT_REACHED"
                server.should_exit = True
                await asyncio.wait_for(task, timeout=20)
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
        return_code = 0 if audit["status"] != "STARTUP_FAILED" else 1
    finally:
        if server is not None:
            server.should_exit = True
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=20)
            except BaseException:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                audit["status"] = "SHUTDOWN_FAILED"
                return_code = 1
        listener.close()
        try:
            audit["isolatedPlanCleanup"] = await _deactivate_isolated_plan(database)
        except Exception as error:
            audit["isolatedPlanCleanup"] = "FAILED"
            audit["cleanupErrorType"] = type(error).__name__
            return_code = 1
        audit["finishedAt"] = datetime.now(_SHANGHAI).isoformat()
        audit["ai"] = ai_budget.snapshot()
        audit["market"] = market_budget.snapshot()
        (folder / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
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
    if not args.run_id or not args.run_id.isascii() or not args.run_id.replace("-", "").isalnum():
        print(json.dumps({"status": "NOT_RUN_INVALID_ID"}))
        return 2
    return asyncio.run(_serve(args.run_id))


if __name__ == "__main__":
    raise SystemExit(main())
