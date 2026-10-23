import argparse
import json
import subprocess

import pytest
from scripts.experiments import native_allocation_probe as probe


def prepared(tmp_path, monkeypatch):
    builds = tmp_path / "builds"
    wheels = builds / "R1/wheels"
    wheels.mkdir(parents=True)
    (wheels / "test.whl").touch()
    artifacts = [dict(sha256="wheel", nativeSha256="native") for _ in range(3)]
    (builds / "report.json").write_text(
        json.dumps(dict(wheelEqual=True, nativeEqual=True, artifacts=artifacts))
    )
    monkeypatch.setattr(probe, "audit_wheel", lambda _: dict(sha256="wheel"))

    class Archive:
        def __init__(self, path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extractall(self, target):
            pass

    monkeypatch.setattr(probe.zipfile, "ZipFile", Archive)
    return argparse.Namespace(
        output=tmp_path / "output",
        release=builds,
        instrumented=builds,
        fixtures=tmp_path / "fixtures",
    )


@pytest.mark.parametrize("field", ["sha256", "nativeSha256"])
def test_reject_inconsistent_reproducibility_claim(tmp_path, monkeypatch, field):
    args = prepared(tmp_path, monkeypatch)
    path = args.release / "report.json"
    manifest = json.loads(path.read_text())
    manifest["artifacts"][2][field] = "different"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unqualified"):
        probe.run(args)
    report = json.loads((args.output / "measurements.json").read_text())
    assert report["attempts"] == []


def test_timeout_retains_attempt_and_partial_output(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch)

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 180, output=b"partial", stderr=b"diagnostic")

    monkeypatch.setattr(probe.subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        probe.run(args)
    report = json.loads((args.output / "measurements.json").read_text())
    (attempt,) = report["attempts"]
    assert attempt["variant"] == "R"
    assert attempt["round"] == 0
    assert attempt["argv"][1:3] == ["-m", "scripts.experiments.native_allocation_child"]
    assert attempt["timeout"] is True
    assert attempt["stdout"] == "partial"
    assert attempt["stderr"] == "diagnostic"
    assert "completed" not in report
    assert not (args.output / "measurements.tmp").exists()
