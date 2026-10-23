import argparse
import json
import subprocess
import tarfile

import pytest
from scripts.experiments import native_determinism_probe as probe


def prepared(tmp_path, monkeypatch, epoch=1700000000):
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as target:
        member = tarfile.TarInfo("source/Cargo.lock")
        member.mtime = epoch
        target.addfile(member)
    monkeypatch.setattr(
        probe,
        "digest",
        lambda _: "62f875393d7f270851f20523dd2e29f082bcc82292d66db2b64ea71f64b6e1c1",
    )
    return argparse.Namespace(
        output=tmp_path / "output",
        archive=archive,
        cache=tmp_path / "cache",
        maturin=tmp_path / "maturin.exe",
        python=tmp_path / "python.exe",
        linker=tmp_path / "link.exe",
        rustbin=tmp_path,
    )


@pytest.mark.parametrize("epoch", [315532799, 4354819199])
def test_epoch_outside_zip_range_never_invokes_tool(tmp_path, monkeypatch, epoch):
    args = prepared(tmp_path, monkeypatch, epoch)
    with pytest.raises(ValueError, match="source epoch"):
        probe.run(args)
    report = json.loads((args.output / "report.json").read_text())
    assert report["commands"] == []
    assert report["status"] == "NOT_PROVEN"


def test_timeout_keeps_diagnostics_and_failure_state(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch)

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1800, output=b"partial", stderr=b"diagnostic")

    monkeypatch.setattr(probe.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="build timeout"):
        probe.run(args)
    report = json.loads((args.output / "report.json").read_text())
    (command,) = report["commands"]
    assert command["timeout"] is True
    assert command["stdout"] == "partial"
    assert command["stderr"] == "diagnostic"
    assert report["status"] == "NOT_PROVEN"
    assert report["artifacts"] == []
    assert not (args.output / "report.tmp").exists()
