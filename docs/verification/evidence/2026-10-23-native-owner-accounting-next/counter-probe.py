"""Diagnostic recipe: in-memory database only; no allocator hooks or reconfiguration."""
import _sqlite3
import ctypes
import gc
import hashlib
import json
import sqlite3
import sys
import sysconfig
import tracemalloc
from pathlib import Path

kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel.GetModuleHandleW.restype = ctypes.c_void_p
kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
kernel.GetModuleFileNameW.restype = ctypes.c_uint32
handle = kernel.GetModuleHandleW("sqlite3.dll")
assert handle
buf = ctypes.create_unicode_buffer(32768)
assert kernel.GetModuleFileNameW(handle, buf, len(buf))
dllpath = Path(buf.value)
dll = ctypes.CDLL(str(dllpath))
dll.sqlite3_sourceid.restype = ctypes.c_char_p
dll.sqlite3_memory_used.restype = ctypes.c_longlong
dll.sqlite3_memory_highwater.argtypes = [ctypes.c_int]
dll.sqlite3_memory_highwater.restype = ctypes.c_longlong
probe = sqlite3.connect(":memory:")
sourceid = probe.execute("select sqlite_source_id()").fetchone()[0]
options = [r[0] for r in probe.execute("pragma compile_options")]
assert sourceid == dll.sqlite3_sourceid().decode()
probe.close()
del probe
gc.collect()
result = dict(
    python=sys.version, gilDisabled=sysconfig.get_config_var("Py_GIL_DISABLED"),
    sqliteVersion=sqlite3.sqlite_version, sqliteSourceId=sourceid, sqliteOptions=options,
    sqliteDll=str(dllpath), sqliteDllSha256=hashlib.sha256(dllpath.read_bytes()).hexdigest(),
    driverPath=_sqlite3.__file__,
    driverSha256=hashlib.sha256(Path(_sqlite3.__file__).read_bytes()).hexdigest(),
    rounds=[], qualification="READ_ONLY_COUNTER_DIAGNOSTIC_NOT_ALLOCATOR_COVERAGE",
)
for turn in range(3):
    tracemalloc.start()
    states = []

    def snap(phase):
        live, peak = tracemalloc.get_traced_memory()
        states.append(dict(phase=phase, pythonTracedLive=live, pythonTracedPeak=peak,
                           sqliteLive=dll.sqlite3_memory_used(),
                           sqlitePeak=dll.sqlite3_memory_highwater(0)))

    snap("baseline")
    python_only = bytearray(8 * 1024 * 1024)
    snap("python_8MiB")
    del python_only
    gc.collect()
    snap("python_released")
    con = sqlite3.connect(":memory:")
    con.execute("create table probe(value blob)")
    con.execute("insert into probe values(zeroblob(?))", (8 * 1024 * 1024,))
    snap("sqlite_table_8MiB")
    cursor = con.execute("select value from probe")
    row = cursor.fetchone()
    assert len(row[0]) == 8 * 1024 * 1024
    snap("python_result_retained")
    cursor.close()
    con.close()
    del cursor, con
    gc.collect()
    snap("connection_closed_result_retained")
    assert len(row[0]) == 8 * 1024 * 1024
    del row
    gc.collect()
    snap("result_released")
    tracemalloc.stop()
    result["rounds"].append(states)
print(json.dumps(result, indent=2))
