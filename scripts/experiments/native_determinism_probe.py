"""Three clean full-core builds; run in the pinned MSVC developer environment."""

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path

from scripts.experiments.native_artifact_audit import audit_wheel
from scripts.experiments.native_build_probe import digest


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(
        status="NOT_PROVEN", commands=[], artifacts=[], runnerSha256=digest(Path(__file__))
    )

    def save():
        temp = args.output / "report.tmp"
        temp.write_text(json.dumps(report, indent=2), encoding="utf8")
        temp.replace(args.output / "report.json")

    def command(argv, cwd, env):
        try:
            r = subprocess.run(
                argv,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=1800,
            )
        except subprocess.TimeoutExpired as error:
            attempt = dict(argv=argv, timeout=True)
            for key, value in (("stdout", error.stdout), ("stderr", error.stderr)):
                attempt[key] = value.decode(errors="replace") if isinstance(value, bytes) else value
            report["commands"].append(attempt)
            save()
            raise RuntimeError("build timeout") from error
        report["commands"].append(
            dict(argv=argv, exitCode=r.returncode, stdout=r.stdout, stderr=r.stderr)
        )
        save()
        r.check_returncode()
        if "LNK4044" in r.stdout + r.stderr:
            raise ValueError("ignored linker option")

    try:
        report["archiveSha256"] = digest(args.archive)
        if (
            report["archiveSha256"]
            != "62f875393d7f270851f20523dd2e29f082bcc82292d66db2b64ea71f64b6e1c1"
        ):
            raise ValueError("unverified source archive")
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper()
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "USERPROFILE",
                "APPDATA",
                "LOCALAPPDATA",
                "INCLUDE",
                "LIB",
                "LIBPATH",
                "VCTOOLSINSTALLDIR",
                "VCTOOLSVERSION",
                "WINDOWSSDKDIR",
                "WINDOWSSDKVERSION",
                "RUSTUP_HOME",
            }
        }
        env.update(RUSTUP_TOOLCHAIN="1.94.0", CARGO_INCREMENTAL="0", CARGO_HOME=str(args.cache))
        report["tools"] = {str(p): digest(p) for p in (args.maturin, args.python, args.linker)}
        with tarfile.open(args.archive) as archive:
            epoch = max(int(m.mtime) for m in archive.getmembers())
        if not 315532800 <= epoch <= 4354819198:
            raise ValueError("source epoch outside ZIP range")
        report["sourceEpoch"] = epoch
        env["SOURCE_DATE_EPOCH"] = str(epoch)
        if getattr(args, "instrument", None):
            report["observerSha256"] = digest(args.instrument)
        if getattr(args, "sbom_script", None):
            env["TPM_SBOM_PYTHON"] = str(args.python)
            env["TPM_SBOM_SCRIPT"] = str(args.sbom_script)
            env["TPM_SOURCE_SHA256"] = report["archiveSha256"]
            if getattr(args, "instrument", None):
                env["TPM_SOURCE_SHA256"] = hashlib.sha256(
                    (
                        report["archiveSha256"]
                        + report["observerSha256"]
                        + "\nmod tpm_alloc_observer;\n"
                    ).encode()
                ).hexdigest()
            report["sbomTransformSha256"] = digest(args.sbom_script)
        for tool, flag in [("rustc", "-Vv"), ("cargo", "-V")]:
            command([str(args.rustbin / (tool + ".exe")), flag], args.output, env)
        for index, name in enumerate(("R1", "R2", "R3 space 中文")):
            dest = args.output / name
            dest.mkdir()
            with tarfile.open(args.archive) as archive:
                archive.extractall(dest, filter="data")
            (source,) = dest.iterdir()
            if getattr(args, "instrument", None):
                (source / "src/tpm_alloc_observer.rs").write_bytes(args.instrument.read_bytes())
                lib = source / "src/lib.rs"
                lib.write_bytes(lib.read_bytes() + b"\nmod tpm_alloc_observer;\n")
            if index == 2:
                for p in source.rglob("*"):
                    if p.is_file():
                        os.utime(p, (epoch + 86400, epoch + 86400))
            env["CARGO_TARGET_DIR"] = str(dest / "target")
            if getattr(args, "sbom_script", None):
                env["TPM_SBOM_AUDIT_DIR"] = str(dest / "sbom-audit")
            flags = [
                "-Clinker=" + str(args.linker),
                "-Clink-arg=/Brepro",
                "-Clink-arg=/INCREMENTAL:NO",
            ]
            for physical, logical in (
                (source, "/qualification/source"),
                (dest / "target", "/qualification/target"),
                (args.cache, "/qualification/cargo"),
            ):
                for spelling in (str(physical), physical.as_posix()):
                    flags += ["--remap-path-prefix", spelling + "=" + logical]
            env["CARGO_ENCODED_RUSTFLAGS"] = "\x1f".join(flags)
            report.setdefault("buildInputs", []).append(
                dict(name=name, flags=flags, lockSha256=digest(source / "Cargo.lock"))
            )
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
                env,
            )
            wheels = list((dest / "wheels").glob("*.whl"))
            if len(wheels) != 1:
                raise ValueError("expected exactly one wheel")
            artifact = audit_wheel(wheels[0])
            artifact["name"] = name
            natives = [h for n, h in artifact["members"].items() if n.endswith(".pyd")]
            if len(natives) != 1:
                raise ValueError("expected one native extension")
            artifact["nativeSha256"] = natives[0]
            report["artifacts"].append(artifact)
            save()
        report["nativeEqual"] = len({a["nativeSha256"] for a in report["artifacts"]}) == 1
        report["wheelEqual"] = len({a["sha256"] for a in report["artifacts"]}) == 1
        report["status"] = "NATIVE_MATCHED" if report["nativeEqual"] else "NATIVE_DIFFERENT"
        if getattr(args, "sbom_script", None):
            report["status"] = "WHEEL_MATCHED" if report["wheelEqual"] else "WHEEL_DIFFERENT"
    except Exception as error:
        report["failure"] = repr(error)
        raise
    finally:
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "output", "cache", "maturin", "python", "linker", "rustbin"):
        parser.add_argument("--" + name, type=lambda v: Path(v).resolve(), required=True)
    parser.add_argument("--sbom-script", type=lambda v: Path(v).resolve())
    parser.add_argument("--instrument", type=lambda v: Path(v).resolve())
    result = run(parser.parse_args())
    raise SystemExit(0 if result["status"] in ("NATIVE_MATCHED", "WHEEL_MATCHED") else 2)
