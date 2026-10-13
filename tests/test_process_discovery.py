from __future__ import annotations

import pytest

from aoe2mr.backends.fake import FakeProcessBackend
from aoe2mr.config import DiscoveryConfig
from aoe2mr.errors import ProcessNotFoundError
from aoe2mr.process_discovery.discovery import ProcessDiscovery
from aoe2mr.process_discovery.models import AccessStatus, Architecture
from tests.conftest import AOE_PID


@pytest.fixture
def discovery(fake_backend: FakeProcessBackend) -> ProcessDiscovery:
    return ProcessDiscovery(fake_backend, DiscoveryConfig())


def test_find_targets(discovery: ProcessDiscovery) -> None:
    [target] = discovery.find_targets()
    assert target.pid == AOE_PID
    assert target.is_target
    assert target.access is AccessStatus.READ
    assert target.architecture is Architecture.X64
    assert target.executable_path is not None
    assert target.executable_path.endswith("AoE2DE_s.exe")


def test_target_name_case_insensitive(discovery: ProcessDiscovery) -> None:
    assert discovery.is_target_name("aoe2de_S.EXE")
    assert not discovery.is_target_name("AoE2DE_s.exe.bak")


def test_list_and_filter_sorted(discovery: ProcessDiscovery) -> None:
    names = [e.name for e in discovery.list_processes()]
    assert names == sorted(names, key=str.casefold)
    assert [e.name for e in discovery.list_processes("NOTE")] == ["notepad.exe"]


def test_denied_identification_is_reported_not_bypassed(
    discovery: ProcessDiscovery, fake_backend: FakeProcessBackend
) -> None:
    d = discovery.describe(4)
    assert d.access is AccessStatus.DENIED
    assert d.executable_path is None
    assert d.architecture is Architecture.UNKNOWN
    assert d.access_error and "Access denied" in d.access_error
    assert fake_backend.opened == []  # no further attempt after denial


def test_query_only_when_read_denied(discovery: ProcessDiscovery) -> None:
    d = discovery.describe(777)
    assert d.access is AccessStatus.QUERY_ONLY
    assert d.executable_path == r"C:\Tools\Elevated.exe"


def test_handles_are_closed(discovery: ProcessDiscovery, fake_backend: FakeProcessBackend) -> None:
    discovery.describe(AOE_PID)
    assert fake_backend.opened and all(h.closed for h in fake_backend.opened)


def test_missing_pid(discovery: ProcessDiscovery) -> None:
    with pytest.raises(ProcessNotFoundError):
        discovery.describe(123456)


def test_process_exits_during_probe(fake_backend: FakeProcessBackend) -> None:
    discovery = ProcessDiscovery(fake_backend, DiscoveryConfig())
    entry = fake_backend.processes[900].entry
    del fake_backend.processes[900]
    assert discovery.describe_entry(entry).access is AccessStatus.EXITED


def test_no_targets() -> None:
    assert ProcessDiscovery(FakeProcessBackend([]), DiscoveryConfig()).find_targets() == []
