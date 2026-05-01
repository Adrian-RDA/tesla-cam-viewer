"""
ui/export_dialog.py — Export dialog for TeslaCam Viewer.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.event import CAMERA_LABELS, CAMERAS, TeslaEvent
from core.exporter import (
    ExportConfig, ExportWorker,
    FrameLoader, GridFrameLoader, get_clip_at,
)


def _fmt(seconds: float) -> str:
    s = int(max(0.0, seconds))
    return f"{s // 60}:{s % 60:02d}"


# ─────────────────────────────────────────────────────────────────────────────
# Dual-handle range slider
# ─────────────────────────────────────────────────────────────────────────────

class RangeSlider(QWidget):
    """
    Two draggable handles (In / Out) with highlighted selection band.

    Signals
    -------
    range_changed(float, float)   emitted while dragging (in_s, out_s)
    in_released(float)            emitted when In handle is released
    out_released(float)           emitted when Out handle is released
    """

    range_changed = Signal(float, float)
    in_released   = Signal(float)
    out_released  = Signal(float)

    _MARGIN   = 10
    _HANDLE_R = 7
    _GROOVE_H = 4
    _HIT_R    = 14

    def __init__(
        self,
        duration: float,
        in_point: float = 0.0,
        out_point: float | None = None,
        marker: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._duration = max(duration, 1.0)
        self._in  = max(0.0, in_point)
        self._out = min(self._duration, out_point if out_point is not None else self._duration)
        self._marker = marker
        self._drag: str | None = None
        self.setMinimumHeight(36)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # --- public API ---

    @property
    def in_point(self) -> float:
        return self._in

    @property
    def out_point(self) -> float:
        return self._out

    def set_range(self, in_pt: float, out_pt: float) -> None:
        self._in  = max(0.0, min(in_pt,  self._duration))
        self._out = max(self._in + 0.5, min(out_pt, self._duration))
        self.update()
        self.range_changed.emit(self._in, self._out)

    def set_marker(self, seconds: float | None) -> None:
        self._marker = seconds
        self.update()

    # --- geometry ---

    def _uw(self) -> int:
        return self.width() - 2 * self._MARGIN

    def _s2x(self, s: float) -> int:
        return int(self._MARGIN + (s / self._duration) * self._uw())

    def _x2s(self, x: int) -> float:
        return max(0.0, min(self._duration, ((x - self._MARGIN) / self._uw()) * self._duration))

    # --- paint ---

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cy = self.height() // 2
        gr = self._GROOVE_H // 2
        m  = self._MARGIN

        # Full groove
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1a1a1a"))
        p.drawRoundedRect(m, cy - gr, self.width() - 2 * m, self._GROOVE_H, gr, gr)

        # Selected range
        in_x  = self._s2x(self._in)
        out_x = self._s2x(self._out)
        p.setBrush(QColor(227, 25, 55, 90))
        p.drawRect(in_x, cy - gr, out_x - in_x, self._GROOVE_H)

        # Event marker diamond
        if self._marker is not None:
            mx = self._s2x(self._marker)
            s = 4
            diamond = QPolygon([
                QPoint(mx,     cy - gr - s - 2),
                QPoint(mx + s, cy - gr - 1),
                QPoint(mx,     cy),
                QPoint(mx - s, cy - gr - 1),
            ])
            p.setBrush(QColor("#e31937"))
            p.drawPolygon(diamond)

        # Handles
        for x, key in ((in_x, "in"), (out_x, "out")):
            if self._drag == key:
                p.setPen(QPen(QColor(227, 25, 55, 55), 5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPoint(x, cy), self._HANDLE_R + 3, self._HANDLE_R + 3)
            p.setPen(QPen(QColor("#e31937"), 2))
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPoint(x, cy), self._HANDLE_R, self._HANDLE_R)

        p.end()

    # --- mouse ---

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x    = event.position().x()
        d_in  = abs(x - self._s2x(self._in))
        d_out = abs(x - self._s2x(self._out))
        if d_in <= self._HIT_R and d_in <= d_out:
            self._drag = "in"
        elif d_out <= self._HIT_R:
            self._drag = "out"

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag is None:
            return
        sec = self._x2s(int(event.position().x()))
        if self._drag == "in":
            self._in = max(0.0, min(sec, self._out - 0.5))
        else:
            self._out = max(self._in + 0.5, min(sec, self._duration))
        self.update()
        self.range_changed.emit(self._in, self._out)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._drag == "in":
            self.in_released.emit(self._in)
        elif self._drag == "out":
            self.out_released.emit(self._out)
        self._drag = None
        self.update()


# ─────────────────────────────────────────────────────────────────────────────
# Preview thumbnail label
# ─────────────────────────────────────────────────────────────────────────────

class _PreviewLabel(QLabel):
    """QLabel showing a video frame thumbnail with a dark placeholder."""

    _W, _H = 310, 233   # 4:3-friendly preview size

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._caption = text
        self.setFixedSize(self._W, self._H)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("exportPreviewLabel")
        self._show_placeholder()

    def _show_placeholder(self) -> None:
        self.setPixmap(QPixmap())
        self.setText(self._caption)

    def set_frame(self, px: QPixmap) -> None:
        scaled = px.scaled(
            self._W, self._H,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)
        self.setText("")


# ─────────────────────────────────────────────────────────────────────────────
# Section label
# ─────────────────────────────────────────────────────────────────────────────

def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("exportSectionLabel")
    return lbl


# ─────────────────────────────────────────────────────────────────────────────
# Export dialog
# ─────────────────────────────────────────────────────────────────────────────

class ExportDialog(QDialog):
    """
    Modal export dialog.

    Parameters
    ----------
    event        The currently loaded TeslaEvent.
    current_pos  Current playback position (seconds) — used to hint In/Out.
    sync         Optional SyncController for live seek preview.
    parent       Parent widget.
    """

    def __init__(
        self,
        event: TeslaEvent,
        current_pos: float = 0.0,
        sync=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._event = event
        self._sync  = sync
        self._worker: ExportWorker | None = None
        self._loaders: list[FrameLoader] = []
        self._output_dir = Path.home() / "Desktop"

        self._in_pt  = 0.0
        self._out_pt = event.duration_seconds

        # Debounce timer — seek preview 120 ms after last drag movement
        self._seek_timer = QTimer(self)
        self._seek_timer.setSingleShot(True)
        self._seek_timer.setInterval(120)
        self._seek_timer.timeout.connect(self._do_seek_preview)
        self._seek_target: float = 0.0

        self.setWindowTitle("Video exportieren")
        self.setModal(True)
        self.setFixedWidth(700)
        self.setObjectName("exportDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self._build()
        self._refresh_output_label()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # Title
        title = QLabel("Video exportieren")
        title.setObjectName("exportTitle")
        root.addWidget(title)

        self._add_divider(root)

        # ── Mode ───────────────────────────────────────────────────────
        root.addWidget(_section("MODUS"))

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self._btn_grid   = QPushButton("▣  4-Kamera Grid")
        self._btn_single = QPushButton("▢  Einzelne Kamera")
        for btn in (self._btn_grid, self._btn_single):
            btn.setObjectName("exportModeBtn")
            btn.setCheckable(True)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_grid.setChecked(True)
        self._btn_grid.clicked.connect(lambda: self._set_mode("grid"))
        self._btn_single.clicked.connect(lambda: self._set_mode("single"))
        mode_row.addWidget(self._btn_grid)
        mode_row.addWidget(self._btn_single)
        root.addLayout(mode_row)

        # Camera selector (hidden in grid mode)
        self._cam_row = QWidget()
        cam_l = QHBoxLayout(self._cam_row)
        cam_l.setContentsMargins(0, 0, 0, 0)
        cam_l.setSpacing(8)
        cam_lbl = QLabel("Kamera:")
        cam_lbl.setObjectName("exportBodyLabel")
        self._cam_combo = QComboBox()
        self._cam_combo.setObjectName("exportCombo")
        self._cam_combo.setFixedHeight(30)
        for cam in CAMERAS:
            if self._event.segments.get(cam):
                self._cam_combo.addItem(CAMERA_LABELS.get(cam, cam), userData=cam)
        cam_l.addWidget(cam_lbl)
        cam_l.addWidget(self._cam_combo)
        cam_l.addStretch()
        self._cam_row.setVisible(False)
        root.addWidget(self._cam_row)

        self._add_divider(root)

        # ── Time range ─────────────────────────────────────────────────
        root.addWidget(_section("ZEITBEREICH"))

        dur    = self._event.duration_seconds
        marker = self._event.event_offset_seconds

        self._range_slider = RangeSlider(duration=dur, marker=marker)
        self._range_slider.range_changed.connect(self._on_range_changed)
        self._range_slider.in_released.connect(self._on_in_released)
        self._range_slider.out_released.connect(self._on_out_released)
        root.addWidget(self._range_slider)

        # Time readout row
        time_row = QHBoxLayout()
        self._lbl_in  = QLabel(_fmt(0.0))
        self._lbl_out = QLabel(_fmt(dur))
        dur_lbl       = QLabel(f"Gesamt: {_fmt(dur)}")
        for lbl in (self._lbl_in, self._lbl_out):
            lbl.setObjectName("exportTimeLabel")
        self._lbl_out.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        dur_lbl.setObjectName("exportDurLabel")
        dur_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_row.addWidget(self._lbl_in)
        time_row.addWidget(dur_lbl, stretch=1)
        time_row.addWidget(self._lbl_out)
        root.addLayout(time_row)

        # ── Preview thumbnails ─────────────────────────────────────────
        preview_row = QHBoxLayout()
        preview_row.setSpacing(12)

        in_col  = QVBoxLayout()
        out_col = QVBoxLayout()
        for col, txt in ((in_col, "In-Punkt"), (out_col, "Out-Punkt")):
            col.setSpacing(4)
            lbl = QLabel(txt)
            lbl.setObjectName("exportPreviewCaption")
            col.addWidget(lbl)

        self._prev_in  = _PreviewLabel("In-Punkt")
        self._prev_out = _PreviewLabel("Out-Punkt")
        in_col.addWidget(self._prev_in)
        out_col.addWidget(self._prev_out)

        preview_row.addLayout(in_col)
        preview_row.addStretch()
        preview_row.addLayout(out_col)
        root.addLayout(preview_row)

        # Seek hint (only shown when SyncController is available)
        if self._sync is not None:
            hint = QLabel("Vorschau: Hauptvideo folgt beim Ziehen der Marker")
            hint.setObjectName("exportHintLabel")
            root.addWidget(hint)

        # Preset buttons
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        btn_full = QPushButton("Ganzes Event")
        btn_full.setObjectName("exportPresetBtn")
        btn_full.setFixedHeight(28)
        btn_full.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_full.clicked.connect(self._preset_full)
        btn_event = QPushButton("±30 s um Event")
        btn_event.setObjectName("exportPresetBtn")
        btn_event.setFixedHeight(28)
        btn_event.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_event.clicked.connect(self._preset_around_event)
        btn_event.setEnabled(marker is not None)
        preset_row.addWidget(btn_full)
        preset_row.addWidget(btn_event)
        preset_row.addStretch()
        root.addLayout(preset_row)

        self._add_divider(root)

        # ── Options ────────────────────────────────────────────────────
        root.addWidget(_section("OPTIONEN"))

        opt_row = QHBoxLayout()
        opt_row.setSpacing(16)
        self._chk_overlay = QCheckBox("Zeitstempel-Overlay")
        self._chk_overlay.setObjectName("exportCheck")
        self._chk_overlay.setChecked(True)
        opt_row.addWidget(self._chk_overlay)
        opt_row.addStretch()
        q_lbl = QLabel("Qualität:")
        q_lbl.setObjectName("exportBodyLabel")
        opt_row.addWidget(q_lbl)
        self._radio_copy = QRadioButton("Original")
        self._radio_h264 = QRadioButton("H.264")
        self._radio_copy.setObjectName("exportRadio")
        self._radio_h264.setObjectName("exportRadio")
        self._radio_h264.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self._radio_copy)
        grp.addButton(self._radio_h264)
        self._radio_copy.toggled.connect(self._on_quality_changed)
        opt_row.addWidget(self._radio_copy)
        opt_row.addWidget(self._radio_h264)
        root.addLayout(opt_row)

        self._add_divider(root)

        # ── Output path ────────────────────────────────────────────────
        root.addWidget(_section("AUSGABE"))
        out_row = QHBoxLayout()
        self._lbl_output = QLabel()
        self._lbl_output.setObjectName("exportPathLabel")
        self._lbl_output.setWordWrap(False)
        self._lbl_output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        btn_change = QPushButton("Ändern")
        btn_change.setObjectName("exportSmallBtn")
        btn_change.setFixedHeight(28)
        btn_change.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_change.clicked.connect(self._pick_output_dir)
        out_row.addWidget(self._lbl_output, stretch=1)
        out_row.addWidget(btn_change)
        root.addLayout(out_row)

        self._add_divider(root)

        # ── Progress ───────────────────────────────────────────────────
        self._progress_widget = QWidget()
        prog_l = QVBoxLayout(self._progress_widget)
        prog_l.setContentsMargins(0, 0, 0, 0)
        prog_l.setSpacing(6)
        self._progress_bar = QProgressBar()
        self._progress_bar.setObjectName("exportProgress")
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(False)
        prog_l.addWidget(self._progress_bar)
        self._lbl_status = QLabel()
        self._lbl_status.setObjectName("exportStatusLabel")
        prog_l.addWidget(self._lbl_status)
        self._progress_widget.setVisible(False)
        root.addWidget(self._progress_widget)

        # ── Footer ─────────────────────────────────────────────────────
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self._btn_cancel = QPushButton("Abbrechen")
        self._btn_cancel.setObjectName("exportCancelBtn")
        self._btn_cancel.setFixedHeight(36)
        self._btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_cancel.clicked.connect(self._on_cancel)
        self._btn_export = QPushButton("Exportieren")
        self._btn_export.setObjectName("exportStartBtn")
        self._btn_export.setFixedHeight(36)
        self._btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_export.clicked.connect(self._start_export)
        footer.addStretch()
        footer.addWidget(self._btn_cancel)
        footer.addWidget(self._btn_export)
        root.addLayout(footer)

        # Load initial preview thumbnails
        QTimer.singleShot(100, lambda: self._load_preview("in",  self._in_pt))
        QTimer.singleShot(200, lambda: self._load_preview("out", self._out_pt))

    @staticmethod
    def _add_divider(layout: QVBoxLayout) -> None:
        line = QWidget()
        line.setFixedHeight(1)
        line.setObjectName("exportDivider")
        layout.addWidget(line)

    # ------------------------------------------------------------------
    # Mode / quality
    # ------------------------------------------------------------------

    def _set_mode(self, mode: str) -> None:
        is_grid = mode == "grid"
        self._btn_grid.setChecked(is_grid)
        self._btn_single.setChecked(not is_grid)
        self._cam_row.setVisible(not is_grid)
        if is_grid and self._radio_copy.isChecked():
            self._radio_h264.setChecked(True)
        self._radio_copy.setEnabled(not is_grid)
        # Reload previews for the new mode
        self._load_preview("in",  self._in_pt)
        self._load_preview("out", self._out_pt)

    def _on_quality_changed(self, copy_checked: bool) -> None:
        if copy_checked:
            self._chk_overlay.setChecked(False)
            self._chk_overlay.setEnabled(False)
        else:
            self._chk_overlay.setEnabled(True)

    # ------------------------------------------------------------------
    # Range slider callbacks
    # ------------------------------------------------------------------

    def _on_range_changed(self, in_pt: float, out_pt: float) -> None:
        self._in_pt  = in_pt
        self._out_pt = out_pt
        self._lbl_in.setText(_fmt(in_pt))
        self._lbl_out.setText(_fmt(out_pt))
        self._refresh_output_label()

        # Debounced seek preview — seek to whichever handle is being dragged
        if self._sync is not None:
            drag = self._range_slider._drag
            self._seek_target = in_pt if drag == "in" else out_pt
            self._seek_timer.start()

    def _do_seek_preview(self) -> None:
        if self._sync is not None:
            self._sync.seek_all(self._seek_target)

    def _on_in_released(self, pos: float) -> None:
        self._load_preview("in", pos)

    def _on_out_released(self, pos: float) -> None:
        self._load_preview("out", pos)

    # ------------------------------------------------------------------
    # Frame preview
    # ------------------------------------------------------------------

    def _load_preview(self, which: str, seconds: float) -> None:
        """Dispatch to grid or single-camera frame loader based on current mode."""
        label = self._prev_in if which == "in" else self._prev_out
        label._show_placeholder()

        if self._btn_grid.isChecked():
            loader: QThread = GridFrameLoader(
                self._event.segments, seconds, out_width=620, parent=self
            )
        else:
            result = get_clip_at(self._event.segments, seconds)
            if result is None:
                return
            clip, offset = result
            loader = FrameLoader(clip, offset, width=310, parent=self)

        loader.frame_ready.connect(label.set_frame)  # type: ignore[attr-defined]
        self._start_loader(loader)

    def _start_loader(self, loader: QThread) -> None:
        loader.finished.connect(  # type: ignore[attr-defined]
            lambda: self._loaders.remove(loader) if loader in self._loaders else None
        )
        self._loaders.append(loader)
        loader.start()

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    def _preset_full(self) -> None:
        self._range_slider.set_range(0.0, self._event.duration_seconds)
        self._load_preview("in",  0.0)
        self._load_preview("out", self._event.duration_seconds)

    def _preset_around_event(self) -> None:
        marker = self._event.event_offset_seconds
        if marker is None:
            return
        dur = self._event.duration_seconds
        in_pt  = max(0.0, marker - 30.0)
        out_pt = min(dur,  marker + 30.0)
        self._range_slider.set_range(in_pt, out_pt)
        self._load_preview("in",  in_pt)
        self._load_preview("out", out_pt)

    # ------------------------------------------------------------------
    # Output path
    # ------------------------------------------------------------------

    def _pick_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Ausgabeordner wählen", str(self._output_dir)
        )
        if folder:
            self._output_dir = Path(folder)
            self._refresh_output_label()

    def _build_output_path(self) -> Path:
        mode = "grid" if self._btn_grid.isChecked() else "single"
        if mode == "single":
            cam = self._cam_combo.currentData() or "front"
            tag = f"_{CAMERA_LABELS.get(cam, cam).lower()}"
        else:
            tag = "_grid"
        ts = self._event.event_time.strftime("%Y-%m-%d_%H-%M-%S")
        return self._output_dir / f"TeslaCam_{ts}{tag}.mp4"

    def _refresh_output_label(self) -> None:
        path = self._build_output_path()
        self._lbl_output.setText(str(path))
        self._lbl_output.setToolTip(str(path))

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _start_export(self) -> None:
        mode    = "grid" if self._btn_grid.isChecked() else "single"
        cam     = self._cam_combo.currentData() or "front"
        quality = "copy" if self._radio_copy.isChecked() else "h264"
        overlay = self._chk_overlay.isChecked() and quality != "copy"

        config = ExportConfig(
            mode=mode, camera=cam,
            segments=self._event.segments,
            in_point=self._in_pt, out_point=self._out_pt,
            quality=quality, timestamp_overlay=overlay,
            event_time=self._event.event_time,
            output_path=self._build_output_path(),
        )

        self._worker = ExportWorker(config, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error_occurred.connect(self._on_error)

        self._btn_export.setEnabled(False)
        self._btn_export.setText("Exportiere …")
        self._progress_widget.setVisible(True)
        self._progress_bar.setValue(0)
        self._lbl_status.setText("Exportiere …")
        self._worker.start()

    def _on_progress(self, pct: int) -> None:
        self._progress_bar.setValue(pct)
        self._lbl_status.setText(f"Exportiere … {pct} %")

    def _on_finished(self, path: str) -> None:
        self._progress_bar.setValue(100)
        self._lbl_status.setText("✓ Export abgeschlossen")
        self._btn_export.setText("Exportieren")
        self._btn_export.setEnabled(True)
        self._btn_cancel.setText("Schließen")
        out_dir = str(Path(path).parent)
        QTimer.singleShot(400, lambda: os.startfile(out_dir))  # type: ignore[attr-defined]

    def _on_error(self, msg: str) -> None:
        self._btn_export.setEnabled(True)
        self._btn_export.setText("Exportieren")
        self._progress_widget.setVisible(False)
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "Export fehlgeschlagen",
                             f"FFmpeg meldete einen Fehler:\n\n{msg}")

    def _on_cancel(self) -> None:
        self._seek_timer.stop()
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        for loader in self._loaders:
            loader.quit()
        self.reject()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._on_cancel()
        super().closeEvent(event)
