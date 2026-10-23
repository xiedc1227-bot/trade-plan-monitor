"""Disposable owner coverage canary. Does not claim backing-memory bounds."""

import gc
import json
import os
import sys
from pathlib import Path
from threading import Thread

sys.path.insert(
    0, str(Path(os.environ.get("TPM_OWNER_IMPORT", ".pytest_cache/native-owner-p0")).resolve())
)
import owner_observer as observer

mode = sys.argv[1]
if mode == "late":
    import sqlite3

    try:
        observer.install(str(Path(sys.base_prefix) / "DLLs/sqlite3.dll"))
    except RuntimeError as error:
        assert "21" in str(error)
        print(json.dumps({"lateRejected": True, "error": str(error)}))
    else:
        raise AssertionError("late setup accepted")
    sys.exit()

if mode != "baseline":
    observer.install(str(Path(sys.base_prefix) / "DLLs/sqlite3.dll"))
# Import order is part of the early-SQLite-hook experiment.
sqlite3 = __import__("sqlite3")
ctypes = __import__("ctypes")

kernel = ctypes.WinDLL("kernel32")
kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel.GetModuleHandleW.restype = ctypes.c_void_p
kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
path_buffer = ctypes.create_unicode_buffer(32768)
assert kernel.GetModuleFileNameW(kernel.GetModuleHandleW("sqlite3.dll"), path_buffer, 32768)
assert Path(path_buffer.value).resolve() == (Path(sys.base_prefix) / "DLLs/sqlite3.dll").resolve()

report = dict(mode=mode, stages=[], qualification="LOGICAL_ONLY", p1="NO_GO")


def snap(name):
    state = observer.snapshot()
    assert sum(state["domains"]) == sum(state["live"])
    report["stages"].append(dict(name=name, **state))


if mode == "overflow":
    values = [bytearray(64) for _ in range(300000)]
    assert observer.snapshot()["lost"] > 0
    print(json.dumps(dict(overflowRejected=True, state=observer.snapshot())))
    sys.exit()

observer.owner(1)
pointer = observer.raw_alloc(8 * 1024 * 1024)
observer.owner(0)
before = observer.snapshot()["live"][1]


def free_elsewhere():
    observer.owner(2)
    observer.raw_free(pointer)


thread = Thread(target=free_elsewhere)
thread.start()
thread.join(10)
assert not thread.is_alive()
after = observer.snapshot()["live"][1]
report["crossThreadReleased"] = before - after
if mode != "baseline":
    assert before - after == 8 * 1024 * 1024
snap("cross_thread")
observer.owner(3)
con = sqlite3.connect(":memory:")
con.execute("create table sample(value blob)")
con.execute("insert into sample values(zeroblob(?))", (8 * 1024 * 1024,))
row = con.execute("select value from sample").fetchone()
assert len(row[0]) == 8 * 1024 * 1024
snap("row_and_connection")
con.close()
del con
gc.collect()
snap("row_without_connection")
del row
gc.collect()
snap("row_released")
observer.owner(4)
pydantic = __import__("pydantic")
TypeAdapter, ValidationError = pydantic.TypeAdapter, pydantic.ValidationError

adapter = TypeAdapter(list[int])
try:
    adapter.validate_python(["invalid"] * 20000, strict=True)
except ValidationError as error:
    assert error.error_count() == 20000
else:
    raise AssertionError("dense errors accepted")
gc.collect()
snap("dense_errors_released")
observer.owner(0)
report["remainingGaps"] = [
    "preinstall frees",
    "nested domain duplication",
    "pool attribution",
    "realloc transient overlap",
    "backing heap bounds",
]
print(json.dumps(report))
