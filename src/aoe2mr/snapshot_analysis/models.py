"""Typed models for snapshots, value filters and candidate sets.

Value arrays use numpy so that scanning a gigabyte of memory takes seconds, not minutes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

import numpy as np
import numpy.typing as npt

AnyArray = npt.NDArray[Any]
Mask = npt.NDArray[np.bool_]


class DataType(StrEnum):
    """Numeric types a candidate value may have. Values are little-endian (x86/x64)."""

    INT8 = "int8"
    UINT8 = "uint8"
    INT16 = "int16"
    UINT16 = "uint16"
    INT32 = "int32"
    UINT32 = "uint32"
    INT64 = "int64"
    UINT64 = "uint64"
    FLOAT32 = "float32"
    FLOAT64 = "float64"

    @property
    def np_dtype(self) -> np.dtype[Any]:
        return np.dtype("<" + _STRUCT[self])

    @property
    def size(self) -> int:
        return struct.calcsize("<" + _STRUCT[self])

    @property
    def is_float(self) -> bool:
        return self in (DataType.FLOAT32, DataType.FLOAT64)

    def decode(self, data: bytes | bytearray) -> int | float:
        value: int | float = struct.unpack("<" + _STRUCT[self], data)[0]
        return value

    def view(self, data: bytes | bytearray | memoryview) -> AnyArray:
        """Zero-copy view of ``data`` as aligned values (trailing partial value ignored)."""
        count = len(data) // self.size
        return np.frombuffer(data, dtype=self.np_dtype, count=count)

    def empty(self) -> AnyArray:
        return np.empty(0, dtype=self.np_dtype)

    def coerce(self, text: str) -> int | float:
        """Parse user input for this type, rejecting values that do not fit."""
        try:
            value: int | float = float(text) if self.is_float else int(text, 0)
        except ValueError:
            raise ValueError(f"{text!r} is not a valid {self.value}") from None
        if not self.is_float:
            info = np.iinfo(self.np_dtype)
            if not info.min <= int(value) <= info.max:
                raise ValueError(f"{value} does not fit {self.value}")
        return value


_STRUCT = {
    DataType.INT8: "b", DataType.UINT8: "B", DataType.INT16: "h", DataType.UINT16: "H",
    DataType.INT32: "i", DataType.UINT32: "I", DataType.INT64: "q", DataType.UINT64: "Q",
    DataType.FLOAT32: "f", DataType.FLOAT64: "d",
}


class FilterKind(StrEnum):
    DISPLAYED = "displayed"  # what the game shows: a float rounded/truncated to an integer
    EQUALS = "equals"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    INCREASED = "increased"
    DECREASED = "decreased"
    INCREASED_BY = "increased_by"
    DECREASED_BY = "decreased_by"

    @property
    def needs_operand(self) -> bool:
        return self in (FilterKind.DISPLAYED, FilterKind.EQUALS, FilterKind.INCREASED_BY,
                        FilterKind.DECREASED_BY)

    @property
    def needs_previous(self) -> bool:
        return self not in (FilterKind.EQUALS, FilterKind.DISPLAYED)


@dataclass(frozen=True)
class ValueFilter:
    kind: FilterKind
    operand: float | int | None = None
    tolerance: float = 0.0  # absolute tolerance

    def __post_init__(self) -> None:
        if self.kind.needs_operand and self.operand is None:
            raise ValueError(f"filter {self.kind.value} needs a value")

    def mask(self, old: AnyArray | None, new: AnyArray) -> Mask:
        """Vectorised filter: which ``new`` values (vs. ``old``) satisfy it."""
        k = self.kind
        tol = self.tolerance
        if np.issubdtype(new.dtype, np.floating):
            finite = np.isfinite(new)
        else:
            finite = np.ones(new.shape, dtype=bool)
        n = new.astype(np.float64)
        if k is FilterKind.DISPLAYED:
            assert self.operand is not None
            # The game shows a whole number. Accept values that truncate or round to it.
            lo, hi = float(self.operand) - 0.5 - tol, float(self.operand) + 1.0 + tol
            return finite & (n >= lo) & (n < hi)
        if k is FilterKind.EQUALS:
            assert self.operand is not None
            return finite & (np.abs(n - float(self.operand)) <= tol)
        assert old is not None, f"{k.value} needs previous values"
        o = old.astype(np.float64)
        if np.issubdtype(old.dtype, np.floating):
            finite &= np.isfinite(old)
        d = n - o
        if k is FilterKind.CHANGED:
            return finite & (np.abs(d) > tol)
        if k is FilterKind.UNCHANGED:
            return finite & (np.abs(d) <= tol)
        if k is FilterKind.INCREASED:
            return finite & (d > tol)
        if k is FilterKind.DECREASED:
            return finite & (d < -tol)
        assert self.operand is not None
        if k is FilterKind.INCREASED_BY:
            return finite & (np.abs(d - float(self.operand)) <= tol)
        return finite & (np.abs(-d - float(self.operand)) <= tol)  # DECREASED_BY

    def matches(self, old: float | int | None, new: float | int) -> bool:
        """Scalar convenience wrapper around :meth:`mask`."""
        o = None if old is None else np.array([old], dtype=np.float64)
        return bool(self.mask(o, np.array([new], dtype=np.float64))[0])

    def describe(self) -> str:
        text = self.kind.value + ("" if self.operand is None else f" {self.operand}")
        return text + (f" ±{self.tolerance:g}" if self.tolerance else "")


@dataclass(frozen=True)
class SnapshotRegion:
    base_address: int
    data: bytes | bytearray  # bytearray when captured whole (avoids a copy); never mutated

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def end_address(self) -> int:
        return self.base_address + len(self.data)

    def contains(self, address: int, size: int = 1) -> bool:
        return self.base_address <= address and address + size <= self.end_address


@dataclass(frozen=True)
class Snapshot:
    """Contents of selected readable regions at one moment (reads are not atomic)."""

    snapshot_id: int
    pid: int
    label: str
    captured_at: datetime
    regions: tuple[SnapshotRegion, ...]
    failed_chunks: int
    truncated: bool
    duration_s: float
    planned_bytes: int = 0  # bytes selected before the cap was applied

    @property
    def total_bytes(self) -> int:
        return sum(r.size for r in self.regions)

    def region_for(self, address: int, size: int = 1) -> SnapshotRegion | None:
        for r in self.regions:
            if r.contains(address, size):
                return r
        return None

    def read_value(self, address: int, data_type: DataType) -> int | float | None:
        r = self.region_for(address, data_type.size)
        if r is None:
            return None
        off = address - r.base_address
        return data_type.decode(r.data[off: off + data_type.size])


@dataclass
class CandidateSet:
    """Addresses still consistent with every filter applied so far (numpy arrays)."""

    data_type: DataType
    addresses: npt.NDArray[np.uint64]
    values: AnyArray
    history: list[str] = field(default_factory=list)
    truncated: bool = False

    def __len__(self) -> int:
        return int(self.addresses.shape[0])

    def items(self, limit: int | None = None) -> list[tuple[int, int | float]]:
        n = len(self) if limit is None else min(limit, len(self))
        return [(int(a), v.item()) for a, v in zip(self.addresses[:n], self.values[:n],
                                                   strict=True)]


@dataclass(frozen=True)
class TimelineEvent:
    at: datetime
    kind: str  # "snapshot" | "scan" | "filter" | "annotation" | "reset"
    message: str
    snapshot_id: int | None = None
    candidate_count: int | None = None
