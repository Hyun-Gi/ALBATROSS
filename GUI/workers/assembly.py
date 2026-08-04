"""Assembly automation worker (QThread) — handles threading/signals only.
The actual loop lives in assembly_ops.run_assembly.

On a part mismatch (step_check failure) it emits the step_failed signal and the worker
blocks until the user presses [Continue] (resume()). The GUI has no stdin, so this is how
"pause assembly" is implemented.
"""
import threading
from PyQt6.QtCore import QThread, pyqtSignal


class AssemblyWorker(QThread):
    log = pyqtSignal(str)
    failed = pyqtSignal(str)
    step_failed = pyqtSignal(str, object, object)   # (part, comp_id, cell_id)
    cell_started = pyqtSignal(int)                  # cell assembly started (for progress display)
    cell_done = pyqtSignal(int)                     # cell assembly finished

    def __init__(self, ctrl, params):
        super().__init__()
        self.ctrl = ctrl
        self.params = params
        self._running = True
        self._resume = threading.Event()

    def stop(self):
        self._running = False
        self._resume.set()          # release a pending pause so the loop can exit

    def resume(self):
        self._resume.set()

    def _on_step_fail(self, part, comp_id, cell_id):
        """Called from the worker thread. Asks the GUI to pause, then blocks until the user continues."""
        self._resume.clear()
        self.step_failed.emit(part, comp_id, cell_id)
        self._resume.wait()

    def run(self):
        try:
            self.ctrl.run_assembly(
                should_run=lambda: self._running,
                log=self.log.emit,
                on_step_fail=self._on_step_fail,
                on_cell_start=self.cell_started.emit,
                on_cell_done=self.cell_done.emit,
                **self.params,
            )
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
