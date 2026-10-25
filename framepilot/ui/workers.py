from __future__ import annotations

import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    result = Signal(object)
    item = Signal(object)
    progress = Signal(int, int, str)
    error = Signal(str)
    finished = Signal()


class FunctionWorker(QRunnable):
    """Cancellable function runner. Target receives this worker as first argument."""

    def __init__(self, target: Callable, *args, **kwargs):
        super().__init__()
        self.target = target
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.cancelled = False

    @Slot()
    def run(self):
        try:
            result = self.target(self, *self.args, **self.kwargs)
            if result is not None:
                self.signals.result.emit(result)
        except Exception:
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()

    def cancel(self) -> None:
        self.cancelled = True

