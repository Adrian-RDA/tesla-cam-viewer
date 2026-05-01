"""
core/exporter.py — Video export via FFmpeg.

Supported modes
  "single"  Export one camera track, optionally trimmed.
  "grid"    Composite all four cameras into a 2×2 grid video.

Quality presets
  "copy"   Stream-copy — near-instant, no quality loss, cut at keyframe.
  "h264"   Re-encode with libx264 (crf 22) — exact cuts, smaller files.

Progress is reported via the ``progress`` signal (0–100 int).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap


# ── Platform flag: suppress console windows on Windows ───────────────────────
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# ── Camera orders ─────────────────────────────────────────────────────────────
_GRID_CAMERA_ORDER = ("front", "right_repeater", "left_repeater", "back")
_CAM_PRIORITY      = ("front", "back", "left_repeater", "right_repeater")


# ── FFmpeg binary ─────────────────────────────────────────────────────────────

def _get_ffmpeg() -> str:
    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys.executable).parent
        for candidate in bundle_dir.glob("imageio_ffmpeg/binaries/ffmpeg*"):
            if candidate.is_file():
                return str(candidate)
    try:
        import imageio_ffmpeg  # type: ignore[import]
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


# ── Clip helpers ──────────────────────────────────────────────────────────────

def _relevant_clips(
    clips: list[Path],
    in_point: float,
    out_point: float,
) -> tuple[list[Path], float, float]:
    """
    Return (relevant_clips, concat_in_offset, concat_out_offset).
    Offsets are relative to the start of the first returned clip.
    """
    from core.event import _mp4_duration

    pos = 0.0
    result: list[Path] = []
    cumulative_before = 0.0

    for clip in clips:
        dur = _mp4_duration(clip)
        clip_end = pos + dur
        if clip_end <= in_point:
            pos = clip_end
            cumulative_before = clip_end
            continue
        if pos >= out_point:
            break
        result.append(clip)
        pos = clip_end

    return result, max(0.0, in_point - cumulative_before), out_point - cumulative_before


def _write_concat_list(clips: list[Path], tmp_dir: str, suffix: str = "") -> str:
    lines = ["ffconcat version 1.0\n"]
    for clip in clips:
        path = str(clip.resolve()).replace("\\", "/")
        lines.append(f"file '{path}'\n")
    list_path = os.path.join(tmp_dir, f"concat{suffix}.txt")
    with open(list_path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    return list_path


# ── Public helpers for preview frame extraction ───────────────────────────────

def get_clip_at(
    segments: dict[str, list[Path]], seconds: float
) -> tuple[Path, float] | None:
    """Return (clip_path, offset_within_clip) for the given absolute position."""
    for cam in _CAM_PRIORITY:
        clips = segments.get(cam, [])
        if not clips:
            continue
        rel, cin, _ = _relevant_clips(clips, seconds, seconds + 0.5)
        if rel:
            return rel[0], cin
    return None


def _clip_at_camera(
    clips: list[Path], seconds: float
) -> tuple[Path, float] | None:
    """Like get_clip_at but for a specific camera's clip list."""
    rel, cin, _ = _relevant_clips(clips, seconds, seconds + 0.5)
    if rel:
        return rel[0], cin
    return None


def _run_frame_extract(args: list[str], tmp_path: str) -> QPixmap | None:
    """Run a single FFmpeg frame-extract command and return a QPixmap or None."""
    try:
        subprocess.run(
            args,
            capture_output=True,
            timeout=15,
            creationflags=_CREATE_NO_WINDOW,
        )
        px = QPixmap(tmp_path)
        return px if not px.isNull() else None
    except Exception:
        return None


# ── Single-camera frame loader ────────────────────────────────────────────────

