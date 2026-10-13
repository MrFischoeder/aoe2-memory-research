"""In-memory backend for tests and offline development. Simulates processes and regions."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from aoe2mr.errors import AccessDeniedError, MemoryReadError, ProcessNotFoundError
from aoe2mr.memory_research.models import MemoryRegion
from aoe2mr.process_discovery.models import Architecture, ProcessEntry


@dataclass
class FakeProcess:
    entry: ProcessEntry
    path: str | None = None
    architecture: Architecture = Architecture.X64
    identify_denied: bool = False
    read_denied: bool = False
    regions: list[MemoryRegion] = field(default_factory=list)
    memory: dict[int, bytes] = field(default_factory=dict)  # region base -> contents


class FakeReadOnlyProcess:
    def __init__(self, proc: FakeProcess) -> None:
        self._proc = proc
        self.pid = proc.entry.pid
        self.closed = False

    def iter_regions(self, max_regions: int) -> Iterator[MemoryRegion]:
        yield from self._proc.regions[:max_regions]

    def read(self, address: int, size: int) -> bytes:
        for region in self._proc.regions:
            if region.contains(address) and region.is_readable:
                data = self._proc.memory.get(region.base_address, b"\x00" * region.size)
                offset = address - region.base_address
                chunk = data[offset: offset + size]
                if len(chunk) == size:
                    return chunk
        raise MemoryReadError(self.pid, address, size, "not readable in fake process")

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FakeReadOnlyProcess:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FakeProcessBackend:
    def __init__(self, processes: list[FakeProcess] | None = None,
                 elevated: bool | None = False) -> None:
        self.processes = {p.entry.pid: p for p in processes or []}
        self.elevated = elevated
        self.opened: list[FakeReadOnlyProcess] = []

    def _get(self, pid: int) -> FakeProcess:
        try:
            return self.processes[pid]
        except KeyError:
            raise ProcessNotFoundError(pid) from None

    def list_processes(self) -> list[ProcessEntry]:
        return [p.entry for p in self.processes.values()]

    def identify(self, pid: int) -> tuple[str | None, Architecture]:
        proc = self._get(pid)
        if proc.identify_denied:
            raise AccessDeniedError(pid, "identify", 5)
        return proc.path, proc.architecture

    def open_read_only(self, pid: int) -> FakeReadOnlyProcess:
        proc = self._get(pid)
        if proc.read_denied or proc.identify_denied:
            raise AccessDeniedError(pid, "read-only memory query", 5)
        handle = FakeReadOnlyProcess(proc)
        self.opened.append(handle)
        return handle

    def is_elevated(self) -> bool | None:
        return self.elevated
