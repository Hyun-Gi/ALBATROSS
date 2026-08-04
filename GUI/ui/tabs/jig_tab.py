"""Manual jig control tab — buttons/inputs only call Controller triggers (the motion logic lives in operations)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QPushButton, QLabel, QSpinBox, QDoubleSpinBox,
                             QLineEdit, QFileDialog, QGridLayout, QScrollArea,
                             QCheckBox)
from albatross.workers.dispose import DisposeWorker


# PLC global variables (name, type). i*/iPos = integer, everything else (b*/On/Clear) = boolean.
PLC_GLOBALS = [
    ("Actu.iIndex", "int"), ("Actu.bMove", "bool"), ("Actu.iPos", "int"),
    ("Motor1.bUp", "bool"), ("Motor1.bOrigin", "bool"),
    ("Motor2.bUp", "bool"), ("Motor2.bOrigin", "bool"),
    ("Motor3.bUp", "bool"), ("Motor3.bOrigin", "bool"),
    ("Motor4.bUp", "bool"), ("Motor4.bOrigin", "bool"),
    ("Crimper_On", "bool"),
    ("bCCS_aligncheck", "bool"), ("bAssem_aligncheck", "bool"), ("bPlate_aligncheck", "bool"),
    ("bJOB_idle", "bool"), ("bAt_readypos", "bool"),
    ("iCCSactu_seq", "int"), ("bCCSactu_move", "bool"),
    ("Program0.JOBList_Clear", "bool"),
]


class JigTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.dispose_worker = None
        v = QVBoxLayout(self)
        v.addWidget(self._coord_box())      # jig coordinate upload — at the top
        v.addWidget(self._jig_box())
        v.addWidget(self._dispose_box())
        v.addWidget(self._motor_box())
        v.addWidget(self._globals_box())    # read/write PLC global variables
        v.addLayout(self._cam_row(), 1)     # live cameras at the bottom (prodtracker excluded)

    def _cam_row(self):
        """Live cameras at the bottom — two panels excluding prodtracker (Camera = live, the other
        a placeholder for a future addition). Reuses the automation tab widgets; CameraView starts
        automatically once the tab becomes visible."""
        from albatross.ui.tabs.automation_tab import CameraView, big_panel
        row = QHBoxLayout()
        self.cam_live = CameraView(self.main, "Camera")        # live (starts automatically)
        self.cam_future = big_panel("To be added later")       # placeholder for a second camera
        row.addWidget(self.cam_live, 1)
        row.addWidget(self.cam_future, 1)
        return row

    def _require_plc(self):
        if not self.main.writable():        # read-only: block all jig motion/writes
            return False
        if not self.main.plc.connected:
            self.main.log("[Warning] The PLC is not connected.")
            return False
        return True

    def _require_conn(self):
        """For reads — only checks the connection (passes even in read-only mode)."""
        if not self.main.plc.connected:
            self.main.log("[Warning] The PLC is not connected.")
            return False
        return True

    def _send_job(self, job, index=0):
        if not self._require_plc():
            return
        self.main.log(f"JOB -> sending [{job}, {index}]")
        self.main.run_task(self.main.ctrl.jigjob_checked, job, index, log=self.main.log)

    def _jig_box(self):
        box = QGroupBox("Jig Motion")
        v = QVBoxLayout(box)

        row1 = QHBoxLayout()
        b_origin = QPushButton("Return to Origin"); b_origin.clicked.connect(lambda: self._send_job("Jig_Origin"))
        b_ready = QPushButton("Ready Position");  b_ready.clicked.connect(lambda: self._send_job("Jig_Readypos"))
        row1.addWidget(b_origin); row1.addWidget(b_ready); row1.addStretch(1)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Jig Channel (0–47)"))
        self.jig_ch = QSpinBox(); self.jig_ch.setRange(0, self.main.cfg.get("plc", {}).get("jig_channels", 48) - 1)
        row2.addWidget(self.jig_ch)
        b_ji = QPushButton("Jig insert");   b_ji.clicked.connect(lambda: self._send_job("Jig_Insert", self.jig_ch.value()))
        b_jr = QPushButton("Jig retrieve"); b_jr.clicked.connect(lambda: self._send_job("Jig_Retrieve", self.jig_ch.value()))
        row2.addWidget(b_ji); row2.addWidget(b_jr); row2.addStretch(1)
        v.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("EIS Channel (0–1)"))
        self.eis_ch = QSpinBox(); self.eis_ch.setRange(0, self.main.cfg.get("plc", {}).get("eis_channels", 2) - 1)
        row3.addWidget(self.eis_ch)
        b_ei = QPushButton("EIS insert");   b_ei.clicked.connect(lambda: self._send_job("EIS_Insert", self.eis_ch.value()))
        b_er = QPushButton("EIS retrieve"); b_er.clicked.connect(lambda: self._send_job("EIS_Retrieve", self.eis_ch.value()))
        row3.addWidget(b_ei); row3.addWidget(b_er); row3.addStretch(1)
        v.addLayout(row3)
        return box

    # ---------- Jig disposal ----------
    def _dispose_box(self):
        box = QGroupBox("Jig Disposal")
        v = QVBoxLayout(box)
        maxch = self.main.cfg.get("plc", {}).get("jig_channels", 48) - 1
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Channel Range"))
        self.dispos_from = QSpinBox(); self.dispos_from.setRange(0, maxch); self.dispos_from.setValue(0)
        self.dispos_to = QSpinBox(); self.dispos_to.setRange(0, maxch); self.dispos_to.setValue(maxch)
        r1.addWidget(self.dispos_from); r1.addWidget(QLabel("~")); r1.addWidget(self.dispos_to)
        self.btn_dispos = QPushButton("Start Disposal"); self.btn_dispos.clicked.connect(self._start_dispose)
        self.btn_dispos_stop = QPushButton("Stop"); self.btn_dispos_stop.setEnabled(False)
        self.btn_dispos_stop.clicked.connect(self._stop_dispose)
        r1.addWidget(self.btn_dispos); r1.addWidget(self.btn_dispos_stop); r1.addStretch(1)
        v.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Or enter directly"))
        self.dispos_text = QLineEdit()
        self.dispos_text.setPlaceholderText("e.g. 0,1,5,12  or  0-5,10-12   (leave empty to use the range above)")
        r2.addWidget(self.dispos_text)
        v.addLayout(r2)
        return box

    def _get_dispos_channels(self):
        """Parse the direct-entry field when filled (0,1,5 / 0-5,10-12); otherwise use the range.
        Only 0..maxch are accepted."""
        maxch = self.main.cfg.get("plc", {}).get("jig_channels", 48) - 1
        text = self.dispos_text.text().strip()
        if not text:
            return list(range(self.dispos_from.value(), self.dispos_to.value() + 1))
        try:
            chans = []
            for part in text.replace(" ", "").split(","):
                if not part:
                    continue
                if "-" in part:
                    a, b = part.split("-", 1)
                    chans.extend(range(int(a), int(b) + 1))
                else:
                    chans.append(int(part))
        except ValueError:
            self.main.log("[Warning] Invalid channel input format (e.g. 0,1,5,12 or 0-5,10-12)")
            return []
        chans = sorted(set(c for c in chans if 0 <= c <= maxch))
        if not chans:
            self.main.log(f"[Warning] No valid disposal channels (must be within 0-{maxch}).")
        return chans

    def _start_dispose(self):
        if self.dispose_worker or not self._require_plc():
            return
        if not self.main.robot.connected:
            self.main.log("[Warning] The robot is not connected (disposal needs tcp(20)).")
            return
        chans = self._get_dispos_channels()
        if not chans:
            return
        self.main.log(f"Jig disposal started: channels {chans}")
        w = DisposeWorker(self.main.ctrl, chans)
        w.log.connect(self.main.log)
        w.failed.connect(lambda m: self.main.log("[Error] " + m))
        w.finished.connect(self._dispose_done)
        self.dispose_worker = w
        self.main._workers.add(w)
        w.start()
        self.btn_dispos.setText("Disposing..."); self.btn_dispos.setEnabled(False)
        self.btn_dispos_stop.setEnabled(True)

    def _stop_dispose(self):
        if self.dispose_worker:
            self.dispose_worker.stop()
        self.btn_dispos_stop.setText("Stopping..."); self.btn_dispos_stop.setEnabled(False)
        self.main.log("Jig disposal stop requested... (stops after the current channel)")

    def _dispose_done(self):
        self.main._workers.discard(self.dispose_worker)
        self.dispose_worker = None
        self.btn_dispos.setText("Start Disposal"); self.btn_dispos.setEnabled(True)
        self.btn_dispos_stop.setText("Stop"); self.btn_dispos_stop.setEnabled(False)

    # ---------- PLC global variables (read/write) ----------
    def _globals_box(self):
        box = QGroupBox("PLC Global Variables (read / write)")
        outer = QVBoxLayout(box)
        top = QHBoxLayout()
        b_read = QPushButton("Read All (refresh)"); b_read.clicked.connect(self._read_globals)
        top.addWidget(b_read)
        top.addWidget(QLabel("int = type a number · bool = check (True) / uncheck (False), then press 'Write'"))
        top.addStretch(1)
        outer.addLayout(top)

        area = QScrollArea(); area.setWidgetResizable(True); area.setMaximumHeight(240)
        inner = QWidget(); grid = QGridLayout(inner)
        grid.setContentsMargins(4, 4, 4, 4); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(3)
        for c, t in enumerate(("Variable", "Current", "Input", "")):
            grid.addWidget(QLabel(f"<b>{t}</b>"), 0, c)
        self._glob = {}     # name -> (type, input_widget, value_label)
        for r, (name, typ) in enumerate(PLC_GLOBALS, start=1):
            grid.addWidget(QLabel(name), r, 0)
            val = QLabel("—"); val.setMinimumWidth(56); val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(val, r, 1)
            if typ == "int":
                inp = QSpinBox(); inp.setRange(-2147483647, 2147483647)
            else:
                inp = QCheckBox("True")
            grid.addWidget(inp, r, 2)
            b_w = QPushButton("Write"); b_w.setFixedWidth(52)
            b_w.clicked.connect(lambda _=False, n=name: self._write_global(n))
            grid.addWidget(b_w, r, 3)
            self._glob[name] = (typ, inp, val)
        grid.setColumnStretch(0, 1)
        area.setWidget(inner)
        outer.addWidget(area)
        return box

    def _read_globals(self):
        """Read and display the current value of every global (also mirrored into the input field).
        Works in read-only mode too."""
        if not self._require_conn():
            return
        ok = 0
        for name, (typ, inp, val) in self._glob.items():
            try:
                v = self.main.plc.read(name)
            except Exception:
                val.setText("ERR"); continue
            if v is None:
                val.setText("—"); continue
            if typ == "int":
                try:
                    iv = int(v); val.setText(str(iv)); inp.setValue(iv)
                except Exception:
                    val.setText(str(v))
            else:
                bv = v.strip().lower() in ("1", "true", "on") if isinstance(v, str) else bool(v)
                val.setText("True" if bv else "False"); inp.setChecked(bv)
            ok += 1
        self.main.log(f"PLC global variable read: {ok}/{len(self._glob)}")

    def _write_global(self, name):
        """Write the input value to that variable. Blocked by writable() in read-only mode."""
        if not self.main.writable() or not self._require_conn():
            return
        typ, inp, val = self._glob[name]
        value = int(inp.value()) if typ == "int" else bool(inp.isChecked())
        try:
            self.main.plc.send(name, value)
            val.setText(str(value) if typ == "int" else ("True" if value else "False"))
            self.main.log(f"PLC global write: {name} = {value}")
        except Exception as e:
            self.main.log(f"[Error] failed to write {name}: {e}")

    def _motor_box(self):
        box = QGroupBox("Motor Parameters (shared by all 4 axes)")
        h = QHBoxLayout(box)
        self.vel = self._spin(200.0); self.accel = self._spin(200.0); self.decel = self._spin(200.0)
        h.addWidget(QLabel("Velocity")); h.addWidget(self.vel)
        h.addWidget(QLabel("Accel")); h.addWidget(self.accel)
        h.addWidget(QLabel("Decel")); h.addWidget(self.decel)
        b_apply = QPushButton("Apply")

        def apply():
            if not self._require_plc():
                return
            self.main.log("Applying motor parameters")
            self.main.run_task(self.main.ctrl.set_motors,
                               vel=self.vel.value(), accel=self.accel.value(),
                               decel=self.decel.value(), busy=b_apply)
        b_apply.clicked.connect(apply)
        h.addWidget(b_apply); h.addStretch(1)
        return box

    def _coord_box(self):
        box = QGroupBox("Jig Coordinate Upload (Excel -> Jigmove_csv / EISmove_csv)")
        h = QHBoxLayout(box)
        # NOTE: this default points at an actual file on disk — the Korean filename is left as-is.
        self.coord_path = QLineEdit("C:/Users/HOME/Desktop/ethercat 지그 좌표.xlsx")
        h.addWidget(self.coord_path)
        b_browse = QPushButton("Browse"); b_browse.clicked.connect(self._browse)
        h.addWidget(b_browse)
        b_up = QPushButton("Upload")

        def upload():
            if not self._require_plc():
                return
            self.main.log("Uploading coordinates...")
            self.main.run_task(self.main.ctrl.upload_coordinates, self.coord_path.text(),
                               busy=b_up, on_done=lambda r: self.main.log(f"Coordinate upload complete: jig {r[0]} / eis {r[1]}"))
        b_up.clicked.connect(upload)
        h.addWidget(b_up)
        return box

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Coordinate Excel File", "", "Excel (*.xlsx *.xls)")
        if path:
            self.coord_path.setText(path)

    @staticmethod
    def _spin(val):
        s = QDoubleSpinBox(); s.setRange(0, 100000); s.setValue(val); return s
