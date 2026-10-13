"""Typed models for virtual memory regions of another process.

Decoding is pure Python so it can be unit-tested on any platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from aoe2mr.backends.win32 import constants as c


class MemoryState(StrEnum):
    COMMIT = "commit"
    RESERVE = "reserve"
    FREE = "free"
    UNKNOWN = "unknown"

    @classmethod
    def from_win32(cls, value: int) -> MemoryState:
        return {
            c.MEM_COMMIT: cls.COMMIT,
            c.MEM_RESERVE: cls.RESERVE,
            c.MEM_FREE: cls.FREE,
        }.get(value, cls.UNKNOWN)


class MemoryType(StrEnum):
    PRIVATE = "private"
    MAPPED = "mapped"
    IMAGE = "image"
    NONE = "none"  # free regions have no type
    UNKNOWN = "unknown"

    @classmethod
    def from_win32(cls, value: int) -> MemoryType:
        if value == 0:
            return cls.NONE
        return {
            c.MEM_PRIVATE: cls.PRIVATE,
            c.MEM_MAPPED: cls.MAPPED,
            c.MEM_IMAGE: cls.IMAGE,
        }.get(value, cls.UNKNOWN)


_BASE_PROTECTION_NAMES = {
    c.PAGE_NOACCESS: "NOACCESS",
    c.PAGE_READONLY: "R",
    c.PAGE_READWRITE: "RW",
    c.PAGE_WRITECOPY: "WC",
    c.PAGE_EXECUTE: "X",
    c.PAGE_EXECUTE_READ: "RX",
    c.PAGE_EXECUTE_READWRITE: "RWX",
    c.PAGE_EXECUTE_WRITECOPY: "XWC",
}

_READABLE_BASE = {
    c.PAGE_READONLY,
    c.PAGE_READWRITE,
    c.PAGE_WRITECOPY,
    c.PAGE_EXECUTE_READ,
    c.PAGE_EXECUTE_READWRITE,
    c.PAGE_EXECUTE_WRITECOPY,
}
_WRITABLE_BASE = {
    c.PAGE_READWRITE,
    c.PAGE_WRITECOPY,
    c.PAGE_EXECUTE_READWRITE,
    c.PAGE_EXECUTE_WRITECOPY,
}
_EXECUTABLE_BASE = {
    c.PAGE_EXECUTE,
    c.PAGE_EXECUTE_READ,
    c.PAGE_EXECUTE_READWRITE,
    c.PAGE_EXECUTE_WRITECOPY,
}


@dataclass(frozen=True)
class Protection:
    """A decoded ``PAGE_*`` protection value."""

    raw: int

    @property
    def base(self) -> int:
        return self.raw & c.PAGE_BASE_MASK

    @property
    def guard(self) -> bool:
        return bool(self.raw & c.PAGE_GUARD)

    @property
    def no_cache(self) -> bool:
        return bool(self.raw & c.PAGE_NOCACHE)

    @property
    def write_combine(self) -> bool:
        return bool(self.raw & c.PAGE_WRITECOMBINE)

    @property
    def readable(self) -> bool:
        return self.base in _READABLE_BASE and not self.guard

    @property
    def writable(self) -> bool:
        """Whether the *target process* may write the page (this tool never does)."""
        return self.base in _WRITABLE_BASE

    @property
    def executable(self) -> bool:
        return self.base in _EXECUTABLE_BASE

    @property
    def label(self) -> str:
        if self.raw == 0:
            return "-"
        name = _BASE_PROTECTION_NAMES.get(self.base, f"0x{self.base:02X}")
        mods = [m for m, on in (("G", self.guard), ("NC", self.no_cache),
                                ("WCB", self.write_combine)) if on]
        return "+".join([name, *mods])


@dataclass(frozen=True)
class MemoryRegion:
    """One contiguous region returned by ``VirtualQueryEx``."""

    base_address: int
    size: int
    allocation_base: int
    allocation_protect: Protection
    state: MemoryState
    protect: Protection
    type: MemoryType

    @property
    def end_address(self) -> int:
        return self.base_address + self.size

    @property
    def is_readable(self) -> bool:
        """True if a read-only ``ReadProcessMemory`` of this region is expected to succeed."""
        return self.state is MemoryState.COMMIT and self.protect.readable

    def contains(self, address: int) -> bool:
        return self.base_address <= address < self.end_address

    @classmethod
    def from_raw(
        cls,
        base_address: int,
        size: int,
        allocation_base: int,
        allocation_protect: int,
        state: int,
        protect: int,
        type_: int,
    ) -> MemoryRegion:
        return cls(
            base_address=base_address,
            size=size,
            allocation_base=allocation_base,
            allocation_protect=Protection(allocation_protect),
            state=MemoryState.from_win32(state),
            protect=Protection(protect),
            type=MemoryType.from_win32(type_),
        )


@dataclass(frozen=True)
class RegionSummary:
    region_count: int
    total_bytes: int
    readable_count: int
    readable_bytes: int
    writable_readable_bytes: int
    bytes_by_type: dict[str, int] = field(default_factory=dict)
    bytes_by_protection: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RegionReport:
    pid: int
    captured_at: datetime
    regions: tuple[MemoryRegion, ...]
    summary: RegionSummary
    truncated: bool
    skipped_regions: int
