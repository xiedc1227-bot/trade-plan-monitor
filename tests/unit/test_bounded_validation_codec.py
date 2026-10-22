"""Experimental transport must preserve evidence and reserve before copying."""

from dataclasses import replace

import pytest
from scripts.experiments.bounded_codec import (
    LIMIT,
    RESERVE,
    AdmissionError,
    ProtocolError,
    decode,
    encode,
    plan,
)

from trade_plan_monitor.state.index_evidence import RawIndexCandidate


def candidate(value=b'{"literal": "unchanged"}', text=True):
    return RawIndexCandidate(
        ("mapping", "code", "cutoff", "request", 1, "hash", "at"),
        ("hash", "mapping", "code", "cutoff", "request", 1, 1, "bars", "formula",
         value, "at", 1), text,
    )


@pytest.mark.parametrize("value", [None, True, False, -5, 2**63-1, b'\xff', "中文😀"])
def test_exact_scalar_round_trip(value):
    row = candidate(value, False)
    assert row.exact(decode(encode((row,)))[0])


def test_missing_payload_and_empty_stream():
    row = replace(candidate(), payload=None)
    assert row.exact(decode(encode((row,)))[0])
    assert decode(encode(())) == ()


@pytest.mark.parametrize("damage", ["trailing", "truncated", "tag"])
def test_decoder_rejects_malformed_frame(damage):
    data = encode((candidate(),))
    if damage == "trailing":
        data += b'x'
    elif damage == "truncated":
        data = data[:-1]
    else:
        data[6] = 255
    with pytest.raises(ProtocolError):
        decode(data)


def test_aggregate_budget_includes_external_leases_and_exact_boundary():
    assert LIMIT == 64 * 1024 * 1024 and RESERVE == 16 * 1024 * 1024
    rows = (candidate(),)
    raw = sum(r.retained_size() for r in rows)
    assert plan(rows, external_bytes=LIMIT-RESERVE-raw).reserved == LIMIT
    with pytest.raises(AdmissionError):
        plan(rows, external_bytes=LIMIT-RESERVE-raw+1)


@pytest.mark.parametrize("value", [b'x'*(16*1024*1024), 1.5, 2**64],
                         ids=["large", "float", "integer-overflow"])
def test_large_or_unsupported_input_never_encodes_before_admission(value):
    with pytest.raises(AdmissionError):
        plan((candidate(value),))


def test_partition_obeys_copy_and_decoded_text_limits():
    rows = (candidate(b'x'*50000),)*30
    admission = plan(rows)
    assert len(admission.chunks) > 1
    for start, end in admission.chunks:
        assert len(encode(rows[start:end])) <= 1024*1024
        assert all(a.exact(b) for a, b in zip(
            rows[start:end], decode(encode(rows[start:end])), strict=True,
        ))
