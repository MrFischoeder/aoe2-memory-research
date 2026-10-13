"""Lazy, read-only ctypes bindings to kernel32/shell32.

Only documented, user-mode APIs are bound, and only those needed to *observe* a process:

* ``CreateToolhelp32Snapshot`` / ``Process32FirstW`` / ``Process32NextW``
* ``OpenProcess`` (access mask validated against a read-only allowlist) / ``CloseHandle``
* ``QueryFullProcessImageNameW``, ``IsWow64Process2`` / ``IsWow64Process``
* ``VirtualQueryEx``, ``ReadProcessMemory``
* ``IsUserAnAdmin``

No API that modifies another process is bound anywhere in this package.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from typing import Any

from aoe2mr.backends.win32 import constants as c
from aoe2mr.backends.win32.access import validate_access_mask
from aoe2mr.backends.win32.structures import (
    MEMORY_BASIC_INFORMATION,
    PROCESSENTRY32W,
    wchar_array_to_str,
)
from aoe2mr.errors import UnsupportedPlatformError

HANDLE = ctypes.c_void_p
BOOL = ctypes.c_int32
DWORD = ctypes.c_uint32
USHORT = ctypes.c_uint16


class Win32Error(OSError):
    def __init__(self, function: str, winerror: int) -> None:
        self.function = function
        self.code = winerror
        super().__init__(f"{function} failed with Win32 error {winerror}")


@dataclass(frozen=True)
class Kernel32:
    """Typed function pointers. Created once per process by :func:`kernel32`."""

    CreateToolhelp32Snapshot: Any
    Process32FirstW: Any
    Process32NextW: Any
    OpenProcess: Any
    CloseHandle: Any
    QueryFullProcessImageNameW: Any
    IsWow64Process: Any
    IsWow64Process2: Any | None
    VirtualQueryEx: Any
    ReadProcessMemory: Any


def _require_windows() -> None:
    if sys.platform != "win32":
        raise UnsupportedPlatformError("Win32 process APIs are only available on Windows")
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise UnsupportedPlatformError("A 64-bit Python interpreter is required")


@cache
def kernel32() -> Kernel32:
    _require_windows()
    dll = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]

    def bind(name: str, restype: Any, argtypes: list[Any]) -> Any:
        fn = getattr(dll, name)
        fn.restype = restype
        fn.argtypes = argtypes
        return fn

    try:
        wow2 = bind("IsWow64Process2", BOOL, [HANDLE, ctypes.POINTER(USHORT),
                                               ctypes.POINTER(USHORT)])
    except AttributeError:  # Windows 10 before 1511
        wow2 = None

    return Kernel32(
        CreateToolhelp32Snapshot=bind("CreateToolhelp32Snapshot", HANDLE, [DWORD, DWORD]),
        Process32FirstW=bind("Process32FirstW", BOOL,
                             [HANDLE, ctypes.POINTER(PROCESSENTRY32W)]),
        Process32NextW=bind("Process32NextW", BOOL, [HANDLE, ctypes.POINTER(PROCESSENTRY32W)]),
        OpenProcess=bind("OpenProcess", HANDLE, [DWORD, BOOL, DWORD]),
        CloseHandle=bind("CloseHandle", BOOL, [HANDLE]),
        QueryFullProcessImageNameW=bind(
            "QueryFullProcessImageNameW", BOOL,
            [HANDLE, DWORD, ctypes.c_wchar_p, ctypes.POINTER(DWORD)],
        ),
        IsWow64Process=bind("IsWow64Process", BOOL, [HANDLE, ctypes.POINTER(BOOL)]),
        IsWow64Process2=wow2,
        VirtualQueryEx=bind(
            "VirtualQueryEx", ctypes.c_size_t,
            [HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t],
        ),
        ReadProcessMemory=bind(
            "ReadProcessMemory", BOOL,
            [HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
             ctypes.POINTER(ctypes.c_size_t)],
        ),
    )


def _last_error() -> int:
    return int(ctypes.get_last_error())  # type: ignore[attr-defined,unused-ignore]


# --- Process enumeration --------------------------------------------------------------------


@dataclass(frozen=True)
class RawProcessEntry:
    pid: int
    parent_pid: int
    name: str
    thread_count: int


def enumerate_processes() -> list[RawProcessEntry]:
    k = kernel32()
    snapshot = k.CreateToolhelp32Snapshot(c.TH32CS_SNAPPROCESS, 0)
    if snapshot is None or snapshot == ctypes.c_void_p(c.INVALID_HANDLE_VALUE).value:
        raise Win32Error("CreateToolhelp32Snapshot", _last_error())
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        result: list[RawProcessEntry] = []
        ok = k.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            result.append(RawProcessEntry(
                pid=int(entry.th32ProcessID),
                parent_pid=int(entry.th32ParentProcessID),
                name=wchar_array_to_str(entry.szExeFile),
                thread_count=int(entry.cntThreads),
            ))
            ok = k.Process32NextW(snapshot, ctypes.byref(entry))
        err = _last_error()
        if err not in (0, c.ERROR_NO_MORE_FILES):
            raise Win32Error("Process32NextW", err)
        return result
    finally:
        k.CloseHandle(snapshot)


# --- Handles --------------------------------------------------------------------------------


class ProcessHandle:
    """An owned, read-only process handle. Use as a context manager."""

    def __init__(self, pid: int, access: int) -> None:
        validate_access_mask(access)
        k = kernel32()
        handle = k.OpenProcess(access, False, pid)
        if not handle:
            raise Win32Error("OpenProcess", _last_error())
        self.pid = pid
        self.access = access
        self._handle: int | None = handle

    @property
    def raw(self) -> int:
        if self._handle is None:
            raise ValueError("Process handle is closed")
        return self._handle

    def close(self) -> None:
        if self._handle is not None:
            kernel32().CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> ProcessHandle:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):  # interpreter shutdown
            self.close()


def query_image_path(handle: ProcessHandle) -> str:
    k = kernel32()
    size = DWORD(32768)
    buf = ctypes.create_unicode_buffer(size.value)
    if not k.QueryFullProcessImageNameW(handle.raw, 0, buf, ctypes.byref(size)):
        raise Win32Error("QueryFullProcessImageNameW", _last_error())
    return buf.value


@dataclass(frozen=True)
class MachineInfo:
    process_machine: int  # IMAGE_FILE_MACHINE_UNKNOWN when not running under WOW64
    native_machine: int


def query_machine(handle: ProcessHandle) -> MachineInfo:
    k = kernel32()
    if k.IsWow64Process2 is not None:
        process_machine = USHORT(0)
        native_machine = USHORT(0)
        if not k.IsWow64Process2(handle.raw, ctypes.byref(process_machine),
                                 ctypes.byref(native_machine)):
            raise Win32Error("IsWow64Process2", _last_error())
        return MachineInfo(process_machine.value, native_machine.value)
    is_wow = BOOL(0)
    if not k.IsWow64Process(handle.raw, ctypes.byref(is_wow)):
        raise Win32Error("IsWow64Process", _last_error())
    return MachineInfo(
        c.IMAGE_FILE_MACHINE_I386 if is_wow.value else c.IMAGE_FILE_MACHINE_UNKNOWN,
        c.IMAGE_FILE_MACHINE_AMD64,
    )


# --- Memory ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class RawRegion:
    base_address: int
    size: int
    allocation_base: int
    allocation_protect: int
    state: int
    protect: int
    type: int


def iterate_regions(handle: ProcessHandle, max_regions: int) -> Iterator[RawRegion]:
    """Yield every region from address 0 upward until ``VirtualQueryEx`` reports the end."""
    k = kernel32()
    mbi = MEMORY_BASIC_INFORMATION()
    address = 0
    count = 0
    while count < max_regions:
        written = k.VirtualQueryEx(handle.raw, ctypes.c_void_p(address), ctypes.byref(mbi),
                                   ctypes.sizeof(mbi))
        if written == 0:
            err = _last_error()
            if err == c.ERROR_INVALID_PARAMETER:  # past the highest user-mode address
                return
            raise Win32Error("VirtualQueryEx", err)
        base = int(mbi.BaseAddress or 0)
        size = int(mbi.RegionSize)
        yield RawRegion(
            base_address=base,
            size=size,
            allocation_base=int(mbi.AllocationBase or 0),
            allocation_protect=int(mbi.AllocationProtect),
            state=int(mbi.State),
            protect=int(mbi.Protect),
            type=int(mbi.Type),
        )
        count += 1
        next_address = base + size
        if size == 0 or next_address <= address:
            return
        address = next_address


def read_memory(handle: ProcessHandle, address: int, size: int) -> tuple[bytes, int]:
    """Read ``size`` bytes. Returns ``(data, Win32 error or 0)``; data may be partial."""
    k = kernel32()
    buf = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    ok = k.ReadProcessMemory(handle.raw, ctypes.c_void_p(address), buf, size,
                             ctypes.byref(read))
    err = 0 if ok else _last_error()
    return buf.raw[: read.value], err


def is_user_admin() -> bool | None:
    if sys.platform != "win32":
        return None
    try:
        shell32 = ctypes.WinDLL("shell32")  # type: ignore[attr-defined,unused-ignore]
        return bool(shell32.IsUserAnAdmin())
    except (OSError, AttributeError):
        return None
