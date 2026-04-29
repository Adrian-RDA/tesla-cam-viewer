from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from core.event import TeslaEvent
from core.scanner import Scanner
from core.sync_controller import SyncController
from ui.event_list import EventList
from ui.grid_view import GridView
from ui.icons import make_icon
from ui.timeline import Timeline

_HERE = Path(__file__).parent.parent
_DEFAULT_CLIPS_PATH = Path("D:/TeslaCam/SavedClips")
_SIDEBAR_DEFAULT_W = 195
_SIDEBAR_MIN_W = 160
_SIDEBAR_MAX_W = 280


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TeslaCam Viewer")
        self.resize(1400, 860)
        self.setMinimumSize(900, 600)

        # App icon
        icon_path = _HERE / "resources" / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._sync = SyncController(self)
        self._scanner = Scanner(self)
        self._current_event: TeslaEvent | None = None
        self._sidebar_visible = True

        self._build_ui()
        self._connect_signals()

        QTimer.singleShot(200, self._auto_load)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Header bar ─────────────────────────────────────────────────
        header = QWidget()
        header.setObjectName("headerBar")
        header.setFixedHeight(46)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(10, 0, 10, 0)
        h_layout.setSpacing(6)

        # Sidebar toggle (leftmost)
        self._btn_toggle = QPushButton()
        self._btn_toggle.setObjectName("headerButton")
        self._btn_toggle.setToolTip("Sidebar ein-/ausblenden")
        self._btn_toggle.setFixedSize(34, 30)
        self._btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_toggle.setIcon(make_icon("panel_left", 16, "#707070"))
        self._btn_toggle.clicked.connect(self._toggle_sidebar)
        h_layout.addWidget(self._btn_toggle)

        # Folder open button
        self._btn_open = QPushButton("  Ordner öffnen")
        self._btn_open.setObjectName("headerButton")
        self._btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_open.setFixedHeight(30)
        self._btn_open.setIcon(make_icon("folder", 15, "#707070"))
        self._btn_open.clicked.connect(self._open_folder)
        h_layout.addWidget(self._btn_open)

        h_layout.addStretch()

        # Centre: camera info when maximised — no background widget, just labels
        # Wrap in a plain transparent container so setVisible() hides all at once
        self._cam_badge = QWidget()
        self._cam_badge.setObjectName("camBadge")
        self._cam_badge.setVisible(False)
        self._cam_badge.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._cam_badge.setAutoFillBackground(False)
        badge_layout = QHBoxLayout(self._cam_badge)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_layout.setSpacing(6)

        # Small accent dot to the left of the name
        self._cam_dot = QLabel("●")
        self._cam_dot.setObjectName("camDotLabel")

        self._cam_name_lbl = QLabel("")
        self._cam_name_lbl.setObjectName("camNameLabel")

        sep = QLabel("·")
        sep.setObjectName("camSepLabel")

        self._cam_hint_lbl = QLabel("Doppelklick zum Zurückschalten")
        self._cam_hint_lbl.setObjectName("camHintLabel")

        badge_layout.addWidget(self._cam_dot)
        badge_layout.addWidget(self._cam_name_lbl)
        badge_layout.addWidget(sep)
        badge_layout.addWidget(self._cam_hint_lbl)

        h_layout.addWidget(self._cam_badge)
        h_layout.addStretch()

        # Right invisible spacer — use addSpacing (no widget, no background) to
        # mirror the left buttons and keep the badge optically centred
        h_layout.addSpacing(
            self._btn_toggle.sizeHint().width()
            + self._btn_open.sizeHint().width()
            + 6
        )

        # ── Status bar ─────────────────────────────────────────────────
        self._status = QStatusBar()
        self._progress = QProgressBar()
        self._progress.setFixedWidth(180)
        self._progress.setVisible(False)
        self._status.addPermanentWidget(self._progress)
        self.setStatusBar(self._status)

        # ── Central widget ─────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(header)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(4)

        self._event_list = EventList()
        self._splitter.addWidget(self._event_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._grid = GridView(self._sync)
        right_layout.addWidget(self._grid, stretch=1)

        self._timeline = Timeline(self._sync)
        self._timeline.setFixedHeight(96)
        self._timeline.setObjectName("timelineBar")
        right_layout.addWidget(self._timeline)

        self._splitter.addWidget(right)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([_SIDEBAR_DEFAULT_W, 1200])

        root_layout.addWidget(self._splitter)

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._event_list.event_selected.connect(self._load_event)
        self._grid.camera_maximized.connect(self._on_camera_maximized)
        self._scanner.event_found.connect(self._event_list.add_event)
        self._scanner.progress.connect(self._on_scan_progress)
        self._scanner.finished.connect(self._on_scan_finished)

    # ------------------------------------------------------------------
    # Sidebar toggle
    # ------------------------------------------------------------------

    def _toggle_sidebar(self) -> None:
        self._sidebar_visible = not self._sidebar_visible
        self._event_list.setVisible(self._sidebar_visible)

        # Update splitter sizes so the player area fills the space
        if self._sidebar_visible:
            self._splitter.setSizes([_SIDEBAR_DEFAULT_W, self.width() - _SIDEBAR_DEFAULT_W])
        else:
            self._splitter.setSizes([0, self.width()])

        # Tint the toggle icon red when sidebar is hidden
        color = "#e31937" if not self._sidebar_visible else "#707070"
        self._btn_toggle.setIcon(make_icon("panel_left", 16, color))

    # ------------------------------------------------------------------
    # Folder / scanning
    # ------------------------------------------------------------------

    def _auto_load(self) -> None:
        if _DEFAULT_CLIPS_PATH.exists():
            self._start_scan(_DEFAULT_CLIPS_PATH)
        else:
            self._status.showMessage("Kein TeslaCam-Ordner gefunden — bitte manuell öffnen.")

    def _open_folder(self) -> None:
        start = str(_DEFAULT_CLIPS_PATH) if _DEFAULT_CLIPS_PATH.exists() else ""
        folder = QFileDialog.getExistingDirectory(
            self, "TeslaCam SavedClips-Ordner auswählen", start
        )
        if folder:
            self._start_scan(Path(folder))

    def _start_scan(self, root: Path) -> None:
        self._event_list.clear()
        self._status.showMessage(f"Scanne {root} …")
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._scanner.scan(root)

    def _on_scan_progress(self, done: int, total: int) -> None:
        self._progress.setMaximum(total)
        self._progress.setValue(done)

    def _on_scan_finished(self) -> None:
        self._progress.setVisible(False)
        self._status.showMessage("Bereit.", 3000)
        self._event_list.select_first()

    # ------------------------------------------------------------------
    # Event loading
    # ------------------------------------------------------------------

    def _load_event(self, event: TeslaEvent) -> None:
        self._current_event = event
        self._sync.pause_all()
        self._grid.load_event(event)
        self._timeline.set_duration(event.duration_seconds)
        self._timeline.set_event_marker(event.event_offset_seconds)
        self._timeline.reset()
        self._status.showMessage(
            f"{event.display_time}  ·  {event.display_location}  ·  {event.trigger_label}"
        )

    # ------------------------------------------------------------------
    # Camera maximise / restore
    # ------------------------------------------------------------------

    def _on_camera_maximized(self, camera: str) -> None:
        from core.event import CAMERA_LABELS
        if camera:
            self._cam_name_lbl.setText(f"{CAMERA_LABELS.get(camera, camera)}-Kamera")
            self._cam_badge.setVisible(True)
        else:
            self._cam_badge.setVisible(False)
