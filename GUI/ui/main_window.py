"""Main window: connection indicators + emergency stop on top, tabs in the middle, shared log at the bottom."""
import datetime
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QPlainTextEdit, QSplitter)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from albatross.controller import Controller
from albatross.workers.base import TaskWorker

from albatross.ui.tabs.connection_tab import ConnectionTab
from albatross.ui.tabs.jig_tab import JigTab
from albatross.ui.tabs.neware_tab import NewareTab
from albatross.ui.tabs.eis_tab import EisTab
from albatross.ui.tabs.automation_tab import AutomationTab
from albatross.ui.tabs.ot2_tab import Ot2Tab


class MainWindow(QMainWindow):
    log_message = pyqtSignal(str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.sim = cfg.get("app", {}).get("simulation", True)
        self.read_only = cfg.get("app", {}).get("read_only", False)
        self._workers = set()        # keeps workers from being garbage-collected
        self._log_entries = []       # (category, line) — per-tab log filter
        self._tab_cat = {}
        self._log_dir = cfg.get("app", {}).get("log_dir", "logs")   # folder for the daily log txt files

        # --- Controller (driver bundle + trigger entry point). Connecting happens in the Connection tab ---
        self.ctrl = Controller.build(cfg)
        self.neware, self.plc, self.biologic = self.ctrl.neware, self.ctrl.plc, self.ctrl.biologic
        self.robot = self.ctrl.robot
        self.ot2 = self.ctrl.ot2
        if self.read_only:                      # read-only: block writes on every driver (backup guard)
            for d in (self.plc, self.robot, self.ot2, self.neware):
                d.read_only = True

        title = "ALBATROSS control"
        if self.read_only:
            title += "  [READ ONLY — writes blocked]"
        elif self.sim:
            title += "  [Simultation]"
        self.setWindowTitle(title)
        self.resize(900, 680)
        self._build_ui()

    def writable(self):
        """Call at the top of every write/motion handler. Returns False and logs when read-only (action blocked)."""
        if self.read_only:
            self.log("[read-only] Motion and writes are blocked — set config app.read_only=false to enable them.")
            return False
        return True

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)

        root.addWidget(self._build_header())

        if self.read_only:                      # read-only notice banner
            ro = QLabel("● Read-only mode — connections and status reads only. All motion and writes are blocked.")
            ro.setStyleSheet("background:#7a2b2b; color:white; font-weight:bold; "
                             "padding:5px 10px; border-radius:4px;")
            root.addWidget(ro)

        self.tabs = QTabWidget()
        self.tab_conn = ConnectionTab(self)
        self.tab_jig = JigTab(self)
        self.tab_neware = NewareTab(self)
        self.tab_eis = EisTab(self)
        self.tab_auto = AutomationTab(self)
        self.tab_ot2 = Ot2Tab(self)
        self.tabs.addTab(self.tab_conn, "Connection")
        self.tabs.addTab(self.tab_ot2, "OT2 (Auto)")
        self.tabs.addTab(self.tab_auto, "Cell Assembly (Auto)")
        self.tabs.addTab(self.tab_neware, "Chg/DChg (Manual)")
        self.tabs.addTab(self.tab_eis, "EIS Measurement (Manual)")
        self.tabs.addTab(self.tab_jig, "Jig Control (Manual)")
        self._tab_cat = {self.tab_conn: "conn", self.tab_ot2: "ot2",
                         self.tab_auto: "auto", self.tab_neware: "neware",
                         self.tab_eis: "eis", self.tab_jig: "jig"}
        self.tabs.currentChanged.connect(self._refresh_log)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.tabs)
        split.addWidget(self.log_view)
        split.setSizes([480, 160])
        root.addWidget(split)

        self.setCentralWidget(central)
        self.log_message.connect(self._append_log)
        self.ot2.set_logger(self.log)
        self.robot.set_logger(self.log)
        self._sw_timer = QTimer(self)
        self._sw_timer.timeout.connect(self._poll_motor_switch)
        self._sw_timer.start(3000)            # poll the physical E-stop (MotorSwitch) every 3 s
        self.log("Program started" + (" (simulation mode)" if self.sim else ""))

    def _build_header(self):
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel("<b>ALBATROSS control</b>"))
        h.addStretch(1)
        self.pills = {}
        for key, name in (("neware", "Neware"), ("plc", "PLC"), ("biologic", "Biologic"), ("robot", "Robot Arm"), ("ot2", "OT2")):
            lbl = QLabel(f"● {name}")
            lbl.setStyleSheet(_pill_style(False))
            self.pills[key] = lbl
            h.addWidget(lbl)
        self.sw_lbl = QLabel("")
        self.sw_lbl.setStyleSheet("")
        h.addWidget(self.sw_lbl)
        self.code_stop_btn = QPushButton("Code Interrupt")
        self.code_stop_btn.setStyleSheet("background:#854F0B; color:white; font-weight:bold; padding:6px 14px;")
        self.code_stop_btn.clicked.connect(self.code_stop)
        h.addWidget(self.code_stop_btn)
        self._robot_paused = False
        self.robot_pause_btn = QPushButton("Robot Pause")
        self.robot_pause_btn.setStyleSheet(_ROBOT_PAUSE)
        self.robot_pause_btn.clicked.connect(self.toggle_robot_pause)
        h.addWidget(self.robot_pause_btn)
        self._estop_on = False
        self.estop_btn = QPushButton("Chg Robot stop off")
        self.estop_btn.setStyleSheet(_ESTOP_OFF)
        self.estop_btn.clicked.connect(self.toggle_estop)
        h.addWidget(self.estop_btn)
        return bar

    # ---------- Shared helpers ----------
    def log(self, msg):
        self.log_message.emit(msg)        # safe to call from any thread

    def _current_cat(self):
        return self._tab_cat.get(self.tabs.currentWidget(), "conn")

    def _append_log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"{ts}  {msg}"
        cat = self._current_cat()
        self._log_entries.append((cat, line))   # categorized by the current tab
        self.log_view.appendPlainText(line)
        self._write_log_file(cat, line)          # append to the daily txt file

    def _write_log_file(self, cat, line):
        """Append one log line to '<date>_<tab>_log.txt' (accumulates per day). Failures are ignored silently."""
        try:
            import os
            os.makedirs(self._log_dir, exist_ok=True)
            date = datetime.datetime.now().strftime("%y%m%d")
            label = _LOG_LABELS.get(cat, cat)
            path = os.path.join(self._log_dir, f"{date}_{label}_log.txt")
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _refresh_log(self):
        """On tab switch, re-display only the log lines belonging to that tab."""
        cat = self._current_cat()
        self.log_view.clear()
        for c, line in self._log_entries:
            if c == cat:
                self.log_view.appendPlainText(line)

    def set_pill(self, key, connected):
        if key in self.pills:
            self.pills[key].setStyleSheet(_pill_style(connected))

    def run_task(self, fn, *args, on_done=None, busy=None, **kwargs):
        """Run a blocking function on a worker thread. on_done(result) is invoked on the GUI thread."""
        w = TaskWorker(fn, *args, **kwargs)
        w.log.connect(self.log)
        w.failed.connect(lambda m: self.log("[Error] " + m))
        if on_done:
            w.done.connect(on_done)
        w.finished.connect(lambda: self._workers.discard(w))
        if busy is not None:
            busy.setEnabled(False)
            w.finished.connect(lambda: busy.setEnabled(True))
        self._workers.add(w)
        w.start()
        return w

    def code_stop(self):
        """Code interrupt — asks the automation loop to stop. Shows 'Interrupting...' until it
        stops, then 'Interrupted'."""
        self.log("=== Code interrupt ===")
        worker = getattr(self.tab_auto, "worker", None)
        if worker is None:
            self.log("No automation is running.")
            return
        self.code_stop_btn.setText("Interrupting...")

        def _done():
            self.code_stop_btn.setText("Interrupted")
            QTimer.singleShot(3000, lambda: self.code_stop_btn.setText("Code Interrupt"))
        worker.finished.connect(_done)
        try:
            self.tab_auto.stop_automation()
        except Exception:
            pass

    def toggle_estop(self):
        """Toggle emergency stop: OFF (green, fbMotorRelay=False) <-> ON (red, fbMotorRelay=True)."""
        if not self.writable():             # read-only: even a software stop is a write, so it is blocked (use the physical E-stop)
            return
        self._estop_on = not self._estop_on
        if self._estop_on:
            self.log("=== EMERGENCY STOP ON (fbMotorRelay=True) ===")
            try:
                self.tab_auto.stop_automation()
            except Exception:
                pass
            try:
                if self.plc.connected:
                    self.plc.set_motor_relay(True)
            except Exception as e:
                self.log(f"[error] emergency stop failed: {e}")
            self.estop_btn.setText("Chg Robot stop on")
            self.estop_btn.setStyleSheet(_ESTOP_ON)
        else:
            self.log("=== EMERGENCY STOP OFF (fbMotorRelay=False) ===")
            try:
                if self.plc.connected:
                    self.plc.set_motor_relay(False)
            except Exception as e:
                self.log(f"[error] emergency stop release failed: {e}")
            self.estop_btn.setText("Chg Robot stop off")
            self.estop_btn.setStyleSheet(_ESTOP_OFF)

    def toggle_robot_pause(self):
        """Toggle robot (xArm) pause: Pause (set_state 3) <-> Resume (set_state 0).
        Same as the pause button in Studio."""
        if not self.writable():             # read-only: robot pause/resume are writes, so they are blocked
            return
        if not self.robot.connected:
            self.log("[warning] The robot is not connected.")
            return
        self._robot_paused = not self._robot_paused
        if self._robot_paused:
            self.log("=== Robot paused ===")
            try:
                self.ctrl.robot_pause()
            except Exception as e:
                self.log(f"[error] robot pause failed: {e}")
            self.robot_pause_btn.setText("Robot Resume")
            self.robot_pause_btn.setStyleSheet(_ROBOT_PAUSED)
        else:
            self.log("=== Robot resumed — continuing with the next motion ===")
            try:
                self.ctrl.robot_resume()
            except Exception as e:
                self.log(f"[error] robot resume failed: {e}")
            self.robot_pause_btn.setText("Robot Pause")
            self.robot_pause_btn.setStyleSheet(_ROBOT_PAUSE)

    def _poll_motor_switch(self):
        if self.plc.connected:
            self.run_task(self.ctrl.read_motor_switch, on_done=self._update_switch_indicator)

    def _update_switch_indicator(self, pressed):
        if pressed:                       # MotorSwitch ON -> emergency stop
            self.sw_lbl.setText("E-STOP")
            self.sw_lbl.setStyleSheet("color:#A32D2D; background:#FCEBEB; border-radius:10px; padding:3px 10px;")
        else:                             # MotorSwitch OFF -> no indicator
            self.sw_lbl.setText("")
            self.sw_lbl.setStyleSheet("")

    def closeEvent(self, event):
        for w in list(self._workers):          # stop running workers (camera, etc.) first
            try:
                if hasattr(w, "stop"):
                    w.stop()
                w.wait(1500)
            except Exception:
                pass
        for c in (self.robot, self.biologic, self.plc, self.neware):
            try:
                (c.disconnect if hasattr(c, "disconnect") else c.close)()
            except Exception:
                pass
        super().closeEvent(event)


