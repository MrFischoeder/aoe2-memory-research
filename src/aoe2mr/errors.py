"""Exception hierarchy shared by all modules."""

from __future__ import annotations


class ResearchError(Exception):
    """Base class for all errors raised by this application."""


class UnsupportedPlatformError(ResearchError):
    """Raised when a Windows-only operation is attempted on another platform."""


class ProcessNotFoundError(ResearchError):
    """Raised when the requested process does not exist (or has exited)."""

    def __init__(self, pid: int, detail: str = "") -> None:
        self.pid = pid
        super().__init__(f"Process {pid} not found" + (f": {detail}" if detail else ""))


class AccessDeniedError(ResearchError):
    """Raised when Windows refuses the requested read-only access.

    The application never attempts to bypass this (no debug privileges, no drivers).
    """

    def __init__(self, pid: int, operation: str, winerror: int | None = None) -> None:
        self.pid = pid
        self.operation = operation
        self.winerror = winerror
        code = f" (Win32 error {winerror})" if winerror is not None else ""
        super().__init__(f"Access denied for {operation} on process {pid}{code}")


class MemoryReadError(ResearchError):
    """Raised when a read of another process's memory fails or is partial."""

    def __init__(self, pid: int, address: int, size: int, detail: str) -> None:
        self.pid = pid
        self.address = address
        self.size = size
        super().__init__(f"Cannot read {size} bytes at 0x{address:X} in process {pid}: {detail}")


class ForbiddenAccessRequestError(ResearchError):
    """Raised when code requests a process access right outside the read-only allowlist."""
