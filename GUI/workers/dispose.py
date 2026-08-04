"""Jig disposal worker (QThread) — iterates a channel list to dispose, with stop support.
The loop itself lives in controller.dispose_channels."""
from PyQt6.QtCore import QThread, pyqtSignal


class DisposeWorker(QThread):
    log = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, ctrl, channels):
        super().__init__()
        self.ctrl = ctrl
        self.channels = list(channels)
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        try:
            self.ctrl.dispose_channels(
                self.channels, should_run=lambda: self._running, log=self.log.emit)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
