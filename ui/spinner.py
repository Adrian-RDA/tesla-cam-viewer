from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class SpinnerOverlay(QWidget):
    """
    Semi-transparent buffering overlay drawn directly over the video surface.

    Shows a rotating arc in Tesla Red when the player is buffering,
    hides itself otherwise.
    """

    _ARC_SPAN = 120   # degrees the arc covers
    _STEP = 9         # degrees per tick
    _INTERVAL = 30    # ms between ticks  (~33 fps)
    _RADIUS = 20      # arc radius in pixels
    _THICKNESS = 3    # pen width

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self._INTERVAL)
        self._timer.timeout.connect(self._tick)
        self.hide()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._angle = 0
        self.show()
        self.raise_()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        # Always fill parent
        if self.parent():
            self.setGeometry(self.parent().rect())  # type: ignore[union-attr]

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dim overlay
        p.fillRect(self.rect(), QColor(0, 0, 0, 150))

        cx = self.width() // 2
        cy = self.height() // 2
        r = self._RADIUS

        from PySide6.QtCore import QRectF
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)

        # Track ring (faint)
        track_pen = QPen(QColor(255, 255, 255, 20), self._THICKNESS)
        track_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(track_pen)
        p.drawEllipse(rect)

        # Spinning arc (Tesla Red)
        arc_pen = QPen(QColor(0xE3, 0x19, 0x37), self._THICKNESS)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(arc_pen)
        # Qt arc angles: 0° = 3 o'clock, positive = CCW, unit = 1/16 degree
        start_angle = (90 - self._angle) * 16   # start at 12 o'clock
        span_angle  = -self._ARC_SPAN * 16       # CW sweep
        p.drawArc(rect, start_angle, span_angle)

        p.end()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        self._angle = (self._angle + self._STEP) % 360
        self.update()
