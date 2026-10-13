"""Smoke tests of the desktop window against the fake backend (offscreen Qt)."""

from __future__ import annotations

import os
import struct
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from aoe2mr.backends.fake import FakeProcessBackend
from aoe2mr.config import AppConfig, PersistenceConfig, RegionsConfig
from aoe2mr.desktop_ui.main_window import MainWindow
from aoe2mr.snapshot_analysis.models import FilterKind
from tests.conftest import AOE_PID


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


def close_window(w: MainWindow) -> None:
    w.close()  # WA_DeleteOnClose: destroyed on the next DeferredDelete pass
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def wait_until(app: QApplication, condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


@pytest.fixture
def window(qapp: QApplication, fake_backend: FakeProcessBackend,
           tmp_path: Path) -> Iterator[MainWindow]:
    cfg = AppConfig(regions=RegionsConfig(min_region_size=0),
                    persistence=PersistenceConfig(data_dir=tmp_path))
    w = MainWindow(fake_backend, cfg)
    yield w
    close_window(w)


def set_wood(backend: FakeProcessBackend, value: int) -> None:
    mem = bytearray(backend.processes[AOE_PID].memory[0x20000])
    struct.pack_into("<i", mem, 0x40, value)
    backend.processes[AOE_PID].memory[0x20000] = bytes(mem)


def test_auto_attaches_to_game_and_lists_regions(qapp: QApplication,
                                                 window: MainWindow) -> None:
    assert window.details is not None and window.details.pid == AOE_PID
    assert "Attached" in window.watch_label.text()
    wait_until(qapp, lambda: window.region_table.rowCount() > 0)
    assert window.region_table.rowCount() == 4  # readable-only by default (guard page hidden)


def test_full_search_workflow(qapp: QApplication, window: MainWindow,
                              fake_backend: FakeProcessBackend, tmp_path: Path) -> None:
    wait_until(qapp, lambda: window.busy is None)
    set_wood(fake_backend, 777_777)
    window.type_combo.setCurrentText("int32")
    window.filter_combo.setCurrentIndex(window.filter_combo.findData(FilterKind.EQUALS.value))
    window.value_edit.setText("777777")
    window.new_scan()
    wait_until(qapp, lambda: window.busy is None and window.session is not None
               and window.session.candidates is not None)
    assert window.candidate_table.rowCount() == 1
    assert window.next_scan_button.isEnabled()

    set_wood(fake_backend, 777_800)
    window.filter_combo.setCurrentIndex(window.filter_combo.findData(FilterKind.INCREASED_BY.value))
    window.value_edit.setText("23")
    window.next_scan()  # reads only the candidate addresses
    wait_until(qapp, lambda: window.busy is None and window.timeline_list.count() == 3)
    assert window.candidate_table.item(0, 0).text() == f"0x{0x20040:016X}"
    assert window.candidate_table.item(0, 2).text() == "777800"

    window._live_tick()
    wait_until(qapp, lambda: window.candidate_table.item(0, 3).text() == "777800")

    window.note_edit.setText("gathered 23 wood")
    window.add_note()
    window.save_session()
    saved = list((tmp_path / "research_session").glob("*.json"))
    assert len(saved) == 1


def test_detects_game_exit(qapp: QApplication, window: MainWindow,
                           fake_backend: FakeProcessBackend) -> None:
    wait_until(qapp, lambda: window.busy is None)
    del fake_backend.processes[AOE_PID]
    window._watch_tick()
    assert window.details is None and window.session is None
    assert "exited" in window.watch_label.text()


def test_waits_when_no_game(qapp: QApplication, tmp_path: Path) -> None:
    w = MainWindow(FakeProcessBackend([]), AppConfig(
        persistence=PersistenceConfig(data_dir=tmp_path)))
    try:
        assert w.details is None and "Waiting for the game" in w.watch_label.text()
        assert not w.new_scan_button.isEnabled()
    finally:
        close_window(w)


def test_denied_process_is_not_researched(qapp: QApplication, window: MainWindow) -> None:
    wait_until(qapp, lambda: window.busy is None)
    window.attach(777)
    assert window.session is None and "query_only" in window.watch_label.text()
