"""Signed high-water cursor helpers for the backtest HTTP boundary."""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest, digest

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.backtest.time import format_shanghai_datetime, parse_shanghai_datetime
from trade_plan_monitor.web.errors import ApiError
from trade_plan_monitor.web.schemas import ApiErrorCode

CURSOR_VERSION = "cursor-v1"
MAX_CURSOR_CHARACTERS = 512
MAX_SAFE_INTEGER = 9_007_199_254_740_991
_CURSOR_FIELDS = {"v", "r", "f", "o", "h", "l"}
_STATUS_FILTERED_JOB_CURSOR_FIELDS = _CURSOR_FIELDS | {"m"}
_BASE64URL_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")
_JOB_ROUTE = "/backtest-jobs"
_POSITION_PARTS = 2
_MAX_POSITION_PART_CHARACTERS = 256


class InvalidBacktestCursorError(ApiError):
    """One non-oracular public error for every invalid cursor."""

    def __init__(self) -> None:
        super().__init__(ApiErrorCode.VALIDATION_ERROR)


class BacktestMembershipConflictError(ApiError):
    """A verified status-filtered job traversal has changed membership."""

    def __init__(self) -> None:
        super().__init__(ApiErrorCode.CONFLICT)


@dataclass(frozen=True, slots=True)
class BacktestCursorState:
    """Verified immutable boundaries carried between keyset pages."""

    high_water: tuple[str, ...]
    last_seen: tuple[str, ...] | None
    membership_revision: int | None


class BacktestApiCursorSigner:
    """Encode and validate API cursors with one installation-local 256-bit key."""

    __slots__ = ("_key",)

    def __init__(self, key: bytes | None) -> None:
        if key is not None and (type(key) is not bytes or len(key) != 32):
            raise ValueError("cursor signing key must contain exactly 32 bytes")
        self._key = key

    def __repr__(self) -> str:
        return f"{type(self).__name__}(configured={self._key is not None})"

    def encode(
        self,
        *,
        route: str,
        filters: object,
        order: str,
        high_water: tuple[str, ...],
        last_seen: tuple[str, ...] | None,
        membership_revision: int | None = None,
    ) -> str:
        """Return one canonical signed cursor without an unsigned fallback."""

        if self._key is None:
            raise InvalidBacktestCursorError
        normalized_route = _context_value(route, "route")
        normalized_order = _context_value(order, "order")
        normalized_filters = _normalized_filters(filters)
        normalized_high_water = _encode_position(high_water)
        normalized_last_seen = None if last_seen is None else _encode_position(last_seen)
        status_filtered = _is_status_filtered_job(normalized_route, normalized_filters)
        normalized_revision = _encode_membership_revision(
            membership_revision,
            required=status_filtered,
        )
        payload_value: dict[str, object] = {
            "v": CURSOR_VERSION,
            "r": normalized_route,
            "f": _filters_hash(normalized_filters),
            "o": normalized_order,
            "h": normalized_high_water,
            "l": normalized_last_seen,
        }
        if status_filtered:
            payload_value["m"] = normalized_revision
        payload = canonical_json(payload_value).encode("utf-8")
        payload_segment = _encode_segment(payload)
        mac_segment = _encode_segment(digest(self._key, payload_segment.encode("ascii"), "sha256"))
        token = f"{payload_segment}.{mac_segment}"
        if len(token) > MAX_CURSOR_CHARACTERS:
            raise ValueError("encoded cursor exceeds 512 characters")
        return token

    def decode(
        self,
        token: str,
        *,
        route: str,
        filters: object,
        order: str,
        current_membership_revision: int | None = None,
    ) -> BacktestCursorState:
        """Validate a cursor and fail uniformly except for verified membership drift."""

        try:
            if self._key is None:
                raise ValueError
            normalized_route = _context_value(route, "route")
            normalized_order = _context_value(order, "order")
            normalized_filters = _normalized_filters(filters)
            if type(token) is not str or not token or len(token) > MAX_CURSOR_CHARACTERS:
                raise ValueError
            token.encode("ascii")
            segments = token.split(".")
            if len(segments) != 2:
                raise ValueError
            payload_segment, supplied_mac_segment = segments
            supplied_mac = _decode_segment(supplied_mac_segment)
            expected_mac = digest(self._key, payload_segment.encode("ascii"), "sha256")
            if len(supplied_mac) != len(expected_mac) or not compare_digest(
                supplied_mac,
                expected_mac,
            ):
                raise ValueError
            payload_bytes = _decode_segment(payload_segment)
            payload = json.loads(
                payload_bytes.decode("utf-8"),
                object_pairs_hook=_unique_object,
            )
            status_filtered = _is_status_filtered_job(normalized_route, normalized_filters)
            expected_fields = (
                _STATUS_FILTERED_JOB_CURSOR_FIELDS if status_filtered else _CURSOR_FIELDS
            )
            if type(payload) is not dict or set(payload) != expected_fields:
                raise ValueError
            if canonical_json(payload).encode("utf-8") != payload_bytes:
                raise ValueError
            if (
                payload["v"] != CURSOR_VERSION
                or payload["r"] != normalized_route
                or payload["f"] != _filters_hash(normalized_filters)
                or payload["o"] != normalized_order
            ):
                raise ValueError
            high_water = _decode_position(payload["h"])
            raw_last_seen = payload["l"]
            last_seen = None if raw_last_seen is None else _decode_position(raw_last_seen)
            membership_revision = _decode_membership_revision(
                payload["m"] if status_filtered else None,
                required=status_filtered,
            )
            if status_filtered:
                current_revision = _decode_membership_revision(
                    current_membership_revision,
                    required=True,
                )
                if membership_revision != current_revision:
                    raise BacktestMembershipConflictError
            return BacktestCursorState(
                high_water=high_water,
                last_seen=last_seen,
                membership_revision=membership_revision,
            )
        except BacktestMembershipConflictError:
            raise
        except (
            binascii.Error,
            KeyError,
            TypeError,
            UnicodeError,
            ValueError,
            json.JSONDecodeError,
        ):
            raise InvalidBacktestCursorError from None

    def high_watermark(
        self,
        *,
        route: str,
        filters: object,
        order: str,
        state: BacktestCursorState,
    ) -> str:
        """Recreate the constant signed first-page anchor for a traversal."""

        if not isinstance(state, BacktestCursorState):
            raise TypeError("state must be a BacktestCursorState")
        return self.encode(
            route=route,
            filters=filters,
            order=order,
            high_water=state.high_water,
            last_seen=None,
            membership_revision=state.membership_revision,
        )


