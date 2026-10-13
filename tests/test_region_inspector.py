from __future__ import annotations

from dataclasses import replace

import pytest

from aoe2mr.backends.fake import FakeProcessBackend
from aoe2mr.concurrency import CancellationToken, OperationCancelledError
from aoe2mr.config import RegionsConfig
from aoe2mr.errors import AccessDeniedError, MemoryReadError, ProcessNotFoundError
from aoe2mr.memory_research.models import MemoryState
from aoe2mr.memory_research.regions import RegionInspector, summarize
from tests.conftest import AOE_PID, region


def test_default_filters(fake_backend: FakeProcessBackend) -> None:
    report = RegionInspector(fake_backend, RegionsConfig()).inspect(AOE_PID)
    bases = [r.base_address for r in report.regions]
    # reserved, free and below-min-size regions are skipped
    assert bases == [0x10000, 0x20000, 0x30000, 0x140000000]
    assert report.skipped_regions == 3
    assert not report.truncated
    assert report.summary.readable_count == 3  # guard page is not readable
    assert report.summary.readable_bytes == 0x1000 + 0x10000 + 0x200000
    assert report.summary.writable_readable_bytes == 0x10000
    assert report.summary.bytes_by_type["image"] == 0x200000


def test_readable_only_and_reserved(fake_backend: FakeProcessBackend) -> None:
    cfg = RegionsConfig(min_region_size=0, committed_only=False)
    inspector = RegionInspector(fake_backend, cfg)
    all_report = inspector.inspect(AOE_PID)
    assert any(r.state is MemoryState.RESERVE for r in all_report.regions)
    assert all(r.state is not MemoryState.FREE for r in all_report.regions)
    readable = inspector.inspect(AOE_PID, readable_only=True)
    assert all(r.is_readable for r in readable.regions)


def test_cap_truncates(fake_backend: FakeProcessBackend) -> None:
    report = RegionInspector(fake_backend, RegionsConfig(max_regions=2)).inspect(AOE_PID)
    assert report.truncated


def test_cancellation(fake_backend: FakeProcessBackend) -> None:
    proc = fake_backend.processes[AOE_PID]
    proc.regions = [region(0x10000 * (i + 1), 0x1000) for i in range(1000)]
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelledError):
        RegionInspector(fake_backend, RegionsConfig()).inspect(AOE_PID, cancel=token)
    assert all(h.closed for h in fake_backend.opened)


def test_access_denied_propagates(fake_backend: FakeProcessBackend) -> None:
    with pytest.raises(AccessDeniedError):
        RegionInspector(fake_backend, RegionsConfig()).inspect(777)
    with pytest.raises(ProcessNotFoundError):
        RegionInspector(fake_backend, RegionsConfig()).inspect(1)


def test_find_region(fake_backend: FakeProcessBackend) -> None:
    inspector = RegionInspector(fake_backend, RegionsConfig())
    found = inspector.find_region(AOE_PID, 0x20010)
    assert found is not None and found.base_address == 0x20000
    assert inspector.find_region(AOE_PID, 0x5) is None


def test_fake_read(fake_backend: FakeProcessBackend) -> None:
    with fake_backend.open_read_only(AOE_PID) as proc:
        assert proc.read(0x20002, 3) == bytes([2, 3, 4])
        with pytest.raises(MemoryReadError):
            proc.read(0x30000, 4)  # guard page


def test_summary_empty() -> None:
    s = summarize([])
    assert s.region_count == 0 and s.total_bytes == 0 and s.bytes_by_type == {}


def test_report_is_immutable(fake_backend: FakeProcessBackend) -> None:
    report = RegionInspector(fake_backend, RegionsConfig()).inspect(AOE_PID)
    with pytest.raises(AttributeError):
        report.regions[0].size = 1  # type: ignore[misc]
    assert replace(report, truncated=True).truncated
