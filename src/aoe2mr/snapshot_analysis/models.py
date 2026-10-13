"""Typed models for snapshots, value filters and candidate sets."""

from __future__ import annotations

import math
import struct
from array import array
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


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
    def typecode(self) -> str:
        return _TYPECODES[self]

    @property
    def size(self) -> int:
        return struct.calcsize("<" + _STRUCT[self])

    @property
    def is_float(self) -> bool:
        return self in (DataType.FLOAT32, DataType.FLOAT64)

    def decode(self, data: bytes) -> int | float:
        value: int | float = struct.unpack("<" + _STRUCT[self], data)[0]
        return value

    def decode_array(self, data: bytes | memoryview) -> array:  # type: ignore[type-arg]
        values = array(self.typecode)
        values.frombytes(bytes(data[: len(data) - len(data) % self.size]))
        return values

    def coerce(self, text: str) -> int | float:
        """Parse user input for this type, rejecting values that do not fit."""
        try:
            value: int | float = float(text) if self.is_float else int(text, 0)
        except ValueError:
            raise ValueError(f"{text!r} is not a valid {self.value}") from None
        if not self.is_float:
            bits = self.size * 8
            lo, hi = ((-(1 << (bits - 1)), (1 << (bits - 1)) - 1)
                      if self.value.startswith("int") else (0, (1 << bits) - 1))
            if not lo <= int(value) <= hi:
                raise ValueError(f"{value} does not fit {self.value}")
        return value


_TYPECODES = {
    DataType.INT8: "b", DataType.UINT8: "B", DataType.INT16: "h", DataType.UINT16: "H",
    DataType.INT32: "i", DataType.UINT32: "I", DataType.INT64: "q", DataType.UINT64: "Q",
    DataType.FLOAT32: "f", DataType.FLOAT64: "d",
}
_STRUCT = _TYPECODES  # identical letters for struct and array on Windows/Linux x64

for _dt in DataType:  # guard against platforms where array sizes differ
    assert array(_dt.typecode).itemsize == _dt.size, _dt


class FilterKind(StrEnum):
    EQUALS = "equals"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    INCREASED = "increased"
    DECREASED = "decreased"
    INCREASED_BY = "increased_by"
    DECREASED_BY = "decreased_by"

    @property
    def needs_operand(self) -> bool:
        return self in (FilterKind.EQUALS, FilterKind.INCREASED_BY, FilterKind.DECREASED_BY)

    @property
    def needs_previous(self) -> bool:
        return self is not FilterKind.EQUALS


@dataclass(frozen=True)
class ValueFilter:
    kind: FilterKind
    operand: float | int | None = None
    tolerance: float = 0.0  # absolute tolerance, used for float types

    def __post_init__(self) -> None:
        if self.kind.needs_operand and self.operand is None:
            raise ValueError(f"filter {self.kind.value} needs a value")

    def matches(self, old: float | int | None, new: float | int) -> bool:
        if isinstance(new, float) and math.isnan(new):
            return False
        tol = self.tolerance
        k = self.kind
        if k is FilterKind.EQUALS:
            assert self.operand is not None
            return abs(new - self.operand) <= tol
        assert old is not None
        if k is FilterKind.CHANGED:
            return abs(new - old) > tol
        if k is FilterKind.UNCHANGED:
            return abs(new - old) <= tol
        if k is FilterKind.INCREASED:
            return new > old + tol
        if k is FilterKind.DECREASED:
            return new < old - tol
        assert self.operand is not None
        if k is FilterKind.INCREASED_BY:
            return abs((new - old) - self.operand) <= tol
        return abs((old - new) - self.operand) <= tol  # DECREASED_BY

    def describe(self) -> str:
        return self.kind.value + ("" if self.operand is None else f" {self.operand}")


@dataclass(frozen=True)
class SnapshotRegion:
    base_address: int
    data: bytes

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

    @property
    def total_bytes(self) -> int:
        return sum(r.size for r in self.regions)

    def region_for(self, address: int, size: int = 1) -> SnapshotRegion | None:
        for r in self.regions:  # regions are sorted; few hundred at most
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
    """Addresses still consistent with every filter applied so far.

    Addresses and values are stored in compact arrays so millions of candidates stay cheap.
    """

    data_type: DataType
    addresses: array  # type: ignore[type-arg]
    values: array  # type: ignore[type-arg]
    snapshot_id: int
    history: list[str] = field(default_factory=list)
    truncated: bool = False

    def __len__(self) -> int:
        return len(self.addresses)

    def items(self, limit: int | None = None) -> list[tuple[int, int | float]]:
        n = len(self.addresses) if limit is None else min(limit, len(self.addresses))
        return [(self.addresses[i], self.values[i]) for i in range(n)]


@dataclass(frozen=True)
class TimelineEvent:
    at: datetime
    kind: str  # "snapshot" | "scan" | "filter" | "annotation" | "reset"
    message: str
    snapshot_id: int | None = None
    candidate_count: int | None = None
