"""Race-safe owner-only storage for the local backtest cursor key."""

from __future__ import annotations

import ctypes
import os
import stat
from ctypes import wintypes
from pathlib import Path
from time import sleep

_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x00000001
_DACL_SECURITY_INFORMATION = 0x00000004
_SE_DACL_PROTECTED = 0x1000
_SET_ACCESS = 2
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_USER = 1
_NO_INHERITANCE = 0
_ACL_SIZE_INFORMATION_CLASS = 2
_ACCESS_ALLOWED_ACE_TYPE = 0
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_SECURITY_DESCRIPTOR_MIN_LENGTH = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 20
_SECURITY_DESCRIPTOR_REVISION = 1
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_READ_CONTROL = 0x00020000
_WRITE_DAC = 0x00040000
_CREATE_NEW = 1
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_TYPE_DISK = 1
_FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
_ERROR_FILE_EXISTS = 80
_ERROR_ALREADY_EXISTS = 183
_ERROR_SHARING_VIOLATION = 32
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_WINDOWS_SHARING_RETRY_ATTEMPTS = 50
_WINDOWS_SHARING_RETRY_SECONDS = 0.01

# Windows analogue of POSIX 0600: generic file read and write rights, with no
# delete, ownership-transfer, or execute access delegated by the DACL.
_OWNER_FILE_READ_WRITE = 0x0012019F


class _TrusteeW(ctypes.Structure):
    _fields_ = (
        ("pMultipleTrustee", ctypes.c_void_p),
        ("MultipleTrusteeOperation", wintypes.DWORD),
        ("TrusteeForm", wintypes.DWORD),
        ("TrusteeType", wintypes.DWORD),
        ("ptstrName", wintypes.LPWSTR),
    )


class _ExplicitAccessW(ctypes.Structure):
    _fields_ = (
        ("grfAccessPermissions", wintypes.DWORD),
        ("grfAccessMode", wintypes.DWORD),
        ("grfInheritance", wintypes.DWORD),
        ("Trustee", _TrusteeW),
    )


class _AclSizeInformation(ctypes.Structure):
    _fields_ = (
        ("AceCount", wintypes.DWORD),
        ("AclBytesInUse", wintypes.DWORD),
        ("AclBytesFree", wintypes.DWORD),
    )


class _AceHeader(ctypes.Structure):
    _fields_ = (
        ("AceType", wintypes.BYTE),
        ("AceFlags", wintypes.BYTE),
        ("AceSize", wintypes.WORD),
    )


class _AccessAllowedAce(ctypes.Structure):
    _fields_ = (
        ("Header", _AceHeader),
        ("Mask", wintypes.DWORD),
        ("SidStart", wintypes.DWORD),
    )


class _SecurityAttributes(ctypes.Structure):
    _fields_ = (
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    )


