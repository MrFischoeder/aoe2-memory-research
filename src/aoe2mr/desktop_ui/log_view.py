"""Forward ``aoe2mr`` log records into a Qt widget."""

from __future__ import annotations

import contextlib
import logging

from PySide6.QtCore import QObject, Signal


class QtLogBridge(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.bridge = QtLogBridge()
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                                            "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        with contextlib.suppress(RuntimeError):  # widget destroyed during shutdown
            self.bridge.message.emit(self.format(record))
