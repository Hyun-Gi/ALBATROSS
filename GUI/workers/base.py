"""Generic background worker. Runs a blocking function on a separate thread so the GUI stays responsive."""
from PyQt6.QtCore import QThread, pyqtSignal


class TaskWorker(QThread):
    log = pyqtSignal(str)
    done = pyqtSignal(object)      # result on success
    failed = pyqtSignal(str)       # error message on failure

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.done.emit(result)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
