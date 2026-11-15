"""Fixed offline PBS browser inputs; production retains every authority decision."""

import json
from copy import deepcopy
from datetime import datetime, time, timedelta
from hashlib import sha256
from pathlib import Path

import httpx
import pandas as pd
import requests
from tests.browser.condition_server import NoNetworkAI
from tests.integration.current_activation_fixture import current_sample_plan
from tests.integration.test_live_pipeline_acceptance import OfflineSDK
from tests.integration.test_market_linkage_review import source_mapping
from tests.unit.test_ai_plan_extraction_v4 import _config

from trade_plan_monitor.ai.composition import ConfiguredAIProviderBinding
from trade_plan_monitor.ai.daily_review import DailyClause, daily_contract_bindings
from trade_plan_monitor.ai.models import AIProviderProfile
from trade_plan_monitor.ai.provider import AIUsage, RawAIResponse
from trade_plan_monitor.ai.review import server_source_clauses
from trade_plan_monitor.domain.unified_plan_models import UnifiedTradePlan
from trade_plan_monitor.domain.unified_plan_validation import BuySuspensionPlanDraft
from trade_plan_monitor.market_data.sessions import expected_minute_ends

REPOSITORY = Path(__file__).resolve().parents[2]
BUILD_RECORD = REPOSITORY / "build/pbs/t12/a11/build.json"
DIST = Path(json.loads(BUILD_RECORD.read_text())["dist"])
STATEMENT = "This new plan replaces the predecessor BUY suspension and supplies a new guard."
DIRECTIVE = "再次跌破24.20后继续空仓，等待新底部结构。"


def sdk_transport(state):
    """Use the verified SDK/query mapping; replace only its remote response."""
    from trade_plan_monitor.market_data.tushare_client import create_tushare_client
    from trade_plan_monitor.runtime import production

    def post(url, **kwargs):
        assert url.startswith("https://api.waditu.com/dataapi/")
        body = kwargs["json"]
        frame = getattr(state.case.sdk, body["api_name"])(**body["params"])
        data = json.loads(frame.to_json(orient="split"))
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"code": 0, "data": {
            "fields": data["columns"], "items": data["data"]}}).encode()
        return response

    state.patch.setattr(production, "create_tushare_client", create_tushare_client)
    state.patch.setattr(requests, "post", post)
    state.guard_calls = []
    native_guard = production.ProductionMonitorPipeline.advance_buy_suspension

    async def observed_guard(pipeline, plan, **kwargs):
        entry = {"plan": plan.plan_id, "at": state.case.clock.now().isoformat()}
        state.guard_calls.append(entry)
        try:
            result = await native_guard(pipeline, plan, **kwargs)
            entry["outcome"] = None if result is None else result["state"].outcome
            return result
        except Exception as error:
            entry["error"] = str(error)
            raise

    state.patch.setattr(production.ProductionMonitorPipeline,
        "advance_buy_suspension", observed_guard)


def validate_static(directory):
    if directory is None or Path(directory).resolve() != DIST.resolve():
        raise ValueError("PBS requires the exact isolated T11 distribution")
    record = json.loads(BUILD_RECORD.read_text())
    manifest = record["assets"]
    if any(sha256((REPOSITORY / p).read_bytes()).hexdigest() != digest
           for p, digest in record["sourceHashes"].items()):
        raise ValueError("Isolated distribution source has changed")
    actual = {p.relative_to(DIST).as_posix(): sha256(p.read_bytes()).hexdigest()
              for p in DIST.rglob("*") if p.is_file()}
    if actual != manifest:
        raise ValueError("Isolated T11 distribution differs from its frozen manifest")


async def current_tradability(state, port):
    """Independent fixed exchange prerequisite through the existing public API."""
    active = await state.lifecycle.get_plan_activation_state(symbol=state.case.plan.symbol)
    saved = await state.lifecycle.get_plan_version(version_id=str(active.plan_version_id))
    if not hasattr(state, "tradability_versions"):
        state.tradability_versions = set()
    if str(saved.id) in state.tradability_versions:
        return
    now = state.case.clock.now().isoformat()
    body = dict(planVersionId=str(saved.id), contentHash=saved.content_hash,
        factId="fixture-tradability-" + str(saved.id), kind="TRADABILITY",
        tradeDate=str(state.case.clock.now().date()), expectedRevision=0,
        evidence="Synthetic exchange verifies tradability only, not a BUY or SELL condition.",
        officialEvidence=dict(issuer="Synthetic exchange fixture",
            documentTitle="Current synthetic tradability evidence",
            documentUrl="https://example.test/tradability", publishedAt=now, verifiedAt=now,
            applicableAssertion="This fixed offline evidence verifies only tradability."))
    async with httpx.ASGITransport(app=state.app, client=("127.0.0.1", 50000)) as transport:
        response = await transport.handle_async_request(httpx.Request("POST",
            f"http://127.0.0.1:{port}/api/v1/plan-facts", json=body, headers={
                "X-Monitor-Contract-Version": "2",
                "Idempotency-Key": "pbs-tradability-" + str(saved.id)})
        )
        await response.aread()
        assert response.status_code == 200, response.text
        state.tradability_versions.add(str(saved.id))


