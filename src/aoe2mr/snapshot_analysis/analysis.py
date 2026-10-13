"""Value scans, snapshot comparison and candidate refinement.

Exact searches use ``bytes.find`` (C speed); comparisons skip unchanged 4 KiB pages before
decoding anything, so cost scales with how much memory actually changed.
"""

from __future__ import annotations

import bisect
import struct
from array import array

from aoe2mr.concurrency import CancellationToken
from aoe2mr.snapshot_analysis.models import (
    CandidateSet,
    DataType,
    FilterKind,
    Snapshot,
    SnapshotRegion,
    ValueFilter,
)

PAGE = 4096
DEFAULT_MAX_CANDIDATES = 2_000_000


def _empty(data_type: DataType, snapshot_id: int, note: str) -> CandidateSet:
    return CandidateSet(data_type, array("Q"), array(data_type.typecode), snapshot_id, [note])


def scan_value(
    snapshot: Snapshot,
    data_type: DataType,
    value_filter: ValueFilter,
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    cancel: CancellationToken | None = None,
) -> CandidateSet:
    """First scan: find aligned addresses whose value satisfies an ``EQUALS`` filter."""
    if value_filter.kind is not FilterKind.EQUALS:
        raise ValueError("a first scan needs an 'equals' filter; compare snapshots otherwise")
    assert value_filter.operand is not None
    result = _empty(data_type, snapshot.snapshot_id,
                    f"scan #{snapshot.snapshot_id} {data_type.value} {value_filter.describe()}")
    size = data_type.size
    exact = not data_type.is_float or value_filter.tolerance == 0
    if exact:
        operand = data_type.coerce(str(value_filter.operand))
        needle = struct.pack("<" + data_type.typecode, operand)
        stored = data_type.decode(needle)  # e.g. float32 rounding of the operand
    for region in snapshot.regions:
        if cancel is not None:
            cancel.raise_if_cancelled()
        base = region.base_address
        if exact:
            data = region.data
            pos = data.find(needle)
            while pos != -1:
                if (base + pos) % size == 0:
                    result.addresses.append(base + pos)
                    result.values.append(stored)
                    if len(result) >= max_candidates:
                        result.truncated = True
                        return result
                pos = data.find(needle, pos + 1)
        else:
            values = data_type.decode_array(region.data)
            for i, v in enumerate(values):
                if cancel is not None and i % 65536 == 0:
                    cancel.raise_if_cancelled()
                if value_filter.matches(None, v):
                    result.addresses.append(base + i * size)
                    result.values.append(v)
                    if len(result) >= max_candidates:
                        result.truncated = True
                        return result
    return result


def _pairs(before: Snapshot, after: Snapshot) -> list[tuple[SnapshotRegion, SnapshotRegion]]:
    after_by_base = {r.base_address: r for r in after.regions}
    pairs = []
    for b in before.regions:
        a = after_by_base.get(b.base_address)
        if a is not None:
            pairs.append((b, a))
    return pairs


def compare_snapshots(
    before: Snapshot,
    after: Snapshot,
    data_type: DataType,
    value_filter: ValueFilter,
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    cancel: CancellationToken | None = None,
) -> CandidateSet:
    """Unknown-initial-value search: every aligned value whose change matches the filter."""
    if before.pid != after.pid:
        raise ValueError("snapshots belong to different processes")
    result = _empty(data_type, after.snapshot_id,
                    f"compare #{before.snapshot_id}->#{after.snapshot_id} {data_type.value} "
                    f"{value_filter.describe()}")
    size = data_type.size
    # Every filter except "unchanged"/"equals" requires a change, so identical pages can be
    # skipped without decoding them.
    skip_equal_pages = value_filter.kind not in (FilterKind.UNCHANGED, FilterKind.EQUALS)
    for b, a in _pairs(before, after):
        n = min(b.size, a.size)
        for start in range(0, n - n % size, PAGE):
            if cancel is not None:
                cancel.raise_if_cancelled()
            end = min(start + PAGE, n - n % size)
            old_page = b.data[start:end]
            new_page = a.data[start:end]
            if skip_equal_pages and old_page == new_page:
                continue
            olds = data_type.decode_array(old_page)
            news = data_type.decode_array(new_page)
            page_base = b.base_address + start
            for i in range(len(news)):
                if value_filter.matches(olds[i], news[i]):
                    result.addresses.append(page_base + i * size)
                    result.values.append(news[i])
                    if len(result) >= max_candidates:
                        result.truncated = True
                        return result
    return result


class _RegionIndex:
    def __init__(self, snapshot: Snapshot) -> None:
        self.regions = sorted(snapshot.regions, key=lambda r: r.base_address)
        self.bases = [r.base_address for r in self.regions]

    def read(self, address: int, data_type: DataType) -> int | float | None:
        i = bisect.bisect_right(self.bases, address) - 1
        if i < 0:
            return None
        r = self.regions[i]
        if not r.contains(address, data_type.size):
            return None
        off = address - r.base_address
        return data_type.decode(r.data[off: off + data_type.size])


def refine(
    candidates: CandidateSet,
    snapshot: Snapshot,
    value_filter: ValueFilter,
    *,
    cancel: CancellationToken | None = None,
) -> CandidateSet:
    """Keep only candidates whose value in ``snapshot`` satisfies the filter.

    Addresses missing from the new snapshot are dropped (stale observation).
    """
    dt = candidates.data_type
    index = _RegionIndex(snapshot)
    out = CandidateSet(dt, array("Q"), array(dt.typecode), snapshot.snapshot_id,
                       [*candidates.history, f"#{snapshot.snapshot_id} {value_filter.describe()}"],
                       candidates.truncated)
    for i, address in enumerate(candidates.addresses):
        if cancel is not None and i % 65536 == 0:
            cancel.raise_if_cancelled()
        new = index.read(address, dt)
        if new is None:
            continue
        if value_filter.matches(candidates.values[i], new):
            out.addresses.append(address)
            out.values.append(new)
    return out
