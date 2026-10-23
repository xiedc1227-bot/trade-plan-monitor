import argparse
import base64
import hashlib
import json
import zipfile

import pytest
from scripts.experiments.native_allocation_probe import run as allocation_run
from scripts.experiments.native_artifact_audit import audit_wheel
from scripts.experiments.native_determinism_probe import run


def wheel(path, *, corrupt=False, duplicate=False, unsafe=False, name="pkg/core.pyd"):
    name = "../escape" if unsafe else name
    payload = b"original"
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
    record = f"{name},sha256={digest},8\npkg-1.dist-info/RECORD,,\n"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name, b"modified" if corrupt else payload)
        if duplicate:
            z.writestr(name, payload)
        z.writestr("pkg-1.dist-info/RECORD", record)
    return path


def test_valid_wheel(tmp_path):
    assert audit_wheel(wheel(tmp_path / "ok.whl"))["members"]["pkg/core.pyd"]


@pytest.mark.parametrize("case", ["corrupt", "duplicate", "unsafe"])
def test_reject_invalid_wheel(tmp_path, case):
    with pytest.raises(ValueError):
        audit_wheel(wheel(tmp_path / "bad.whl", **{case: True}))


@pytest.mark.parametrize(
    "record",
    [
        "pkg/core.pyd,sha256=wrong,8\npkg-1.dist-info/RECORD,,\n",
        "pkg-1.dist-info/RECORD,,\n",
        "pkg-1.dist-info/RECORD,,\npkg-1.dist-info/RECORD,,\n",
        "pkg-1.dist-info/RECORD,sha256=wrong,1\n",
    ],
)
def test_record_tamper(tmp_path, record):
    path = tmp_path / "record.whl"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("pkg/core.pyd", b"original")
        z.writestr("pkg-1.dist-info/RECORD", record)
    with pytest.raises(ValueError):
        audit_wheel(path)


def test_failed_source_preserves_report(tmp_path):
    source = tmp_path / "source"
    source.write_bytes(b"tampered")
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="unverified"):
        run(argparse.Namespace(output=output, archive=source))
    report = json.loads((output / "report.json").read_text())
    assert report["status"] == "NOT_PROVEN"
    assert report["commands"] == []
    assert "unverified" in report["failure"]


def test_allocation_requires_artifact_gate(tmp_path):
    builds = tmp_path / "builds"
    builds.mkdir()
    (builds / "report.json").write_text(json.dumps({"wheelEqual": False, "artifacts": []}))
    output = tmp_path / "allocation"
    with pytest.raises(ValueError, match="unqualified"):
        allocation_run(argparse.Namespace(output=output, release=builds, instrumented=builds))
    report = json.loads((output / "measurements.json").read_text())
    assert report["attempts"] == []
    assert "unqualified" in report["failure"]


@pytest.mark.parametrize(
    "name",
    [
        "pkg/./core.pyd",
        "pkg//core.pyd",
        "pkg/core.pyd.",
        "pkg /core.pyd",
        "pkg/CON.pyd",
        "pkg/core?.pyd",
    ],
)
def test_reject_windows_path_alias(tmp_path, name):
    with pytest.raises(ValueError, match="unsafe"):
        audit_wheel(wheel(tmp_path / "alias.whl", name=name))


@pytest.mark.parametrize("second", ["PKG/core.pyd", "pkg/core.pyd/child"])
def test_reject_extraction_collision(tmp_path, second):
    path = wheel(tmp_path / "collision.whl")
    with zipfile.ZipFile(path, "a") as z:
        z.writestr(second, b"other")
    with pytest.raises(ValueError, match="colliding"):
        audit_wheel(path)


def test_reject_symlink(tmp_path):
    path = wheel(tmp_path / "link.whl")
    with zipfile.ZipFile(path, "a") as z:
        entry = zipfile.ZipInfo("pkg/link")
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        z.writestr(entry, "core.pyd")
    with pytest.raises(ValueError, match="unsafe"):
        audit_wheel(path)
