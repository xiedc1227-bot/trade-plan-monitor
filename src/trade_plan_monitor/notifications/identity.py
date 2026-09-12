"""Stable notification deduplication identities."""

from __future__ import annotations

from hashlib import sha256
from uuid import UUID, uuid5

from trade_plan_monitor.decision.explicit_rules import ExplicitSignalIntent
from trade_plan_monitor.decision.models import SignalIntent

_EXPLICIT_ALERT_DOMAIN = b"explicit-rule-alert-v1\0"
_EXPLICIT_EVENT_NAMESPACE = UUID("a13edc5b-f107-4d49-8799-f2ad1cc54560")


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


def explicit_alert_dedup_key(signal: ExplicitSignalIntent) -> str:
    """Hash the complete activation-aware explicit rule occurrence identity."""

    if type(signal) is not ExplicitSignalIntent:
        raise TypeError("signal must be an ExplicitSignalIntent")
    fields = (
        signal.payload_schema_version,
        signal.plan_hash,
        str(signal.activation_revision),
        signal.symbol,
        signal.rule_id,
        signal.target_bucket_end.isoformat(),
        signal.action.type,
        str(signal.action.quantity),
    )
    preimage = _EXPLICIT_ALERT_DOMAIN + b"\0".join(item.encode("utf-8") for item in fields)
    return sha256(preimage).hexdigest()


def explicit_alert_event_id(signal: ExplicitSignalIntent) -> UUID:
    """Derive a stable UUID so transaction retries retain the same public event ID."""

    return uuid5(_EXPLICIT_EVENT_NAMESPACE, explicit_alert_dedup_key(signal))


__all__ = ["alert_dedup_key", "explicit_alert_dedup_key", "explicit_alert_event_id"]
