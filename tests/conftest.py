from __future__ import annotations

import os
import sys

import pytest

from aoe2mr.backends.fake import FakeProcess, FakeProcessBackend
from aoe2mr.backends.win32 import constants as c
from aoe2mr.memory_research.models import MemoryRegion
from aoe2mr.process_discovery.models import Architecture, ProcessEntry

AOE_PID = 4242


def region(base: int, size: int, state: int = c.MEM_COMMIT, protect: int = c.PAGE_READWRITE,
           type_: int = c.MEM_PRIVATE) -> MemoryRegion:
    return MemoryRegion.from_raw(base, size, base, protect, state, protect, type_)


@pytest.fixture
def fake_backend() -> FakeProcessBackend:
    aoe = FakeProcess(
        entry=ProcessEntry(AOE_PID, 100, "AoE2DE_s.exe", 64),
        path=r"C:\Steam\steamapps\common\AoE2DE\AoE2DE_s.exe",
        architecture=Architecture.X64,
        regions=[
            region(0x10000, 0x1000, protect=c.PAGE_READONLY),
            region(0x20000, 0x10000),  # RW private
            region(0x30000, 0x2000, protect=c.PAGE_READWRITE | c.PAGE_GUARD),  # guard page
            region(0x40000, 0x8000, state=c.MEM_RESERVE, protect=0, type_=c.MEM_PRIVATE),
            region(0x50000, 0x100, protect=c.PAGE_READWRITE),  # below min size
            region(0x140000000, 0x200000, protect=c.PAGE_EXECUTE_READ, type_=c.MEM_IMAGE),
            region(0x7FF000000000, 0x1000, state=c.MEM_FREE, protect=c.PAGE_NOACCESS, type_=0),
        ],
        memory={0x20000: bytes(range(256)) * 256},
    )
    protected = FakeProcess(entry=ProcessEntry(4, 0, "System", 200), identify_denied=True)
    elevated = FakeProcess(
        entry=ProcessEntry(777, 1, "Elevated.exe", 3),
        path=r"C:\Tools\Elevated.exe",
        read_denied=True,
    )
    notepad = FakeProcess(entry=ProcessEntry(900, 1, "notepad.exe", 2),
                          path=r"C:\Windows\notepad.exe", architecture=Architecture.X64)
    return FakeProcessBackend([aoe, protected, elevated, notepad])


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """On GitHub Actions, surface failures as annotations (readable without the raw log)."""
    if not report.failed or not os.environ.get("GITHUB_ACTIONS"):
        return
    text = str(report.longrepr)[-3000:]
    message = text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    sys.__stdout__.write(f"\n::error title={report.nodeid} ({report.when})::{message}\n")
    sys.__stdout__.flush()
