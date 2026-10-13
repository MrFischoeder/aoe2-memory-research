"""A research session: snapshots, the current candidate set and a change timeline.

This is the single object the CLI and the desktop UI drive. It keeps at most a few snapshots
in memory (bounded memory use) and records every step so results are reproducible.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aoe2mr.backends.base import ProcessBackend
from aoe2mr.concurrency import CancellationToken
from aoe2mr.config import RegionsConfig, SamplingConfig
from aoe2mr.errors import MemoryReadError, ResearchError
from aoe2mr.snapshot_analysis.analysis import (
    DEFAULT_MAX_CANDIDATES,
    compare_snapshots,
    refine,
    scan_value,
)
from aoe2mr.snapshot_analysis.capture import CaptureSelection, ProgressCallback, SnapshotCapturer
from aoe2mr.snapshot_analysis.models import (
    CandidateSet,
    DataType,
    Snapshot,
    TimelineEvent,
    ValueFilter,
)

MAX_SNAPSHOTS_IN_MEMORY = 2  # enough to compare; bounds memory use


class SessionStateError(ResearchError):
    """Raised when an operation is not possible in the current session state."""


@dataclass(frozen=True)
class LiveValue:
    address: int
    value: int | float | None  # None when the address can no longer be read


class ResearchSession:
    def __init__(self, backend: ProcessBackend, pid: int, regions: RegionsConfig,
                 sampling: SamplingConfig, *,
                 max_candidates: int = DEFAULT_MAX_CANDIDATES) -> None:
        self.backend = backend
        self.pid = pid
        self._capturer = SnapshotCapturer(backend, regions, sampling)
        self._max_candidates = max_candidates
        self.snapshots: deque[Snapshot] = deque(maxlen=MAX_SNAPSHOTS_IN_MEMORY)
        self.candidates: CandidateSet | None = None
        self.timeline: list[TimelineEvent] = []
        self._lock = threading.Lock()

    # -- helpers ----------------------------------------------------------------------------

    def _event(self, kind: str, message: str, snapshot_id: int | None = None) -> TimelineEvent:
        count = len(self.candidates) if self.candidates is not None else None
        event = TimelineEvent(datetime.now(UTC), kind, message, snapshot_id, count)
        self.timeline.append(event)
        return event

    @property
    def latest(self) -> Snapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    # -- operations -------------------------------------------------------------------------

    def capture(self, label: str = "", *, selection: CaptureSelection | None = None,
                cancel: CancellationToken | None = None,
                progress: ProgressCallback | None = None) -> Snapshot:
        snap = self._capturer.capture(self.pid, label, selection=selection, cancel=cancel,
                                      progress=progress)
        with self._lock:
            self.snapshots.append(snap)
            note = (f"snapshot #{snap.snapshot_id} {label!r}: {snap.total_bytes:,} bytes, "
                    f"{len(snap.regions)} regions, {snap.duration_s:.2f}s")
            if snap.truncated:
                note += " (truncated by max_snapshot_bytes)"
            if snap.failed_chunks:
                note += f", {snap.failed_chunks} unreadable chunks"
            self._event("snapshot", note, snap.snapshot_id)
        return snap

    def scan_value(self, data_type: DataType, value_filter: ValueFilter, *,
                   cancel: CancellationToken | None = None) -> CandidateSet:
        snap = self.latest
        if snap is None:
            raise SessionStateError("take a snapshot first")
        result = scan_value(snap, data_type, value_filter, max_candidates=self._max_candidates,
                            cancel=cancel)
        with self._lock:
            self.candidates = result
            self._event("scan", result.history[-1], snap.snapshot_id)
        return result

    def apply_filter(self, value_filter: ValueFilter, *, data_type: DataType | None = None,
                     cancel: CancellationToken | None = None) -> CandidateSet:
        """Narrow the candidates using the newest snapshot.

        Without candidates, compares the two newest snapshots (unknown initial value).
        """
        snap = self.latest
        if snap is None:
            raise SessionStateError("take a snapshot first")
        if self.candidates is None:
            if data_type is None:
                raise SessionStateError("choose a data type")
            if not value_filter.kind.needs_previous:
                return self.scan_value(data_type, value_filter, cancel=cancel)
            if len(self.snapshots) < 2:
                raise SessionStateError("take two snapshots, or scan for a known value first")
            result = compare_snapshots(self.snapshots[-2], snap, data_type, value_filter,
                                       max_candidates=self._max_candidates, cancel=cancel)
        else:
            if self.candidates.snapshot_id == snap.snapshot_id and value_filter.kind.needs_previous:
                raise SessionStateError("take a new snapshot before filtering by change")
            result = refine(self.candidates, snap, value_filter, cancel=cancel)
        with self._lock:
            self.candidates = result
            self._event("filter", result.history[-1], snap.snapshot_id)
        return result

    def annotate(self, text: str) -> TimelineEvent:
        with self._lock:
            return self._event("annotation", text)

    def reset(self) -> None:
        with self._lock:
            self.candidates = None
            self._event("reset", "candidates cleared")

    def read_live(self, limit: int = 200) -> list[LiveValue]:
        """Read the current value of the first ``limit`` candidates directly (small reads)."""
        cand = self.candidates
        if cand is None:
            return []
        out = []
        size = cand.data_type.size
        with self.backend.open_read_only(self.pid) as proc:
            for address, _ in cand.items(limit):
                try:
                    out.append(LiveValue(address, cand.data_type.decode(proc.read(address, size))))
                except MemoryReadError:
                    out.append(LiveValue(address, None))
        return out

    def to_record(self, max_candidates: int = 10_000) -> dict[str, Any]:
        """A JSON-ready record of the session (no raw memory contents)."""
        cand = self.candidates
        return {
            "pid": self.pid,
            "snapshots": [
                {"id": s.snapshot_id, "label": s.label, "captured_at": s.captured_at,
                 "bytes": s.total_bytes, "regions": len(s.regions), "truncated": s.truncated,
                 "failed_chunks": s.failed_chunks, "duration_s": round(s.duration_s, 3)}
                for s in self.snapshots
            ],
            "candidates": None if cand is None else {
                "data_type": cand.data_type,
                "count": len(cand),
                "truncated": cand.truncated,
                "history": cand.history,
                "items": [{"address": f"0x{a:X}", "value": v}
                          for a, v in cand.items(max_candidates)],
            },
            "timeline": self.timeline,
        }
