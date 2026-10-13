"""Read-only memory-region inspection (M1). No memory contents are captured here."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime

from aoe2mr.app_logging import get_logger
from aoe2mr.backends.base import ProcessBackend
from aoe2mr.concurrency import CancellationToken
from aoe2mr.config import RegionsConfig
from aoe2mr.memory_research.models import MemoryRegion, MemoryState, RegionReport, RegionSummary

log = get_logger("memory_research")

_CANCEL_CHECK_EVERY = 256


def summarize(regions: Iterable[MemoryRegion]) -> RegionSummary:
    count = total = readable_count = readable_bytes = rw_bytes = 0
    by_type: Counter[str] = Counter()
    by_prot: Counter[str] = Counter()
    for r in regions:
        count += 1
        total += r.size
        by_type[r.type.value] += r.size
        by_prot[r.protect.label] += r.size
        if r.is_readable:
            readable_count += 1
            readable_bytes += r.size
            if r.protect.writable:
                rw_bytes += r.size
    return RegionSummary(
        region_count=count,
        total_bytes=total,
        readable_count=readable_count,
        readable_bytes=readable_bytes,
        writable_readable_bytes=rw_bytes,
        bytes_by_type=dict(by_type.most_common()),
        bytes_by_protection=dict(by_prot.most_common()),
    )


class RegionInspector:
    def __init__(self, backend: ProcessBackend, config: RegionsConfig) -> None:
        self._backend = backend
        self._config = config

    def _keep(self, region: MemoryRegion, readable_only: bool) -> bool:
        if region.state is MemoryState.FREE:
            return False
        if self._config.committed_only and region.state is not MemoryState.COMMIT:
            return False
        if region.size < self._config.min_region_size:
            return False
        return not (readable_only and not region.is_readable)

    def inspect(
        self,
        pid: int,
        *,
        readable_only: bool = False,
        cancel: CancellationToken | None = None,
    ) -> RegionReport:
        """Enumerate regions of ``pid``. Raises AccessDenied/ProcessNotFound errors as-is."""
        kept: list[MemoryRegion] = []
        seen = skipped = 0
        max_regions = self._config.max_regions
        with self._backend.open_read_only(pid) as proc:
            for region in proc.iter_regions(max_regions):
                seen += 1
                if cancel is not None and seen % _CANCEL_CHECK_EVERY == 0:
                    cancel.raise_if_cancelled()
                if self._keep(region, readable_only):
                    kept.append(region)
                else:
                    skipped += 1
        truncated = seen >= max_regions
        if truncated:
            log.warning("Region enumeration for pid %d stopped at cap of %d", pid, max_regions)
        log.info("pid %d: %d regions kept, %d skipped", pid, len(kept), skipped)
        return RegionReport(
            pid=pid,
            captured_at=datetime.now(UTC),
            regions=tuple(kept),
            summary=summarize(kept),
            truncated=truncated,
            skipped_regions=skipped,
        )

    def find_region(self, pid: int, address: int) -> MemoryRegion | None:
        """Return the region (of any state) containing ``address``, if any."""
        with self._backend.open_read_only(pid) as proc:
            for region in proc.iter_regions(self._config.max_regions):
                if region.contains(address):
                    return region
        return None
