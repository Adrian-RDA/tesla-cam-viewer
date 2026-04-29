from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QPainter, QPolygon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.sync_controller import SyncController
from ui.icons import make_icon

# Available playback speeds
_SPEEDS = [0.25, 0.5, 1.0, 1.5, 2.0, 4.0]
_SPEED_LABELS = ["¼×", "½×", "1×", "1.5×", "2×", "4×"]
_DEFAULT_SPEED_IDX = 2  # 1×


def _fmt(seconds: float) -> str:
    s = int(max(0, seconds))
    return f"{s // 60}:{s % 60:02d}"


# ──────────────────────────────────────────────────────────────────────────────
# Custom slider with an optional event-timestamp marker
# ──────────────────────────────────────────────────────────────────────────────

class MarkerSlider(QSlider):
    """QSlider that paints a small red diamond at the event trigger timestamp."""

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self._marker_ratio: float | None = None   # 0.0 … 1.0 within range

    def set_marker(self, ratio: float | None) -> None:
        self._marker_ratio = ratio
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if self._marker_ratio is None:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Groove spans roughly 8 px from each edge (matches Qt's default style)
        margin = 9
        usable_w = self.width() - 2 * margin
        x = int(margin + self._marker_ratio * usable_w)
        cy = self.height() // 2

        # Small red diamond ◆
        s = 5
        diamond = QPolygon([
            QPoint(x,     cy - s),
            QPoint(x + s, cy    ),
            QPoint(x,     cy + s),
            QPoint(x - s, cy    ),
        ])

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#e31937"))
        p.drawPolygon(diamond)

        # Thin vertical tick line above the groove
        p.setPen(QColor(227, 25, 55, 160))
        p.drawLine(x, 2, x, cy - s - 1)
        p.end()


# ──────────────────────────────────────────────────────────────────────────────
# Speed segmented control
# ──────────────────────────────────────────────────────────────────────────────

class SpeedControl(QWidget):
    """Row of speed-option buttons. Emits speed_changed(float) on every change."""

    speed_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: list[QPushButton] = []
        self._current_idx = _DEFAULT_SPEED_IDX

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        for i, lbl in enumerate(_SPEED_LABELS):
            btn = QPushButton(lbl)
            btn.setObjectName("speedSegBtn")
            btn.setFixedHeight(26)
            btn.setMinimumWidth(36)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, idx=i: self._select(idx))
            layout.addWidget(btn)
            self._buttons.append(btn)

        self._refresh()

    @property
    def current_speed(self) -> float:
        return _SPEEDS[self._current_idx]

    def step(self, delta: int) -> None:
        self._select(max(0, min(self._current_idx + delta, len(_SPEEDS) - 1)))

    def _select(self, idx: int) -> None:
        if idx == self._current_idx and self._buttons[idx].isChecked():
            # already active — re-check it (user may have clicked to uncheck)
            self._buttons[idx].setChecked(True)
            return
        self._current_idx = idx
        self._refresh()
        self.speed_changed.emit(_SPEEDS[idx])

    def _refresh(self) -> None:
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == self._current_idx)
            btn.style().unpolish(btn)
            btn.style().polish(btn)


# ──────────────────────────────────────────────────────────────────────────────
# Main timeline bar
# ──────────────────────────────────────────────────────────────────────────────

