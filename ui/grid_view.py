from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QStackedWidget, QWidget

from core.event import CAMERAS, TeslaEvent
from core.sync_controller import SyncController
from ui.player_widget import PlayerWidget

# Camera positions in the 2×2 grid
#   front         right_repeater
#   left_repeater back
_GRID_POS: dict[str, tuple[int, int]] = {
    "front":          (0, 0),
    "right_repeater": (0, 1),
    "left_repeater":  (1, 0),
    "back":           (1, 1),
}


class GridView(QWidget):
    """
    Shows four PlayerWidgets in a 2×2 grid.

    Double-clicking a camera toggles between the full grid and a
    maximised single-camera view.

    Signals
    -------
    camera_maximized(camera)   — "" means grid mode
    """

    camera_maximized = Signal(str)

    def __init__(self, sync: SyncController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sync = sync
        self._players: dict[str, PlayerWidget] = {}
        self._maximized_cam: str = ""

        self._build()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        from PySide6.QtWidgets import QVBoxLayout

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Stacked widget: page 0 = grid, page 1 = single maximised player
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        # --- Page 0: 2×2 grid ---
        grid_page = QWidget()
        self._grid_layout = QGridLayout(grid_page)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        self._grid_layout.setSpacing(4)
        self._grid_layout.setColumnStretch(0, 1)
        self._grid_layout.setColumnStretch(1, 1)
        self._grid_layout.setRowStretch(0, 1)
        self._grid_layout.setRowStretch(1, 1)

        for cam in CAMERAS:
            player = PlayerWidget(cam)
            player.double_clicked.connect(self._on_double_click)
            self._players[cam] = player
            self._sync.register(cam, player)
            row, col = _GRID_POS[cam]
            self._grid_layout.addWidget(player, row, col)

        self._stack.addWidget(grid_page)  # index 0

        # --- Page 1: single maximised view (placeholder, swapped dynamically) ---
        self._max_page = QWidget()
        from PySide6.QtWidgets import QVBoxLayout as VL
        max_layout = VL(self._max_page)
        max_layout.setContentsMargins(0, 0, 0, 0)
        self._max_placeholder = QWidget()
        max_layout.addWidget(self._max_placeholder)
        self._stack.addWidget(self._max_page)  # index 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_event(self, event: TeslaEvent) -> None:
        """Load all camera playlists for the given event."""
        self._sync.stop()
        for cam, player in self._players.items():
            player.load_playlist(event.playlist(cam))
        self._sync.start()

    def toggle_maximize(self, camera: str) -> None:
        """Switch between grid and maximised view for *camera*."""
        if self._maximized_cam == camera:
            self._restore_grid()
        else:
            self._maximize(camera)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _maximize(self, camera: str) -> None:
        player = self._players[camera]
        # Reparent the player widget into the max page
        self._max_page.layout().removeWidget(self._max_placeholder)
        self._max_placeholder.hide()

        row, col = _GRID_POS[camera]
        self._grid_layout.removeWidget(player)
        self._max_page.layout().addWidget(player)

        self._maximized_cam = camera
        self._stack.setCurrentIndex(1)
        self._sync.set_master(camera)
        self.camera_maximized.emit(camera)

    def _restore_grid(self) -> None:
        if not self._maximized_cam:
            return
        camera = self._maximized_cam
        player = self._players[camera]

        # Move player back to grid
        self._max_page.layout().removeWidget(player)
        row, col = _GRID_POS[camera]
        self._grid_layout.addWidget(player, row, col)

        self._max_placeholder.show()
        self._max_page.layout().addWidget(self._max_placeholder)

        self._maximized_cam = ""
        self._stack.setCurrentIndex(0)
        self._sync.set_master("front")
        self.camera_maximized.emit("")

    def _on_double_click(self, camera: str) -> None:
        self.toggle_maximize(camera)
