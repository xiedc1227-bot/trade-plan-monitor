"""Two clean locked native builds; run in an x64 MSVC developer environment."""

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import zipfile
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def members(path):
    with zipfile.ZipFile(path) as wheel:
        return {name: hashlib.sha256(wheel.read(name)).hexdigest() for name in wheel.namelist()}


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(
        status="NOT_PROVEN",
        archiveSha256=digest(args.archive),
        commands=[],
        runnerSha256=digest(Path(__file__)),
    )
    env = os.environ.copy()
    env["RUSTUP_TOOLCHAIN"] = "1.94.0"
    env["RUSTFLAGS"] = ""
    env["CARGO_HOME"] = str(args.output / "cargo-home")
    env["CARGO_INCREMENTAL"] = "0"
    env.pop("RUSTC_WRAPPER", None)
    env.pop("RUSTC_WORKSPACE_WRAPPER", None)
    env.pop("CARGO_ENCODED_RUSTFLAGS", None)
    env.pop("CARGO_BUILD_RUSTFLAGS", None)

    def command(argv, cwd):
        result = subprocess.run(
            argv, cwd=cwd, env=env, capture_output=True, text=True, errors="replace", timeout=1800
        )
        report["commands"].append(
            dict(argv=argv, exitCode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        )
        save()
        result.check_returncode()

    def save():
        (args.output / "build.json").write_text(json.dumps(report, indent=2), encoding="utf8")

    try:
        if report["archiveSha256"] != (
            "62f875393d7f270851f20523dd2e29f082bcc82292d66db2b64ea71f64b6e1c1"
        ):
            raise ValueError("unverified source archive")
        for tool in (("rustc", "-Vv"), ("cargo", "-V"), (str(args.maturin), "--version")):
            command(list(tool), args.output)
        report["compilerEnvironment"] = {
            name: env.get(name.upper(), env.get(name))
            for name in (
                "VCToolsVersion",
                "WindowsSDKVersion",
                "VCToolsInstallDir",
                "WindowsSdkDir",
            )
        }
        canary = args.output / "flag-canary"
        (canary / "src").mkdir(parents=True)
        (canary / "Cargo.toml").write_text(
            '[package]\nname="flag-canary"\nversion="0.1.0"\nedition="2024"\n',
            encoding="utf8",
        )
        (canary / "src/main.rs").write_text("fn main() {}", encoding="utf8")
        (canary / "build.rs").write_text(
            'fn main() { for key in ["RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS"] {'
            'println!("cargo:warning={}={:?}", key, std::env::var(key)); }}',
            encoding="utf8",
        )
        env["CARGO_TARGET_DIR"] = str(canary / "target")
        env["RUSTFLAGS"] = "-Copt-level=2"
        command(["cargo", "build", "--offline", "--verbose"], canary)
        env["RUSTFLAGS"] = ""
        for name in ("R1", "R2"):
            dest = args.output / name
            dest.mkdir()
            with tarfile.open(args.archive) as archive:
                archive.extractall(dest, filter="data")
            (source,) = dest.iterdir()
            env["CARGO_TARGET_DIR"] = str(dest / "target")
            report[name + "LockSha256"] = digest(source / "Cargo.lock")
            command(["cargo", "fetch", "--locked", "--target", "x86_64-pc-windows-msvc"], source)
            command(
                [
                    str(args.maturin),
                    "build",
                    "--release",
                    "--locked",
                    "--offline",
                    "--verbose",
                    "--target",
                    "x86_64-pc-windows-msvc",
                    "--interpreter",
                    str(args.python),
                    "--out",
                    str(dest / "wheels"),
                ],
                source,
            )
        wheels = [next((args.output / name / "wheels").glob("*.whl")) for name in ("R1", "R2")]
        report["members"] = [members(wheel) for wheel in wheels]
        report["identicalMembers"] = report["members"][0] == report["members"][1]
        report["status"] = "MATCHED" if report["identicalMembers"] else "DIFFERENT"
        report["qualification"] = "Build comparison only; native allocation bounds NOT_PROVEN"
    except Exception as error:
        report["failure"] = str(error)
        raise
    finally:
        save()
    return report["status"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "output", "maturin", "python"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    raise SystemExit(0 if run(parser.parse_args()) == "MATCHED" else 2)
