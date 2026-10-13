"""A research session: new scan / next scan, candidates and a change timeline.

Workflow (the same as classic memory scanners, but read-only):

* **New scan** with a known value (``displayed`` or ``equals``): take a snapshot, search it,
  keep the matches as candidates and free the snapshot.
* **New scan** without a value (``changed``, ``increased``...): take a baseline snapshot only.
* **Next scan**: with candidates, read just those addresses from the live process and filter;
  with only a baseline, take a second snapshot and compare the two.

Every step is recorded in the timeline so results are reproducible.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aoe2mr.backends.base import ProcessBackend
from aoe2mr.concurrency import CancellationToken
from aoe2mr.config import RegionsConfig, SamplingConfig
from aoe2mr.errors import ResearchError
from aoe2mr.snapshot_analysis.analysis import (
    DEFAULT_MAX_CANDIDATES,
    compare_snapshots,
    read_current,
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
        self.baseline: Snapshot | None = None  # only held for an unknown-value search
        self.candidates: CandidateSet | None = None
        self.timeline: list[TimelineEvent] = []
        self._lock = threading.Lock()

    # -- helpers ----------------------------------------------------------------------------

    def _event(self, kind: str, message: str, snapshot_id: int | None = None) -> TimelineEvent:
        count = len(self.candidates) if self.candidates is not None else None
        event = TimelineEvent(datetime.now(UTC), kind, message, snapshot_id, count)
        self.timeline.append(event)
        return event

    def _capture(self, label: str, selection: CaptureSelection | None,
                 cancel: CancellationToken | None,
                 progress: ProgressCallback | None) -> Snapshot:
        snap = self._capturer.capture(self.pid, label, selection=selection, cancel=cancel,
                                      progress=progress)
        note = (f"snapshot #{snap.snapshot_id} {label!r}: {snap.total_bytes / 2**20:,.0f} MiB "
                f"of {snap.planned_bytes / 2**20:,.0f} MiB, {len(snap.regions)} regions, "
                f"{snap.duration_s:.1f}s")
        if snap.truncated:
            note += " (TRUNCATED: raise the snapshot limit)"
        if snap.failed_chunks:
            note += f", {snap.failed_chunks} unreadable chunks"
        with self._lock:
            self._event("snapshot", note, snap.snapshot_id)
        return snap

    def set_snapshot_limit(self, max_bytes: int) -> None:
        self._capturer.max_bytes = max_bytes

    @property
    def awaiting_next_scan(self) -> bool:
        return self.candidates is not None or self.baseline is not None

    # -- operations -------------------------------------------------------------------------

    def new_scan(self, data_type: DataType, value_filter: ValueFilter, *, label: str = "",
                 selection: CaptureSelection | None = None,
                 cancel: CancellationToken | None = None,
                 progress: ProgressCallback | None = None) -> CandidateSet | None:
        """Start over. Returns candidates, or ``None`` when only a baseline was taken."""
        with self._lock:
            self.candidates = None
            self.baseline = None  # free memory before capturing
        snap = self._capture(label or "new scan", selection, cancel, progress)
        if value_filter.kind.needs_previous:
            with self._lock:
                self.baseline = snap
                self._event("scan", f"baseline for unknown {data_type.value} value; change it "
                                    "in game, then run a next scan", snap.snapshot_id)
            return None
        result = scan_value(snap, data_type, value_filter, max_candidates=self._max_candidates,
                            cancel=cancel)
        with self._lock:
            self.candidates = result
            self._event("scan", result.history[-1]
                        + (" (candidate cap reached)" if result.truncated else ""),
                        snap.snapshot_id)
        return result

    def next_scan(self, value_filter: ValueFilter, *, data_type: DataType | None = None,
                  selection: CaptureSelection | None = None,
                  cancel: CancellationToken | None = None,
                  progress: ProgressCallback | None = None) -> CandidateSet:
        """Narrow the candidates (live reads) or compare against the baseline snapshot."""
        cand = self.candidates
        if cand is not None:
            if value_filter.kind.needs_previous and not len(cand):
                raise SessionStateError("no candidates left; start a new scan")
            with self.backend.open_read_only(self.pid) as proc:
                values, ok = read_current(proc, cand.data_type, cand.addresses, cancel=cancel)
            result = refine(cand, values, ok, value_filter,
                            f"next {cand.data_type.value} {value_filter.describe()}")
            with self._lock:
                self.candidates = result
                self._event("filter", result.history[-1])
            return result

        baseline = self.baseline
        if baseline is None:
            raise SessionStateError("start with a new scan")
        if data_type is None:
            raise SessionStateError("choose a data type")
        if not value_filter.kind.needs_previous:
            # A value is known now: search the live process instead of comparing.
            found = self.new_scan(data_type, value_filter, selection=selection, cancel=cancel,
                                  progress=progress)
            assert found is not None
            return found
        snap = self._capture("next scan", selection, cancel, progress)
        result = compare_snapshots(baseline, snap, data_type, value_filter,
                                   max_candidates=self._max_candidates, cancel=cancel)
        with self._lock:
            self.baseline = None  # candidates carry their own values from here on
            self.candidates = result
            self._event("filter", result.history[-1]
                        + (" (candidate cap reached)" if result.truncated else ""),
                        snap.snapshot_id)
        return result

    def annotate(self, text: str) -> TimelineEvent:
        with self._lock:
            return self._event("annotation", text)

    def reset(self) -> None:
        with self._lock:
            self.candidates = None
            self.baseline = None
            self._event("reset", "candidates cleared")

    def read_live(self, limit: int = 200) -> list[LiveValue]:
        """Read the current value of the first ``limit`` candidates directly."""
        cand = self.candidates
        if cand is None or not len(cand):
            return []
        addresses = cand.addresses[:limit]
        with self.backend.open_read_only(self.pid) as proc:
            values, ok = read_current(proc, cand.data_type, addresses)
        return [LiveValue(int(a), v.item() if good else None)
                for a, v, good in zip(addresses, values, ok, strict=True)]

    def to_record(self, max_candidates: int = 10_000) -> dict[str, Any]:
        """A JSON-ready record of the session (no raw memory contents)."""
        cand = self.candidates
        return {
            "pid": self.pid,
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
