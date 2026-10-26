"""Frozen pretrade evidence embedded in owned signal and evaluation records."""

from datetime import date, datetime
from typing import Literal

from pydantic import model_validator

from trade_plan_monitor.decision.p2_economics import EconomicsResult
from trade_plan_monitor.decision.p2_sizing import SizingResult
from trade_plan_monitor.domain.daily_hash import daily_hash
from trade_plan_monitor.domain.daily_plan_models import DailyValue
from trade_plan_monitor.domain.p2_policy_models import PretradePolicy
from trade_plan_monitor.domain.plan_hash import daily_plan_content_sha256
from trade_plan_monitor.market_data.models import ShanghaiDatetime


class FrozenPretrade(DailyValue):
    version: Literal["p2-pretrade-evidence-v1"] = "p2-pretrade-evidence-v1"
    rule_id: str
    content_hash: str
    decision_session: date
    cutoff: ShanghaiDatetime
    policy: PretradePolicy
    sizing: SizingResult
    economics: EconomicsResult | None
    evidence_hash: str

    @model_validator(mode="after")
    def verify(self):
        if self.decision_session > self.cutoff.date() or self.evidence_hash != daily_hash(
                self.version, self.model_dump(mode="json", exclude={"evidence_hash"})):
            raise ValueError("pretrade evidence hash or cutoff mismatch")
        return self


def freeze_pretrade(plan, rule, *, sizing, economics, decision_session, cutoff):
    if isinstance(decision_session, str):
        decision_session = date.fromisoformat(decision_session)
    if isinstance(cutoff, str):
        cutoff = datetime.fromisoformat(cutoff)
    raw = dict(rule_id=rule.rule_id, content_hash=daily_plan_content_sha256(plan),
        decision_session=decision_session, cutoff=cutoff, policy=rule.pretrade_policy,
        sizing=SizingResult.model_validate(sizing), economics=economics)
    # Validate values first; never hash a mixture of Python dates and JSON strings.
    unsigned = FrozenPretrade.model_construct(**raw, evidence_hash="")
    payload = unsigned.model_dump(mode="json", exclude={"evidence_hash"})
    return FrozenPretrade.model_validate(payload | {
        "evidence_hash": daily_hash("p2-pretrade-evidence-v1", payload)})
