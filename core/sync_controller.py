from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer

if TYPE_CHECKING:
    from ui.player_widget import PlayerWidget

# How often we check / correct sync drift (ms)
_SYNC_INTERVAL_MS = 150
# Minimum drift before we force-seek (seconds)
_DRIFT_THRESHOLD_S = 0.25


class SyncController(QObject):
    """
    Keeps all four camera players locked to the same playback position.

    One player acts as "master" (front camera by default). Every
    _SYNC_INTERVAL_MS milliseconds the controller reads the master's
    time-pos and nudges any player that has drifted more than
    _DRIFT_THRESHOLD_S seconds.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._players: dict[str, "PlayerWidget"] = {}
        self._master_cam = "front"
        self._timer = QTimer(self)
        self._timer.setInterval(_SYNC_INTERVAL_MS)
        self._timer.timeout.connect(self._sync)
        self._enabled = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, camera: str, player: "PlayerWidget") -> None:
        self._players[camera] = player

    def set_master(self, camera: str) -> None:
        if camera in self._players:
            self._master_cam = camera

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def seek_all(self, seconds: float) -> None:
        """Seek all players to an absolute position (used by the timeline scrubber)."""
        self._enabled = False
        for player in self._players.values():
            player.seek(seconds)
        # Re-enable sync after a short grace period so the seek can settle
        QTimer.singleShot(300, lambda: self.set_enabled(True))

    def play_all(self) -> None:
        for player in self._players.values():
            player.set_paused(False)

    def pause_all(self) -> None:
        for player in self._players.values():
            player.set_paused(True)

    def set_speed_all(self, speed: float) -> None:
        for player in self._players.values():
            player.set_speed(speed)

    @property
    def master_position(self) -> float:
        """Current playback position of the master player (seconds)."""
        master = self._players.get(self._master_cam)
        if master is None:
            return 0.0
        return master.position

    @property
    def is_paused(self) -> bool:
        master = self._players.get(self._master_cam)
        if master is None:
            return True
        return master.paused

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sync(self) -> None:
        if not self._enabled:
            return
        master = self._players.get(self._master_cam)
        if master is None or master.paused:
            return
        ref = master.position
        for cam, player in self._players.items():
            if cam == self._master_cam:
                continue
            drift = abs(player.position - ref)
            if drift > _DRIFT_THRESHOLD_S:
                player.seek(ref)
