"""Isolated offline daily browser fixture; real APIs, SQLite and daily participant."""

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from tests.integration.test_daily_plan_chain import FRIDAY, SH, SYMBOL, TUESDAY, WEDNESDAY, Chain
from tests.integration.test_web_api import _FakeMonitorReadService
from tests.unit.test_ai_plan_extraction_v4 import _config

from trade_plan_monitor.ai.composition import ConfiguredAIProviderBinding
from trade_plan_monitor.ai.models import AIProviderProfile
from trade_plan_monitor.ai.provider import AIUsage, RawAIResponse
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.domain.daily_plan_validation import DailyPlanDraft
from trade_plan_monitor.state.models import TradingCalendar
from trade_plan_monitor.web.ai_service import ConfiguredAIWebLifecycle
from trade_plan_monitor.web.routers.ai import ConfiguredAIRuntimeView


class NoNetworkAI(ConfiguredAIWebLifecycle):
    """Only the external provider is injected; the extraction lifecycle stays real."""

    async def start(self):
        config = _config().model_copy(update={"prompt_version": "plan-extract-v7"})
        owner = self

        class Provider:
            async def extract_plan(self, request):
                raw = DailyPlanDraft.from_executable(owner.plan).model_dump(mode="json")
                raw["ordinary_rules"][0]["technical"] = None
                output = {
                    "draft": raw,
                    "bindings": [],
                    "clauses": [
                        {
                            "clause_id": c.clause_id,
                            "start": c.start,
                            "end": c.end,
                            "excerpt": c.excerpt,
                            "disposition": "UNRESOLVED",
                            "paths": [],
                            "reason": "Synthetic source needs independent human policy review",
                        }
                        for c in server_source_clauses(owner.source)
                    ],
                }
                return RawAIResponse(
                    request_id=request.request_id,
                    provider_id=config.provider_id,
                    model=config.model,
                    content=json.dumps(output),
                    finish_reason="stop",
                    usage=AIUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
                    attempts=1,
                )

        self._client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(AssertionError("Network prohibited"))
            )
        )
        self._binding = ConfiguredAIProviderBinding(
            profile=AIProviderProfile.OPENAI_COMPATIBLE, config=config, provider=Provider()
        )
        self._bindings = {config.provider_id: self._binding}
        return {"provider": "OFFLINE_SYNTHETIC"}

    async def get_configured_ai(self):
        return ConfiguredAIRuntimeView(
            provider_id=self._binding.config.provider_id,
            display_name="离线人工补充测试",
            base_url="https://example.invalid",
            model="offline",
            configured=True,
            enabled=True,
            max_input_chars=200000,
            max_output_tokens=16384,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="tpm-daily-browser-") as directory:
        root = Path(directory)
        ai = NoNetworkAI(config_path=root / "unused-offline.yaml")
        chain = Chain(
            root,
            bind_port=args.port,
            static_directory=Path(__file__).resolve().parents[2] / "web/dist-legacy-test",
            ai_lifecycle_factory=lambda: ai,
            read_service=_FakeMonitorReadService(),
        )
        ai.plan = chain.plan
        ai.source = (
            "Synthetic offline daily candidate; technical definition deliberately missing. "
            "Announcement verification is outside daily monitoring."
        )
        ai._review_store = chain.plans
        app = chain.app
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
        )

        @app.get("/_test/isolation")
        def isolation():
            return {
                "root": str(root),
                "database": str(root / "daily.sqlite"),
                "provider": "OFFLINE_SYNTHETIC",
            }

        @app.post("/_test/setup")
        def setup():
            with chain.plans._unit_of_work() as work:
                for previous, day in (
                    (date(2026, 9, 17), FRIDAY),
                    (FRIDAY, TUESDAY),
                    (TUESDAY, WEDNESDAY),
                ):
                    work.daily.session.add(
                        TradingCalendar(
                            exchange="SSE", cal_date=day, is_open=True, previous_trade_date=previous
                        )
                    )
                work.commit()
            return {"source": ai.source}

        @app.post("/_test/confirm-close")
        def close():
            from trade_plan_monitor.domain.plan_codec import load_plan_json

            with chain.plans._unit_of_work() as work:
                active = work.plans.get_active(SYMBOL)
                details = work.plans.get_version_details(active.plan_version_id)
                chain.plan = load_plan_json(details.payload_json)
                chain.version = {"id": details.id, "contentHash": details.content_hash}
            chain.evaluate(series=chain.series(), official=FRIDAY)
            chain.facts()
            return chain.evaluate(series=chain.series(), official=FRIDAY).model_dump(mode="json")

        @app.post("/_test/live")
        def live():
            chain.now = datetime(2026, 9, 22, 10, tzinfo=SH)
            return chain.evaluate(series=chain.series(), price=3970).model_dump(mode="json")

        @app.post("/_test/risk-close")
        def risk_close():
            chain.now = datetime(2026, 9, 22, 16, tzinfo=SH)
            return chain.evaluate(series=chain.series(TUESDAY), official=TUESDAY).model_dump(
                mode="json"
            )

        @app.post("/_test/risk-next-session")
        def risk_next_session():
            chain.now = datetime(2026, 9, 23, 10, tzinfo=SH)
            return chain.evaluate(series=chain.series(TUESDAY), price=3970).model_dump(mode="json")

        @app.post("/_test/expiry")
        def expiry():
            chain.now = chain.now.replace(hour=15, minute=0)
            return chain.evaluate(series=chain.series(TUESDAY), price=3970).model_dump(mode="json")

        @app.post("/_test/shutdown")
        def shutdown():
            server.should_exit = True
            return {"stopping": True}

        app.router.routes.sort(
            key=lambda route: not getattr(route, "path", "").startswith("/_test/")
        )
        server.run()


if __name__ == "__main__":
    main()
