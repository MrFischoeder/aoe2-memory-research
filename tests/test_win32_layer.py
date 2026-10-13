"""Platform-independent checks of the Win32 binding layer."""

from __future__ import annotations

import ctypes
import sys

import pytest

from aoe2mr.backends import create_default_backend
from aoe2mr.backends.win32 import api
from aoe2mr.backends.win32 import constants as c
from aoe2mr.backends.win32.access import (
    ALLOWED_ACCESS_MASK,
    IDENTIFY_ACCESS,
    READ_ACCESS,
    validate_access_mask,
)
from aoe2mr.backends.win32.structures import MEMORY_BASIC_INFORMATION, PROCESSENTRY32W
from aoe2mr.backends.windows import architecture_from_machine
from aoe2mr.errors import ForbiddenAccessRequestError, UnsupportedPlatformError
from aoe2mr.process_discovery.models import Architecture

IS_64 = ctypes.sizeof(ctypes.c_void_p) == 8

# Rights that would allow modifying or controlling a process. None may ever be requested.
PROCESS_TERMINATE = 0x0001
PROCESS_CREATE_THREAD = 0x0002
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_DUP_HANDLE = 0x0040
PROCESS_SET_INFORMATION = 0x0200
PROCESS_SUSPEND_RESUME = 0x0800
PROCESS_ALL_ACCESS = 0x001FFFFF


@pytest.mark.skipif(not IS_64, reason="64-bit layouts")
def test_structure_sizes_match_sdk_x64() -> None:
    assert ctypes.sizeof(MEMORY_BASIC_INFORMATION) == 48
    assert MEMORY_BASIC_INFORMATION.RegionSize.offset == 24
    assert MEMORY_BASIC_INFORMATION.Type.offset == 40
    assert ctypes.sizeof(PROCESSENTRY32W) == 568
    assert PROCESSENTRY32W.th32DefaultHeapID.offset == 16
    assert PROCESSENTRY32W.szExeFile.offset == 44


def test_read_only_masks_allowed() -> None:
    assert validate_access_mask(IDENTIFY_ACCESS) == c.PROCESS_QUERY_LIMITED_INFORMATION
    assert validate_access_mask(READ_ACCESS) == READ_ACCESS
    assert validate_access_mask(ALLOWED_ACCESS_MASK) == ALLOWED_ACCESS_MASK


@pytest.mark.parametrize(
    "right",
    [PROCESS_TERMINATE, PROCESS_CREATE_THREAD, PROCESS_VM_OPERATION, PROCESS_VM_WRITE,
     PROCESS_DUP_HANDLE, PROCESS_SET_INFORMATION, PROCESS_SUSPEND_RESUME, PROCESS_ALL_ACCESS,
     0x00100000, 0x00080000],  # SYNCHRONIZE, WRITE_OWNER
)
def test_write_or_control_rights_rejected(right: int) -> None:
    with pytest.raises(ForbiddenAccessRequestError):
        validate_access_mask(right | c.PROCESS_VM_READ)
    with pytest.raises(ForbiddenAccessRequestError):
        validate_access_mask(right)


def test_empty_mask_rejected() -> None:
    with pytest.raises(ForbiddenAccessRequestError):
        validate_access_mask(0)


def test_process_handle_validates_before_calling_windows() -> None:
    # Must fail on the policy check on every platform, before any DLL is loaded.
    with pytest.raises(ForbiddenAccessRequestError):
        api.ProcessHandle(1234, PROCESS_VM_WRITE)


@pytest.mark.parametrize(
    ("process_machine", "native", "expected"),
    [
        (c.IMAGE_FILE_MACHINE_UNKNOWN, c.IMAGE_FILE_MACHINE_AMD64, Architecture.X64),
        (c.IMAGE_FILE_MACHINE_I386, c.IMAGE_FILE_MACHINE_AMD64, Architecture.X86),
        (c.IMAGE_FILE_MACHINE_UNKNOWN, c.IMAGE_FILE_MACHINE_ARM64, Architecture.ARM64),
        (0x1234, c.IMAGE_FILE_MACHINE_AMD64, Architecture.UNKNOWN),
    ],
)
def test_architecture_mapping(process_machine: int, native: int,
                              expected: Architecture) -> None:
    assert architecture_from_machine(api.MachineInfo(process_machine, native)) is expected


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behaviour")
def test_non_windows_is_refused_cleanly() -> None:
    with pytest.raises(UnsupportedPlatformError):
        create_default_backend()
    with pytest.raises(UnsupportedPlatformError):
        api.kernel32()
    assert api.is_user_admin() is None


def test_wchar_decoding() -> None:
    from aoe2mr.backends.win32.structures import wchar_array_to_str

    entry = PROCESSENTRY32W()
    encoded = "AoE2DE_s.exe".encode("utf-16-le")
    ctypes.memmove(ctypes.addressof(entry) + PROCESSENTRY32W.szExeFile.offset, encoded,
                   len(encoded))
    assert wchar_array_to_str(entry.szExeFile) == "AoE2DE_s.exe"
