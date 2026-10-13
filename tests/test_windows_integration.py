"""End-to-end test against the real Win32 APIs using the synthetic target process.

Runs only on Windows (e.g. the windows-latest CI job or a developer machine).
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import pytest

from aoe2mr.config import DiscoveryConfig, RegionsConfig
from aoe2mr.errors import ProcessNotFoundError
from aoe2mr.memory_research.models import MemoryState
from aoe2mr.memory_research.regions import RegionInspector
from aoe2mr.process_discovery.discovery import ProcessDiscovery
from aoe2mr.process_discovery.models import AccessStatus, Architecture
from aoe2mr.synthetic.target import MAGIC

pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(sys.platform != "win32", reason="requires Windows"),
]


class Target:
    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "aoe2mr.synthetic.target"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
        )
        self.ready = self._read()

    def _read(self) -> dict[str, Any]:
        assert self.proc.stdout is not None
        result: dict[str, Any] = json.loads(self.proc.stdout.readline())
        return result

    def send(self, command: str) -> dict[str, Any]:
        assert self.proc.stdin is not None
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()
        return self._read()

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.send("quit")
            self.proc.wait(timeout=10)


@pytest.fixture
def target() -> Iterator[Target]:
    t = Target()
    try:
        yield t
    finally:
        t.stop()


@pytest.fixture
def backend():  # type: ignore[no-untyped-def]
    from aoe2mr.backends.windows import WindowsProcessBackend

    return WindowsProcessBackend()


def test_discovery_sees_synthetic_target(target: Target, backend) -> None:  # type: ignore[no-untyped-def]
    pid = target.ready["pid"]
    details = ProcessDiscovery(backend, DiscoveryConfig(("python.exe",))).describe(pid)
    assert details.access is AccessStatus.READ
    assert details.architecture is Architecture.X64
    assert details.executable_path and details.executable_path.lower().endswith(".exe")


def test_regions_and_read_only_value(target: Target, backend) -> None:  # type: ignore[no-untyped-def]
    pid, address = target.ready["pid"], target.ready["address"]
    wood = target.ready["layout"]["wood"]["offset"]
    inspector = RegionInspector(backend, RegionsConfig(min_region_size=0))
    report = inspector.inspect(pid)
    assert report.summary.region_count > 10 and report.summary.readable_bytes > 0

    region = inspector.find_region(pid, address)
    assert region is not None and region.state is MemoryState.COMMIT and region.is_readable

    with backend.open_read_only(pid) as proc:
        raw = proc.read(address, target.ready["size"])
        assert struct.unpack_from("<Q", raw, 0)[0] == MAGIC
        assert struct.unpack_from("<i", raw, wood)[0] == 200
        target.send("add wood 25")
        assert struct.unpack_from("<i", proc.read(address + wood, 4))[0] == 225


def test_exited_process(backend) -> None:  # type: ignore[no-untyped-def]
    t = Target()
    pid = t.ready["pid"]
    t.stop()
    with pytest.raises(ProcessNotFoundError):
        ProcessDiscovery(backend, DiscoveryConfig()).describe(pid)


def test_protected_system_process_is_not_readable(backend) -> None:  # type: ignore[no-untyped-def]
    details = ProcessDiscovery(backend, DiscoveryConfig()).describe(4)  # "System"
    assert details.access in (AccessStatus.DENIED, AccessStatus.QUERY_ONLY)
