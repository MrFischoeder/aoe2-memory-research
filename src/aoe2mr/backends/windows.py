"""Windows implementation of :class:`ProcessBackend` using read-only Win32 APIs."""

from __future__ import annotations

from collections.abc import Iterator

from aoe2mr.backends.win32 import api
from aoe2mr.backends.win32 import constants as c
from aoe2mr.backends.win32.access import IDENTIFY_ACCESS, READ_ACCESS
from aoe2mr.errors import AccessDeniedError, MemoryReadError, ProcessNotFoundError
from aoe2mr.memory_research.models import MemoryRegion
from aoe2mr.process_discovery.models import Architecture, ProcessEntry

_MACHINE_TO_ARCH = {
    c.IMAGE_FILE_MACHINE_I386: Architecture.X86,
    c.IMAGE_FILE_MACHINE_AMD64: Architecture.X64,
    c.IMAGE_FILE_MACHINE_ARMNT: Architecture.ARM,
    c.IMAGE_FILE_MACHINE_ARM64: Architecture.ARM64,
}


def architecture_from_machine(info: api.MachineInfo) -> Architecture:
    machine = info.process_machine
    if machine == c.IMAGE_FILE_MACHINE_UNKNOWN:  # not WOW64: native architecture
        machine = info.native_machine
    return _MACHINE_TO_ARCH.get(machine, Architecture.UNKNOWN)


def _open(pid: int, access: int, operation: str) -> api.ProcessHandle:
    try:
        return api.ProcessHandle(pid, access)
    except api.Win32Error as exc:
        if exc.code == c.ERROR_ACCESS_DENIED:
            raise AccessDeniedError(pid, operation, exc.code) from exc
        if exc.code == c.ERROR_INVALID_PARAMETER:  # OpenProcess: no such PID
            raise ProcessNotFoundError(pid) from exc
        raise


class WindowsReadOnlyProcess:
    def __init__(self, handle: api.ProcessHandle) -> None:
        self._handle = handle
        self.pid = handle.pid

    def iter_regions(self, max_regions: int) -> Iterator[MemoryRegion]:
        for raw in api.iterate_regions(self._handle, max_regions):
            yield MemoryRegion.from_raw(
                raw.base_address, raw.size, raw.allocation_base, raw.allocation_protect,
                raw.state, raw.protect, raw.type,
            )

    def read(self, address: int, size: int) -> bytes:
        if size <= 0:
            raise ValueError("size must be positive")
        data, err = api.read_memory(self._handle, address, size)
        if len(data) != size:
            detail = "partial copy" if err == c.ERROR_PARTIAL_COPY else f"Win32 error {err}"
            raise MemoryReadError(self.pid, address, size, detail)
        return data

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> WindowsReadOnlyProcess:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class WindowsProcessBackend:
    def list_processes(self) -> list[ProcessEntry]:
        return [
            ProcessEntry(pid=e.pid, parent_pid=e.parent_pid, name=e.name,
                         thread_count=e.thread_count)
            for e in api.enumerate_processes()
        ]

    def identify(self, pid: int) -> tuple[str | None, Architecture]:
        with _open(pid, IDENTIFY_ACCESS, "identify") as handle:
            try:
                path: str | None = api.query_image_path(handle)
            except api.Win32Error:
                path = None
            try:
                arch = architecture_from_machine(api.query_machine(handle))
            except api.Win32Error:
                arch = Architecture.UNKNOWN
            return path, arch

    def open_read_only(self, pid: int) -> WindowsReadOnlyProcess:
        return WindowsReadOnlyProcess(_open(pid, READ_ACCESS, "read-only memory query"))

    def is_elevated(self) -> bool | None:
        return api.is_user_admin()
