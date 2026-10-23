"""Isolated one-pass normalization experiment, not a native allocation guarantee."""

import runpy
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel
from scripts.experiments import c_validator
from scripts.experiments.bounded_c_producer import DecimalText, SizedDict, SizedList, bound

from trade_plan_monitor.market_index import canonical


def _planned(value):
    if isinstance(value, BaseModel):
        return _planned(value.model_dump(mode="python", round_trip=True))
    if isinstance(value, Enum):
        return _planned(value.value)
    if isinstance(value, Decimal):
        text = DecimalText(canonical.canonical_decimal(value))
        return text, len(text) + 2
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("timezone required")
        value = value.isoformat(timespec="microseconds")
    elif isinstance(value, date):
        value = value.isoformat()
    if value is None or type(value) in (bool, int, str):
        return value, bound(value)
    if isinstance(value, Mapping):
        result, total = SizedDict(), 2
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("string keys required")
            normalized, size = _planned(item)
            result[key] = normalized
            total += 6 * len(key) + 2 + size + 2
    elif isinstance(value, (tuple, list)):
        result, total = SizedList(), 2
        for item in value:
            normalized, size = _planned(item)
            result.append(normalized)
            total += size + 1
    else:
        raise TypeError("unsupported canonical value")
    result.encoded_bound = total
    return result, total


def normalize(value):
    return _planned(value)[0]


# A separate private namespace retains all prior proof and producer ownership rules.
# No production function, process-global canonical API or other adapter is patched.
_private = runpy.run_path(str(Path(c_validator.__file__)))
_private["_namespace"]["canonical"] = SimpleNamespace(
    **{**vars(canonical), "canonical_value": normalize}
)
latest = _private["latest"]
