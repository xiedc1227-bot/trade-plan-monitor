"""Installed v2 contracts and explicit v1 fixture contracts share one drift gate."""

from pathlib import Path

import pytest
from scripts import generate_frontend_types as generator


def _output_paths(root: Path, version: int) -> tuple[Path, Path]:
    if version == 2:
        return (
            root / "openapi.runtime-status.json",
            root / "web/src/api/generated-runtime-status.ts",
        )
    return root / "openapi.json", root / "web/src/api/generated.ts"


def _freeze_outputs(root: Path) -> None:
    for version in (2, 1):
        document = generator.build_openapi_document(monitor_contract_version=version)
        snapshot, typescript = _output_paths(root, version)
        snapshot.write_bytes(generator.render_openapi_snapshot(document).encode("utf-8"))
        typescript.parent.mkdir(parents=True, exist_ok=True)
        contracts = generator.render_typescript_contracts(
            document, monitor_contract_version=version
        )
        typescript.write_bytes(contracts.encode("utf-8"))


@pytest.fixture
def isolated_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(generator, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(generator, "OPENAPI_PATH", tmp_path / "openapi.json")
    monkeypatch.setattr(generator, "TYPESCRIPT_PATH", tmp_path / "web/src/api/generated.ts")
    _freeze_outputs(tmp_path)
    return tmp_path


def test_default_check_covers_installed_v2_and_legacy_v1(isolated_outputs: Path, capsys) -> None:
    assert generator.main(["--check"]) == 0
    output = capsys.readouterr().out
    assert "canonical monitor v2" in output
    assert "compatibility monitor v1" in output


@pytest.mark.parametrize("version", [2, 1])
@pytest.mark.parametrize("output_index", [0, 1])
def test_default_check_rejects_either_contract_drift_without_writing(
    isolated_outputs: Path, capsys, version: int, output_index: int
) -> None:
    stale = _output_paths(isolated_outputs, version)[output_index]
    stale.write_bytes(b"stale\n")
    assert generator.main(["--check"]) == 1
    assert stale.read_bytes() == b"stale\n"
    assert stale.name in capsys.readouterr().err


def test_explicit_legacy_check_does_not_claim_canonical_v2(isolated_outputs: Path, capsys) -> None:
    _output_paths(isolated_outputs, 2)[0].write_bytes(b"stale\n")
    assert generator.main(["--check", "--monitor-contract-version", "1"]) == 0
    output = capsys.readouterr().out
    assert "compatibility monitor v1" in output
    assert "canonical monitor v2" not in output


def test_default_generation_writes_both_labeled_contracts(isolated_outputs: Path) -> None:
    for version in (2, 1):
        for path in _output_paths(isolated_outputs, version):
            path.unlink()
    assert generator.main([]) == 0
    canonical = _output_paths(isolated_outputs, 2)[1].read_text(encoding="utf-8")
    compatibility = _output_paths(isolated_outputs, 1)[1].read_text(encoding="utf-8")
    assert "Canonical installed monitor contract v2" in canonical
    assert "Compatibility monitor contract v1" in compatibility
    assert "export type RuntimeDashboardResponse" in canonical
    assert "export type DashboardResponse" in compatibility
    assert generator.main(["--check"]) == 0
