"""
Lightweight SVG icon renderer for TeslaCam Viewer.

Icons are defined as SVG strings (Heroicons-style, 24×24 viewBox).
Use make_icon() to get a QIcon at any size and color.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# ── SVG templates (use {c} as color placeholder) ──────────────────────────

_SVG_SKIP_BACK = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{c}">
  <rect x="5" y="5" width="2.5" height="14" rx="1.25"/>
  <path d="M19 5.5a1 1 0 0 0-1.6-.8l-9 6.5a1 1 0 0 0 0 1.6l9 6.5A1 1 0 0 0 19 18.5V5.5Z"/>
</svg>"""

_SVG_SKIP_FWD = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{c}">
  <rect x="16.5" y="5" width="2.5" height="14" rx="1.25"/>
  <path d="M5 5.5a1 1 0 0 1 1.6-.8l9 6.5a1 1 0 0 1 0 1.6l-9 6.5A1 1 0 0 1 5 18.5V5.5Z"/>
</svg>"""

_SVG_PLAY = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{c}">
  <path d="M6.5 4.5a1 1 0 0 1 1.53-.85l11 6.5a1 1 0 0 1 0 1.7l-11 6.5A1 1 0 0 1 6.5 17.5V4.5Z"/>
</svg>"""

_SVG_PAUSE = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{c}">
  <rect x="5.5" y="4" width="4" height="16" rx="1.5"/>
  <rect x="14.5" y="4" width="4" height="16" rx="1.5"/>
</svg>"""

_SVG_FOLDER = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="{c}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
  <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/>
</svg>"""

# Sidebar panel toggle — shows/hides the left panel
_SVG_PANEL_LEFT = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="{c}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="3" width="18" height="18" rx="2.5"/>
  <line x1="9" y1="3.5" x2="9" y2="20.5"/>
</svg>"""

# Export / download arrow icon
_SVG_EXPORT = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="{c}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 3v12m0 0-4-4m4 4 4-4"/>
  <path d="M3 17v2a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-2"/>
</svg>"""

# Public registry
ICONS: dict[str, str] = {
    "skip_back":   _SVG_SKIP_BACK,
    "skip_fwd":    _SVG_SKIP_FWD,
    "play":        _SVG_PLAY,
    "pause":       _SVG_PAUSE,
    "folder":      _SVG_FOLDER,
    "panel_left":  _SVG_PANEL_LEFT,
    "export":      _SVG_EXPORT,
}


def make_icon(name: str, size: int = 20, color: str = "#909090") -> QIcon:
    """Render a named SVG icon to a QIcon at *size*×*size* px with *color*."""
    svg_str = ICONS[name].replace("{c}", color)
    renderer = QSvgRenderer(QByteArray(svg_str.encode()))
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    renderer.render(painter)
    painter.end()
    return QIcon(px)


def make_dual_icon(name: str, size: int = 20,
                   color_normal: str = "#707070",
                   color_hover: str = "#e31937") -> QIcon:
    """Icon with Normal + Active states (for hover-like toggling via setIcon)."""
    icon = QIcon()
    icon.addPixmap(_render_px(name, size, color_normal), QIcon.Mode.Normal)
    icon.addPixmap(_render_px(name, size, color_hover),  QIcon.Mode.Active)
    icon.addPixmap(_render_px(name, size, color_hover),  QIcon.Mode.Selected)
    return icon


def _render_px(name: str, size: int, color: str) -> QPixmap:
    svg_str = ICONS[name].replace("{c}", color)
    renderer = QSvgRenderer(QByteArray(svg_str.encode()))
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    renderer.render(p)
    p.end()
    return px
