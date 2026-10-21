"""Bound byte reads without weakening the immutable artifact checks."""
from hashlib import sha256
from pathlib import Path

import pytest

from trade_plan_monitor.backtest import loop_input_store as module
from trade_plan_monitor.backtest.loop_input_store import LoopInputStore


def digest(payload):
    return sha256(b"bounded-read-test\0" + payload).hexdigest()


def test_read_requests_small_chunks_and_accepts_short_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_MAX_OBJECT_BYTES", 262144)
    path = tmp_path / "artifact.bin"
    payload = b"evidence" * 20000
    path.write_bytes(payload)
    original_open = Path.open
    requests = []

    class ShortReader:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.file.__exit__(*args)

        def read(self, size):
            requests.append(size)
            assert 0 < size <= 65536
            return self.file.read(min(size, 19001))

    def observed_open(target, *args, **kwargs):
        file = original_open(target, *args, **kwargs)
        return ShortReader(file) if target == path else file

    monkeypatch.setattr(Path, "open", observed_open)
    store = LoopInputStore(tmp_path / "result.sqlite3")
    assert store._read(path, "bounded-read-test", digest(payload)) == payload
    assert len(requests) > 2


@pytest.mark.parametrize("size", [0, 1, 63, 64, 65])
def test_exact_byte_boundary_is_preserved(tmp_path, monkeypatch, size):
    monkeypatch.setattr(module, "_MAX_OBJECT_BYTES", 64)
    path = tmp_path / "artifact.bin"
    payload = b"x" * size
    path.write_bytes(payload)
    store = LoopInputStore(tmp_path / "result.sqlite3")
    if size <= 64:
        assert store._read(path, "bounded-read-test", digest(payload)) == payload
    else:
        with pytest.raises(RuntimeError, match="exceeds existing evidence bounds"):
            store._read(path, "bounded-read-test", digest(payload))


def test_equal_size_and_timestamp_tampering_is_rechecked(tmp_path):
    import os

    path = tmp_path / "artifact.bin"
    payload = b"original evidence"
    path.write_bytes(payload)
    before = path.stat()
    store = LoopInputStore(tmp_path / "result.sqlite3")
    assert store._read(path, "bounded-read-test", digest(payload)) == payload
    path.write_bytes(b"X" + payload[1:])
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(RuntimeError, match="content hash is invalid"):
        store._read(path, "bounded-read-test", digest(payload))
    path.unlink()
    with pytest.raises(RuntimeError, match="object is missing"):
        store._read(path, "bounded-read-test", digest(payload))


@pytest.mark.parametrize("replacement", [b"short", b"x" * 65])
def test_replacement_after_stat_does_not_bypass_hash_or_limit(tmp_path, monkeypatch, replacement):
    monkeypatch.setattr(module, "_MAX_OBJECT_BYTES", 64)
    path = tmp_path / "artifact.bin"
    payload = b"original evidence"
    path.write_bytes(payload)
    original_open = Path.open

    def replaced_open(target, *args, **kwargs):
        if target == path:
            with original_open(path, "wb") as file:
                file.write(replacement)
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", replaced_open)
    with pytest.raises(RuntimeError, match="content hash is invalid"):
        LoopInputStore(tmp_path / "result.sqlite3")._read(
            path, "bounded-read-test", digest(payload),
        )


@pytest.mark.parametrize("kind", ["is_symlink", "is_junction"])
def test_link_evidence_is_rejected_before_open(tmp_path, monkeypatch, kind):
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"evidence")
    original = getattr(Path, kind)
    monkeypatch.setattr(Path, kind, lambda target: target == path or original(target))
    with pytest.raises(RuntimeError, match="cannot be a link"):
        LoopInputStore(tmp_path / "result.sqlite3")._read(
            path, "bounded-read-test", digest(b"evidence"),
        )