class _TokenUser(ctypes.Structure):
    _fields_ = (("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD))


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = (("FileAttributes", wintypes.DWORD), ("ReparseTag", wintypes.DWORD))


def create_cursor_key_file(path: Path, key: bytes) -> None:
    """Create ``path`` owner-only before writing exactly one 256-bit key."""

    normalized_key = _validate_key(key)
    if os.name == "nt":
        _create_windows_key(path, normalized_key)
        return
    _create_posix_key(path, normalized_key)


def read_cursor_key_file(path: Path) -> bytes:
    """Validate and read one key through the same non-replaceable file handle."""

    if os.name == "nt":
        return _read_windows_key_with_retry(path)
    return _read_posix_key(path)


def windows_cursor_key_acl_is_owner_only(path: Path) -> bool:
    """Return whether ``path`` has one protected current-owner read/write ACE."""

    if os.name != "nt":
        raise OSError("Windows file security APIs are unavailable")
    advapi32, kernel32 = _windows_libraries()
    handle = _open_windows_file(
        path,
        desired_access=_GENERIC_READ | _READ_CONTROL,
        creation_disposition=_OPEN_EXISTING,
    )
    try:
        _require_regular_windows_file(handle, kernel32)
        return _windows_handle_acl_is_owner_only(handle, advapi32, kernel32)
    finally:
        _close_windows_handle(handle, kernel32)


def _create_posix_key(path: Path, key: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        _require_owned_posix_regular_file(metadata)
        os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise PermissionError("cursor key file is not an owner-only regular file")
        _write_descriptor(descriptor, key)
        os.fsync(descriptor)
    except BaseException:
        os.close(descriptor)
        try:
            path.unlink()
        except OSError:
            pass
        raise
    else:
        os.close(descriptor)


def _read_posix_key(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        _require_owned_posix_regular_file(metadata)
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise PermissionError("cursor key file is not an owner-only regular file")
        key = os.read(descriptor, 33)
        if metadata.st_size != 32 or len(key) != 32:
            raise ValueError("cursor key must contain exactly 32 bytes")
        return key
    finally:
        os.close(descriptor)


def _require_owned_posix_regular_file(metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise PermissionError("cursor key file is not an owner-only regular file")
    if metadata.st_uid != os.geteuid():
        raise PermissionError("cursor key file is not owned by the current user")


def _create_windows_key(path: Path, key: bytes) -> None:
    advapi32, kernel32 = _windows_libraries()
    sid_buffer, owner_sid = _current_windows_user_sid(advapi32, kernel32)
    security_descriptor = ctypes.create_string_buffer(_SECURITY_DESCRIPTOR_MIN_LENGTH)
    acl = _owner_only_acl(owner_sid, advapi32)
    try:
        if not advapi32.InitializeSecurityDescriptor(
            security_descriptor, _SECURITY_DESCRIPTOR_REVISION
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not advapi32.SetSecurityDescriptorOwner(security_descriptor, owner_sid, False):
            raise ctypes.WinError(ctypes.get_last_error())
        if not advapi32.SetSecurityDescriptorDacl(security_descriptor, True, acl, False):
            raise ctypes.WinError(ctypes.get_last_error())
        if not advapi32.SetSecurityDescriptorControl(
            security_descriptor,
            _SE_DACL_PROTECTED,
            _SE_DACL_PROTECTED,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        attributes = _SecurityAttributes(
            nLength=ctypes.sizeof(_SecurityAttributes),
            lpSecurityDescriptor=ctypes.cast(security_descriptor, ctypes.c_void_p),
            bInheritHandle=False,
        )
        handle = _open_windows_file(
            path,
            desired_access=_GENERIC_READ | _GENERIC_WRITE | _READ_CONTROL | _WRITE_DAC,
            creation_disposition=_CREATE_NEW,
            security_attributes=attributes,
        )
        try:
            _require_regular_windows_file(handle, kernel32)
            if not _windows_handle_acl_is_owner_only(handle, advapi32, kernel32):
                raise PermissionError("cursor key Windows ACL is not owner-only")
            _write_windows_key(handle, key, kernel32)
        except BaseException:
            _close_windows_handle(handle, kernel32, raise_on_error=False)
            try:
                path.unlink()
            except OSError:
                pass
            raise
        else:
            _close_windows_handle(handle, kernel32)
    finally:
        del sid_buffer
        kernel32.LocalFree(acl)


def _read_windows_key(path: Path) -> bytes:
    advapi32, kernel32 = _windows_libraries()
    handle = _open_windows_file(
        path,
        desired_access=_GENERIC_READ | _READ_CONTROL,
        creation_disposition=_OPEN_EXISTING,
    )
    try:
        _require_regular_windows_file(handle, kernel32)
        if not _windows_handle_acl_is_owner_only(handle, advapi32, kernel32):
            raise PermissionError("cursor key Windows ACL is not owner-only")
        return _read_windows_key_bytes(handle, kernel32)
    finally:
        _close_windows_handle(handle, kernel32)


def _read_windows_key_with_retry(path: Path) -> bytes:
    for attempt in range(_WINDOWS_SHARING_RETRY_ATTEMPTS):
        try:
            return _read_windows_key(path)
        except PermissionError as error:
            if (
                getattr(error, "winerror", None) != _ERROR_SHARING_VIOLATION
                or attempt == _WINDOWS_SHARING_RETRY_ATTEMPTS - 1
            ):
                raise
            sleep(_WINDOWS_SHARING_RETRY_SECONDS)
    raise AssertionError("unreachable Windows cursor-key retry state")


def _windows_handle_acl_is_owner_only(
    handle: int,
    advapi32: ctypes.WinDLL,
    kernel32: ctypes.WinDLL,
) -> bool:
    owner_sid = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    security_descriptor = ctypes.c_void_p()
    error = advapi32.GetSecurityInfo(
        handle,
        _SE_FILE_OBJECT,
        _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner_sid),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(security_descriptor),
    )
    if error:
        raise ctypes.WinError(error)
    sid_buffer, current_sid = _current_windows_user_sid(advapi32, kernel32)
    try:
        if not owner_sid.value or not dacl.value:
            return False
        if not advapi32.EqualSid(owner_sid, current_sid):
            return False
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(
            security_descriptor,
            ctypes.byref(control),
            ctypes.byref(revision),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not control.value & _SE_DACL_PROTECTED:
            return False
        acl_information = _AclSizeInformation()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(acl_information),
            ctypes.sizeof(acl_information),
            _ACL_SIZE_INFORMATION_CLASS,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if acl_information.AceCount != 1:
            return False
        ace_pointer = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, 0, ctypes.byref(ace_pointer)):
            raise ctypes.WinError(ctypes.get_last_error())
        ace = ctypes.cast(ace_pointer, ctypes.POINTER(_AccessAllowedAce)).contents
        if (
            ace.Header.AceType != _ACCESS_ALLOWED_ACE_TYPE
            or ace.Header.AceFlags != _NO_INHERITANCE
            or ace.Mask != _OWNER_FILE_READ_WRITE
        ):
            return False
        ace_sid = ctypes.c_void_p(ace_pointer.value + _AccessAllowedAce.SidStart.offset)
        return bool(advapi32.EqualSid(owner_sid, ace_sid))
    finally:
        del sid_buffer
        kernel32.LocalFree(security_descriptor)


def _owner_only_acl(owner_sid: ctypes.c_void_p, advapi32: ctypes.WinDLL) -> ctypes.c_void_p:
    access = _ExplicitAccessW(
        grfAccessPermissions=_OWNER_FILE_READ_WRITE,
        grfAccessMode=_SET_ACCESS,
        grfInheritance=_NO_INHERITANCE,
        Trustee=_TrusteeW(
            pMultipleTrustee=None,
            MultipleTrusteeOperation=0,
            TrusteeForm=_TRUSTEE_IS_SID,
            TrusteeType=_TRUSTEE_IS_USER,
            ptstrName=ctypes.cast(owner_sid, wintypes.LPWSTR),
        ),
    )
    acl = ctypes.c_void_p()
    error = advapi32.SetEntriesInAclW(1, ctypes.byref(access), None, ctypes.byref(acl))
    if error:
        raise ctypes.WinError(error)
    return acl


def _current_windows_user_sid(
    advapi32: ctypes.WinDLL,
    kernel32: ctypes.WinDLL,
) -> tuple[ctypes.Array[ctypes.c_char], ctypes.c_void_p]:
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(required))
        if required.value == 0:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(
            token,
            _TOKEN_USER,
            buffer,
            required.value,
            ctypes.byref(required),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents.Sid
        if not sid or not advapi32.IsValidSid(sid):
            raise PermissionError("current Windows user SID is invalid")
        return buffer, ctypes.c_void_p(sid)
    finally:
        _close_windows_handle(token.value, kernel32)


def _open_windows_file(
    path: Path,
    *,
    desired_access: int,
    creation_disposition: int,
    security_attributes: _SecurityAttributes | None = None,
) -> int:
    _, kernel32 = _windows_libraries()
    attributes_pointer = None if security_attributes is None else ctypes.byref(security_attributes)
    handle = kernel32.CreateFileW(
        str(path),
        desired_access,
        0,
        attributes_pointer,
        creation_disposition,
        _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    handle_value = ctypes.cast(handle, ctypes.c_void_p).value
    if handle_value == _INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        if creation_disposition == _CREATE_NEW and error in {
            _ERROR_FILE_EXISTS,
            _ERROR_ALREADY_EXISTS,
        }:
            raise FileExistsError(error, os.strerror(error), str(path))
        raise ctypes.WinError(error)
    if handle_value is None:
        raise OSError("CreateFileW returned a null cursor-key handle")
    return handle_value


def _require_regular_windows_file(handle: int, kernel32: ctypes.WinDLL) -> None:
    if kernel32.GetFileType(handle) != _FILE_TYPE_DISK:
        raise ValueError("cursor key path must be a regular non-reparse file")
    information = _FileAttributeTagInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        _FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    if information.FileAttributes & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError("cursor key path must be a regular non-reparse file")


def _write_windows_key(handle: int, key: bytes, kernel32: ctypes.WinDLL) -> None:
    buffer = ctypes.create_string_buffer(key)
    written = wintypes.DWORD()
    if not kernel32.WriteFile(
        handle,
        buffer,
        len(key),
        ctypes.byref(written),
        None,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    if written.value != len(key):
        raise OSError("cursor key write did not complete")
    if not kernel32.FlushFileBuffers(handle):
        raise ctypes.WinError(ctypes.get_last_error())


def _read_windows_key_bytes(handle: int, kernel32: ctypes.WinDLL) -> bytes:
    size = ctypes.c_longlong()
    if not kernel32.GetFileSizeEx(handle, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(33)
    read = wintypes.DWORD()
    if not kernel32.ReadFile(handle, buffer, 33, ctypes.byref(read), None):
        raise ctypes.WinError(ctypes.get_last_error())
    if size.value != 32 or read.value != 32:
        raise ValueError("cursor key must contain exactly 32 bytes")
    return bytes(buffer.raw[:32])


def _write_descriptor(descriptor: int, key: bytes) -> None:
    remaining = memoryview(key)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("cursor key write made no progress")
        remaining = remaining[written:]


def _close_windows_handle(
    handle: int,
    kernel32: ctypes.WinDLL,
    *,
    raise_on_error: bool = True,
) -> None:
    if not kernel32.CloseHandle(handle) and raise_on_error:
        raise ctypes.WinError(ctypes.get_last_error())


def _validate_key(key: bytes) -> bytes:
    if not isinstance(key, bytes):
        raise TypeError("cursor key must be bytes")
    if len(key) != 32:
        raise ValueError("cursor key must contain exactly 32 bytes")
    return key


def _windows_libraries() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    advapi32.OpenProcessToken.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    )
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.IsValidSid.argtypes = (ctypes.c_void_p,)
    advapi32.IsValidSid.restype = wintypes.BOOL
    advapi32.InitializeSecurityDescriptor.argtypes = (ctypes.c_void_p, wintypes.DWORD)
    advapi32.InitializeSecurityDescriptor.restype = wintypes.BOOL
    advapi32.SetSecurityDescriptorOwner.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
    )
    advapi32.SetSecurityDescriptorOwner.restype = wintypes.BOOL
    advapi32.SetSecurityDescriptorDacl.argtypes = (
        ctypes.c_void_p,
        wintypes.BOOL,
        ctypes.c_void_p,
        wintypes.BOOL,
    )
    advapi32.SetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi32.SetSecurityDescriptorControl.argtypes = (
        ctypes.c_void_p,
        wintypes.WORD,
        wintypes.WORD,
    )
    advapi32.SetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.SetEntriesInAclW.argtypes = (
        wintypes.ULONG,
        ctypes.POINTER(_ExplicitAccessW),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.SetEntriesInAclW.restype = wintypes.DWORD
    advapi32.GetSecurityInfo.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = (
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
    advapi32.EqualSid.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SecurityAttributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileType.argtypes = (wintypes.HANDLE,)
    kernel32.GetFileType.restype = wintypes.DWORD
    kernel32.GetFileInformationByHandleEx.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    )
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    )
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
    kernel32.FlushFileBuffers.restype = wintypes.BOOL
    kernel32.GetFileSizeEx.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong))
    kernel32.GetFileSizeEx.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    return advapi32, kernel32


__all__ = [
    "create_cursor_key_file",
    "read_cursor_key_file",
    "windows_cursor_key_acl_is_owner_only",
]
