from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from core.event import CAMERA_LABELS
from ui.spinner import SpinnerOverlay

# States that indicate the player is busy loading/buffering
_BUFFERING_STATES = {
    QMediaPlayer.MediaStatus.LoadingMedia,
    QMediaPlayer.MediaStatus.BufferingMedia,
    QMediaPlayer.MediaStatus.StalledMedia,
}


class PlayerWidget(QWidget):
    """
    Single camera player built on Qt Multimedia.
    GPU decoding via Windows Media Foundation (D3D11/D3D12) — no extra DLL.

    Signals
    -------
    double_clicked(camera)   — user wants to maximise this camera
    """

    double_clicked = Signal(str)

    def __init__(self, camera: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.camera = camera
        self._playlist: list[str] = []
        self._current_index: int = 0

        self._build_ui()
        self._build_player()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._label = QLabel(CAMERA_LABELS.get(self.camera, self.camera))
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setFixedHeight(20)
        self._label.setObjectName("cameraLabel")

        # Video + spinner container so the spinner overlays the video
        self._video_container = QWidget()
        self._video_container.setStyleSheet("background:#000;")
        self._video_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._video = QVideoWidget(self._video_container)
        self._video.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._video.mouseDoubleClickEvent = self._on_double_click  # type: ignore[method-assign]

        # Spinner lives inside the video container, above the video
        self._spinner = SpinnerOverlay(self._video_container)

        layout.addWidget(self._label)
        layout.addWidget(self._video_container, stretch=1)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        # Keep video and spinner filling the container
        if hasattr(self, "_video_container"):
            rect = self._video_container.rect()
            self._video.setGeometry(rect)
            self._spinner.setGeometry(rect)

    # ------------------------------------------------------------------
    # Player setup
    # ------------------------------------------------------------------

    def _build_player(self) -> None:
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setMuted(self.camera != "front")
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)

        self._player.mediaStatusChanged.connect(self._on_media_status)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_playlist(self, paths: list[str]) -> None:
        self._playlist = paths
        self._current_index = 0
        if not paths:
            return
        self._player.setSource(QUrl.fromLocalFile(paths[0]))
        self._player.pause()

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._player.pause()
        else:
            self._player.play()

    def seek(self, seconds: float) -> None:
        if not self._playlist:
            return
        seg_duration = 60
        target_idx = int(seconds // seg_duration)
        target_idx = max(0, min(target_idx, len(self._playlist) - 1))
        offset_ms = int((seconds % seg_duration) * 1000)

        if target_idx != self._current_index:
            self._current_index = target_idx
            was_paused = self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
            self._player.setSource(QUrl.fromLocalFile(self._playlist[target_idx]))
            if was_paused:
                self._player.pause()
            else:
                self._player.play()
            QTimer.singleShot(80, lambda: self._player.setPosition(offset_ms))
        else:
            self._player.setPosition(offset_ms)

    def set_speed(self, speed: float) -> None:
        self._player.setPlaybackRate(speed)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def position(self) -> float:
        seg_pos_s = self._player.position() / 1000.0
        return self._current_index * 60.0 + seg_pos_s

    @property
    def paused(self) -> bool:
        return self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        # Buffering indicator
        if status in _BUFFERING_STATES:
            self._spinner.start()
        else:
            self._spinner.stop()

        # Auto-advance playlist when segment ends
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            next_idx = self._current_index + 1
            if next_idx < len(self._playlist):
                self._current_index = next_idx
                self._player.setSource(QUrl.fromLocalFile(self._playlist[next_idx]))
                self._player.play()

    def _on_double_click(self, event: QMouseEvent) -> None:
        self.double_clicked.emit(self.camera)
        event.accept()
