"""Differential contracts for the isolated normalization candidate."""

from decimal import Decimal

import pytest
import test_bounded_c_producer as contracts
from scripts.experiments import c_validator, fused_c_validator
from scripts.experiments.bounded_c_producer import bound, normalize
from scripts.experiments.fused_c_validator import normalize as fused


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        -123,
        "中文😀\n",
        Decimal("-0.00"),
        Decimal("1E-999"),
        [],
        {},
        {"a": [1, None, Decimal("2.50")]},
    ],
)
def test_value_and_bound(value):
    expected, actual = normalize(value), fused(value)
    assert actual == expected
    assert bound(actual) == bound(expected)


@pytest.mark.parametrize("value", [1.5, {1: "wrong key"}, Decimal("NaN")])
def test_same_rejection(value):
    with pytest.raises((ValueError, TypeError)) as previous:
        normalize(value)
    with pytest.raises(type(previous.value)):
        fused(value)


@pytest.fixture
def candidate(monkeypatch):
    monkeypatch.setattr(c_validator, "latest", fused_c_validator.latest)
    monkeypatch.setattr(contracts, "normalize", fused)


@pytest.mark.parametrize("field", range(19))
def test_raw_fields(candidate, field):
    contracts.test_every_raw_field_differential(field)


@pytest.mark.parametrize("field", ["bar_set_hash", "request_set_hash", "formula_definition_hash"])
def test_rehashed_domains(candidate, field):
    contracts.test_rehashed_root_cannot_hide_domain_tamper(field)


@pytest.mark.parametrize(
    "name",
    [
        "test_literal_and_logical_bound",
        "test_parallel_producers_do_not_share_context",
        "test_cancel_mid_production_releases_current_buffer",
        "test_cleanup_debt_prevents_new_production",
        "test_invalidated_size_fences_and_retains_debt",
        "test_storage_stop_prevents_next_encoding_unit",
    ],
)
def test_existing_lifecycle(candidate, name):
    getattr(contracts, name)()
