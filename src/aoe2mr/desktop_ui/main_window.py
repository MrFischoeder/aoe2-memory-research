"""Main window: Process Monitor, Memory Research, Game State, Strategic Advisor, Logs.

Everything runs only while this window is open. The game watcher polls the process list (no
memory access) every few seconds until the game appears; heavy work runs in worker threads.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from aoe2mr import __version__
from aoe2mr.app_logging import LOGGER_NAME, get_logger
from aoe2mr.backends.base import ProcessBackend
from aoe2mr.concurrency import CancellationToken
from aoe2mr.config import AppConfig
from aoe2mr.desktop_ui.log_view import QtLogHandler
from aoe2mr.desktop_ui.workers import Worker
from aoe2mr.errors import ResearchError
from aoe2mr.memory_research.models import RegionReport
from aoe2mr.memory_research.regions import RegionInspector
from aoe2mr.persistence.json_store import ResultStore
from aoe2mr.process_discovery.discovery import ProcessDiscovery
from aoe2mr.process_discovery.models import AccessStatus, ProcessDetails
from aoe2mr.snapshot_analysis.models import CandidateSet, DataType, FilterKind, ValueFilter
from aoe2mr.snapshot_analysis.session import LiveValue, ResearchSession

log = get_logger("desktop_ui")

WATCH_INTERVAL_MS = 2000
MAX_REGION_ROWS = 2000
MAX_CANDIDATE_ROWS = 500
LIVE_ROWS = 200

FILTER_LABELS = {
    FilterKind.DISPLAYED: "value shown in game",
    FilterKind.EQUALS: "exact value",
    FilterKind.CHANGED: "changed",
    FilterKind.UNCHANGED: "unchanged",
    FilterKind.INCREASED: "increased",
    FilterKind.DECREASED: "decreased",
    FilterKind.INCREASED_BY: "increased by value",
    FilterKind.DECREASED_BY: "decreased by value",
}


def _fmt_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return str(n)


def _fmt_value(value: int | float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _readonly_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    mono = QFont("Consolas")
    mono.setStyleHint(QFont.StyleHint.Monospace)
    table.setFont(mono)
    return table


class MainWindow(QMainWindow):
    def __init__(self, backend: ProcessBackend, config: AppConfig,
                 attach_pid: int | None = None) -> None:
        super().__init__()
        self.backend = backend
        self.config = config
        self.discovery = ProcessDiscovery(backend, config.discovery)
        self.inspector = RegionInspector(backend, config.regions)
        self.store = ResultStore(config.persistence.data_dir)
        self.pool = QThreadPool.globalInstance()
        self.details: ProcessDetails | None = None
        self.session: ResearchSession | None = None
        self.busy: Worker | None = None
        self.live_busy = False
        self._live_worker: Worker | None = None

        # Destroy the C++ widget tree on close, before QApplication goes away; otherwise Python
        # reference cycles (signal lambdas) keep it alive until interpreter shutdown, which
        # crashes Qt.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"AoE2 Memory Research {__version__} (read-only)")
        self.resize(1150, 780)
        tabs = QTabWidget()
        tabs.addTab(self._build_process_tab(), "Process Monitor")
        tabs.addTab(self._build_research_tab(), "Memory Research")
        tabs.addTab(self._placeholder("Validated game state arrives in milestone M5.\n"
                                      "Nothing is shown until values are validated."),
                    "Game State")
        tabs.addTab(self._placeholder("Rule-based recommendations arrive in milestone M6."),
                    "Strategic Advisor")
        tabs.addTab(self._build_log_tab(), "Logs")
        self.tabs = tabs
        self.setCentralWidget(tabs)
        self.statusBar().showMessage("Read-only. Single-player only.")

        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(WATCH_INTERVAL_MS)
        self.watch_timer.timeout.connect(self._watch_tick)
        self.live_timer = QTimer(self)
        self.live_timer.setInterval(max(250, config.sampling.interval_ms))
        self.live_timer.timeout.connect(self._live_tick)

        if attach_pid is not None:
            self.attach(attach_pid)
        else:
            self._watch_tick()
        self.watch_timer.start()
        self._update_buttons()

    # ---------------------------------------------------------------- tab construction

    def _placeholder(self, text: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        label = QLabel(text)
        label.setWordWrap(True)
        lay.addWidget(label)
        lay.addStretch(1)
        return w

    def _build_process_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self.watch_label = QLabel()
        self.watch_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        lay.addWidget(self.watch_label)

        box = QGroupBox("Process")
        form = QFormLayout(box)
        self.info_labels: dict[str, QLabel] = {}
        for key in ("PID", "Name", "Executable", "Architecture", "Access", "Note",
                    "Tool elevated"):
            label = QLabel("-")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
            self.info_labels[key] = label
            form.addRow(key + ":", label)
        lay.addWidget(box)

        row = QHBoxLayout()
        row.addWidget(QLabel("Attach to another PID (e.g. the synthetic target):"))
        self.pid_spin = QSpinBox()
        self.pid_spin.setRange(0, 2**31 - 1)
        row.addWidget(self.pid_spin)
        self.attach_button = QPushButton("Attach")
        self.attach_button.clicked.connect(lambda: self.attach(self.pid_spin.value()))
        row.addWidget(self.attach_button)
        self.detach_button = QPushButton("Detach / watch for game")
        self.detach_button.clicked.connect(self.detach)
        row.addWidget(self.detach_button)
        row.addStretch(1)
        lay.addLayout(row)

        regions_box = QGroupBox("Memory regions")
        rlay = QVBoxLayout(regions_box)
        rrow = QHBoxLayout()
        self.refresh_regions_button = QPushButton("Refresh regions")
        self.refresh_regions_button.clicked.connect(self.refresh_regions)
        rrow.addWidget(self.refresh_regions_button)
        self.readable_only_check = QCheckBox("Readable only")
        self.readable_only_check.setChecked(True)
        rrow.addWidget(self.readable_only_check)
        self.region_summary = QLabel("-")
        self.region_summary.setWordWrap(True)
        rrow.addWidget(self.region_summary, 1)
        rlay.addLayout(rrow)
        self.region_table = _readonly_table(["Base", "Size", "State", "Type", "Protect",
                                             "Readable"])
        rlay.addWidget(self.region_table)
        lay.addWidget(regions_box, 1)
        return w

    def _build_research_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        help_label = QLabel(
            "<b>How to find a value</b> (e.g. wood): type the number the game shows, "
            "click <b>New scan</b>. Change it in game (gather wood), type the new number, "
            "click <b>Next scan</b>. Repeat until a few candidates remain, then tick "
            "<b>Live values</b>. Resources are usually <b>float32</b>; try int32 if nothing "
            "is found."
        )
        help_label.setWordWrap(True)
        lay.addWidget(help_label)

        scan_box = QGroupBox("Search")
        grid = QVBoxLayout(scan_box)
        grow = QHBoxLayout()
        grow.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        for dt in DataType:
            self.type_combo.addItem(dt.value, dt.value)
        self.type_combo.setCurrentText(DataType.FLOAT32.value)
        grow.addWidget(self.type_combo)
        grow.addWidget(QLabel("Filter:"))
        self.filter_combo = QComboBox()
        for kind, text in FILTER_LABELS.items():
            self.filter_combo.addItem(text, kind.value)
        self.filter_combo.currentIndexChanged.connect(self._update_buttons)
        grow.addWidget(self.filter_combo)
        grow.addWidget(QLabel("Value:"))
        self.value_edit = QLineEdit()
        self.value_edit.setMaximumWidth(110)
        self.value_edit.setPlaceholderText("e.g. 207")
        self.value_edit.returnPressed.connect(self._enter_pressed)
        grow.addWidget(self.value_edit)
        grow.addWidget(QLabel("Tolerance:"))
        self.tolerance_edit = QLineEdit("0")
        self.tolerance_edit.setMaximumWidth(60)
        grow.addWidget(self.tolerance_edit)
        grow.addStretch(1)
        grid.addLayout(grow)

        brow = QHBoxLayout()
        self.new_scan_button = QPushButton("New scan")
        self.new_scan_button.setToolTip("Snapshot the game's memory and search it. With "
                                        "'changed'/'increased'/... only a baseline is taken.")
        self.new_scan_button.clicked.connect(self.new_scan)
        brow.addWidget(self.new_scan_button)
        self.next_scan_button = QPushButton("Next scan")
        self.next_scan_button.setToolTip("Re-read the current candidates (fast) and keep "
                                         "those that match the filter.")
        self.next_scan_button.clicked.connect(self.next_scan)
        brow.addWidget(self.next_scan_button)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset_candidates)
        brow.addWidget(self.reset_button)
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        brow.addWidget(self.progress)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_work)
        brow.addWidget(self.cancel_button)
        brow.addStretch(1)
        brow.addWidget(QLabel("Snapshot limit (MiB):"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(64, 16384)
        self.limit_spin.setSingleStep(512)
        self.limit_spin.setValue(self.config.sampling.max_snapshot_bytes // 2**20)
        self.limit_spin.setToolTip("Upper bound on memory read by one snapshot. The timeline "
                                   "says TRUNCATED when the game had more.")
        brow.addWidget(self.limit_spin)
        grid.addLayout(brow)
        lay.addWidget(scan_box)

        split = QSplitter()
        cand_box = QGroupBox("Candidates")
        clay = QVBoxLayout(cand_box)
        crow = QHBoxLayout()
        self.candidate_label = QLabel("No candidates.")
        crow.addWidget(self.candidate_label, 1)
        self.live_check = QCheckBox("Live values")
        self.live_check.setToolTip(f"Re-read the first {LIVE_ROWS} candidates every "
                                   f"{self.config.sampling.interval_ms} ms while checked")
        self.live_check.toggled.connect(self._toggle_live)
        crow.addWidget(self.live_check)
        clay.addLayout(crow)
        self.candidate_table = _readonly_table(["Address", "Type", "At last scan", "Live"])
        clay.addWidget(self.candidate_table)
        split.addWidget(cand_box)

        tl_box = QGroupBox("Timeline and notes")
        tlay = QVBoxLayout(tl_box)
        self.timeline_list = QListWidget()
        tlay.addWidget(self.timeline_list)
        nrow = QHBoxLayout()
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText("experiment note, e.g. 'expected wood = 225'")
        self.note_edit.returnPressed.connect(self.add_note)
        nrow.addWidget(self.note_edit, 1)
        self.note_button = QPushButton("Add note")
        self.note_button.clicked.connect(self.add_note)
        nrow.addWidget(self.note_button)
        tlay.addLayout(nrow)
        self.save_button = QPushButton("Save session to research_data")
        self.save_button.clicked.connect(self.save_session)
        tlay.addWidget(self.save_button)
        split.addWidget(tl_box)
        split.setSizes([700, 420])
        lay.addWidget(split, 1)
        return w

    def _build_log_tab(self) -> QWidget:
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_handler = QtLogHandler()
        self.log_handler.bridge.message.connect(self.log_view.appendPlainText)
        logging.getLogger(LOGGER_NAME).addHandler(self.log_handler)
        return self.log_view

    # ---------------------------------------------------------------- process watching

    def _set_watch_text(self, text: str, ok: bool | None = None) -> None:
        color = {True: "#1a7f37", False: "#b42318", None: "#9a6700"}[ok]
        self.watch_label.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {color};")
        self.watch_label.setText(text)

    def _watch_tick(self) -> None:
        try:
            if self.details is not None:
                alive = any(e.pid == self.details.pid for e in self.backend.list_processes())
                if not alive:
                    log.info("Process %d exited", self.details.pid)
                    self.detach(message=f"Process {self.details.pid} exited. Watching for the "
                                        "game...")
                return
            targets = self.discovery.find_targets()
        except ResearchError as exc:
            self._set_watch_text(f"Process watching unavailable: {exc}", False)
            self.watch_timer.stop()
            return
        if targets:
            self._show_details(targets[0])
        else:
            names = ", ".join(self.config.discovery.target_executables)
            self._set_watch_text(f"Waiting for the game ({names})... start a single-player "
                                 "game; this window will attach automatically.")

    def attach(self, pid: int) -> None:
        try:
            details = self.discovery.describe(pid)
        except ResearchError as exc:
            QMessageBox.warning(self, "Attach failed", str(exc))
            return
        self._show_details(details)

    def detach(self, *_: Any, message: str = "Detached. Watching for the game...") -> None:
        self.cancel_work()
        self.live_check.setChecked(False)
        self.details = None
        self.session = None
        for label in self.info_labels.values():
            label.setText("-")
        self.region_table.setRowCount(0)
        self.region_summary.setText("-")
        self._refresh_candidates(None)
        self.timeline_list.clear()
        self._set_watch_text(message)
        self._update_buttons()

    def _show_details(self, d: ProcessDetails) -> None:
        self.details = d
        info = self.info_labels
        info["PID"].setText(str(d.pid))
        info["Name"].setText(d.name + ("  [game]" if d.is_target else ""))
        info["Executable"].setText(d.executable_path or "UNKNOWN")
        info["Architecture"].setText(d.architecture.value)
        info["Access"].setText(d.access.value)
        info["Note"].setText(d.access_error or "-")
        elevated = self.backend.is_elevated()
        info["Tool elevated"].setText("UNKNOWN" if elevated is None else str(elevated))
        if d.access is AccessStatus.READ:
            self.session = ResearchSession(self.backend, d.pid, self.config.regions,
                                           self.config.sampling)
            self._set_watch_text(f"Attached to {d.name} (PID {d.pid}), read-only.", True)
            self.refresh_regions()
        else:
            self.session = None
            self._set_watch_text(f"Found {d.name} (PID {d.pid}) but read access is "
                                 f"{d.access.value}. Run the game and this tool at the same "
                                 "privilege level (normally neither as administrator).", False)
        self._update_buttons()

    # ---------------------------------------------------------------- background work

    def _run(self, fn: Callable[[CancellationToken, Callable[[int, int], None]], Any],
             done: Callable[[Any], None], description: str) -> None:
        if self.busy is not None:
            return
        worker = Worker(fn)
        self.busy = worker
        self.progress.setRange(0, 0)
        self.statusBar().showMessage(description + "...")

        def finish() -> None:
            self.busy = None
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
            self._update_buttons()

        def ok(result: Any) -> None:
            finish()
            self.statusBar().showMessage(description + ": done", 5000)
            done(result)

        def failed(message: str) -> None:
            finish()
            log.error("%s failed: %s", description, message)
            self.statusBar().showMessage(f"{description} failed: {message.splitlines()[0]}")

        def cancelled() -> None:
            finish()
            self.statusBar().showMessage(description + ": cancelled", 5000)

        def progress(done_bytes: int, total: int) -> None:
            if total > 0:
                self.progress.setRange(0, 1000)
                self.progress.setValue(int(1000 * done_bytes / total))

        worker.signals.finished.connect(ok)
        worker.signals.failed.connect(failed)
        worker.signals.cancelled.connect(cancelled)
        worker.signals.progress.connect(progress)
        self._update_buttons()
        self.pool.start(worker)

    def cancel_work(self) -> None:
        if self.busy is not None:
            self.busy.token.cancel()

    def refresh_regions(self) -> None:
        if self.details is None:
            return
        pid = self.details.pid
        readable_only = self.readable_only_check.isChecked()
        self._run(lambda token, _p: self.inspector.inspect(pid, readable_only=readable_only,
                                                            cancel=token),
                  self._show_regions, "Region inspection")

    def _show_regions(self, report: RegionReport) -> None:
        s = report.summary
        self.region_summary.setText(
            f"{s.region_count} regions, {_fmt_bytes(s.total_bytes)} total, "
            f"{_fmt_bytes(s.readable_bytes)} readable "
            f"({_fmt_bytes(s.writable_readable_bytes)} writable by the game)"
            + (" - TRUNCATED" if report.truncated else "")
        )
        rows = report.regions[:MAX_REGION_ROWS]
        self.region_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, text in enumerate((f"0x{r.base_address:016X}", _fmt_bytes(r.size),
                                      r.state.value, r.type.value, r.protect.label,
                                      "yes" if r.is_readable else "no")):
                self.region_table.setItem(i, j, QTableWidgetItem(text))
        self.region_table.resizeColumnsToContents()

    def _current_filter(self) -> tuple[DataType, ValueFilter] | None:
        dt = DataType(self.type_combo.currentData())
        kind = FilterKind(self.filter_combo.currentData())
        try:
            text = self.value_edit.text().strip().replace(",", ".")
            if kind.needs_operand and not text:
                raise ValueError("enter a value")
            operand = dt.coerce(text) if kind.needs_operand else None
            tolerance = float(self.tolerance_edit.text().replace(",", ".") or 0)
            if tolerance < 0:
                raise ValueError("tolerance must be >= 0")
            return dt, ValueFilter(kind, operand, tolerance)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid search", str(exc))
            return None

    def _apply_limit(self) -> None:
        if self.session is not None:
            self.session.set_snapshot_limit(self.limit_spin.value() * 2**20)

    def new_scan(self) -> None:
        session = self.session
        parsed = self._current_filter()
        if session is None or parsed is None:
            return
        self._apply_limit()
        dt, value_filter = parsed
        self._run(lambda token, progress: session.new_scan(dt, value_filter, cancel=token,
                                                           progress=progress),
                  lambda _c: self._after_session_change(), "New scan")

    def next_scan(self) -> None:
        session = self.session
        parsed = self._current_filter()
        if session is None or parsed is None:
            return
        self._apply_limit()
        dt, value_filter = parsed
        self._run(lambda token, progress: session.next_scan(value_filter, data_type=dt,
                                                            cancel=token, progress=progress),
                  lambda _c: self._after_session_change(), "Next scan")

    def _enter_pressed(self) -> None:
        if self.next_scan_button.isEnabled():
            self.next_scan()
        elif self.new_scan_button.isEnabled():
            self.new_scan()

    def reset_candidates(self) -> None:
        if self.session is not None:
            self.session.reset()
            self._after_session_change()

    def add_note(self) -> None:
        text = self.note_edit.text().strip()
        if self.session is not None and text:
            self.session.annotate(text)
            self.note_edit.clear()
            self._after_session_change()

    def save_session(self) -> None:
        if self.session is None or self.details is None:
            return
        record = self.session.to_record()
        record["process"] = self.details
        try:
            path = self.store.save("research_session", record)
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        log.info("Session saved to %s", path)
        self.statusBar().showMessage(f"Saved {path}", 8000)

    # ---------------------------------------------------------------- candidates and live view

    def _after_session_change(self) -> None:
        session = self.session
        if session is None:
            return
        self.timeline_list.clear()
        for e in session.timeline:
            count = "" if e.candidate_count is None else f"  [{e.candidate_count:,} candidates]"
            self.timeline_list.addItem(f"{e.at:%H:%M:%S}  {e.kind:<10} {e.message}{count}")
        self.timeline_list.scrollToBottom()
        self._refresh_candidates(session.candidates)
        self._update_buttons()

    def _refresh_candidates(self, cand: CandidateSet | None) -> None:
        if cand is None:
            self.candidate_label.setText("No candidates. Take a snapshot, then search.")
            self.candidate_table.setRowCount(0)
            return
        shown = min(len(cand), MAX_CANDIDATE_ROWS)
        more = "" if shown == len(cand) else f" (showing first {shown})"
        trunc = " - search stopped at the candidate cap" if cand.truncated else ""
        self.candidate_label.setText(f"{len(cand):,} candidates{more}{trunc}")
        self.candidate_table.setRowCount(shown)
        for i, (address, value) in enumerate(cand.items(shown)):
            self.candidate_table.setItem(i, 0, QTableWidgetItem(f"0x{address:016X}"))
            self.candidate_table.setItem(i, 1, QTableWidgetItem(cand.data_type.value))
            self.candidate_table.setItem(i, 2, QTableWidgetItem(_fmt_value(value)))
            self.candidate_table.setItem(i, 3, QTableWidgetItem(""))
        self.candidate_table.resizeColumnsToContents()

    def _toggle_live(self, on: bool) -> None:
        if on:
            self.live_timer.start()
            log.info("Live value refresh started (%d ms)", self.live_timer.interval())
        else:
            self.live_timer.stop()

    def _live_tick(self) -> None:
        session = self.session
        if session is None or session.candidates is None or self.live_busy:
            return
        self.live_busy = True
        worker = Worker(lambda _t, _p: session.read_live(LIVE_ROWS))

        def show(values: list[LiveValue]) -> None:
            self.live_busy = False
            for i, lv in enumerate(values[: self.candidate_table.rowCount()]):
                self.candidate_table.setItem(i, 3, QTableWidgetItem(_fmt_value(lv.value)))

        def failed(message: str) -> None:
            self.live_busy = False
            log.warning("Live read failed: %s", message.splitlines()[0])

        worker.signals.finished.connect(show)
        worker.signals.failed.connect(failed)
        self._live_worker = worker  # keep the Python wrapper (and its signals) alive
        self.pool.start(worker)

    # ---------------------------------------------------------------- state

    def _update_buttons(self) -> None:
        idle = self.busy is None
        attached = self.session is not None
        waiting = self.session is not None and self.session.awaiting_next_scan
        data = self.filter_combo.currentData()
        kind = FilterKind(data) if data is not None else None
        self.value_edit.setEnabled(kind is not None and kind.needs_operand)
        self.refresh_regions_button.setEnabled(idle and self.details is not None)
        self.new_scan_button.setEnabled(idle and attached)
        self.next_scan_button.setEnabled(idle and waiting)
        self.reset_button.setEnabled(idle and attached)
        self.note_button.setEnabled(attached)
        self.save_button.setEnabled(attached)
        self.cancel_button.setEnabled(not idle)
        self.attach_button.setEnabled(idle)
        self.detach_button.setEnabled(self.details is not None)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.watch_timer.stop()
        self.live_timer.stop()
        self.cancel_work()
        self.pool.waitForDone(5000)
        logging.getLogger(LOGGER_NAME).removeHandler(self.log_handler)
        super().closeEvent(event)
