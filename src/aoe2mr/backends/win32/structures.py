"""ctypes structure layouts matching the 64-bit Windows SDK definitions.

Fixed-width ctypes types are used instead of ``ctypes.wintypes`` so the layouts can be
imported and size-checked on any platform.
"""

from __future__ import annotations

import ctypes

DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16
LONG = ctypes.c_int32
ULONG_PTR = ctypes.c_size_t
# Windows WCHAR is always 16 bits; ctypes.c_wchar is 32 bits on Linux, so use uint16.
WCHAR = ctypes.c_uint16
MAX_PATH = 260


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", DWORD),
        ("cntUsage", DWORD),
        ("th32ProcessID", DWORD),
        ("th32DefaultHeapID", ULONG_PTR),
        ("th32ModuleID", DWORD),
        ("cntThreads", DWORD),
        ("th32ParentProcessID", DWORD),
        ("pcPriClassBase", LONG),
        ("dwFlags", DWORD),
        ("szExeFile", WCHAR * MAX_PATH),
    ]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    """64-bit layout (``PartitionId`` exists only in the _WIN64 definition)."""

    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", DWORD),
        ("PartitionId", WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", DWORD),
        ("Protect", DWORD),
        ("Type", DWORD),
    ]


def wchar_array_to_str(array: ctypes.Array[ctypes.c_uint16]) -> str:
    """Decode a NUL-terminated UTF-16LE ``WCHAR[]`` field."""
    return bytes(array).decode("utf-16-le", errors="replace").split("\0", 1)[0]
