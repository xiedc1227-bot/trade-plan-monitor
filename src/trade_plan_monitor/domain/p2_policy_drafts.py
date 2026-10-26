"""Nullable review candidates retain omissions; executable models remain strict."""

from typing import Annotated

from pydantic import create_model

from trade_plan_monitor.domain import p2_policy_models as policy
from trade_plan_monitor.domain.daily_plan_models import DailyValue


def _nullable(model, **nested):
    """Retain scalar constraints and required keys, without executable cross-field validators."""
    fields = {name: ((Annotated[nested[name], *field.metadata]
                     if name in nested and field.metadata else
                     nested.get(name, field.rebuild_annotation())) | None, ...)
              for name, field in model.model_fields.items()}
    return create_model("Draft" + model.__name__, __base__=DailyValue,
                        __module__=__name__, **fields)


DraftVolatilityTier = _nullable(policy.VolatilityTier)
DraftTierSizing = _nullable(policy.TierSizing, tiers=tuple[DraftVolatilityTier, ...])
DraftProvenance = _nullable(policy.Provenance)
DraftFeeComponent = _nullable(policy.FeeComponent)
DraftFeeSchedule = _nullable(policy.FeeSchedule, provenance=DraftProvenance,
                            components=tuple[DraftFeeComponent, ...])
DraftEconomicsGates = _nullable(policy.EconomicsGates)
DraftEconomicsPreview = _nullable(policy.EconomicsPreview, fee_schedule=DraftFeeSchedule)
DraftRequiredEconomics = _nullable(policy.RequiredEconomics, fee_schedule=DraftFeeSchedule,
                                  gates=DraftEconomicsGates)
DraftLevelEvidence = _nullable(policy.LevelEvidence)
DraftPretradePolicy = _nullable(policy.PretradePolicy,
    sizing=policy.FixedSizing | DraftTierSizing,
    economics=policy.NoEconomics | DraftEconomicsPreview | DraftRequiredEconomics,
    level_evidence=tuple[DraftLevelEvidence, ...])
DraftDerivedQuantityPolicy = _nullable(policy.DerivedQuantityPolicy)
