"""Existing AI aggregate wire bytes stay fixed when adding separate human provenance."""

from hashlib import sha256

import pytest
from tests.unit.test_source_change_assurance import _case
from tests.unit.test_source_change_composition import _assess
from tests.unit.test_source_control_changes import _case as _control_case

_BASELINES = {
    "cap": (21851, "6635891ea7c525230920a1ce9170747c8b514521b8e2229b1e179ae9a5d157e2",
            "4bf5115a7183119d20bbb63ae85479afdcf59d3bf3e721d328edddbc76a88f0b"),
    "current_unknown": (22904, "fc05d98ac784adf7d347c55fd7ada0c1d71c2930634374123c3864c9b8a7297e",
                        "b89266da1230255ed6633a4f1e203db90335a82ee19f95257448a420c233d2fa"),
    "parent_unknown": (22557, "2993f4e763c1c35cf04f5695b16d2cb77323eb21c17594088cc4b1080b1a3b94",
                       "5c35a76fe83833256149a56411fc62aa12b3a0097aa7af8eeaaf07390633c846"),
    "revoke": (24344, "f7eecb5f0cdc96ee8d808ed7b27fb122e00a64c871bd2cb6eacbeb952d68553d",
               "d3def600f452490899b756d4afdbc54a62f1f30e5c7186ffe2a19f5f5b718a71"),
}


@pytest.mark.parametrize("kind", _BASELINES)
def test_ai_aggregate_full_json_and_evidence_hash_remain_exact(kind):
    if kind == "cap":
        case = _case()
    elif kind == "current_unknown":
        case = _case(extra="Only buy when turnover exceeds 3 percent.")
    elif kind == "parent_unknown":
        case = _case(parent_extra="Every action also depends on the blue lantern.")
    else:
        case = _control_case("取消原来的买入规则。")
    result = _assess(case)
    length, digest, evidence = _BASELINES[kind]
    wire = result.model_dump_json().encode()
    assert len(wire) == length
    assert sha256(wire).hexdigest() == digest
    assert result.evidence_hash == evidence
