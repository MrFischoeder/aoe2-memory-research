"""Desktop entry point: ``aoe2mr-gui`` or ``python -m aoe2mr.desktop_ui``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from aoe2mr.app_logging import configure_logging
from aoe2mr.backends import create_default_backend
from aoe2mr.config import ConfigError, load_config
from aoe2mr.errors import UnsupportedPlatformError


def default_data_dir() -> Path:
    """Next to the .exe when frozen, otherwise the current directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "research_data"
    return Path("research_data")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aoe2mr-gui", description="AoE2 memory research UI")
    parser.add_argument("--config", type=Path, help="user TOML config overriding defaults")
    parser.add_argument("--pid", type=int, help="attach to this PID instead of waiting for AoE2")
    args = parser.parse_args(argv)

    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QMessageBox

    from aoe2mr.desktop_ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        QMessageBox.critical(None, "Configuration error", str(exc))
        return 1
    if args.config is None and config.persistence.data_dir == Path("research_data"):
        from dataclasses import replace

        config = replace(config, persistence=replace(config.persistence,
                                                     data_dir=default_data_dir()))
    configure_logging(config.logging, config.persistence.data_dir / "logs")
    try:
        backend = create_default_backend()
    except UnsupportedPlatformError as exc:
        QMessageBox.critical(None, "Unsupported platform", str(exc))
        return 1
    window = MainWindow(backend, config, attach_pid=args.pid)
    window.show()
    code = int(app.exec())
    # Make sure no widget outlives the event loop (see MainWindow WA_DeleteOnClose).
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    return code
