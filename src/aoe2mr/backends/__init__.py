"""Data-source backends. Only read-only operations are exposed.

Interfaces live in :mod:`aoe2mr.backends.base`. This module intentionally imports nothing
eagerly so that the pure constant/model modules can be imported without cycles.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aoe2mr.errors import UnsupportedPlatformError

if TYPE_CHECKING:
    from aoe2mr.backends.base import ProcessBackend

__all__ = ["create_default_backend"]


def create_default_backend() -> ProcessBackend:
    """Return the backend for the current platform (only Windows is supported)."""
    if sys.platform != "win32":
        raise UnsupportedPlatformError(
            "Process inspection requires Windows; use FakeProcessBackend for tests"
        )
    from aoe2mr.backends.windows import WindowsProcessBackend

    return WindowsProcessBackend()
