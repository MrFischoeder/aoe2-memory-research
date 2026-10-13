"""Bounded, cancellable capture of readable regions into an in-memory snapshot."""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from aoe2mr.app_logging import get_logger
from aoe2mr.backends.base import ProcessBackend
from aoe2mr.concurrency import CancellationToken
from aoe2mr.config import RegionsConfig, SamplingConfig
from aoe2mr.errors import MemoryReadError
from aoe2mr.memory_research.models import MemoryRegion, MemoryType
from aoe2mr.snapshot_analysis.models import Snapshot, SnapshotRegion

log = get_logger("snapshot_analysis")

CHUNK_SIZE = 1024 * 1024
ProgressCallback = Callable[[int, int], None]  # (bytes done, bytes planned)


@dataclass(frozen=True)
class CaptureSelection:
    """Which regions to capture. Defaults target where mutable game state normally lives."""

    private: bool = True
    mapped: bool = False
    image: bool = False
    writable_only: bool = True

    def accepts(self, region: MemoryRegion) -> bool:
        if not region.is_readable:
            return False
        if self.writable_only and not region.protect.writable:
            return False
        return {
            MemoryType.PRIVATE: self.private,
            MemoryType.MAPPED: self.mapped,
            MemoryType.IMAGE: self.image,
        }.get(region.type, False)


class SnapshotCapturer:
    def __init__(self, backend: ProcessBackend, regions: RegionsConfig,
                 sampling: SamplingConfig) -> None:
        self._backend = backend
        self._regions = regions
        self._max_bytes = sampling.max_snapshot_bytes
        self._ids = itertools.count(1)

    def capture(
        self,
        pid: int,
        label: str = "",
        *,
        selection: CaptureSelection | None = None,
        cancel: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> Snapshot:
        selection = selection or CaptureSelection()
        started = time.perf_counter()
        captured: list[SnapshotRegion] = []
        failed = 0
        truncated = False
        with self._backend.open_read_only(pid) as proc:
            plan = [r for r in proc.iter_regions(self._regions.max_regions)
                    if selection.accepts(r)]
            planned = sum(r.size for r in plan)
            budget = self._max_bytes
            done = 0
            for region in plan:
                if budget <= 0:
                    truncated = True
                    break
                size = min(region.size, budget)
                truncated = truncated or size < region.size
                # Read in chunks; a failed chunk splits the region into separate pieces.
                piece_start = region.base_address
                piece = bytearray()
                for offset in range(0, size, CHUNK_SIZE):
                    if cancel is not None:
                        cancel.raise_if_cancelled()
                    address = region.base_address + offset
                    length = min(CHUNK_SIZE, size - offset)
                    try:
                        data = proc.read(address, length)
                    except MemoryReadError:
                        failed += 1
                        if piece:
                            captured.append(SnapshotRegion(piece_start, bytes(piece)))
                        piece = bytearray()
                        piece_start = address + length
                        continue
                    piece += data
                    done += length
                    if progress is not None:
                        progress(done, min(planned, self._max_bytes))
                if piece:
                    captured.append(SnapshotRegion(piece_start, bytes(piece)))
                budget -= size
        snap = Snapshot(
            snapshot_id=next(self._ids),
            pid=pid,
            label=label,
            captured_at=datetime.now(UTC),
            regions=tuple(captured),
            failed_chunks=failed,
            truncated=truncated,
            duration_s=time.perf_counter() - started,
        )
        log.info("Snapshot #%d of pid %d: %d bytes in %d regions (%.2fs, %d failed chunks%s)",
                 snap.snapshot_id, pid, snap.total_bytes, len(snap.regions), snap.duration_s,
                 failed, ", TRUNCATED" if truncated else "")
        return snap
