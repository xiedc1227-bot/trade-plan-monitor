"""Minimal Windows Credential Manager adapter for live-provider secrets.

The implementation follows the Win32 ``CredReadW``/``CredWriteW`` contract and
always releases the native credential buffer with ``CredFree``.

Sources:
https://learn.microsoft.com/windows/win32/api/wincred/nf-wincred-credreadw
https://learn.microsoft.com/windows/win32/api/wincred/nf-wincred-credwritew
"""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from ctypes import wintypes
from typing import Final

_CRED_TYPE_GENERIC: Final = 1
_CRED_PERSIST_LOCAL_MACHINE: Final = 2
_MAX_TARGET_LENGTH: Final = 256
_MAX_SECRET_BYTES: Final = 8_192


class WindowsCredentialError(RuntimeError):
    """Stable failure that never contains credential material or native messages."""


class _CREDENTIALW(ctypes.Structure):
    _fields_ = (
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    )


def _validate_target(target: str) -> str:
    if (
        type(target) is not str
        or not target
        or len(target) > _MAX_TARGET_LENGTH
        or target != target.strip()
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in target)
    ):
        raise ValueError("credential target is invalid")
    return target


def _zero(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


def read_windows_generic_credential(
    target: str,
    *,
    native_reader: Callable[[str], bytearray] | None = None,
) -> bytearray:
    """Return one mutable copy and erase the native-reader result immediately."""

    validated_target = _validate_target(target)
    reader = _read_native_credential if native_reader is None else native_reader
    native_value = reader(validated_target)
    if type(native_value) is not bytearray:
        raise TypeError("native credential reader must return a bytearray")
    try:
        value = bytearray(native_value)
    finally:
        _zero(native_value)
    if not value:
        raise WindowsCredentialError("Windows credential is empty")
    if len(value) > _MAX_SECRET_BYTES:
        _zero(value)
        raise WindowsCredentialError("Windows credential is too large")
    return value


def write_windows_generic_credential(
    target: str,
    secret: bytearray,
    *,
    native_writer: Callable[[str, bytearray], None] | None = None,
) -> None:
    """Store one generic credential without mutating the caller-owned buffer."""

    validated_target = _validate_target(target)
    if type(secret) is not bytearray:
        raise TypeError("secret must be a bytearray")
    if not secret or len(secret) > _MAX_SECRET_BYTES:
        raise WindowsCredentialError("Windows credential size is invalid")
    writer = _write_native_credential if native_writer is None else native_writer
    temporary = bytearray(secret)
    try:
        writer(validated_target, temporary)
    finally:
        _zero(temporary)


def _advapi32() -> object:
    if os.name != "nt":
        raise WindowsCredentialError("Windows Credential Manager is unavailable")
    return ctypes.WinDLL("Advapi32.dll", use_last_error=True)


def _read_native_credential(target: str) -> bytearray:
    library = _advapi32()
    cred_read = library.CredReadW
    cred_read.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
    )
    cred_read.restype = wintypes.BOOL
    cred_free = library.CredFree
    cred_free.argtypes = (ctypes.c_void_p,)
    cred_free.restype = None

    credential = ctypes.POINTER(_CREDENTIALW)()
    if not cred_read(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(credential)):
        raise WindowsCredentialError("Windows credential is unavailable")
    try:
        size = int(credential.contents.CredentialBlobSize)
        if size <= 0 or size > _MAX_SECRET_BYTES:
            raise WindowsCredentialError("Windows credential size is invalid")
        return bytearray(ctypes.string_at(credential.contents.CredentialBlob, size))
    finally:
        cred_free(credential)


def _write_native_credential(target: str, secret: bytearray) -> None:
    library = _advapi32()
    cred_write = library.CredWriteW
    cred_write.argtypes = (ctypes.POINTER(_CREDENTIALW), wintypes.DWORD)
    cred_write.restype = wintypes.BOOL

    native = (ctypes.c_ubyte * len(secret)).from_buffer_copy(secret)
    credential = _CREDENTIALW(
        Flags=0,
        Type=_CRED_TYPE_GENERIC,
        TargetName=target,
        Comment="trade-plan-monitor live Tushare token",
        LastWritten=wintypes.FILETIME(),
        CredentialBlobSize=len(secret),
        CredentialBlob=ctypes.cast(native, ctypes.POINTER(ctypes.c_ubyte)),
        Persist=_CRED_PERSIST_LOCAL_MACHINE,
        AttributeCount=0,
        Attributes=None,
        TargetAlias=None,
        UserName="TUSHARE_TOKEN",
    )
    try:
        if not cred_write(ctypes.byref(credential), 0):
            raise WindowsCredentialError("Windows credential could not be stored")
    finally:
        ctypes.memset(ctypes.addressof(native), 0, len(native))


__all__ = [
    "WindowsCredentialError",
    "read_windows_generic_credential",
    "write_windows_generic_credential",
]
