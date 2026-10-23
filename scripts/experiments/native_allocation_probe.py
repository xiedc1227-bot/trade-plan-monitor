"""Compare isolated R/I imports; Rust-only observations cannot lower admission."""

import argparse
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from scripts.experiments.native_artifact_audit import audit_wheel


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(attempts=[], qualification="RUST_DOMAIN_ONLY", p1="NO_GO")
    imports, expected = {}, {}

    def save():
        temp = args.output / "measurements.tmp"
        temp.write_text(json.dumps(report, indent=2), encoding="utf8")
        temp.replace(args.output / "measurements.json")

    try:
        for variant, builds in [("R", args.release), ("I", args.instrumented)]:
            manifest = json.loads((builds / "report.json").read_text())
            artifacts = manifest.get("artifacts", [])
            if (
                not manifest.get("wheelEqual")
                or not manifest.get("nativeEqual")
                or len(artifacts) != 3
                or len({a.get("sha256") for a in artifacts}) != 1
                or len({a.get("nativeSha256") for a in artifacts}) != 1
                or not all(a.get("sha256") and a.get("nativeSha256") for a in artifacts)
            ):
                raise ValueError("unqualified artifact reproducibility")
            (wheel,) = (builds / "R1/wheels").glob("*.whl")
            audit = audit_wheel(wheel)
            if audit["sha256"] != manifest["artifacts"][0]["sha256"]:
                raise ValueError("artifact changed after qualification")
            expected[variant] = manifest["artifacts"][0]["nativeSha256"]
            target = args.output / (variant + "-import")
            target.mkdir()
            with zipfile.ZipFile(wheel) as z:
                z.extractall(target)
            imports[variant] = target.resolve()
        for turn in range(3):
            for variant in ("R", "I") if turn % 2 == 0 else ("I", "R"):
                dest = args.output / f"{variant}-{turn}"
                env = os.environ.copy()
                env["PYTHONPATH"] = str(imports[variant])
                command = [
                    sys.executable,
                    "-m",
                    "scripts.experiments.native_allocation_child",
                    "--fixtures",
                    str(args.fixtures),
                    "--output",
                    str(dest),
                ]
                attempt = dict(variant=variant, round=turn, argv=command)
                report["attempts"].append(attempt)
                save()
                try:
                    child = subprocess.run(
                        command,
                        env=env,
                        capture_output=True,
                        text=True,
                        errors="replace",
                        timeout=180,
                    )
                except subprocess.TimeoutExpired as error:
                    # subprocess.run has killed and waited for this direct child.
                    attempt["timeout"] = True
                    for key, value in (("stdout", error.stdout), ("stderr", error.stderr)):
                        attempt[key] = (
                            value.decode(errors="replace") if isinstance(value, bytes) else value
                        )
                    raise
                attempt.update(exitCode=child.returncode, stdout=child.stdout, stderr=child.stderr)
                if (dest / "result.json").exists():
                    attempt["result"] = json.loads((dest / "result.json").read_text())
                save()
                child.check_returncode()
                result = attempt["result"]
                if result["nativeSha256"] != expected[variant]:
                    raise ValueError("wrong native import")
                if variant == "I" and result["pythonDomainControl"]["before"] is None:
                    raise ValueError("observer missing")
        report["completed"] = True
    except Exception as error:
        report["failure"] = repr(error)
        raise
    finally:
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("release", "instrumented", "fixtures", "output"):
        parser.add_argument("--" + name, type=lambda p: Path(p).resolve(), required=True)
    run(parser.parse_args())
