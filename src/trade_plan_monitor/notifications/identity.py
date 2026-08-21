"""Stable notification deduplication identities."""

from __future__ import annotations

from hashlib import sha256

from trade_plan_monitor.decision.models import SignalIntent


def alert_dedup_key(signal: SignalIntent) -> str:
    """Hash the five approved alert-identity fields in their fixed order."""

    if not isinstance(signal, SignalIntent):
        raise TypeError("signal must be a SignalIntent")
    quantity = "" if signal.quantity is None else str(signal.quantity)
    preimage = "|".join(
        (
            signal.plan_hash,
            signal.trading_date.isoformat(),
            signal.signal_type.value,
            signal.cause_id,
            quantity,
        )
    )
    return sha256(preimage.encode("utf-8")).hexdigest()


__all__ = ["alert_dedup_key"]
