from __future__ import annotations

import pytest

from aoe2mr.backends.win32 import constants as c
from aoe2mr.memory_research.models import MemoryRegion, MemoryState, MemoryType, Protection


@pytest.mark.parametrize(
    ("raw", "label", "readable", "writable", "executable"),
    [
        (c.PAGE_NOACCESS, "NOACCESS", False, False, False),
        (c.PAGE_READONLY, "R", True, False, False),
        (c.PAGE_READWRITE, "RW", True, True, False),
        (c.PAGE_WRITECOPY, "WC", True, True, False),
        (c.PAGE_EXECUTE, "X", False, False, True),
        (c.PAGE_EXECUTE_READ, "RX", True, False, True),
        (c.PAGE_EXECUTE_READWRITE, "RWX", True, True, True),
        (c.PAGE_EXECUTE_WRITECOPY, "XWC", True, True, True),
        (c.PAGE_READWRITE | c.PAGE_GUARD, "RW+G", False, True, False),
        (c.PAGE_READWRITE | c.PAGE_NOCACHE, "RW+NC", True, True, False),
        (c.PAGE_READONLY | c.PAGE_WRITECOMBINE, "R+WCB", True, False, False),
        (0, "-", False, False, False),
    ],
)
def test_protection_decoding(raw: int, label: str, readable: bool, writable: bool,
                             executable: bool) -> None:
    p = Protection(raw)
    assert p.label == label
    assert p.readable is readable
    assert p.writable is writable
    assert p.executable is executable


def test_state_and_type_decoding() -> None:
    assert MemoryState.from_win32(c.MEM_COMMIT) is MemoryState.COMMIT
    assert MemoryState.from_win32(c.MEM_RESERVE) is MemoryState.RESERVE
    assert MemoryState.from_win32(c.MEM_FREE) is MemoryState.FREE
    assert MemoryState.from_win32(0x1234) is MemoryState.UNKNOWN
    assert MemoryType.from_win32(c.MEM_IMAGE) is MemoryType.IMAGE
    assert MemoryType.from_win32(c.MEM_MAPPED) is MemoryType.MAPPED
    assert MemoryType.from_win32(c.MEM_PRIVATE) is MemoryType.PRIVATE
    assert MemoryType.from_win32(0) is MemoryType.NONE
    assert MemoryType.from_win32(7) is MemoryType.UNKNOWN


def test_region_readability_requires_commit() -> None:
    committed = MemoryRegion.from_raw(0x1000, 0x1000, 0x1000, 4, c.MEM_COMMIT, 4, c.MEM_PRIVATE)
    reserved = MemoryRegion.from_raw(0x1000, 0x1000, 0x1000, 4, c.MEM_RESERVE, 4, c.MEM_PRIVATE)
    assert committed.is_readable
    assert not reserved.is_readable
    assert committed.end_address == 0x2000
    assert committed.contains(0x1FFF)
    assert not committed.contains(0x2000)
