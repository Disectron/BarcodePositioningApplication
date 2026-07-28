"""Background export worker.

Export is the only unbounded work in the application, so it is the only thing
that runs off the GUI thread.

Qt thread rules observed here, all satisfied structurally rather than by
discipline:

* The worker never touches a widget. It communicates purely through signals.
* No QPixmap is created off the GUI thread - the PDF backend uses no Qt at all.
* The configuration snapshot is a frozen dataclass, so there is no aliasing
  between threads.
* Cancellation deletes any partial file, so a cancelled export never leaves
  something that looks like a valid strip behind.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from aops.core.config import AopsConfig
from aops.core.stats import DerivedGeometry
from aops.render.pdf.export import ExportCancelled, export_all
from aops.symbols.cache import SymbolCache


class ExportWorker(QObject):
    """Runs an export on a worker thread."""

    progress = Signal(int, int, str)  # done, total, phase
    finished = Signal(list)  # list[str] of written paths
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        cfg: AopsConfig,
        derived: DerivedGeometry,
        cache: SymbolCache,
        out_dir: Path,
        basename: str,
    ) -> None:
        super().__init__()
        self._cfg = cfg
        self._derived = derived
        self._cache = cache
        self._out_dir = out_dir
        self._basename = basename
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        try:
            results = export_all(
                self._cfg,
                self._derived,
                self._cache,
                self._out_dir,
                basename=self._basename,
                progress=lambda d, t, p: self.progress.emit(d, t, p),
                cancel=self._cancel,
            )
            written = [str(p) for r in results for p in r.paths]
            self.finished.emit(written)
        except ExportCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
