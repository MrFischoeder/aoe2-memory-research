"""Typed models describing processes and the access this tool obtained to them."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Architecture(StrEnum):
    X86 = "x86"
    X64 = "x64"
    ARM = "arm"
    ARM64 = "arm64"
    UNKNOWN = "unknown"


class AccessStatus(StrEnum):
    """How much read-only access Windows granted to this tool for a process."""

    READ = "read"  # region query + memory read granted
    QUERY_ONLY = "query_only"  # identification only (path, architecture)
    DENIED = "denied"  # even limited query refused (e.g. protected or elevated process)
    EXITED = "exited"  # process disappeared during inspection
    UNSUPPORTED = "unsupported"  # not running on Windows


@dataclass(frozen=True)
class ProcessEntry:
    """A row from the system process list (no handle required)."""

    pid: int
    parent_pid: int
    name: str
    thread_count: int


@dataclass(frozen=True)
class ProcessDetails:
    """A process plus everything learned about it with read-only access."""

    entry: ProcessEntry
    executable_path: str | None
    architecture: Architecture
    access: AccessStatus
    access_error: str | None
    is_target: bool

    @property
    def pid(self) -> int:
        return self.entry.pid

    @property
    def name(self) -> str:
        return self.entry.name
