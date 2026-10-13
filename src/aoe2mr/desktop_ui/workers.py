"""Run blocking research operations off the GUI thread."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

from aoe2mr.concurrency import CancellationToken, OperationCancelledError
from aoe2mr.errors import ResearchError


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(int, int)


class Worker(QRunnable):
    """Calls ``fn(token, progress)`` in a pool thread and reports through Qt signals."""

    def __init__(self, fn: Callable[[CancellationToken, Callable[[int, int], None]], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.token = CancellationToken()
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn(self.token, self.signals.progress.emit)
        except OperationCancelledError:
            self.signals.cancelled.emit()
        except ResearchError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:  # report, never crash the GUI thread
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
        else:
            self.signals.finished.emit(result)
