"""Build an isolated Windows diagnostic extension; never install into the service."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path.cwd()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=Path(".pytest_cache/native-owner-p0"))
options = parser.parse_args()
out = options.output.resolve()
out.mkdir(exist_ok=True)
vs = Path("C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools")
command = 'cmd.exe /d /s /c ""' + str(vs / "Common7/Tools/VsDevCmd.bat")
command += '" -no_logo -arch=x64 && set"'
result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=True)
env = os.environ.copy()
for line in result.stdout.splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        if key:
            env[key] = value
compiler = vs / "VC/Tools/MSVC/14.44.35207/bin/Hostx64/x64/cl.exe"
args = [
    str(compiler),
    "/nologo",
    "/LD",
    "/O2",
    "/W3",
    "/I" + str(Path(sys.base_prefix) / "include"),
    str(root / "scripts/experiments/owner_observer.c"),
    "/link",
    "/LIBPATH:" + str(Path(sys.base_prefix) / "libs"),
    "/OUT:" + str(out / "owner_observer.pyd"),
]
result = subprocess.run(
    args, cwd=out, env=env, capture_output=True, text=True, errors="replace", timeout=120
)
(out / "build.json").write_text(
    json.dumps(
        dict(argv=args, exitCode=result.returncode, stdout=result.stdout, stderr=result.stderr),
        indent=2,
    ),
    encoding="utf8",
)
print("Native compile exit:", result.returncode, "(details in build.json)")
result.check_returncode()
