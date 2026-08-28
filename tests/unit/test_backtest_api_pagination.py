"""Security and stability contracts for backtest API cursor pagination."""

from __future__ import annotations

import base64
import json
from dataclasses import FrozenInstanceError
from hashlib import sha256
from hmac import digest

import pytest

from trade_plan_monitor.backtest.canonical import canonical_json
from trade_plan_monitor.web.backtest_pagination import (
    BacktestApiCursorSigner,
    BacktestCursorState,
    BacktestMembershipConflictError,
    InvalidBacktestCursorError,
)
from trade_plan_monitor.web.schemas import ApiErrorCode

_KEY = bytes(range(32))
_ROTATED_KEY = bytes(reversed(range(32)))
_ROUTE = "/backtest-runs"
_ORDER = "completedAt DESC,runId DESC"
_FILTERS = {
    "symbol": "000001.SZ",
    "planVersionId": None,
    "datasetHash": None,
    "completedFrom": None,
    "completedTo": None,
    "pinned": None,
}
_HIGH_WATER = ("2026-08-28T15:00:00.000000+08:00", "f" * 64)
_LAST_SEEN = ("2026-08-27T15:00:00.000000+08:00", "e" * 64)


def _decode_segment(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _encode_segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _signed_token(payload_text: str, *, key: bytes = _KEY) -> str:
    payload_segment = _encode_segment(payload_text.encode("utf-8"))
    mac_segment = _encode_segment(digest(key, payload_segment.encode("ascii"), "sha256"))
    return f"{payload_segment}.{mac_segment}"


def _encode_run_cursor(
    signer: BacktestApiCursorSigner,
    *,
    last_seen: tuple[str, ...] | None = _LAST_SEEN,
) -> str:
    return signer.encode(
        route=_ROUTE,
        filters=_FILTERS,
        order=_ORDER,
        high_water=_HIGH_WATER,
        last_seen=last_seen,
    )


def test_cursor_uses_exact_two_unpadded_base64url_hmac_sha256_segments() -> None:
    signer = BacktestApiCursorSigner(_KEY)

    token = _encode_run_cursor(signer)
    segments = token.split(".")

    assert len(segments) == 2
    assert all(segment and "=" not in segment for segment in segments)
    base64url_characters = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert all(set(segment) <= base64url_characters for segment in segments)
    payload_segment, mac_segment = segments
    payload = json.loads(_decode_segment(payload_segment))
    assert payload == {
        "v": "cursor-v1",
        "r": _ROUTE,
        "f": _encode_segment(sha256(canonical_json(_FILTERS).encode("utf-8")).digest()),
        "o": _ORDER,
        "h": list(_HIGH_WATER),
        "l": list(_LAST_SEEN),
    }
    assert _decode_segment(mac_segment) == digest(
        _KEY,
        payload_segment.encode("ascii"),
        "sha256",
    )


def test_cursor_state_is_frozen_and_high_water_anchor_is_stable() -> None:
    signer = BacktestApiCursorSigner(_KEY)
    token = _encode_run_cursor(signer)

    state = signer.decode(token, route=_ROUTE, filters=_FILTERS, order=_ORDER)
    anchor = signer.high_watermark(
        route=_ROUTE,
        filters=_FILTERS,
        order=_ORDER,
        state=state,
    )

    assert state == BacktestCursorState(
        high_water=_HIGH_WATER,
        last_seen=_LAST_SEEN,
        membership_revision=None,
    )
    assert signer.decode(
        anchor,
        route=_ROUTE,
        filters=_FILTERS,
        order=_ORDER,
    ) == BacktestCursorState(
        high_water=_HIGH_WATER,
        last_seen=None,
        membership_revision=None,
    )
    assert anchor == _encode_run_cursor(signer, last_seen=None)
    with pytest.raises(FrozenInstanceError):
        state.last_seen = None  # type: ignore[misc]


def test_static_keyset_traversal_has_no_gap_or_duplicate_and_excludes_late_rows() -> None:
    signer = BacktestApiCursorSigner(_KEY)
    rows = tuple(
        (f"2026-08-{day:02d}T15:00:00.000000+08:00", f"{day:064x}") for day in range(28, 23, -1)
    )
    high_water = rows[0]
    first_page = rows[:2]
    cursor = signer.encode(
        route=_ROUTE,
        filters=_FILTERS,
        order=_ORDER,
        high_water=high_water,
        last_seen=first_page[-1],
    )
    late_row = ("2026-08-29T15:00:00.000000+08:00", "9" * 64)

    state = signer.decode(cursor, route=_ROUTE, filters=_FILTERS, order=_ORDER)
    remaining = tuple(
        row
        for row in (late_row, *rows)
        if row <= state.high_water and state.last_seen is not None and row < state.last_seen
    )

    assert first_page + remaining == rows
    assert len(set(first_page + remaining)) == len(rows)
    assert late_row not in first_page + remaining
    assert signer.high_watermark(
        route=_ROUTE,
        filters=_FILTERS,
        order=_ORDER,
        state=state,
    ) == signer.encode(
        route=_ROUTE,
        filters=_FILTERS,
        order=_ORDER,
        high_water=high_water,
        last_seen=None,
    )


@pytest.mark.parametrize(
    ("token_factory", "route", "filters", "order", "signing_key"),
    (
        (
            lambda token: token[:-1] + ("A" if token[-1] != "A" else "B"),
            _ROUTE,
            _FILTERS,
            _ORDER,
            _KEY,
        ),
        (lambda token: token + "=", _ROUTE, _FILTERS, _ORDER, _KEY),
        (lambda _token: "not-base64!.still-not-base64!", _ROUTE, _FILTERS, _ORDER, _KEY),
        (lambda token: token, "/backtest-datasets", _FILTERS, _ORDER, _KEY),
        (lambda token: token, _ROUTE, _FILTERS | {"pinned": True}, _ORDER, _KEY),
        (lambda token: token, _ROUTE, _FILTERS, "completedAt ASC,runId ASC", _KEY),
        (lambda token: token, _ROUTE, _FILTERS, _ORDER, _ROTATED_KEY),
        (lambda token: token, _ROUTE, _FILTERS, _ORDER, None),
    ),
    ids=(
        "tampered-mac",
        "padded-encoding",
        "malformed-encoding",
        "route-mismatch",
        "filter-mismatch",
        "order-mismatch",
        "rotated-key",
        "missing-key",
    ),
)
def test_invalid_cursor_causes_one_non_oracular_validation_error(
    token_factory: object,
    route: str,
    filters: dict[str, object],
    order: str,
    signing_key: bytes | None,
) -> None:
    token = _encode_run_cursor(BacktestApiCursorSigner(_KEY))
    mutated = token_factory(token)  # type: ignore[operator]

    with pytest.raises(InvalidBacktestCursorError) as captured:
        BacktestApiCursorSigner(signing_key).decode(
            mutated,
            route=route,
            filters=filters,
            order=order,
        )

    assert captured.value.code is ApiErrorCode.VALIDATION_ERROR
    assert captured.value.details == ()
    assert str(captured.value) == ApiErrorCode.VALIDATION_ERROR.value


@pytest.mark.parametrize(
    "payload_update",
    (
        {"v": "cursor-v0"},
        {"unexpected": "field"},
        {"h": []},
        {"h": ["created-at", "identity", "unexpected"]},
        {"h": ["2026-08-28T15:00:00.000000Z", "identity"]},
        {"h": ["valid", 1]},
        {"l": []},
        {"l": ["created-at"]},
        {"l": ["2026-08-28T15:00:00+08:00", "identity"]},
        {"m": None},
        {"m": True},
        {"m": -1},
        {"m": 9_007_199_254_740_992},
    ),
)
def test_signed_malformed_payload_still_has_the_uniform_validation_error(
    payload_update: dict[str, object],
) -> None:
    token = _encode_run_cursor(BacktestApiCursorSigner(_KEY))
    payload = json.loads(_decode_segment(token.split(".")[0]))
    payload.update(payload_update)
    malformed = _signed_token(canonical_json(payload))

    with pytest.raises(InvalidBacktestCursorError) as captured:
        BacktestApiCursorSigner(_KEY).decode(
            malformed,
            route=_ROUTE,
            filters=_FILTERS,
            order=_ORDER,
        )

    assert captured.value.code is ApiErrorCode.VALIDATION_ERROR
    assert captured.value.details == ()


@pytest.mark.parametrize(
    ("high_water", "last_seen"),
    (
        (("identity",), None),
        ((_HIGH_WATER[0], "identity", "unexpected"), None),
        ((_HIGH_WATER[0], "identity"), ("identity",)),
        ((_HIGH_WATER[0], "identity"), (_LAST_SEEN[0], "identity", "unexpected")),
    ),
)
def test_encoder_rejects_every_non_two_part_keyset_position(
    high_water: tuple[str, ...],
    last_seen: tuple[str, ...] | None,
) -> None:
    with pytest.raises(ValueError, match="exactly two"):
        BacktestApiCursorSigner(_KEY).encode(
            route=_ROUTE,
            filters=_FILTERS,
            order=_ORDER,
            high_water=high_water,
            last_seen=last_seen,
        )


@pytest.mark.parametrize(
    "event_time",
    (
        "2026-08-28T15:00:00.000000Z",
        "2026-08-28T15:00:00+08:00",
        "2026-08-28T15:00:00.000000+00:00",
        "2026-08-28T15:00:00.0000000+08:00",
    ),
)
def test_encoder_requires_fixed_six_digit_shanghai_keyset_time(event_time: str) -> None:
    with pytest.raises(ValueError, match=r"fixed-six-digit.*\+08:00"):
        BacktestApiCursorSigner(_KEY).encode(
            route=_ROUTE,
            filters=_FILTERS,
            order=_ORDER,
            high_water=(event_time, "f" * 64),
            last_seen=None,
        )


def test_status_filtered_job_cursor_binds_membership_revision_and_detects_drift() -> None:
    signer = BacktestApiCursorSigner(_KEY)
    filters = {
        "kind": None,
        "status": ["QUEUED", "RUNNING"],
        "runId": None,
        "datasetHash": None,
        "createdFrom": None,
        "createdTo": None,
    }
    token = signer.encode(
        route="/backtest-jobs",
        filters=filters,
        order="createdAt DESC,jobId DESC",
        high_water=("2026-08-28T10:00:00.000000+08:00", "job-2"),
        last_seen=("2026-08-28T09:00:00.000000+08:00", "job-1"),
        membership_revision=7,
    )

    state = signer.decode(
        token,
        route="/backtest-jobs",
        filters=filters,
        order="createdAt DESC,jobId DESC",
        current_membership_revision=7,
    )
    assert state.membership_revision == 7

    with pytest.raises(BacktestMembershipConflictError) as captured:
        signer.decode(
            token,
            route="/backtest-jobs",
            filters=filters,
            order="createdAt DESC,jobId DESC",
            current_membership_revision=8,
        )
    assert captured.value.code is ApiErrorCode.CONFLICT
    assert captured.value.details == ()
    assert str(captured.value) == ApiErrorCode.CONFLICT.value


def test_unfiltered_job_cursor_ignores_heartbeat_progress_and_status_revision_changes() -> None:
    signer = BacktestApiCursorSigner(_KEY)
    filters = {
        "kind": ["BACKTEST_RUN"],
        "status": None,
        "runId": None,
        "datasetHash": None,
        "createdFrom": None,
        "createdTo": None,
    }
    token = signer.encode(
        route="/backtest-jobs",
        filters=filters,
        order="createdAt DESC,jobId DESC",
        high_water=("2026-08-28T10:00:00.000000+08:00", "job-2"),
        last_seen=("2026-08-28T09:00:00.000000+08:00", "job-1"),
    )

    before = signer.decode(
        token,
        route="/backtest-jobs",
        filters=filters,
        order="createdAt DESC,jobId DESC",
        current_membership_revision=7,
    )
    after_progress_and_status_changes = signer.decode(
        token,
        route="/backtest-jobs",
        filters=filters,
        order="createdAt DESC,jobId DESC",
        current_membership_revision=99,
    )

    assert before == after_progress_and_status_changes
    assert before.membership_revision is None


@pytest.mark.parametrize(
    ("filters", "membership_revision"),
    (
        ({"status": ["RUNNING"]}, None),
        ({"status": ["RUNNING"]}, True),
        ({"status": ["RUNNING"]}, -1),
        ({"status": ["RUNNING"]}, 9_007_199_254_740_992),
        ({"status": None}, 0),
        ({}, 0),
    ),
)
def test_membership_revision_is_required_only_for_status_filtered_jobs(
    filters: dict[str, object],
    membership_revision: object,
) -> None:
    with pytest.raises(ValueError, match="membership revision"):
        BacktestApiCursorSigner(_KEY).encode(
            route="/backtest-jobs",
            filters=filters,
            order="createdAt DESC,jobId DESC",
            high_water=("2026-08-28T10:00:00.000000+08:00", "job-2"),
            last_seen=None,
            membership_revision=membership_revision,  # type: ignore[arg-type]
        )


def test_signer_never_exposes_the_secret_or_falls_back_to_unsigned_tokens() -> None:
    signer = BacktestApiCursorSigner(_KEY)
    unavailable = BacktestApiCursorSigner(None)

    assert _KEY.hex() not in repr(signer)
    with pytest.raises(InvalidBacktestCursorError):
        _encode_run_cursor(unavailable)
