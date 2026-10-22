"""Canonical JSON and content hashes for board-index facts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256

from pydantic import BaseModel

from trade_plan_monitor.market_index.models import (
    MarketIndexBar,
    MarketIndexFactRequest,
    MarketIndexSnapshot,
)

_MAX_CANONICAL_DECIMAL_CHARACTERS = 10_000
_FORMULA_DEFINITIONS = {
    "formulaVersion": "market-index-facts-v1",
    "SMA": "mean(last period official open-day closes)",
    "SMA_LOOKBACK": "current SMA and SMA ending lookback official open days earlier",
    "RETURN": "(current close / close exactly window_size observations earlier) - 1",
    "decimalDivision": "precision-50-half-even",
}


def canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("canonical decimals must be finite")
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover - finite guard above
        raise ValueError("canonical decimal exponent must be finite")
    if not any(digits):
        return "0"
    coefficient_length = len(digits)
    if exponent >= 0:
        expanded_length = coefficient_length + exponent
    else:
        decimal_position = coefficient_length + exponent
        expanded_length = coefficient_length + 1 if decimal_position > 0 else 2 - decimal_position
    if expanded_length + int(bool(sign)) > _MAX_CANONICAL_DECIMAL_CHARACTERS:
        raise ValueError("canonical decimal expansion is too large")
    exact = format(value, "f")
    return exact.rstrip("0").rstrip(".") if "." in exact else exact


def canonical_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return canonical_value(value.model_dump(mode="python", round_trip=True))
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("canonical datetime must be timezone-aware")
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if value is None or type(value) in {bool, int, str}:
        return value
    if isinstance(value, float):
        raise ValueError("canonical index values must not use binary floating point")
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("canonical mapping keys must be strings")
            normalized[key] = canonical_value(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    raise TypeError(f"unsupported canonical market-index value: {type(value).__name__}")


def canonical_json(value: object) -> str:
    return _encode_canonical_value(canonical_value(value))


def _encode_canonical_value(value: object) -> str:
    """Encode only a tree already normalized by this module's canonical policy."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(domain: bytes, value: object) -> str:
    return sha256(domain + canonical_json(value).encode("utf-8")).hexdigest()


FORMULA_DEFINITION_HASH = _digest(
    b"market-index-facts-v1\0",
    _FORMULA_DEFINITIONS,
)


def market_index_bar_set_hash(bars: tuple[MarketIndexBar, ...]) -> str:
    if type(bars) is not tuple or any(type(bar) is not MarketIndexBar for bar in bars):
        raise TypeError("bars must be an exact tuple of MarketIndexBar values")
    ordered = sorted(bars, key=lambda bar: (bar.interval.value, bar.bar_at))
    return _digest(b"market-index-bars-v1\0", ordered)


def market_index_request_set_hash(requests: tuple[MarketIndexFactRequest, ...]) -> str:
    if type(requests) is not tuple:
        raise TypeError("requests must be a tuple")
    ordered = sorted(requests, key=canonical_json)
    return _digest(b"market-index-requests-v1\0", ordered)


def market_index_snapshot_hash(payload: object) -> str:
    return _digest(b"market-index-snapshot-v1\0", payload)


def validate_market_index_snapshot_integrity(snapshot: MarketIndexSnapshot) -> None:
    """Fail closed if any stored snapshot content hash is inconsistent."""

    _verified_market_index_value(snapshot)


def verified_market_index_snapshot_json(snapshot: MarketIndexSnapshot) -> str:
    """Fully verify one snapshot and return its literal canonical storage representation.

    The normalized tree lives only for this call. Domain hashes and the final
    byte comparison reuse its values without skipping typed/model validation.
    """

    return _encode_canonical_value(_verified_market_index_value(snapshot))


def _verified_market_index_value(snapshot: MarketIndexSnapshot) -> dict[str, object]:
    if type(snapshot) is not MarketIndexSnapshot:
        raise TypeError("snapshot must be a MarketIndexSnapshot")
    bars = snapshot.five_minute_bars + snapshot.official_daily_bars
    if type(bars) is not tuple or any(type(bar) is not MarketIndexBar for bar in bars):
        raise TypeError("bars must be an exact tuple of MarketIndexBar values")
    if type(snapshot.fact_requests) is not tuple:
        raise TypeError("requests must be a tuple")
    value = canonical_value(snapshot)

    def digest(domain: bytes, part: object) -> str:
        return sha256(domain + _encode_canonical_value(part).encode("utf-8")).hexdigest()

    normalized_bars = value["five_minute_bars"] + value["official_daily_bars"]
    ordered_bars = [
        normalized
        for _, normalized in sorted(
            zip(bars, normalized_bars, strict=True),
            key=lambda pair: (pair[0].interval.value, pair[0].bar_at),
        )
    ]
    if snapshot.bar_set_hash != digest(b"market-index-bars-v1\0", ordered_bars):
        raise ValueError("market-index snapshot bar_set_hash mismatch")
    requests = sorted(value["fact_requests"], key=_encode_canonical_value)
    if snapshot.request_set_hash != digest(b"market-index-requests-v1\0", requests):
        raise ValueError("market-index snapshot request_set_hash mismatch")
    if snapshot.formula_definition_hash != FORMULA_DEFINITION_HASH:
        raise ValueError("market-index snapshot formula_definition_hash mismatch")
    if any(
        fact.formula_definition_hash != snapshot.formula_definition_hash
        for fact in snapshot.indicator_facts
    ):
        raise ValueError("market-index fact formula hash mismatch")
    payload = {key: part for key, part in value.items() if key != "snapshot_hash"}
    if snapshot.snapshot_hash != digest(b"market-index-snapshot-v1\0", payload):
        raise ValueError("market-index snapshot_hash mismatch")
    return value


__all__ = [
    "FORMULA_DEFINITION_HASH",
    "canonical_decimal",
    "canonical_json",
    "canonical_value",
    "market_index_bar_set_hash",
    "market_index_request_set_hash",
    "market_index_snapshot_hash",
    "validate_market_index_snapshot_integrity",
    "verified_market_index_snapshot_json",
]