_ESTOP_OFF = "background:#0F6E56; color:white; font-weight:bold; padding:6px 14px;"  # green = E-stop OFF (normal)
_ESTOP_ON = "background:#A32D2D; color:white; font-weight:bold; padding:6px 14px;"   # red = E-stop ON
_ROBOT_PAUSE = "background:#3B5BA9; color:white; font-weight:bold; padding:6px 14px;"    # blue = robot pause button (normal)
_ROBOT_PAUSED = "background:#B8860B; color:white; font-weight:bold; padding:6px 14px;"   # amber = robot paused (awaiting resume)

# Log filename labels (tab category -> filename fragment). File: <date>_<label>_log.txt
_LOG_LABELS = {"conn": "Connection", "ot2": "OT2", "auto": "Automation",
               "neware": "ChgDChg", "eis": "EIS", "jig": "Jig"}


def _pill_style(state):
    if state == "connecting":            # connecting -> white
        return ("color:#5F5E5A; background:#FFFFFF; border:1px solid #B4B2A9; "
                "border-radius:10px; padding:3px 10px;")
    if state is True:                    # connected -> green
        return "color:#0F6E56; background:#E1F5EE; border-radius:10px; padding:3px 10px;"
    return "color:#A32D2D; background:#FCEBEB; border-radius:10px; padding:3px 10px;"
