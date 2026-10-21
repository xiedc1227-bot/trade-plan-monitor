"""Literal SQL storage types and complete input fields belong to the equality fence."""

from types import SimpleNamespace

from trade_plan_monitor.state.index_evidence import (
    HEAD_FIELDS,
    PAYLOAD_FIELDS,
    RawIndexCandidate,
)
from trade_plan_monitor.state.models import MarketIndexSnapshot, MarketIndexSnapshotHead


def test_all_stored_head_and_payload_columns_are_included():
    assert set(HEAD_FIELDS) == set(MarketIndexSnapshotHead.__table__.c.keys())
    assert set(PAYLOAD_FIELDS) == set(MarketIndexSnapshot.__table__.c.keys())


def test_json_text_blob_whitespace_scalar_type_and_missing_marker_remain_distinct():
    head = SimpleNamespace(**dict.fromkeys(HEAD_FIELDS, "head"))
    payload = SimpleNamespace(**dict.fromkeys(PAYLOAD_FIELDS, "payload"))
    payload.snapshot_json = '{"中文":"value"}'
    original = RawIndexCandidate.capture(head, payload)
    assert original.decoded()[1].snapshot_json == payload.snapshot_json
    assert original.exact(RawIndexCandidate.capture(head, payload))
    for raw in (payload.snapshot_json.encode(), payload.snapshot_json + " ", None):
        changed = SimpleNamespace(**vars(payload))
        changed.snapshot_json = raw
        assert not original.exact(RawIndexCandidate.capture(head, changed))
    head.provider_content_revision = 1
    integer = RawIndexCandidate.capture(head, payload)
    head.provider_content_revision = True
    assert not integer.exact(RawIndexCandidate.capture(head, payload))
    assert not original.exact(RawIndexCandidate.capture(head, None))
    assert RawIndexCandidate.capture(head, None).decoded()[1] is None
