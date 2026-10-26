"""Lossless per-decision references for repeated Schema 7/8 signal evidence."""

from pydantic import Field

from trade_plan_monitor.backtest.models import Sha256Hex
from trade_plan_monitor.state.daily_state_models import DailySignalState


class ResearchSignalReference(DailySignalState):
    market_linkage_ref: Sha256Hex
    market_linkage: None = Field(default=None, exclude=True)
    pretrade_ref: Sha256Hex | None = Field(default=None, exclude_if=lambda value: value is None)
    pretrade: None = Field(default=None, exclude=True)


def compact_signal_evidence(values):
    """Keep each frozen calculation once; never discard or recompute its evidence."""
    current = {value.evidence_hash for value in values.get("market_linkage", ())}
    proofs = {}
    pretrades = {}
    for field in ("signals", "resulting_signals"):
        signals = []
        for signal in values[field]:
            proof = signal.market_linkage
            if proof is None or proof.version != "market-linkage-evidence-v2":
                signals.append(signal)
                continue
            if proof.evidence_hash not in current:
                proofs[proof.evidence_hash] = proof
            pretrade = signal.pretrade
            if pretrade is not None:
                pretrades[pretrade.evidence_hash] = pretrade
            signals.append(ResearchSignalReference.model_validate({
                **signal.model_dump(mode="python", exclude={"market_linkage", "pretrade"}),
                "market_linkage_ref": proof.evidence_hash,
                **({"pretrade_ref": pretrade.evidence_hash} if pretrade is not None else {}),
            }))
        values[field] = tuple(signals)
    values["signal_linkage"] = tuple(proofs.values())
    if pretrades:
        values["signal_pretrade"] = tuple(pretrades.values())
    return values


def validate_signal_references(event):
    proofs = {proof.evidence_hash: proof for proof in (
        *(event.market_linkage or ()), *(event.signal_linkage or ()))}
    pretrades = {proof.evidence_hash: proof for proof in
                getattr(event, "signal_pretrade", ()) or ()}
    for signal in (*event.signals, *event.resulting_signals):
        if isinstance(signal, ResearchSignalReference):
            proof = proofs.get(signal.market_linkage_ref)
            if proof is None:
                raise ValueError("research signal lacks its frozen linkage evidence")
            pretrade = pretrades.get(signal.pretrade_ref)
            if signal.pretrade_ref is not None and pretrade is None:
                raise ValueError("research signal lacks its frozen pretrade evidence")
            DailySignalState.model_validate({
                **signal.model_dump(mode="python", exclude={"market_linkage_ref", "pretrade_ref"}),
                "market_linkage": proof,
                **({"pretrade": pretrade} if pretrade is not None else {}),
            })
