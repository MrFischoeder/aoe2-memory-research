"""Process discovery: list processes, find AoE2 DE, and report the access obtained."""

from __future__ import annotations

from aoe2mr.app_logging import get_logger
from aoe2mr.backends.base import ProcessBackend
from aoe2mr.config import DiscoveryConfig
from aoe2mr.errors import AccessDeniedError, ProcessNotFoundError
from aoe2mr.process_discovery.models import (
    AccessStatus,
    Architecture,
    ProcessDetails,
    ProcessEntry,
)

log = get_logger("process_discovery")


class ProcessDiscovery:
    def __init__(self, backend: ProcessBackend, config: DiscoveryConfig) -> None:
        self._backend = backend
        self._targets = {name.casefold() for name in config.target_executables}

    def is_target_name(self, name: str) -> bool:
        return name.casefold() in self._targets

    def list_processes(self, name_filter: str | None = None) -> list[ProcessEntry]:
        entries = self._backend.list_processes()
        if name_filter:
            needle = name_filter.casefold()
            entries = [e for e in entries if needle in e.name.casefold()]
        return sorted(entries, key=lambda e: (e.name.casefold(), e.pid))

    def find_targets(self) -> list[ProcessDetails]:
        """Return details for every running process whose executable name is a target."""
        found = [e for e in self._backend.list_processes() if self.is_target_name(e.name)]
        log.info("Found %d target process(es)", len(found))
        return [self.describe_entry(e) for e in found]

    def describe(self, pid: int) -> ProcessDetails:
        for entry in self._backend.list_processes():
            if entry.pid == pid:
                return self.describe_entry(entry)
        raise ProcessNotFoundError(pid)

    def describe_entry(self, entry: ProcessEntry) -> ProcessDetails:
        """Probe access step by step. Denials are recorded, never worked around."""
        is_target = self.is_target_name(entry.name)
        try:
            path, arch = self._backend.identify(entry.pid)
        except AccessDeniedError as exc:
            log.warning("Identification denied for pid %d: %s", entry.pid, exc)
            return ProcessDetails(entry, None, Architecture.UNKNOWN, AccessStatus.DENIED,
                                  str(exc), is_target)
        except ProcessNotFoundError as exc:
            return ProcessDetails(entry, None, Architecture.UNKNOWN, AccessStatus.EXITED,
                                  str(exc), is_target)

        try:
            with self._backend.open_read_only(entry.pid):
                pass
        except AccessDeniedError as exc:
            log.warning("Read-only access denied for pid %d: %s", entry.pid, exc)
            return ProcessDetails(entry, path, arch, AccessStatus.QUERY_ONLY, str(exc),
                                  is_target)
        except ProcessNotFoundError as exc:
            return ProcessDetails(entry, path, arch, AccessStatus.EXITED, str(exc), is_target)

        return ProcessDetails(entry, path, arch, AccessStatus.READ, None, is_target)
