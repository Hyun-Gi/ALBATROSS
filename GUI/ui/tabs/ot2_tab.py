"""OT2 tab — basic control + electrolyte dosing (formulate) + plate layout / required amounts / composition table views."""
import re
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QPushButton, QLabel, QSpinBox, QDoubleSpinBox,
                             QLineEdit, QCheckBox, QDialog, QTableWidget,
                             QTableWidgetItem, QTextEdit, QFileDialog)
from albatross.workers.dose import DoseWorker
from albatross.ui.tabs.automation_tab import CellProgressWidget


class Ot2Tab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.dose_worker = None
        self._dose_running = False
        v = QVBoxLayout(self)
        v.addWidget(self._basic_box())
        v.addWidget(self._dose_box())
        v.addStretch(1)

    def _require(self, *clients):
        if not self.main.writable():        # read-only: block OT2 writes (temperature, dosing, etc.)
            return False
        for c, name in clients:
            if not c.connected:
                self.main.log(f"[Warning] {name} is not connected.")
                return False
        return True

    # ---------- Basic control ----------
    def _basic_box(self):
        box = QGroupBox("Basic Control")
        v = QVBoxLayout(box)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Temperature (°C)"))
        self.temp = QDoubleSpinBox(); self.temp.setRange(0, 99); self.temp.setValue(35)
        r1.addWidget(self.temp)
        b_set = QPushButton("Set Temp")
        b_set.clicked.connect(lambda: self._do(
            lambda: self.main.ctrl.ot2_set_temp(self.temp.value()),
            f"Set temperature {self.temp.value():.0f}°C"))
        b_off = QPushButton("Temp Off")
        b_off.clicked.connect(lambda: self._do(self.main.ctrl.ot2_deactivate_temp, "Temp off"))
        r1.addWidget(b_set); r1.addWidget(b_off); r1.addStretch(1)
        v.addLayout(r1)
        r2 = QHBoxLayout()
        b_home = QPushButton("Home")
        b_home.clicked.connect(lambda: self._do(self.main.ctrl.ot2_home, "Home"))
        b_out = QPushButton("View OT2 Output")
        b_out.clicked.connect(self._show_output)
        r2.addWidget(b_home); r2.addWidget(b_out); r2.addStretch(1)
        v.addLayout(r2)
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Direct Command"))
        self.cmd = QLineEdit(); self.cmd.setPlaceholderText("e.g. protocol.set_rail_lights(True)")
        r3.addWidget(self.cmd)
        b_send = QPushButton("Send"); b_send.clicked.connect(self._send_cmd)
        r3.addWidget(b_send)
        v.addLayout(r3)
        return box

    def _do(self, fn, msg):
        if not self._require((self.main.ot2, "OT2")):
            return
        self.main.log(f"OT2: {msg}")
        self.main.run_task(fn)

    def _send_cmd(self):
        if not self._require((self.main.ot2, "OT2")):
            return
        c = self.cmd.text().strip()
        if c:
            self.main.run_task(self.main.ctrl.ot2_raw, c)

    def _show_output(self):
        if not self._require((self.main.ot2, "OT2")):
            return
        self.main.run_task(self.main.ctrl.ot2_get_output,
                           on_done=lambda o: self.main.log(f"OT2 ▶ {o}"))

    # ---------- Electrolyte dosing ----------
    def _dose_box(self):
        box = QGroupBox("Electrolyte Dosing (formulate)")
        v = QVBoxLayout(box)

        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Recipe CSV"))
        self.recipe_path = QLineEdit(self.main.cfg.get("ot2", {}).get("recipe_csv", ""))
        self.recipe_path.editingFinished.connect(
            lambda: self.main.ctrl.set_recipe_csv(self.recipe_path.text()))
        r0.addWidget(self.recipe_path)
        b_browse = QPushButton("Browse"); b_browse.clicked.connect(self._browse_recipe)
        r0.addWidget(b_browse)
        v.addLayout(r0)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Composition No."))
        self.n_from = QSpinBox(); self.n_from.setRange(0, 95)
        self.n_to = QSpinBox(); self.n_to.setRange(0, 95); self.n_to.setValue(5)
        r1.addWidget(self.n_from); r1.addWidget(QLabel("~")); r1.addWidget(self.n_to)
        self.heated = QCheckBox("Use heating (salt solution plate10)"); self.heated.setChecked(True)
        r1.addWidget(self.heated); r1.addStretch(1)
        v.addLayout(r1)

        # View / check buttons
        rv = QHBoxLayout()
        b_map = QPushButton("View Plate Layout"); b_map.clicked.connect(self._show_plate_map)
        b_amt = QPushButton("Required Volumes"); b_amt.clicked.connect(self._show_amounts)
        b_sel = QPushButton("View Selected (No.)"); b_sel.clicked.connect(self._show_recipe_sel)
        b_rec = QPushButton("View All Composition Table"); b_rec.clicked.connect(self._show_recipe_all)
        rv.addWidget(b_map); rv.addWidget(b_amt); rv.addWidget(b_sel); rv.addWidget(b_rec); rv.addStretch(1)
        v.addLayout(rv)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Tiprack Reset  Pipette0"))
        self.p0 = QSpinBox(); self.p0.setRange(0, 96)
        r2.addWidget(self.p0)
        r2.addWidget(QLabel("Pipette1"))
        self.p1 = QSpinBox(); self.p1.setRange(0, 96)
        r2.addWidget(self.p1)
        b_tip = QPushButton("Apply"); b_tip.clicked.connect(self._set_tiprack)
        r2.addWidget(b_tip); r2.addStretch(1)
        v.addLayout(r2)

        r3 = QHBoxLayout()
        self.btn_dose = QPushButton("Start Dosing"); self.btn_dose.clicked.connect(self._start_dose)
        self.btn_dose_stop = QPushButton("Stop Dosing"); self.btn_dose_stop.setEnabled(False)
        self.btn_dose_stop.clicked.connect(self._stop_dose)
        r3.addWidget(self.btn_dose); r3.addWidget(self.btn_dose_stop); r3.addStretch(1)
        v.addLayout(r3)
        self.dose_progress = CellProgressWidget(per_row=12)   # composition squares (filled in when done)
        v.addWidget(self.dose_progress)
        return box

    # ----- View dialogs -----
    def _show_plate_map(self):
        try:
            mapping = self.main.ctrl.plate_mapping(self.heated.isChecked())
        except Exception as e:
            self.main.log(f"[Error] Plate map: {e}"); return
        plates = {}
        for sol, loc in mapping.items():
            m = re.match(r"(\w+)\['?([A-Za-z])(\d+)'?\]", loc)
            if m:
                plates.setdefault(m.group(1), {})[(m.group(2), int(m.group(3)))] = sol
        dlg = QDialog(self); dlg.setWindowTitle("Plate Layout (Solution Positions)")
        lay = QVBoxLayout(dlg)
        if not plates:
            lay.addWidget(QLabel("plate_mapping is empty."))
        for plate, wells in plates.items():
            lay.addWidget(QLabel(f"<b>{plate}</b>"))
            dims = self.main.cfg.get("ot2", {}).get("plate_dims", {}).get(plate)
            if dims:                                   # plate size from config (show empty wells too)
                nr, nc = int(dims["rows"]), int(dims["cols"])
            else:                                      # otherwise up to last used row/col
                nr = ord(max(r for r, _ in wells)) - ord("A") + 1
                nc = max(c for _, c in wells)
            rows = [chr(ord("A") + i) for i in range(nr)]   # A..(A+nr-1)
            cols = list(range(1, nc + 1))                    # 1..nc
            t = QTableWidget(len(rows), len(cols))
            t.setHorizontalHeaderLabels([str(c) for c in cols])
            t.setVerticalHeaderLabels(rows)
            t.setShowGrid(True)
            t.setStyleSheet("QTableWidget{ gridline-color:#FFFFFF; }")   # white separators
            for (r, c), sol in wells.items():
                t.setItem(rows.index(r), cols.index(c), QTableWidgetItem(sol))
            for c in range(len(cols)):
                t.setColumnWidth(c, 140)        # uniform column width
            for r in range(len(rows)):
                t.setRowHeight(r, 28)           # uniform row height
            lay.addWidget(t)
        dlg.resize(780, 460); dlg.exec()

    def _show_amounts(self):
        a, b = self.n_from.value(), self.n_to.value()
        try:
            amts = self.main.ctrl.required_amounts(a, b, include_zero=True)   # also show 0 µL components
        except Exception as e:
            self.main.log(f"[Error] Failed to compute required amounts (check recipe CSV): {e}"); return
        lines = [f"Solution volumes required for compositions {a} ~ {b}", ""]
        for comp, ul in amts.items():                    # display order (salt first, solvents PC-EMC-DPE-DME-DEGDME-CME)
            lines.append(f"  {comp:18s}: {ul:8.0f} µL")
        if not amts:
            lines.append("  (no solution needed / check range)")
        dlg = QDialog(self); dlg.setWindowTitle("Required Volumes")
        lay = QVBoxLayout(dlg)
        te = QTextEdit(); te.setReadOnly(True); te.setPlainText("\n".join(lines))
        te.setStyleSheet("font-family: monospace;")
        lay.addWidget(te); dlg.resize(380, 380); dlg.exec()

    def _show_recipe_all(self):
        self._show_recipe()

    def _show_recipe_sel(self):
        self._show_recipe(self.n_from.value(), self.n_to.value())

    def _show_recipe(self, n_from=None, n_to=None):
        try:
            df = self.main.ctrl.get_result_df()
        except Exception as e:
            self.main.log(f"[Error] Failed to load composition table (check recipe CSV): {e}"); return
        title = "Composition / Dose Table (result_df) — All"
        if n_from is not None:
            df = df.loc[n_from:n_to]                       # Composition No. range (inclusive)
            title = f"Composition Table — No. {n_from} ~ {n_to}"
            if df.empty:
                self.main.log(f"[Info] No rows fall in the composition range {n_from}-{n_to}.")
        dlg = QDialog(self); dlg.setWindowTitle(title)
        lay = QVBoxLayout(dlg)
        t = QTableWidget(len(df), len(df.columns))
        t.setHorizontalHeaderLabels([str(c) for c in df.columns])
        t.setVerticalHeaderLabels([str(i) for i in df.index])
        for r in range(len(df)):
            for c in range(len(df.columns)):
                t.setItem(r, c, QTableWidgetItem(str(df.iat[r, c])))
        t.resizeColumnsToContents()
        lay.addWidget(t); dlg.resize(820, 500); dlg.exec()

    def _browse_recipe(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Recipe CSV", "", "CSV (*.csv)")
        if path:
            self.recipe_path.setText(path)
            self.main.ctrl.set_recipe_csv(path)
            self.main.log(f"Recipe CSV set: {path}")

    # ----- Tiprack / dosing -----
    def _set_tiprack(self):
        if not self._require((self.main.plc, "PLC")):
            return
        self.main.log(f"Tiprack reset: Pipette0={self.p0.value()}, Pipette1={self.p1.value()}")
        self.main.run_task(self.main.ctrl.set_tiprack, self.p0.value(), self.p1.value())

    def _start_dose(self):
        if self.dose_worker or not self._require((self.main.ot2, "OT2"), (self.main.plc, "PLC")):
            return
        a, b, heated = self.n_from.value(), self.n_to.value(), self.heated.isChecked()
        if b < a:
            self.main.log("[Warning] Composition range invalid (from > to).")
            return
        self._dose_a = a
        self.dose_progress.setup(list(range(a, b + 1)))          # composition squares
        w = DoseWorker(self.main.ctrl, a, b, heated)
        w.log.connect(self.main.log)
        w.failed.connect(lambda m: self.main.log("[Error] " + m))
        w.comp_started.connect(lambda n: self.dose_progress.set_active(n - self._dose_a))
        w.comp_done.connect(lambda n: self.dose_progress.set_done(n - self._dose_a))
        w.finished.connect(self._dose_done)
        self.dose_worker = w
        self.main._workers.add(w)
        w.start()
        self.btn_dose.setText("Dosing..."); self.btn_dose.setEnabled(False)
        self.btn_dose_stop.setEnabled(True)

    def _stop_dose(self):
        if self.dose_worker:
            self.dose_worker.stop()
        self.btn_dose_stop.setText("Stopping..."); self.btn_dose_stop.setEnabled(False)
        self.main.log("Stop dosing requested... (stops after current composition)")

    def _dose_done(self):
        self.main._workers.discard(self.dose_worker)
        self.dose_worker = None
        self.btn_dose.setText("Start Dosing"); self.btn_dose.setEnabled(True)
        self.btn_dose_stop.setText("Stop Dosing"); self.btn_dose_stop.setEnabled(False)
