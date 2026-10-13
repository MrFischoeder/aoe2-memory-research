"""Backend interfaces. Services depend on these protocols, never on Win32 directly.

This keeps discovery and region inspection testable with :mod:`aoe2mr.backends.fake` and
leaves room for other data sources (replay parsing, screen observation) later.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from aoe2mr.memory_research.models import MemoryRegion
from aoe2mr.process_discovery.models import Architecture, ProcessEntry


class ReadOnlyProcess(Protocol):
    """An open read-only view of one process."""

    pid: int

    def iter_regions(self, max_regions: int) -> Iterator[MemoryRegion]: ...

    def read(self, address: int, size: int) -> bytes:
        """Read exactly ``size`` bytes or raise :class:`aoe2mr.errors.MemoryReadError`."""
        ...

    def close(self) -> None: ...

    def __enter__(self) -> ReadOnlyProcess: ...

    def __exit__(self, *exc: object) -> None: ...


class ProcessBackend(Protocol):
    """Operating-system access needed by M1. All operations are read-only."""

    def list_processes(self) -> list[ProcessEntry]: ...

    def identify(self, pid: int) -> tuple[str | None, Architecture]:
        """Return ``(executable_path, architecture)`` using limited query rights.

        Raises ``ProcessNotFoundError`` or ``AccessDeniedError``.
        """
        ...

    def open_read_only(self, pid: int) -> ReadOnlyProcess:
        """Open the process for region queries and reads.

        Raises ``ProcessNotFoundError`` or ``AccessDeniedError``.
        """
        ...

    def is_elevated(self) -> bool | None: ...
