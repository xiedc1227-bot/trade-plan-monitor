"""The approved capital-limit scope is pinned to the actual original prompt."""

import hashlib
import json
from pathlib import Path


def test_original_source_snapshot_and_tool_boundaries_are_exact():
    fixture = json.loads((Path(__file__).parents[1] / "fixtures/p3_original_prompt.json")
                         .read_text(encoding="utf-8"))
    assert fixture["sha256_utf8"] == (
        "f17e12b88f4c12d7af7b67caabede2e9d7c2712142a64e67a212c7621865f731")
    assert hashlib.sha256(fixture["source_text"].encode()).hexdigest() == fixture["sha256_utf8"]
    assert len(fixture["excerpts"]) == 5
    assert all(value in fixture["source_text"] for value in fixture["excerpts"])
    assert "真实成交、委托占额及部分成交" in fixture["excerpts"][3]
    assert "一次完整应用正数100股整数倍数量，与真实持仓分开" in fixture["excerpts"][4]
