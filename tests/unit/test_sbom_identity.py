import copy

import pytest
from scripts.experiments.sbom_identity import normalize


def fixture(root):
    return {
        "metadata": {"component": {"bom-ref": root}},
        "components": [{"bom-ref": "registry:dependency", "version": "1"}],
        "dependencies": [{"ref": root, "dependsOn": ["registry:dependency"]}],
    }


def test_paths_and_graph():
    a = fixture("path+file:///A#core@1")
    b = fixture("path+file:///中文 B#core@1")
    original = copy.deepcopy(a)
    assert normalize(a, "a" * 64) == normalize(b, "a" * 64)
    assert a == original
    assert normalize(a, "a" * 64) != normalize(a, "b" * 64)


def test_broken_graph():
    a = fixture("path+file:///A#core@1")
    a["dependencies"][0]["dependsOn"].append("missing")
    with pytest.raises(ValueError):
        normalize(a, "a" * 64)


@pytest.mark.parametrize("kind", ["duplicate", "external", "unhandled", "hash"])
def test_reject_identity_ambiguity(kind):
    root = "path+file:///中文#core@1"
    a = fixture(root)
    if kind == "duplicate":
        a["components"].append({"bom-ref": root})
    elif kind == "external":
        a["components"].append({"bom-ref": "path+file:///other#core@1"})
    elif kind == "unhandled":
        a["unexpected"] = root
    with pytest.raises(ValueError):
        normalize(a, "invalid" if kind == "hash" else "a" * 64)


def test_dependency_change_is_not_hidden():
    a = fixture("path+file:///A#core@1")
    b = copy.deepcopy(a)
    b["components"][0]["version"] = "2"
    assert normalize(a, "a" * 64) != normalize(b, "a" * 64)
