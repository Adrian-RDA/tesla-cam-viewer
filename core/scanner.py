from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from core.event import TeslaEvent, load_event


class _ScanWorker(QRunnable):
    """Background worker — scans a folder and emits results via signals."""

    class Signals(QObject):
        event_found = Signal(object)   # TeslaEvent — Signal(object) for Python dataclasses
        progress = Signal(int, int)
        finished = Signal()

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.signals = _ScanWorker.Signals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        candidates = sorted(
            [d for d in self.root.iterdir() if d.is_dir()],
            reverse=True,  # newest first
        )
        total = len(candidates)
        for i, folder in enumerate(candidates):
            event = load_event(folder)
            if event is not None:
                self.signals.event_found.emit(event)
            self.signals.progress.emit(i + 1, total)
        self.signals.finished.emit()


class Scanner(QObject):
    """
    Async scanner for a TeslaCam SavedClips directory.

    Signals
    -------
    event_found(TeslaEvent)   — emitted for each successfully parsed event
    progress(int, int)        — (scanned, total) for progress bars
    finished()                — scan complete
    """

    event_found = Signal(object)   # TeslaEvent
    progress = Signal(int, int)
    finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()

    def scan(self, root: Path) -> None:
        """Start an async scan. Signals are emitted on the calling thread via Qt queued connections."""
        worker = _ScanWorker(root)
        worker.signals.event_found.connect(self.event_found)
        worker.signals.progress.connect(self.progress)
        worker.signals.finished.connect(self.finished)
        self._pool.start(worker)
