"""Shared canonical JSON primitives for deterministic backtest identities."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

_MAX_CANONICAL_DECIMAL_CHARACTERS = 10_000


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
        expanded_length = (
            coefficient_length + 1
            if decimal_position > 0
            else 2 - decimal_position + coefficient_length
        )
    if expanded_length + int(bool(sign)) > _MAX_CANONICAL_DECIMAL_CHARACTERS:
        raise ValueError("canonical decimal expansion is too large")
    exact = format(value, "f")
    return exact.rstrip("0").rstrip(".") if "." in exact else exact


def canonical_value(value: object) -> object:
    """Normalize equivalent Python values to one JSON-compatible representation."""

    if isinstance(value, BaseModel):
        return canonical_value(value.model_dump(mode="python", round_trip=True))
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical datetimes must be timezone-aware")
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if value is None or type(value) in {bool, int, str}:
        return value
    if isinstance(value, float):
        raise ValueError("canonical values must not use binary floating point")
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical mapping keys must be strings")
            normalized[key] = canonical_value(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json(value: object) -> str:
    """Return stable UTF-8 JSON text without insignificant whitespace."""

    return json.dumps(
        canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = ["canonical_decimal", "canonical_json", "canonical_value"]