def legacy_plan(*, seed=False):
    raw = current_sample_plan().model_dump(mode="json")
    raw["ordinary_rules"][0]["validity"] = {"mode": "PLAN_ACTIVE"}
    sell = deepcopy(raw["ordinary_rules"][0])
    sell.update(rule_id="pbs-independent-sell", side="SELL")
    raw["ordinary_rules"].append(sell)
    if seed:
        raw["alert_rules"] = [dict(kind="RISK_ALERT", rule_id="pbs-seed-alert",
            condition=raw["ordinary_rules"][0]["condition"],
            confirmation=raw["ordinary_rules"][0]["confirmation"])]
        raw["ordinary_rules"] = []
    return UnifiedTradePlan.model_validate(raw)


def source_case(*, replacement=False):
    raw = legacy_plan().model_dump(mode="json")
    raw.update(schema_version=10, execution_version="condition-plan-v6",
        plan_id="pbs-browser-replacement" if replacement else "pbs-browser-initial",
        version=1, buy_suspension=None)
    if replacement:
        raw["ordinary_rules"] = raw["ordinary_rules"][:1]
    bare = BuySuspensionPlanDraft.model_validate(raw)
    source, mapping = source_mapping(bare)
    # The four guard values require explicit registration against this original
    # obligation; FIELD declarations for unrelated policy remain intact.
    source += "\n" + DIRECTIVE
    if replacement:
        source += '\n' + STATEMENT + '\nstrategy_effective_from = "2026-09-08T09:50:00+08:00"'
    extra = tuple(DailyClause.model_validate(c.model_dump() | dict(
        disposition="CONTEXT", semantic_role="COMMENTARY", paths=(),
        reason="Untrusted source proposal; independent guard review required"))
        for c in server_source_clauses(source)[len(mapping.clauses):])
    raw["buy_suspension"] = dict(condition=dict(type="MINUTE_CLOSE_BELOW",
        timeframe_minutes=5, price_fen=2420), effective_from=(
            "2026-09-08T09:45:00+08:00" if replacement else "2026-09-08T09:30:00+08:00"))
    draft = BuySuspensionPlanDraft.model_validate(raw)
    return draft, source, mapping.model_copy(update={"clauses": (*mapping.clauses, *extra)})


class PBSInputs(OfflineSDK):
    """Only market responses are synthetic; no state/outcome is supplied."""

    def _stock_minutes(self, name, kwargs):
        frame = super()._stock_minutes(name, kwargs)
        frame["open"], frame["high"], frame["low"] = "24.30", "24.35", "24.19"
        frame["vol"], frame["amount"] = 100, "2430"
        ends = [datetime.fromisoformat(t) + timedelta(minutes=1) for t in frame["time"]]
        frame["close"] = ["24.19" if end.time() == time(9, 40) else (
            "24.35" if end.time() >= time(9, 45) else "24.30") for end in ends]
        return frame

    def _limits(self, kwargs):
        frame = super()._limits(kwargs)
        frame["up_limit"], frame["down_limit"] = "26.00", "22.00"
        return frame

    def stk_mins(self, **kwargs):
        self.calls.append(("stk_mins", dict(kwargs)))
        cutoff = datetime.fromisoformat(kwargs["end_date"]).replace(tzinfo=self.clock.now().tzinfo)
        ends = (cutoff.replace(hour=9, minute=30, second=0, microsecond=0),
                *expected_minute_ends(cutoff.date(), is_open=True))
        return pd.DataFrame([dict(ts_code=kwargs["ts_code"],
            trade_time=end.strftime("%Y-%m-%d %H:%M:%S"), open="24.30", high="24.35",
            low="24.19", close="24.19" if end.time() == time(9, 40) else (
                "24.35" if end.time() >= time(9, 45) else "24.30"),
            vol=100, amount="2430") for end in ends if end <= cutoff])

    def adj_factor(self, **kwargs):
        self.calls.append(("adj_factor", dict(kwargs)))
        return pd.DataFrame([dict(ts_code=kwargs["ts_code"],
            trade_date=str(kwargs["start_date"]).replace("-", ""), adj_factor="2.75")])


class PBSExtraction(NoNetworkAI):
    """Actual configured v13 extraction lifecycle with one offline provider double."""

    async def start(self):
        config = _config().model_copy(update={"prompt_version": "plan-extract-v13",
                                             "max_input_chars": 200000})
        self.calls = []
        owner = self

        class Provider:
            async def extract_plan(self, request):
                choices = [source_case(replacement=r) for r in (False, True)]
                data = json.loads(request.prompt.split("\nUNTRUSTED_PLAN_DATA_START\n")[1]
                    .split("\nUNTRUSTED_PLAN_DATA_END")[0])
                draft, source, mapping = next(c for c in choices if c[1] == data["source_text"])
                owner.calls.append(dict(prompt_version=config.prompt_version,
                    source_hash=sha256(source.encode()).hexdigest()))
                products = daily_contract_bindings(draft)
                fixed_paths = {b.path for b in products}
                output = dict(contract_version="plan-buy-suspension-extraction-v1",
                    draft=draft.model_dump(mode="json"),
                    clauses=[c.model_dump(mode="json") for c in mapping.clauses],
                    bindings=[b.model_dump(mode="json") for b in (*products,
                        *(b for b in mapping.bindings if b.path not in fixed_paths))])
                return RawAIResponse(request_id=request.request_id, provider_id=config.provider_id,
                    model=config.model, content=json.dumps(output), finish_reason="stop",
                    usage=AIUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
                    attempts=1)

        self._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError("External provider prohibited"))),
            trust_env=False)
        self._binding = ConfiguredAIProviderBinding(profile=AIProviderProfile.OPENAI_COMPATIBLE,
            config=config, provider=Provider())
        self._bindings = {config.provider_id: self._binding}
        return {"provider": "OFFLINE_SYNTHETIC_V13"}