class FrameLoader(QThread):
    """Extract one frame from a single clip."""

    frame_ready = Signal(object)  # QPixmap

    def __init__(
        self, clip: Path, offset: float, width: int = 224, parent=None
    ) -> None:
        super().__init__(parent)
        self._clip   = clip
        self._offset = max(0.0, offset)
        self._width  = width

    def run(self) -> None:
        fd, tmp = -1, ""
        try:
            fd, tmp = tempfile.mkstemp(suffix=".jpg")
            os.close(fd); fd = -1

            args = [
                _get_ffmpeg(), "-y",
                "-ss", f"{self._offset:.3f}",
                "-i", str(self._clip),
                "-frames:v", "1", "-q:v", "3",
                "-vf", f"scale={self._width}:-1",
                tmp,
            ]
            px = _run_frame_extract(args, tmp)
            if px is not None:
                self.frame_ready.emit(px)
        except Exception:
            pass
        finally:
            if fd != -1:
                try: os.close(fd)
                except OSError: pass
            if tmp and os.path.exists(tmp):
                try: os.unlink(tmp)
                except OSError: pass


# ── 2×2 grid composite frame loader ──────────────────────────────────────────

class GridFrameLoader(QThread):
    """
    Extract one composite frame showing all available cameras in a 2×2 grid.
    Uses FFmpeg's xstack filter to produce a single image.
    """

    frame_ready = Signal(object)  # QPixmap

    def __init__(
        self,
        segments: dict[str, list[Path]],
        seconds: float,
        out_width: int = 448,   # total composite width; height auto-calculated
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._segments  = segments
        self._seconds   = seconds
        self._out_width = out_width

    def run(self) -> None:
        fd, tmp = -1, ""
        try:
            fd, tmp = tempfile.mkstemp(suffix=".jpg")
            os.close(fd); fd = -1

            # Collect (clip, offset) per camera in grid order
            inputs: list[tuple[Path, float]] = []
            for cam in _GRID_CAMERA_ORDER:
                clips = self._segments.get(cam, [])
                if not clips:
                    continue
                result = _clip_at_camera(clips, self._seconds)
                if result:
                    inputs.append(result)

            if not inputs:
                return

            n = len(inputs)
            # Cell size: half the composite width, 4:3 height (Tesla cam aspect)
            cell_w = self._out_width // 2
            cell_h = int(cell_w * 3 / 4)

            args = [_get_ffmpeg(), "-y"]
            for clip, offset in inputs:
                args += ["-ss", f"{offset:.3f}", "-i", str(clip)]

            # Scale each stream to cell size, then stack
            scale_parts = [
                f"[{i}:v]scale={cell_w}:{cell_h}:force_original_aspect_ratio=decrease,"
                f"pad={cell_w}:{cell_h}:trunc((ow-iw)/2):trunc((oh-ih)/2):black,setsar=1[v{i}]"
                for i in range(n)
            ]
            video_labels = "".join(f"[v{i}]" for i in range(n))

            layout_map = {
                1: "0_0",
                2: "0_0|w0_0",
                3: "0_0|w0_0|0_h0",
                4: "0_0|w0_0|0_h0|w0_h0",
            }
            layout = layout_map.get(n, "0_0")

            scale_parts.append(
                f"{video_labels}xstack=inputs={n}:layout={layout}:fill=black[out]"
            )

            args += [
                "-filter_complex", ";".join(scale_parts),
                "-map", "[out]",
                "-frames:v", "1", "-q:v", "3",
                tmp,
            ]

            px = _run_frame_extract(args, tmp)
            if px is not None:
                self.frame_ready.emit(px)

        except Exception:
            pass
        finally:
            if fd != -1:
                try: os.close(fd)
                except OSError: pass
            if tmp and os.path.exists(tmp):
                try: os.unlink(tmp)
                except OSError: pass


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class ExportConfig:
    mode: str
    camera: str
    segments: dict[str, list[Path]]
    in_point: float
    out_point: float
    quality: str
    timestamp_overlay: bool
    event_time: datetime
    output_path: Path


# ── Worker ────────────────────────────────────────────────────────────────────

class ExportWorker(QThread):
    progress       = Signal(int)
    finished       = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, config: ExportConfig, parent=None) -> None:
        super().__init__(parent)
        self._config    = config
        self._cancelled = False
        self._proc: subprocess.Popen | None = None

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc is not None:
            try: self._proc.terminate()
            except Exception: pass

    def run(self) -> None:
        try:
            out = self._do_export()
            if not self._cancelled:
                self.finished.emit(str(out))
        except Exception as exc:
            if not self._cancelled:
                self.error_occurred.emit(str(exc))

    def _do_export(self) -> Path:
        with tempfile.TemporaryDirectory() as tmp:
            return (self._export_grid(tmp)
                    if self._config.mode == "grid"
                    else self._export_single(tmp))

    # ------------------------------------------------------------------
    # Single-camera
    # ------------------------------------------------------------------

    def _export_single(self, tmp: str) -> Path:
        cfg = self._config
        clips = cfg.segments.get(cfg.camera, [])
        if not clips:
            raise RuntimeError(f"Keine Clips für Kamera '{cfg.camera}' gefunden.")

        rel_clips, concat_in, _ = _relevant_clips(clips, cfg.in_point, cfg.out_point)
        if not rel_clips:
            raise RuntimeError("Im gewählten Zeitbereich wurden keine Clips gefunden.")

        export_dur   = cfg.out_point - cfg.in_point
        concat_file  = _write_concat_list(rel_clips, tmp)

        for with_audio in (True, False):
            args = self._single_args(cfg, concat_file, concat_in, export_dur, with_audio)
            try:
                self._run_ffmpeg(args, export_dur)
                return cfg.output_path
            except RuntimeError as exc:
                if with_audio and "matches no streams" in str(exc):
                    self.progress.emit(0)
                    continue
                raise
        return cfg.output_path

    def _single_args(
        self,
        cfg: ExportConfig,
        concat_file: str,
        concat_in: float,
        export_dur: float,
        with_audio: bool,
    ) -> list[str]:
        args = [_get_ffmpeg(), "-y",
                "-f", "concat", "-safe", "0", "-i", concat_file]

        if cfg.quality == "copy":
            args += ["-ss", f"{concat_in:.3f}",
                     "-t",  f"{export_dur:.3f}",
                     "-c", "copy"]
        else:
            vf = f"trim=start={concat_in:.3f}:duration={export_dur:.3f},setpts=PTS-STARTPTS"
            if cfg.timestamp_overlay:
                dt = _drawtext(cfg.event_time)
                if dt:
                    vf += f",{dt}"

            if with_audio:
                af = f"atrim=start={concat_in:.3f}:duration={export_dur:.3f},asetpts=PTS-STARTPTS"
                args += ["-filter_complex",
                         f"[0:v]{vf}[vout];[0:a]{af}[aout]",
                         "-map", "[vout]", "-map", "[aout]",
                         "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                         "-c:a", "aac", "-b:a", "128k"]
            else:
                args += ["-filter_complex", f"[0:v]{vf}[vout]",
                         "-map", "[vout]",
                         "-c:v", "libx264", "-preset", "fast", "-crf", "22"]

        args.append(str(cfg.output_path))
        return args

    # ------------------------------------------------------------------
    # Grid
    # ------------------------------------------------------------------

    def _export_grid(self, tmp: str) -> Path:
        cfg        = self._config
        export_dur = cfg.out_point - cfg.in_point

        inputs: list[tuple[str, list[Path], float]] = []
        for cam in _GRID_CAMERA_ORDER:
            clips = cfg.segments.get(cam, [])
            if not clips:
                continue
            rel, cin, _ = _relevant_clips(clips, cfg.in_point, cfg.out_point)
            if rel:
                inputs.append((cam, rel, cin))

        if not inputs:
            raise RuntimeError("Im gewählten Zeitbereich wurden keine Clips gefunden.")

        for with_audio in (True, False):
            args = self._grid_args(cfg, inputs, export_dur, tmp, with_audio)
            try:
                self._run_ffmpeg(args, export_dur)
                return cfg.output_path
            except RuntimeError as exc:
                if with_audio and "matches no streams" in str(exc):
                    self.progress.emit(0)
                    continue
                raise
        return cfg.output_path

    def _grid_args(
        self,
        cfg: ExportConfig,
        inputs: list[tuple[str, list[Path], float]],
        export_dur: float,
        tmp: str,
        with_audio: bool,
    ) -> list[str]:
        args = [_get_ffmpeg(), "-y"]
        for i, (_, rel_clips, _) in enumerate(inputs):
            cf = _write_concat_list(rel_clips, tmp, suffix=f"_{i}")
            args += ["-f", "concat", "-safe", "0", "-i", cf]

        trim_parts:  list[str] = []
        video_labels: list[str] = []

        for i, (_, _, cin) in enumerate(inputs):
            lbl = f"v{i}"
            trim_parts.append(
                f"[{i}:v]trim=start={cin:.3f}:duration={export_dur:.3f},"
                f"setpts=PTS-STARTPTS,"
                f"scale=960:540:force_original_aspect_ratio=decrease,"
                f"pad=960:540:trunc((ow-iw)/2):trunc((oh-ih)/2):black,setsar=1[{lbl}]"
            )
            video_labels.append(f"[{lbl}]")

        if with_audio:
            _, _, cin0 = inputs[0]
            trim_parts.append(
                f"[0:a]atrim=start={cin0:.3f}:duration={export_dur:.3f},"
                f"asetpts=PTS-STARTPTS[aout]"
            )

        n = len(inputs)
        layout_map = {1: "0_0", 2: "0_0|960_0",
                      3: "0_0|960_0|0_540", 4: "0_0|960_0|0_540|960_540"}
        layout = layout_map.get(n, "0_0")

        overlay_str = ""
        if cfg.timestamp_overlay:
            dt = _drawtext(cfg.event_time)
            if dt:
                overlay_str = f",{dt}"

        trim_parts.append(
            f"{''.join(video_labels)}xstack=inputs={n}:layout={layout}"
            f":fill=black{overlay_str}[vout]"
        )

        args += ["-filter_complex", ";".join(trim_parts), "-map", "[vout]"]
        if with_audio:
            args += ["-map", "[aout]"]
        args += ["-c:v", "libx264", "-preset", "fast", "-crf", "22"]
        if with_audio:
            args += ["-c:a", "aac", "-b:a", "128k"]

        args.append(str(cfg.output_path))
        return args

    # ------------------------------------------------------------------
    # FFmpeg runner
    # ------------------------------------------------------------------

    def _run_ffmpeg(self, args: list[str], total_seconds: float) -> None:
        full_args = args[:-1] + ["-progress", "pipe:1", "-nostats"] + [args[-1]]

        self._proc = subprocess.Popen(
            full_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
        )

        stderr_buf: list[str] = []

        def _drain() -> None:
            assert self._proc is not None
            for line in self._proc.stderr:  # type: ignore[union-attr]
                stderr_buf.append(line)

        t = threading.Thread(target=_drain, daemon=True)
        t.start()

        time_re = re.compile(r"out_time_ms=(\d+)")
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._cancelled:
                break
            m = time_re.search(line.strip())
            if m and total_seconds > 0:
                elapsed_s = int(m.group(1)) / 1_000_000
                self.progress.emit(min(99, int(elapsed_s / total_seconds * 100)))

        t.join()
        self._proc.wait()

        if self._cancelled:
            return

        if self._proc.returncode != 0:
            snippet = "".join(stderr_buf[-30:]).strip()
            raise RuntimeError(
                f"FFmpeg beendet mit Code {self._proc.returncode}.\n\n{snippet}"
            )

        self.progress.emit(100)


# ── Drawtext helper ───────────────────────────────────────────────────────────

def _drawtext(event_time: datetime) -> str:
    time_str  = event_time.strftime("%d.%m.%Y  %H\\:%M\\:%S")
    font_part = ""
    if sys.platform == "win32":
        font_part = "fontfile='C\\:/Windows/Fonts/arial.ttf':"
    return (
        f"drawtext={font_part}"
        f"text='{time_str}':"
        f"x=12:y=main_h-th-12:"
        f"fontsize=20:fontcolor=white:"
        f"box=1:boxcolor=black@0.65:boxborderw=6"
    )
