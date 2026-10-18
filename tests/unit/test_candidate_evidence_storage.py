"""Deduplicated evidence storage is reversible and retains expansion bounds."""

import copy

import pytest

from trade_plan_monitor.ai.candidate_storage import pack_evidence, unpack_evidence


def example():
    clause = {"clause_id": "c1", "excerpt": "Keep this rule", "paths": ["quantity"]}
    return {
        "schema_version": "monitor-loop-materialized-update-v1",
        "extraction": {},
        "review": {
            "bindings": [
                {"path": "a", "clauses": [clause]},
                {"path": "b", "clauses": [copy.deepcopy(clause)]},
            ]
        },
    }


def test_shared_source_evidence_is_stored_once_and_restored_exactly():
    value = example()
    packed = pack_evidence(value)
    assert len(packed["clause_pool"]) == 1
    assert packed["review"]["bindings"][0]["clauses"] == [0]
    assert unpack_evidence(packed) == value
    assert value == example()


def test_storage_never_accepts_a_missing_or_negative_reference():
    for index in (-1, 10, True):
        packed = pack_evidence(example())
        packed["review"]["bindings"][0]["clauses"] = [index]
        with pytest.raises(ValueError):
            unpack_evidence(packed)


def test_storage_expansion_limit_is_not_bypassed_by_references():
    value = example()
    value["review"]["bindings"][0]["clauses"][0]["excerpt"] = "x" * 600000
    value["review"]["bindings"][1]["clauses"] = value["review"]["bindings"][0]["clauses"]
    with pytest.raises(ValueError, match="expansion"):
        unpack_evidence(pack_evidence(value))


def test_repeated_path_lists_are_pooled_across_extraction_and_source_evidence():
    value = example()
    paths = [f"ordinary_rules[0].condition.conditions[{n}].type" for n in range(40)]
    value["extraction"] = {
        "output": {"clauses": [{"clause_id": f"c{i}", "paths": paths} for i in range(100)]}
    }
    for binding in value["review"]["bindings"]:
        binding["clauses"][0]["paths"] = paths
    packed = pack_evidence(value)
    assert "string_list_pool" in packed
    assert unpack_evidence(packed) == value


def test_string_pool_rejects_invalid_references_and_recursive_values():
    packed = pack_evidence(example())
    packed["clause_pool"][0]["paths"] = {"$strings": -1}
    with pytest.raises(ValueError):
        unpack_evidence(packed)


@pytest.mark.parametrize("review", [None, [], {"bindings": [None]}])
def test_malformed_storage_shape_is_a_validation_error(review):
    packed = pack_evidence(example())
    packed["review"] = review
    with pytest.raises(ValueError):
        unpack_evidence(packed)
