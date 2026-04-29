from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

CAMERAS = ("front", "back", "left_repeater", "right_repeater")
CAMERA_LABELS = {
    "front": "Front",
    "back": "Back",
    "left_repeater": "Links",
    "right_repeater": "Rechts",
}

_SEGMENT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})-("
    + "|".join(CAMERAS)
    + r")\.mp4$"
)

TRIGGER_LABELS = {
    "user_interaction_dashcam_launcher_action_tapped": "Manuell gespeichert",
    "user_interaction_honk": "Hupe",
    "sentry_aware_object_detection": "Sentry Mode",
    "sentry_mode": "Sentry Mode",
    "alert": "Alarm",
}


# ── MP4 duration reader ───────────────────────────────────────────────────────

def _mp4_duration(path: Path) -> float:
    """
    Read the actual playback duration (seconds) from an MP4 file
    by parsing its moov/mvhd box. No external dependencies required.
    Falls back to 60.0 on any error.
    """
    try:
        with path.open("rb") as f:
            while True:
                raw = f.read(8)
                if len(raw) < 8:
                    break
                size = int.from_bytes(raw[:4], "big")
                box_type = raw[4:8]

                if size == 1:          # 64-bit extended size
                    ext = f.read(8)
                    if len(ext) < 8:
                        break
                    size = int.from_bytes(ext, "big")
                    content_size = size - 16
                elif size == 0:        # box runs to EOF — skip
                    break
                else:
                    content_size = size - 8

                if box_type == b"moov":
                    moov = f.read(content_size)
                    idx = moov.find(b"mvhd")
                    if idx < 0:
                        return 60.0
                    # mvhd layout:
                    #  4 bytes  box size (already consumed)
                    #  4 bytes  'mvhd'  (already consumed via find)
                    #  1 byte   version, 3 bytes flags
                    data = moov[idx + 4:]          # data after 'mvhd' tag
                    version = data[0]
                    if version == 1:               # 64-bit timestamps
                        # +4 skip v+flags, +8 create, +8 modify → timescale at 20
                        timescale = int.from_bytes(data[20:24], "big")
                        duration  = int.from_bytes(data[24:32], "big")
                    else:                          # version 0, 32-bit timestamps
                        # +4 skip v+flags, +4 create, +4 modify → timescale at 12
                        timescale = int.from_bytes(data[12:16], "big")
                        duration  = int.from_bytes(data[16:20], "big")
                    if timescale > 0:
                        return duration / timescale
                    return 60.0
                else:
                    f.seek(content_size, 1)
    except Exception:
        pass
    return 60.0


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class TeslaEvent:
    folder: Path
    event_time: datetime
    city: str = ""
    lat: float = 0.0
    lon: float = 0.0
    reason: str = ""
    thumbnail: Path | None = None
    segments: dict[str, list[Path]] = field(default_factory=dict)
    # Actual measured duration — filled by load_event(), NOT a property
    actual_duration: float = field(default=0.0)

    @property
    def duration_seconds(self) -> float:
        """Total recorded duration in seconds (measured from MP4 headers)."""
        return self.actual_duration

    @property
    def trigger_label(self) -> str:
        return TRIGGER_LABELS.get(self.reason, self.reason.replace("_", " ").title())

    @property
    def display_time(self) -> str:
        return self.event_time.strftime("%d.%m.%Y  %H:%M:%S")

    @property
    def display_location(self) -> str:
        return self.city or f"{self.lat:.4f}, {self.lon:.4f}"

    @property
    def event_offset_seconds(self) -> float | None:
        """
        Seconds from the start of playback to the event trigger timestamp.

        Uses a clip-aware calculation: instead of comparing wall-clock offsets
        against the sum of clip durations (which always differ because clips have
        small timing gaps between them), we walk through each clip, accumulate
        the measured video position, and return the position the moment the clip's
        wall-clock window contains the event timestamp.

        Returns None if it cannot be determined or falls outside the clip range.
        """
        # Use CAMERAS priority order; take first camera that has clips
        ref_clips: list[Path] = []
        for cam in CAMERAS:
            clips = self.segments.get(cam, [])
            if clips:
                ref_clips = clips
                break

        if not ref_clips:
            return None

        cumulative = 0.0
        last_clip_end: datetime | None = None

        for clip in ref_clips:
            ts_part = clip.stem[:19]   # "2025-04-30_17-05-20"
            try:
                clip_start = datetime.strptime(ts_part, "%Y-%m-%d_%H-%M-%S")
            except ValueError:
                cumulative += _mp4_duration(clip)
                continue

            clip_dur = _mp4_duration(clip)
            clip_end = clip_start + timedelta(seconds=clip_dur)

            if clip_start <= self.event_time < clip_end:
                return cumulative + (self.event_time - clip_start).total_seconds()

            last_clip_end = clip_end
            cumulative += clip_dur

        # Tolerate the event_time falling slightly past the last clip's end
        # (≤ 30 s overrun), e.g. when the event fires right at clip boundary.
        if last_clip_end is not None:
            overrun = (self.event_time - last_clip_end).total_seconds()
            if 0.0 <= overrun < 30.0:
                return self.actual_duration

        return None

    def playlist(self, camera: str) -> list[str]:
        return [str(p) for p in self.segments.get(camera, [])]


def _compute_duration(segments: dict[str, list[Path]]) -> float:
    """Sum MP4 durations for the first available camera track."""
    for cam in CAMERAS:
        clips = segments.get(cam, [])
        if clips:
            return sum(_mp4_duration(p) for p in clips)
    return 0.0


def load_event(folder: Path) -> TeslaEvent | None:
    if not folder.is_dir():
        return None

    event_time = _parse_folder_timestamp(folder.name)
    if event_time is None:
        return None

    city = ""
    lat = lon = 0.0
    reason = ""
    json_path = folder / "event.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            city   = data.get("city", "")
            lat    = float(data.get("est_lat", 0))
            lon    = float(data.get("est_lon", 0))
            reason = data.get("reason", "")
            ts_str = data.get("timestamp", "")
            if ts_str:
                try:
                    event_time = datetime.fromisoformat(ts_str)
                except ValueError:
                    pass
        except Exception:
            pass

    thumbnail = folder / "thumb.png"
    if not thumbnail.exists():
        thumbnail = None

    segments: dict[str, list[Path]] = {cam: [] for cam in CAMERAS}
    for f in sorted(folder.iterdir()):
        m = _SEGMENT_RE.match(f.name)
        if m:
            segments[m.group(2)].append(f)

    if not any(segments.values()):
        return None

    # Measure actual duration from MP4 headers (fast — reads only a few KB per file)
    actual_duration = _compute_duration(segments)

    return TeslaEvent(
        folder=folder,
        event_time=event_time,
        city=city,
        lat=lat,
        lon=lon,
        reason=reason,
        thumbnail=thumbnail,
        segments=segments,
        actual_duration=actual_duration,
    )


def _parse_folder_timestamp(name: str) -> datetime | None:
    try:
        return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return None