class Timeline(QWidget):
    """
    Transport bar: scrubber (with event marker) + centred play controls
    + speed segmented control.
    """

    def __init__(self, sync: SyncController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sync = sync
        self._duration = 0
        self._dragging = False
        self._was_playing = False

        self._build()

        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._update_position)
        self._poll.start()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 6)
        root.setSpacing(6)

        # ── Scrubber row ────────────────────────────────────────────────
        scrubber_row = QHBoxLayout()
        scrubber_row.setSpacing(10)

        self._slider = MarkerSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 1000)
        self._slider.setValue(0)
        self._slider.setObjectName("timelineSlider")
        self._slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self._slider.sliderPressed.connect(self._on_slider_press)
        self._slider.sliderReleased.connect(self._on_slider_release)
        scrubber_row.addWidget(self._slider, stretch=1)

        self._time_lbl = QLabel("0:00 / 0:00")
        self._time_lbl.setObjectName("timeLabel")
        self._time_lbl.setFixedWidth(96)
        self._time_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        scrubber_row.addWidget(self._time_lbl)

        root.addLayout(scrubber_row)

        # ── Controls row — 3-zone layout ────────────────────────────────
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(0)

        # Left zone: speed selector
        left_w = QWidget()
        left_l = QHBoxLayout(left_w)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(0)
        self._speed_ctrl = SpeedControl()
        self._speed_ctrl.speed_changed.connect(self._on_speed_changed)
        left_l.addWidget(self._speed_ctrl)
        left_l.addStretch()
        left_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        ctrl_row.addWidget(left_w, stretch=1)

        # Centre zone: transport buttons
        centre_w = QWidget()
        centre_l = QHBoxLayout(centre_w)
        centre_l.setContentsMargins(0, 0, 0, 0)
        centre_l.setSpacing(8)

        icon_size = 18

        self._btn_slower = QPushButton()
        self._btn_slower.setObjectName("transportButton")
        self._btn_slower.setToolTip("Langsamer")
        self._btn_slower.setFixedSize(38, 32)
        self._btn_slower.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_slower.setIcon(make_icon("skip_back", icon_size, "#707070"))
        self._btn_slower.clicked.connect(self._slower)

        self._btn_play = QPushButton()
        self._btn_play.setObjectName("playButton")
        self._btn_play.setToolTip("Play / Pause")
        self._btn_play.setFixedSize(44, 36)
        self._btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_play.setIcon(make_icon("play", icon_size + 2, "#ffffff"))
        self._btn_play.clicked.connect(self._toggle_play)

        self._btn_faster = QPushButton()
        self._btn_faster.setObjectName("transportButton")
        self._btn_faster.setToolTip("Schneller")
        self._btn_faster.setFixedSize(38, 32)
        self._btn_faster.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_faster.setIcon(make_icon("skip_fwd", icon_size, "#707070"))
        self._btn_faster.clicked.connect(self._faster)

        centre_l.addWidget(self._btn_slower)
        centre_l.addWidget(self._btn_play)
        centre_l.addWidget(self._btn_faster)
        centre_w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        ctrl_row.addWidget(centre_w)

        # Right zone: empty mirror (keeps centre truly centred)
        right_w = QWidget()
        right_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        ctrl_row.addWidget(right_w, stretch=1)

        root.addLayout(ctrl_row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_duration(self, seconds: int) -> None:
        self._duration = seconds
        self._slider.setRange(0, max(seconds, 1))
        self._update_time_label(0)

    def set_event_marker(self, offset_seconds: float | None) -> None:
        """Show (or hide) the red event marker on the scrubber."""
        if offset_seconds is None or self._duration == 0:
            self._slider.set_marker(None)
        else:
            self._slider.set_marker(offset_seconds / self._duration)

    def reset(self) -> None:
        self._slider.setValue(0)
        self._update_time_label(0)
        self._btn_play.setIcon(make_icon("play", 20, "#ffffff"))

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _toggle_play(self) -> None:
        if self._sync.is_paused:
            self._sync.play_all()
            self._btn_play.setIcon(make_icon("pause", 20, "#ffffff"))
        else:
            self._sync.pause_all()
            self._btn_play.setIcon(make_icon("play", 20, "#ffffff"))

    def _slower(self) -> None:
        self._speed_ctrl.step(-1)   # SpeedControl emits speed_changed → _on_speed_changed

    def _faster(self) -> None:
        self._speed_ctrl.step(+1)

    def _on_speed_changed(self, speed: float) -> None:
        self._sync.set_speed_all(speed)

    def _on_slider_press(self) -> None:
        self._was_playing = not self._sync.is_paused
        self._dragging = True
        self._sync.pause_all()

    def _on_slider_release(self) -> None:
        pos = float(self._slider.value())
        self._dragging = False
        self._sync.seek_all(pos)
        if self._was_playing:
            QTimer.singleShot(380, self._resume_if_not_dragging)

    def _resume_if_not_dragging(self) -> None:
        if not self._dragging:
            self._sync.play_all()
            self._btn_play.setIcon(make_icon("pause", 20, "#ffffff"))

    # ------------------------------------------------------------------
    # Position polling
    # ------------------------------------------------------------------

    def _update_position(self) -> None:
        if self._dragging or self._duration == 0:
            return
        pos = self._sync.master_position
        self._slider.blockSignals(True)
        self._slider.setValue(int(pos))
        self._slider.blockSignals(False)
        self._update_time_label(pos)

        # Keep play icon in sync
        is_playing = not self._sync.is_paused
        icon_name = "pause" if is_playing else "play"
        self._btn_play.setIcon(make_icon(icon_name, 20, "#ffffff"))

    def _update_time_label(self, pos: float) -> None:
        self._time_lbl.setText(f"{_fmt(pos)} / {_fmt(self._duration)}")
