"""Lossless per-decision references for repeated Schema 7/8 signal evidence."""

from pydantic import Field

from trade_plan_monitor.backtest.models import Sha256Hex
from trade_plan_monitor.backtest.research_input import ResearchValue
from trade_plan_monitor.decision.p3_composition import CapitalCalculation, CapitalMarketDecision
from trade_plan_monitor.state.daily_state_models import DailySignalState
from trade_plan_monitor.state.market_exception_models import ExceptionBinding


class ResearchSignalReference(DailySignalState):
    market_linkage_ref: Sha256Hex
    market_linkage: None = Field(default=None, exclude=True)
    pretrade_ref: Sha256Hex | None = Field(default=None, exclude_if=lambda value: value is None)
    pretrade: None = Field(default=None, exclude=True)


class CapitalSignalReference(ResearchSignalReference):
    capital_execution_ref: Sha256Hex | None
    capital_execution: None = Field(default=None, exclude=True)


class CapitalLinkageReference(ResearchValue):
    """Losslessly reuse identical market/technical facts with a distinct whole calculation."""

    base_evidence_hash: Sha256Hex
    calculation: CapitalCalculation
    approval_binding: ExceptionBinding | None
    evidence_hash: Sha256Hex


def _shared_facts(proof):
    return proof.model_dump(mode="json", exclude={
        "evidence_hash", "calculation", "approval_binding"})


def compact_signal_evidence(values):
    """Keep each frozen calculation once; never discard or recompute its evidence."""
    current = {value.evidence_hash for value in values.get("market_linkage", ())}
    proofs = {}
    pretrades = {}
    capitals = {}
    for field in ("signals", "resulting_signals"):
        signals = []
        for signal in values[field]:
            proof = signal.market_linkage
            if proof is None or proof.version not in {
                "market-linkage-evidence-v2", "capital-market-evidence-v1"
            }:
                signals.append(signal)
                continue
            if proof.evidence_hash not in current:
                base = next((p for p in values.get("market_linkage", ())
                    if isinstance(p, CapitalMarketDecision)
                    and isinstance(proof, CapitalMarketDecision)
                    and _shared_facts(p) == _shared_facts(proof)), None)
                proofs[proof.evidence_hash] = (proof if base is None else CapitalLinkageReference(
                    base_evidence_hash=base.evidence_hash, calculation=proof.calculation,
                    approval_binding=proof.approval_binding, evidence_hash=proof.evidence_hash))
            pretrade = signal.pretrade
            if pretrade is not None:
                pretrades[pretrade.evidence_hash] = pretrade
            capital = signal.capital_execution
            is_capital = proof.version == "capital-market-evidence-v1"
            if is_capital and capital is not None:
                capitals[capital.evidence_hash] = capital
            reader = CapitalSignalReference if is_capital else ResearchSignalReference
            signals.append(reader.model_validate({
                **signal.model_dump(mode="python", exclude={"market_linkage", "pretrade"}
                    | ({"capital_execution"} if is_capital else set())),
                "market_linkage_ref": proof.evidence_hash,
                **({"pretrade_ref": pretrade.evidence_hash} if pretrade is not None else {}),
                **({"capital_execution_ref": None if capital is None else capital.evidence_hash}
                   if is_capital else {}),
            }))
        values[field] = tuple(signals)
    values["signal_linkage"] = tuple(proofs.values())
    if pretrades:
        values["signal_pretrade"] = tuple(pretrades.values())
    if capitals:
        values["signal_capital"] = tuple(capitals.values())
    return values


def validate_signal_references(event):
    proofs = {proof.evidence_hash: proof for proof in (
        *(event.market_linkage or ()), *(event.signal_linkage or ()))
        if not isinstance(proof, CapitalLinkageReference)}
    for reference in event.signal_linkage or ():
        if isinstance(reference, CapitalLinkageReference):
            base = proofs.get(reference.base_evidence_hash)
            if not isinstance(base, CapitalMarketDecision):
                raise ValueError("research linkage lacks its frozen capital base")
            proofs[reference.evidence_hash] = CapitalMarketDecision.model_validate({
                **base.model_dump(mode="python"),
                **reference.model_dump(mode="python", exclude={"base_evidence_hash"})})
    pretrades = {proof.evidence_hash: proof for proof in
                getattr(event, "signal_pretrade", ()) or ()}
    capitals = {proof.evidence_hash: proof for proof in
                getattr(event, "signal_capital", ()) or ()}
    for signal in (*event.signals, *event.resulting_signals):
        if isinstance(signal, ResearchSignalReference):
            proof = proofs.get(signal.market_linkage_ref)
            if proof is None:
                raise ValueError("research signal lacks its frozen linkage evidence")
            pretrade = pretrades.get(signal.pretrade_ref)
            if signal.pretrade_ref is not None and pretrade is None:
                raise ValueError("research signal lacks its frozen pretrade evidence")
            capital = (capitals.get(signal.capital_execution_ref)
                       if isinstance(signal, CapitalSignalReference) else None)
            if (isinstance(signal, CapitalSignalReference)
                    and signal.capital_execution_ref is not None and capital is None):
                raise ValueError("research signal lacks its frozen capital evidence")
            DailySignalState.model_validate({
                **signal.model_dump(mode="python", exclude={
                    "market_linkage_ref", "pretrade_ref", "capital_execution_ref"}),
                "market_linkage": proof,
                **({"pretrade": pretrade} if pretrade is not None else {}),
                **({"capital_execution": capital} if capital is not None else {}),
            })
