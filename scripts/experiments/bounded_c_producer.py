"""P0 logical producer bounds; native allocator qualification remains a separate gate."""

import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from time import monotonic

from pydantic import BaseModel
from scripts.experiments.global_evidence_budget import BudgetUnavailable

from trade_plan_monitor.market_index.canonical import canonical_decimal


class SizedDict(dict):
    pass


class SizedList(list):
    pass


class DecimalText(str):
    pass


def bound(value):
    if isinstance(value, (SizedDict, SizedList)):
        return value.encoded_bound
    if isinstance(value, DecimalText):
        return len(value) + 2
    if type(value) is str:
        return 6 * len(value) + 2
    if value is None or type(value) is bool:
        return 5
    if type(value) is int:
        return len(str(value))
    if type(value) is dict:
        return 2 + sum(bound(k) + bound(v) + 2 for k, v in value.items())
    if type(value) in (tuple, list):
        return 2 + sum(bound(v) + 1 for v in value)
    raise TypeError("unsupported normalized value")


def normalize(value):
    if isinstance(value, BaseModel):
        return normalize(value.model_dump(mode="python", round_trip=True))
    if isinstance(value, Enum):
        return normalize(value.value)
    if isinstance(value, Decimal):
        return DecimalText(canonical_decimal(value))
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("timezone required")
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("string keys required")
        result = SizedDict((key, normalize(item)) for key, item in value.items())
    elif isinstance(value, (tuple, list)):
        result = SizedList(normalize(item) for item in value)
    else:
        raise TypeError("unsupported canonical value")
    # Calculate before enabling the cached path. No separate full-tree size map.
    result.encoded_bound = bound(dict(result) if isinstance(result, dict) else tuple(result))
    return result


class Producer:
    def __init__(self, budget, *, target=262144, cancelled=None, deadline=None):
        if target not in (65536, 262144):
            raise ValueError("unsupported target")
        self.budget, self.target = budget, target
        self.cancelled = cancelled
        self.deadline = monotonic() + 15 if deadline is None else deadline
        self.calls = self.maximum = 0

    def check(self):
        if (
            self.budget.closing
            or monotonic() >= self.deadline
            or (self.cancelled and self.cancelled.is_set())
        ):
            raise BudgetUnavailable("producer no longer admitted")

    def pieces(self, value):
        # One traversal lease covers preceding/current chunks across yield boundaries.
        # Consumers must consume synchronously, not retain an unbounded output list.
        self.check()
        with self.budget.acquire(
            12 * self.target + 4096, "encoder", cancelled=self.cancelled, deadline=self.deadline
        ) as lease:
            yield from self._pieces(value, lease)

    def _pieces(self, value, lease):
        self.check()
        size = bound(value)
        if size <= self.target:
            # This diagnostic factor is NOT a proved native writer allocation bound.
            self.calls += 1
            text = json.dumps(
                value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
            )
            data = text.encode("utf8")
            if len(data) > size:
                lease.failed = True
                self.budget.stop()
                raise BudgetUnavailable("producer bound invalidated")
            self.maximum = max(self.maximum, len(data))
            try:
                yield data
            finally:
                del text, data
            return
        if isinstance(value, dict):
            yield b"{"
            for index, key in enumerate(sorted(value)):
                self.check()
                if index:
                    yield b","
                yield from self._pieces(key, lease)
                yield b":"
                yield from self._pieces(value[key], lease)
            yield b"}"
        elif isinstance(value, (tuple, list)):
            # Encode one bounded item at a time; no uncharged growing batch vector.
            yield b"["
            for index, item in enumerate(value):
                self.check()
                if index:
                    yield b","
                yield from self._pieces(item, lease)
            yield b"]"
        else:
            raise BudgetUnavailable("scalar exceeds logical envelope")
