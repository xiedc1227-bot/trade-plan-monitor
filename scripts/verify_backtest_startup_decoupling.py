"""MV11 real-server fixture; browser evidence is collected separately with CUA.

Run from the repository with --serve, --probe, or --stop. Only disposable roots
created by this script are accepted. Production composition and SPA are reused;
the Python profiler/audit hook observe calls and block non-loopback connections.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
import platform
import sys
import threading
import time
from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

REPOSITORY = Path(__file__).resolve().parents[1]
MARKER = ".mv11-disposable"


def json_default(value):
    if callable(getattr(value, "model_dump", None)):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported observation type: {type(value)}")


def timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()


def append(path: Path, payload: dict) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps({"at": timestamp(), **payload}, ensure_ascii=False, default=json_default)
            + "\n"
        )


def inventory(root: Path) -> list[dict]:
    return [
        {"path": str(path.relative_to(root)), "bytes": path.stat().st_size}
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


async def serve(root: Path, evidence: Path, port: int) -> None:
    import uvicorn

    sys.path.insert(0, str(REPOSITORY / "src"))
    # CWD redirects unchanged production backtest defaults into isolated storage.
    os.chdir(root)
    from trade_plan_monitor.web.app import create_production_app

    counts: Counter[str] = Counter()
    lock = threading.RLock()
    lifecycle_path = evidence / "lifecycle.jsonl"
    network_attempts: list[str] = []
    observed_modules = {
        "composition.py",
        "market_store.py",
        "results.py",
        "repository.py",
        "coordinator.py",
        "thread_lifecycle.py",
        "thread_ownership.py",
    }

    def profile(frame, event, _arg):
        if event != "call":
            return
        filename = frame.f_code.co_filename.replace("\\", "/")
        qualname = frame.f_code.co_qualname
        backtest = "/trade_plan_monitor/backtest/" in filename
        selected = backtest and (
            filename.rsplit("/", 1)[-1] in observed_modules
            and (
                frame.f_code.co_name
                in {
                    "__init__",
                    "factory",
                    "create_backtest_composition",
                    "start",
                    "_load_or_create_cursor_key",
                    "_read_cursor_key",
                    "submit",
                }
            )
        )
        monitor = filename.endswith("/web/monitor_composition.py") and qualname in {
            "MonitorWebComposition.start",
            "MonitorWebComposition.stop",
        }
        if selected or monitor:
            name = filename.split("/trade_plan_monitor/", 1)[-1] + ":" + qualname
            with lock:
                counts[name] += 1
                append(
                    lifecycle_path,
                    {"event": "call", "name": name, "thread": threading.current_thread().name},
                )

    def audit(event, args):
        if event == "socket.connect":
            address = args[1]
            host = address[0] if isinstance(address, tuple) else str(address)
            try:
                permitted = ipaddress.ip_address(host).is_loopback
            except ValueError:
                permitted = host == "localhost"
            if not permitted:
                with lock:
                    network_attempts.append("non-loopback connection rejected")
                raise RuntimeError("MV11 prohibits external connections")
        elif event in {"open", "sqlite3.connect"}:
            target = str(args[0]).replace("\\", "/")
            if "backtest-" in target and target.endswith((".key", ".sqlite3")):
                append(lifecycle_path, {"event": event, "path": target})

    sys.addaudithook(audit)
    sys.setprofile(profile)
    threading.setprofile(profile)
    append(
        lifecycle_path,
        {
            "event": "fixture_start",
            "pid": os.getpid(),
            "port": port,
            "root": str(root),
            "python": sys.version,
            "platform": platform.platform(),
            "uvicorn": uvicorn.__version__,
            "network_guard": "reject non-loopback socket.connect",
        },
    )

    with create_production_app(
        config_path=root / "config/app.yaml",
        database_path=root / "data/monitor.sqlite3",
        bind_host="127.0.0.1",
        bind_port=port,
    ) as app:
        assets = REPOSITORY / "src/trade_plan_monitor/web/dist"
        append(
            lifecycle_path,
            {
                "event": "assets",
                "files": [
                    {
                        "path": str(p.relative_to(assets)),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    }
                    for p in sorted(assets.rglob("*"))
                    if p.is_file()
                ],
            },
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                access_log=True,
                log_level="info",
            )
        )

        def snapshot(phase: str) -> dict:
            manager = getattr(app.state, "backtest_lifecycle", None)
            runtime = getattr(app.state, "runtime_lifecycle", None)
            with lock:
                value = {
                    "at": timestamp(),
                    "phase": phase,
                    "pid": os.getpid(),
                    "server_started": server.started,
                    "calls": dict(counts),
                    "threads": [t.name for t in threading.enumerate()],
                    "tasks": [t.get_name() for t in asyncio.all_tasks()],
                    "files": inventory(root),
                    "blocked_network": list(network_attempts),
                    "backtest": None if manager is None else asdict(manager.snapshot),
                    "runtime": None if runtime is None else runtime.health(),
                }
            temporary = evidence / "latest.tmp"
            temporary.write_text(
                json.dumps(value, indent=2, default=json_default), encoding="utf-8"
            )
            temporary.replace(evidence / "latest.json")
            return value

        async def observe() -> None:
            while not server.should_exit:
                if server.started:
                    snapshot("serving")
                if (root / "stop.request").exists():
                    append(
                        lifecycle_path,
                        {"event": "before_normal_shutdown", **snapshot("before_shutdown")},
                    )
                    server.should_exit = True
                    return
                await asyncio.sleep(0.5)

        observer = asyncio.create_task(observe(), name="mv11-observer")
        try:
            await server.serve()
        finally:
            observer.cancel()
            await asyncio.gather(observer, return_exceptions=True)
            append(lifecycle_path, {"event": "server_returned", **snapshot("after_shutdown")})
    sys.setprofile(None)
    threading.setprofile(None)
    append(lifecycle_path, {"event": "fixture_exit", "pid": os.getpid()})


def probe(evidence: Path, port: int, paths: list[str], label: str) -> None:
    opener = build_opener(ProxyHandler({}))
    for path in paths:
        if not path.startswith("/"):
            raise ValueError("probe requires a local absolute HTTP path")
        start = time.monotonic()
        request = Request(
            f"http://127.0.0.1:{port}{path}", headers={"X-Monitor-Contract-Version": "2"}
        )
        try:
            response = opener.open(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            headers = dict(response.headers.items())
            content_type = response.headers.get("Content-Type", "")
            payload = {
                "label": label,
                "path": path,
                "status": response.code,
                "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
                "headers": headers,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
            if "json" in content_type:
                payload["body"] = json.loads(body)
            else:
                payload["body_prefix"] = body[:1000].decode("utf-8", errors="replace")
            append(evidence / "http.jsonl", payload)
            print(
                json.dumps(
                    {"path": path, "status": response.code, "elapsed_ms": payload["elapsed_ms"]}
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--probe", nargs="+")
    parser.add_argument("--label", default="manual")
    parser.add_argument("--corrupt-key", action="store_true")
    args = parser.parse_args()
    root, evidence = args.root.resolve(), args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    if args.serve:
        if root.exists() and not (root / MARKER).is_file():
            raise ValueError("existing unmarked root is not disposable")
        root.mkdir(parents=True, exist_ok=True)
        (root / MARKER).touch()
        (root / "config").mkdir(exist_ok=True)
        (root / "config/app.yaml").write_text("{}\n", encoding="utf-8")
        (root / "stop.request").unlink(missing_ok=True)
        if args.corrupt_key:
            from trade_plan_monitor.backtest.cursor_key_security import create_cursor_key_file

            key_path = root / "data/backtest-cursor.key"
            key_path.parent.mkdir(exist_ok=True)
            if not key_path.exists():
                create_cursor_key_file(key_path, bytes(32))
            # Preserve the owner-only ACL and deliberately truncate test material.
            key_path.write_bytes(b"MV11-corrupt-key")
        asyncio.run(serve(root, evidence, args.port))
    elif args.stop:
        if not (root / MARKER).is_file():
            raise ValueError("stop requires marked disposable root")
        (root / "stop.request").touch()
    elif args.probe:
        probe(evidence, args.port, args.probe, args.label)
    else:
        parser.error("select --serve, --stop, or --probe")


if __name__ == "__main__":
    main()
