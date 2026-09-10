"""Shared installation-local signing-key loader for Web API cursors."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from secrets import token_bytes

from trade_plan_monitor.backtest.cursor_key_security import (
    create_cursor_key_file,
    read_cursor_key_file,
)

CursorKeyCreator = Callable[[Path, bytes], None]
CursorKeyReader = Callable[[Path], bytes]


def load_or_create_cursor_key(
    path: Path,
    *,
    create: CursorKeyCreator = create_cursor_key_file,
    read: CursorKeyReader = read_cursor_key_file,
) -> bytes:
    """Load one local 256-bit cursor key, creating it with owner-only mode."""

    if not isinstance(path, Path):
        raise TypeError("path must be a Path")
    absolute = path.absolute()
    absolute.parent.mkdir(parents=True, exist_ok=True)
    if absolute.exists() or absolute.is_symlink():
        return read(absolute)

    key = token_bytes(32)
    try:
        create(absolute, key)
    except FileExistsError:
        return read(absolute)
    return key


__all__ = ["load_or_create_cursor_key"]
