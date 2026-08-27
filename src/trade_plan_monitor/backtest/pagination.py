"""Opaque HMAC-signed cursors for bounded backtest keyset pagination."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest, digest
from typing import Protocol

from trade_plan_monitor.backtest.canonical import canonical_json

CURSOR_VERSION = "cursor-v1"
MAX_CURSOR_CHARACTERS = 512
MAX_PAGE_ITEMS = 100
MAX_PAGE_BYTES = 4 * 1024 * 1024
_CURSOR_FIELDS = {"v", "r", "f", "o", "h", "l"}


class InvalidCursorError(ValueError):
    """Uniform failure for every invalid or context-mismatched cursor."""

    def __init__(self) -> None:
        super().__init__("invalid cursor")


@dataclass(frozen=True, slots=True)
class DecodedCursor:
    """Verified keyset boundaries extracted from an opaque token."""

    high_water: tuple[str, ...]
    last_seen: tuple[str, ...] | None


class CursorSigner(Protocol):
    """Injectable cursor-signing boundary shared by application services."""

    def encode(
        self,
        *,
        route: str,
        filters: object,
        order: str,
        high_water: tuple[str, ...],
        last_seen: tuple[str, ...] | None,
    ) -> str: ...

    def decode(
        self,
        token: str,
        *,
        route: str,
        filters: object,
        order: str,
    ) -> DecodedCursor: ...


class HmacCursorSigner:
    """Sign canonical cursor payloads with an installation-local 256-bit key."""

    def __init__(self, key: bytes) -> None:
        if type(key) is not bytes or len(key) != 32:
            raise ValueError("cursor signing key must contain exactly 32 bytes")
        self._key = key

    def encode(
        self,
        *,
        route: str,
        filters: object,
        order: str,
        high_water: tuple[str, ...],
        last_seen: tuple[str, ...] | None,
    ) -> str:
        normalized_route = _context_value(route, "route")
        normalized_order = _context_value(order, "order")
        normalized_high_water = _position(high_water)
        normalized_last_seen = None if last_seen is None else _position(last_seen)
        payload = canonical_json(
            {
                "v": CURSOR_VERSION,
                "r": normalized_route,
                "f": _filters_hash(filters),
                "o": normalized_order,
                "h": normalized_high_water,
                "l": normalized_last_seen,
            }
        ).encode("utf-8")
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
    ) -> DecodedCursor:
        try:
            normalized_route = _context_value(route, "route")
            normalized_order = _context_value(order, "order")
            if type(token) is not str or not token or len(token) > MAX_CURSOR_CHARACTERS:
                raise ValueError
            token.encode("ascii")
            segments = token.split(".")
            if len(segments) != 2 or not all(segments):
                raise ValueError
            payload_segment, supplied_mac_segment = segments
            payload_bytes = _decode_segment(payload_segment)
            supplied_mac = _decode_segment(supplied_mac_segment)
            expected_mac = digest(self._key, payload_segment.encode("ascii"), "sha256")
            if len(supplied_mac) != len(expected_mac) or not compare_digest(
                supplied_mac, expected_mac
            ):
                raise ValueError
            payload = json.loads(payload_bytes, object_pairs_hook=_unique_object)
            if type(payload) is not dict or set(payload) != _CURSOR_FIELDS:
                raise ValueError
            if (
                payload["v"] != CURSOR_VERSION
                or payload["r"] != normalized_route
                or payload["f"] != _filters_hash(filters)
                or payload["o"] != normalized_order
            ):
                raise ValueError
            high_water = _position(payload["h"])
            raw_last_seen = payload["l"]
            last_seen = None if raw_last_seen is None else _position(raw_last_seen)
            return DecodedCursor(high_water=high_water, last_seen=last_seen)
        except binascii.Error, KeyError, TypeError, UnicodeError, ValueError, json.JSONDecodeError:
            raise InvalidCursorError from None


def validate_page_limit(limit: int) -> int:
    """Reject booleans and every public result page outside the 1..100 contract."""

    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_ITEMS:
        raise ValueError("limit must be between 1 and 100")
    return limit


def require_bounded_page_json(payload_json: str) -> None:
    """Fail closed if one serialized page crosses the public four-MiB ceiling."""

    if type(payload_json) is not str:
        raise TypeError("payload_json must be a string")
    if len(payload_json.encode("utf-8")) >= MAX_PAGE_BYTES:
        raise ValueError("serialized result page must be smaller than 4 MiB")


def _filters_hash(filters: object) -> str:
    return _encode_segment(sha256(canonical_json(filters).encode("utf-8")).digest())


def _context_value(value: str, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"cursor {name} must be a non-empty string")
    return value


def _position(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("cursor position must be a non-empty tuple")
    if any(type(item) is not str or not item for item in value):
        raise ValueError("cursor position values must be non-empty strings")
    return tuple(value)


def _encode_segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_segment(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate cursor payload field")
        value[key] = item
    return value


__all__ = [
    "CURSOR_VERSION",
    "MAX_CURSOR_CHARACTERS",
    "MAX_PAGE_BYTES",
    "MAX_PAGE_ITEMS",
    "CursorSigner",
    "DecodedCursor",
    "HmacCursorSigner",
    "InvalidCursorError",
    "require_bounded_page_json",
    "validate_page_limit",
]
