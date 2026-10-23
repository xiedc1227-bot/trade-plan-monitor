import argparse
import json
import zipfile

import pytest
from scripts.experiments.native_build_probe import members, run


def test_member_comparison_detects_native_change(tmp_path):
    paths = [tmp_path / name for name in ("one.whl", "two.whl")]
    for path, binary in zip(paths, (b"one", b"two"), strict=True):
        with zipfile.ZipFile(path, "w") as wheel:
            wheel.writestr("core.pyd", binary)
    assert members(paths[0]) != members(paths[1])


def test_wrong_archive_stops_before_compiler(tmp_path):
    archive = tmp_path / "source.tar.gz"
    archive.write_bytes(b"untrusted")
    output = tmp_path / "output"
    args = argparse.Namespace(archive=archive, output=output)
    with pytest.raises(ValueError, match="unverified"):
        run(args)
    report = json.loads((output / "build.json").read_text())
    assert report["status"] == "NOT_PROVEN"
    assert report["commands"] == []
