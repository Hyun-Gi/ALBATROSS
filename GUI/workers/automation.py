"""Automation worker (QThread) — handles threading/signals only.
The actual loop lives in automation_ops.run_cycle_server."""
from PyQt6.QtCore import QThread, pyqtSignal
from albatross.operations import automation_ops


class CycleServerWorker(QThread):
    log = pyqtSignal(str)
    measured = pyqtSignal(int, str)
    failed = pyqtSignal(str)

    def __init__(self, neware, plc, biologic, directory, check_ch,
                 eis_jig=1, eis_params=None, ocv_params=None, poll_interval=1.0):
        super().__init__()
        self.neware, self.plc, self.biologic = neware, plc, biologic
        self.directory = directory
        self.check_ch = list(check_ch)
        self.eis_jig = eis_jig
        self.eis_params = eis_params
        self.ocv_params = ocv_params
        self.poll_interval = poll_interval
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        try:
            automation_ops.run_cycle_server(
                self.neware, self.plc, self.biologic, self.directory, self.check_ch,
                eis_jig=self.eis_jig, params=self.eis_params, ocv_params=self.ocv_params,
                should_run=lambda: self._running, log=self.log.emit,
                on_measured=self.measured.emit, poll_interval=self.poll_interval)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
