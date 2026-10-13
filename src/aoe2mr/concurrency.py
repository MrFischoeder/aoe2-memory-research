"""Cooperative cancellation primitives for background work."""

from __future__ import annotations

import threading


class OperationCancelledError(Exception):
    """Raised when a long-running operation observes a cancellation request."""


class CancellationToken:
    """Thread-safe flag checked periodically by long-running operations."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OperationCancelledError("Operation cancelled by user")
