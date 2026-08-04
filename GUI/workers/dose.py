"""OT2 electrolyte dosing worker (QThread) — per-composition progress signals, with stop support.
The loop itself lives in controller.dose_range."""
from PyQt6.QtCore import QThread, pyqtSignal


class DoseWorker(QThread):
    log = pyqtSignal(str)
    failed = pyqtSignal(str)
    comp_started = pyqtSignal(int)     # dosing started for composition n
    comp_done = pyqtSignal(int)        # dosing finished for composition n

    def __init__(self, ctrl, n_from, n_to, heated=True):
        super().__init__()
        self.ctrl = ctrl
        self.n_from = n_from
        self.n_to = n_to
        self.heated = heated
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        try:
            self.ctrl.dose_range(
                self.n_from, self.n_to, heated=self.heated,
                should_run=lambda: self._running, log=self.log.emit,
                on_comp_start=self.comp_started.emit,
                on_comp_done=self.comp_done.emit)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
