"""Value scans, snapshot comparison and candidate refinement (vectorised with numpy).

* First scan: search one snapshot for a known value (``equals`` or ``displayed``).
* Unknown value: compare two snapshots; unchanged 4 KiB pages are skipped cheaply.
* Next scan: read only the candidate addresses from the live process (page-batched), so no
  full snapshot is needed after the first scan.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from aoe2mr.backends.base import ReadOnlyProcess
from aoe2mr.concurrency import CancellationToken
from aoe2mr.errors import MemoryReadError
from aoe2mr.snapshot_analysis.models import (
    AnyArray,
    CandidateSet,
    DataType,
    FilterKind,
    Mask,
    Snapshot,
    SnapshotRegion,
    ValueFilter,
)

PAGE = 4096
DEFAULT_MAX_CANDIDATES = 5_000_000
_SCAN_BLOCK = 16 * 1024 * 1024  # bytes per vectorised step; bounds temporaries and cancel latency
_MAX_RUN_PAGES = 16  # consecutive pages fetched with one read during a next scan


def _empty(data_type: DataType, note: str) -> CandidateSet:
    return CandidateSet(data_type, np.empty(0, dtype=np.uint64), data_type.empty(), [note])


class _Collector:
    """Accumulates (address, value) chunks up to a cap."""

    def __init__(self, data_type: DataType, max_candidates: int) -> None:
        self.data_type = data_type
        self.max = max_candidates
        self.addresses: list[npt.NDArray[np.uint64]] = []
        self.values: list[AnyArray] = []
        self.count = 0
        self.truncated = False

    @property
    def full(self) -> bool:
        return self.count >= self.max

    def add(self, base: int, values: AnyArray, mask: Mask) -> None:
        idx = np.flatnonzero(mask)
        room = self.max - self.count
        if idx.size > room:
            idx = idx[:room]
            self.truncated = True
        if idx.size:
            self.addresses.append(np.uint64(base) + idx.astype(np.uint64)
                                  * np.uint64(self.data_type.size))
            self.values.append(values[idx].copy())
            self.count += int(idx.size)

    def result(self, history: list[str]) -> CandidateSet:
        dt = self.data_type
        addresses = (np.concatenate(self.addresses) if self.addresses
                     else np.empty(0, dtype=np.uint64))
        values = np.concatenate(self.values) if self.values else dt.empty()
        return CandidateSet(dt, addresses, values, history, self.truncated)


def scan_value(
    snapshot: Snapshot,
    data_type: DataType,
    value_filter: ValueFilter,
    *,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    cancel: CancellationToken | None = None,
) -> CandidateSet:
    """First scan: aligned addresses whose value matches ``equals``/``displayed``."""
    if value_filter.kind.needs_previous:
        raise ValueError("a first scan needs 'equals' or 'displayed'; compare snapshots otherwise")
    out = _Collector(data_type, max_candidates)
    size = data_type.size
    for region in snapshot.regions:
        for start in range(0, region.size - region.size % size, _SCAN_BLOCK):
            if cancel is not None:
                cancel.raise_if_cancelled()
            block = data_type.view(memoryview(region.data)[start: start + _SCAN_BLOCK])
            out.add(region.base_address + start, block, value_filter.mask(None, block))
            if out.full:
                break
    return out.result([f"scan #{snapshot.snapshot_id} {data_type.value} "
                       f"{value_filter.describe()}"])


def _pairs(before: Snapshot, after: Snapshot) -> list[tuple[SnapshotRegion, SnapshotRegion]]:
    after_by_base = {r.base_address: r for r in after.regions}
    return [(b, after_by_base[b.base_address]) for b in before.regions
            if b.base_address in after_by_base]


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
    out = _Collector(data_type, max_candidates)
    size = data_type.size
    # Every filter except "unchanged" requires a change, so identical pages can be skipped.
    skip_equal = value_filter.kind is not FilterKind.UNCHANGED
    for b, a in _pairs(before, after):
        n = min(b.size, a.size)
        n -= n % size
        bv, av = memoryview(b.data), memoryview(a.data)
        for start in range(0, n, _SCAN_BLOCK):
            if cancel is not None:
                cancel.raise_if_cancelled()
            end = min(start + _SCAN_BLOCK, n)
            old = data_type.view(bv[start:end])
            new = data_type.view(av[start:end])
            if skip_equal:
                if bv[start:end] == av[start:end]:
                    continue
                # Narrow to pages that differ before evaluating the filter.
                per_page = PAGE // size
                pages = (end - start + PAGE - 1) // PAGE
                o8 = np.frombuffer(bv[start:end], dtype=np.uint8)
                n8 = np.frombuffer(av[start:end], dtype=np.uint8)
                pad = pages * PAGE - (end - start)
                if pad:
                    o8 = np.concatenate([o8, np.zeros(pad, np.uint8)])
                    n8 = np.concatenate([n8, np.zeros(pad, np.uint8)])
                changed_pages = np.flatnonzero(
                    (o8.reshape(pages, PAGE) != n8.reshape(pages, PAGE)).any(axis=1))
                for p in changed_pages:
                    lo, hi = int(p) * per_page, min((int(p) + 1) * per_page, new.size)
                    out.add(b.base_address + start + lo * size, new[lo:hi],
                            value_filter.mask(old[lo:hi], new[lo:hi]))
            else:
                out.add(b.base_address + start, new, value_filter.mask(old, new))
            if out.full:
                return out.result([_describe_compare(before, after, data_type, value_filter)])
    return out.result([_describe_compare(before, after, data_type, value_filter)])


def _describe_compare(before: Snapshot, after: Snapshot, data_type: DataType,
                      value_filter: ValueFilter) -> str:
    return (f"compare #{before.snapshot_id}->#{after.snapshot_id} {data_type.value} "
            f"{value_filter.describe()}")


def read_current(
    proc: ReadOnlyProcess,
    data_type: DataType,
    addresses: npt.NDArray[np.uint64],
    *,
    cancel: CancellationToken | None = None,
) -> tuple[AnyArray, Mask]:
    """Read the current value at each address. Returns ``(values, readable_mask)``.

    Addresses are grouped by page and consecutive pages are fetched together, so a million
    candidates cost thousands of reads, not a million.
    """
    size = data_type.size
    values = np.zeros(addresses.shape[0], dtype=data_type.np_dtype)
    ok = np.zeros(addresses.shape[0], dtype=bool)
    if addresses.size == 0:
        return values, ok
    order = np.argsort(addresses, kind="stable")
    sorted_addr = addresses[order]
    pages = sorted_addr // np.uint64(PAGE)
    unique_pages = np.unique(pages)
    # Group consecutive pages into runs.
    runs: list[tuple[int, int]] = []  # (first page, page count)
    for page in unique_pages.tolist():
        if runs and runs[-1][0] + runs[-1][1] == page and runs[-1][1] < _MAX_RUN_PAGES:
            runs[-1] = (runs[-1][0], runs[-1][1] + 1)
        else:
            runs.append((page, 1))
    for i, (first_page, count) in enumerate(runs):
        if cancel is not None and i % 1024 == 0:
            cancel.raise_if_cancelled()
        base = first_page * PAGE
        try:
            buf = proc.read(base, count * PAGE)
        except MemoryReadError:
            # A run can span an unreadable page; fall back to single pages.
            for p in range(first_page, first_page + count):
                try:
                    _fill(proc.read(p * PAGE, PAGE), p * PAGE, sorted_addr, order, size,
                          data_type, values, ok)
                except MemoryReadError:
                    continue
            continue
        _fill(buf, base, sorted_addr, order, size, data_type, values, ok)
    return values, ok


def _fill(buf: bytes, base: int, sorted_addr: npt.NDArray[np.uint64],
          order: npt.NDArray[np.intp], size: int, data_type: DataType, values: AnyArray,
          ok: Mask) -> None:
    lo = int(np.searchsorted(sorted_addr, np.uint64(base), side="left"))
    hi = int(np.searchsorted(sorted_addr, np.uint64(base + len(buf) - size), side="right"))
    if hi <= lo:
        return
    offsets = (sorted_addr[lo:hi] - np.uint64(base)).astype(np.int64)
    arr = np.frombuffer(buf, dtype=np.uint8)
    idx = offsets[:, None] + np.arange(size)
    raw = arr[idx].reshape(-1).tobytes()
    targets = order[lo:hi]
    values[targets] = np.frombuffer(raw, dtype=data_type.np_dtype)
    ok[targets] = True


def refine(
    candidates: CandidateSet,
    new_values: AnyArray,
    readable: Mask,
    value_filter: ValueFilter,
    note: str,
) -> CandidateSet:
    """Keep candidates whose new value satisfies the filter; unreadable ones are dropped."""
    keep = readable & value_filter.mask(candidates.values, new_values)
    return CandidateSet(
        candidates.data_type,
        candidates.addresses[keep],
        new_values[keep],
        [*candidates.history, note],
        candidates.truncated,
    )


def refine_from_snapshot(
    candidates: CandidateSet,
    snapshot: Snapshot,
    value_filter: ValueFilter,
) -> CandidateSet:
    """Like :func:`refine`, but take the new values from a snapshot."""
    dt = candidates.data_type
    regions = sorted(snapshot.regions, key=lambda r: r.base_address)
    bases = np.array([r.base_address for r in regions], dtype=np.uint64)
    values = np.zeros(len(candidates), dtype=dt.np_dtype)
    ok = np.zeros(len(candidates), dtype=bool)
    if regions and len(candidates):
        idx = np.searchsorted(bases, candidates.addresses, side="right") - 1
        for i, address in enumerate(candidates.addresses.tolist()):
            j = int(idx[i])
            if j < 0:
                continue
            r = regions[j]
            if r.contains(address, dt.size):
                off = address - r.base_address
                values[i] = dt.decode(r.data[off: off + dt.size])
                ok[i] = True
    return refine(candidates, values, ok, value_filter,
                  f"#{snapshot.snapshot_id} {value_filter.describe()}")
