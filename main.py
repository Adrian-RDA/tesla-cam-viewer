from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow

_HERE = Path(__file__).parent
_APP_ID = "nexave.TeslaCamViewer.1"   # unique AUMID — Windows uses this for taskbar grouping


def _set_taskbar_icon() -> None:
    """
    Tell Windows to treat this process as its own app identity so the
    taskbar shows our custom icon instead of the generic Python icon.
    Must be called *before* the QApplication is created.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_ID)
    except AttributeError:
        pass   # non-Windows — silently ignore


def _load_style(app: QApplication) -> None:
    qss_path = _HERE / "resources" / "style.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))


def main() -> None:
    _set_taskbar_icon()   # must come first, before QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("TeslaCam Viewer")
    app.setOrganizationName("nexave")

    _load_style(app)

    icon_path = _HERE / "resources" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