def _normalized_filters(filters: object) -> object:
    canonical_payload = getattr(filters, "canonical_payload", None)
    return canonical_payload() if callable(canonical_payload) else filters


def _is_status_filtered_job(route: str, filters: object) -> bool:
    return (
        route == _JOB_ROUTE
        and isinstance(filters, Mapping)
        and (filters.get("status") is not None or filters.get("datasetHash") is not None)
    )


def _filters_hash(filters: object) -> str:
    return _encode_segment(sha256(canonical_json(filters).encode("utf-8")).digest())


def _context_value(value: str, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"cursor {name} must be a non-empty string")
    return value


def _encode_membership_revision(value: object, *, required: bool) -> int | None:
    if required:
        if type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER:
            raise ValueError("status-filtered job cursor requires a safe membership revision")
        return value
    if value is not None:
        raise ValueError("unfiltered cursor must not include a membership revision")
    return None


def _decode_membership_revision(value: object, *, required: bool) -> int | None:
    if required:
        if type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER:
            raise ValueError
        return value
    if value is not None:
        raise ValueError
    return None


def _encode_position(value: object) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise ValueError("cursor position must be a tuple")
    return _validate_position_values(value)


def _decode_position(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise ValueError
    return _validate_position_values(value)


def _validate_position_values(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != _POSITION_PARTS:
        raise ValueError("cursor position must contain exactly two values")
    if any(
        type(item) is not str or not item or len(item) > _MAX_POSITION_PART_CHARACTERS
        for item in value
    ):
        raise ValueError("cursor position values must be bounded non-empty strings")
    normalized = tuple(value)
    event_time = normalized[0]
    try:
        parsed_event_time = parse_shanghai_datetime(event_time)
    except TypeError, ValueError:
        raise ValueError("cursor time must use fixed-six-digit +08:00") from None
    if format_shanghai_datetime(parsed_event_time) != event_time:
        raise ValueError("cursor time must use fixed-six-digit +08:00")
    return normalized


def _encode_segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_segment(value: str) -> bytes:
    if type(value) is not str or _BASE64URL_SEGMENT.fullmatch(value) is None:
        raise ValueError
    padding = "=" * (-len(value) % 4)
    decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    if _encode_segment(decoded) != value:
        raise ValueError
    return decoded


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


__all__ = [
    "CURSOR_VERSION",
    "MAX_CURSOR_CHARACTERS",
    "BacktestApiCursorSigner",
    "BacktestCursorState",
    "BacktestMembershipConflictError",
    "InvalidBacktestCursorError",
]
