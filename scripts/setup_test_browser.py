"""Install the pinned, isolated Chrome for Testing; never modify system Chrome."""

import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    pin = json.loads((root / "web/test-browser.json").read_text(encoding="utf-8"))
    if pin["chromiumRevision"] < pin["requiredFixRevision"]:
        raise ValueError("Pinned Chrome predates the required stream-completion fix")
    machine = platform.machine().lower()
    architectures = {"arm64": "arm64", "aarch64": "arm64", "amd64": "x64", "x86_64": "x64"}
    architecture = architectures.get(machine, machine)
    key = f"{sys.platform}-{architecture}"
    if key not in pin["platforms"]:
        raise SystemExit(f"No pinned Chrome for Testing package for {key}")
    package = pin["platforms"][key]
    cache = root / "web/.test-browsers" / pin["version"]
    executable = cache / package["executable"]
    ready = cache / f"{package['archive']}.ready"
    if executable.is_file() and ready.is_file():
        print(f"Pinned Chrome {pin['version']} is ready: {executable}")
        return
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"chrome-{package['archive']}.zip"
    if not archive.is_file():
        url = (
            "https://storage.googleapis.com/chrome-for-testing-public/"
            f"{pin['version']}/{package['archive']}/chrome-{package['archive']}.zip"
        )
        partial = archive.with_suffix(".zip.part")
        print(f"Downloading official Chrome for Testing {pin['version']} ({package['archive']})")
        with urlopen(url, timeout=60) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
            expected = response.headers.get("Content-Length")
            if expected is not None and output.tell() != int(expected):
                raise RuntimeError("Incomplete pinned browser download; rerun setup")
        partial.replace(archive)
    with ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            if not (cache / entry.filename).resolve().is_relative_to(cache.resolve()):
                raise ValueError("Browser archive entry escapes its cache directory")
        if sys.platform == "darwin":
            # Preserve macOS framework symlinks and executable permissions.
            subprocess.run(["ditto", "-x", "-k", str(archive), str(cache)], check=True)
        else:
            bundle.extractall(cache)
            if sys.platform != "win32":
                for entry in bundle.infolist():
                    if (entry.external_attr >> 16) & 0o111:
                        (cache / entry.filename).chmod(0o755)
    if not executable.is_file():
        raise RuntimeError("Pinned browser archive did not contain its expected executable")
    ready.write_text(pin["version"], encoding="utf-8")
    print(f"Pinned Chrome {pin['version']} is ready: {executable}")


if __name__ == "__main__":
    main()
