from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.event import TeslaEvent

_THUMB_W = 152
_THUMB_H = 86
_CARD_PAD = 8          # horizontal padding inside card
_SIDEBAR_W = 180       # default sidebar width


def _fmt_dur(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d} min"


class EventCard(QWidget):
    """Compact card: thumbnail + event metadata. Background is transparent."""

    def __init__(self, event: TeslaEvent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tesla_event = event
        # Make the widget background transparent so the list-item
        # hover/selection colour shows through without black boxes
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_CARD_PAD, 8, _CARD_PAD, 6)
        layout.setSpacing(3)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # ── Thumbnail ────────────────────────────────────────────────────
        thumb = QLabel()
        thumb.setFixedSize(_THUMB_W, _THUMB_H)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet("border-radius:4px; background:#0d0d0d;")
        if self.tesla_event.thumbnail and self.tesla_event.thumbnail.exists():
            px = QPixmap(str(self.tesla_event.thumbnail)).scaled(
                _THUMB_W, _THUMB_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            # Crop to exact size (KeepAspectRatioByExpanding may overshoot)
            if px.width() > _THUMB_W or px.height() > _THUMB_H:
                x = (px.width()  - _THUMB_W) // 2
                y = (px.height() - _THUMB_H) // 2
                px = px.copy(x, y, _THUMB_W, _THUMB_H)
            thumb.setPixmap(px)
        layout.addWidget(thumb, alignment=Qt.AlignmentFlag.AlignHCenter)

        # ── Labels ───────────────────────────────────────────────────────
        def lbl(text: str, obj_name: str) -> QLabel:
            l = QLabel(text)
            l.setObjectName(obj_name)
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setWordWrap(True)
            # Transparent so list hover colour shows through
            l.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            l.setAutoFillBackground(False)
            return l

        layout.addWidget(lbl(self.tesla_event.display_time,     "eventTime"))
        layout.addWidget(lbl(self.tesla_event.display_location, "eventLocation"))
        layout.addWidget(lbl(self.tesla_event.trigger_label,    "eventReason"))
        layout.addWidget(lbl(_fmt_dur(self.tesla_event.duration_seconds), "eventDuration"))


class EventList(QWidget):
    """
    Left sidebar: scrollable event list.

    Signals
    -------
    event_selected(object)   — emits a TeslaEvent
    """

    event_selected = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("EVENTS")
        header.setObjectName("sidebarHeader")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setFixedHeight(36)
        layout.addWidget(header)

        self._list = QListWidget()
        self._list.setObjectName("eventList")
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setSpacing(2)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list, stretch=1)

        # Allow the splitter to resize the sidebar (min / max instead of fixed)
        self.setMinimumWidth(160)
        self.setMaximumWidth(280)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_event(self, event: TeslaEvent) -> None:
        card = EventCard(event)
        item = QListWidgetItem()
        # Size hint: card height + spacing
        item.setSizeHint(card.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, event)
        self._list.addItem(item)
        self._list.setItemWidget(item, card)

    def clear(self) -> None:
        self._list.clear()

    def select_first(self) -> None:
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
            self._on_item_clicked(self._list.item(0))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        event: TeslaEvent = item.data(Qt.ItemDataRole.UserRole)
        if event:
            self.event_selected.emit(event)
