"""Automation tab — cell assembly automation (two modes).

  Mode A · Assembly only        : assemble -> crimp -> return to storage rack
  Mode B · Assembly + cycling   : assemble -> crimp -> insert into cycler + neware_start

On a part mismatch (step_check) assembly pauses and a dialog asks for [Continue] / [Stop].
(The original EIS auto-measurement server run_cycle_server is preserved as-is in
controller.run_automation.)
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QPushButton, QLabel, QSpinBox, QLineEdit,
                             QRadioButton, QButtonGroup, QFileDialog, QMessageBox,
                             QGridLayout, QSizePolicy)
from PyQt6.QtCore import Qt, QTimer
from albatross.workers.assembly import AssemblyWorker


_CP_EMPTY = "border:2px solid #B4B2A9; background:#FFFFFF; color:#5F5E5A; border-radius:6px; font-weight:bold;"
_CP_DONE  = "border:2px solid #0F6E56; background:#0F6E56; color:white; border-radius:6px; font-weight:bold;"
_CP_ON    = "border:2px solid #B8860B; background:#F3D28A; color:#5F3B00; border-radius:6px; font-weight:bold;"
_CP_OFF   = "border:2px solid #B8860B; background:#FFFFFF; color:#B8860B; border-radius:6px; font-weight:bold;"

_PANEL_STYLE = "background:#12333d; color:#e8f4f8; border:1px solid #2b6b7a; font-size:18px;"


def camera_source(cfg):
    """config(vision) -> camera source. Returns an RTSP URL (str) when camera_ip is set,
    otherwise a webcam index (int).
    The password stays in config only and is URL-encoded here (never hardcode it)."""
    vis = cfg.get("vision", {})
    ip = str(vis.get("camera_ip", "") or "").strip()
    if ip:
        from urllib.parse import quote
        user = str(vis.get("camera_user", "admin"))
        pw = quote(str(vis.get("camera_pass", "")), safe="")
        ch = str(vis.get("camera_channel", "102"))
        return f"rtsp://{user}:{pw}@{ip}:554/Streaming/Channels/{ch}"
    return int(vis.get("camera_index", 0))


def big_panel(text):
    """Large placeholder panel — e.g. for prodtracker. Expands to the same size as the camera panels."""
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setMinimumHeight(300)
    lbl.setStyleSheet(_PANEL_STYLE)
    lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return lbl


class LatestImageView(QLabel):
    """prodtracker panel — by default (Live Off) it periodically shows the newest saved image in
    the folder; toggling Live On switches to the live camera. Falls back to the title text when
    the folder or images are missing. Rescales with the window.
    The Live toggle is exposed as self.btn_live (placed below, outside the box)."""
    _EXTS = ("*.png", "*.jpg", "*.jpeg", "*.bmp")

    def __init__(self, main, title="prodtracker", folder="", interval_ms=3000):
        super().__init__(title)
        self.main = main
        self._title = title
        self.folder = folder or ""
        self._interval = interval_ms
        self._files = []                 # images newest-first (0 = newest)
        self._idx = 0                    # currently viewed position
        self._cur = None                 # path of the file currently displayed
        self._loaded = None              # last loaded file (skips reloading when unchanged)
        self._pixmap = None              # original pixmap (for rescaling)
        self.worker = None               # live camera worker (only while Live On)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(300)
        self.setStyleSheet(_PANEL_STYLE)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        # Controls (below, outside the box): ◀ position ▶ · Live toggle
        self.btn_prev = QPushButton("◀"); self.btn_prev.setFixedWidth(34)
        self.btn_prev.setToolTip("Newer image"); self.btn_prev.clicked.connect(self.prev)
        self.btn_next = QPushButton("▶"); self.btn_next.setFixedWidth(34)
        self.btn_next.setToolTip("Older image"); self.btn_next.clicked.connect(self.next)
        self.lbl_counter = QLabel("0/0"); self.lbl_counter.setMinimumWidth(54)
        self.lbl_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_live = QPushButton("Live On")     # Off by default -> press to go live
        self.btn_live.setCheckable(True)
        self.btn_live.toggled.connect(self._on_live_toggled)
        if self.folder:
            self._timer.start(interval_ms)
        self.refresh()                   # initial display (0/0 when there is no folder)

    # ---- Live Off: saved-image browser (newest first, ◀ ▶) ----
    def _scan(self):
        import glob
        import os
        if not self.folder or not os.path.isdir(self.folder):
            return []
        files = []
        for ext in self._EXTS:
            files += glob.glob(os.path.join(self.folder, "**", ext), recursive=True)
        files.sort(key=os.path.getmtime, reverse=True)   # newest first
        return files

    def refresh(self):
        """Rescan the folder. If the newest image (position 0) is being viewed, follow new images
        automatically; while browsing back, keep the image currently shown."""
        old = self._cur
        self._files = self._scan()
        if not self._files:
            self._idx = 0; self._cur = None; self._loaded = None; self._pixmap = None
            self.setText(self._title); self._update_nav(); return
        if self._idx == 0 or old not in self._files:
            self._idx = 0                                 # follow the newest automatically
        else:
            self._idx = self._files.index(old)            # keep the image being viewed
        self._show_current()

    def _show_current(self):
        from PyQt6.QtGui import QPixmap
        path = self._files[self._idx]
        self._cur = path
        if path != self._loaded:                          # skip reloading the same file (avoids flicker)
            pm = QPixmap(path)
            if not pm.isNull():
                self._pixmap = pm; self._loaded = path
                self._apply()
        self._update_nav()

    def prev(self):      # ◀ newer
        if self._idx > 0:
            self._idx -= 1
            self._show_current()

    def next(self):      # ▶ older
        if self._idx < len(self._files) - 1:
            self._idx += 1
            self._show_current()

    def _update_nav(self):
        n = len(self._files)
        live = self.worker is not None
        self.btn_prev.setEnabled(not live and self._idx > 0)
        self.btn_next.setEnabled(not live and self._idx < n - 1)
        self.lbl_counter.setText("LIVE" if live else (f"{self._idx + 1}/{n}" if n else "0/0"))

    # ---- Live On: live camera ----
    def _on_live_toggled(self, on):
        self._start_live() if on else self._stop_live()

    def _start_live(self):
        from albatross.workers.camera import CameraWorker, HAS_CV2
        if not HAS_CV2:
            self.main.log("[Warning] opencv is not installed — run 'pip install opencv-python' first.")
            self.btn_live.setChecked(False)
            return
        self._timer.stop()                         # stop refreshing the latest image
        self.btn_live.setText("Live Off")
        w = CameraWorker(camera_source(self.main.cfg))
        w.frame.connect(self._on_live_frame)
        w.failed.connect(lambda m: self.main.log("[prodtracker] " + m))
        w.finished.connect(self._on_live_finished)
        self.worker = w
        self.main._workers.add(w)
        w.start()
        self._update_nav()                         # disable ◀▶ while live + show 'LIVE'

    def _stop_live(self):
        self.btn_live.setText("Live On")
        if self.worker:
            self.worker.stop()                     # finished -> _on_live_finished

    def _on_live_frame(self, img):
        from PyQt6.QtGui import QPixmap
        self._pixmap = QPixmap.fromImage(img)
        self._apply()

    def _on_live_finished(self):
        self.main._workers.discard(self.worker)
        self.worker = None
        self._cur = None                           # force the latest image to reload
        self._loaded = None
        if self.folder:
            self._timer.start(self._interval)
        self.refresh()                             # back to the newest + re-enable ◀▶

    # ---- Shared ----
    def _apply(self):
        if self._pixmap is not None:
            self.setPixmap(self._pixmap.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        self._apply()                    # rescale the current image when the window resizes
        super().resizeEvent(e)


class CameraView(QLabel):
    """Live-only camera box (QLabel) — same size as prodtracker. Starts automatically the first
    time the tab is opened. No buttons or capture (live view only). Local webcam or RTSP (config).
    Without opencv it only shows a notice."""
    def __init__(self, main, title="Camera"):
        super().__init__(title)
        self.main = main
        self._title = title
        self.worker = None
        self._started = False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(300)
        self.setStyleSheet(_PANEL_STYLE)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.source = camera_source(self.main.cfg)     # RTSP (str) or webcam index (int)

    def showEvent(self, e):
        if not self._started:                          # auto-start once, the first time the tab is shown
            self._started = True
            self.start()
        super().showEvent(e)

    def start(self):
        from albatross.workers.camera import CameraWorker, HAS_CV2
        if self.worker:
            return
        if not HAS_CV2:
            self.main.log("[Warning] opencv is not installed — run 'pip install opencv-python' first.")
            return
        w = CameraWorker(self.source)
        w.frame.connect(self._on_frame)
        w.failed.connect(lambda m: self.main.log("[Camera] " + m))
        w.finished.connect(self._on_finished)
        self.worker = w
        self.main._workers.add(w)          # prevents GC and marks it for cleanup on exit
        w.start()

    def stop(self):
        if self.worker:
            self.worker.stop()

    def _on_frame(self, img):
        from PyQt6.QtGui import QPixmap
        self.setPixmap(QPixmap.fromImage(img).scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _on_finished(self):
        self.main._workers.discard(self.worker)
        self.worker = None
        self.setText(self._title)          # clear the last frame and restore the label


class CellProgressWidget(QWidget):
    """Cell assembly progress display — each square is a cell (labelled with its composition
    number). Blinking = being assembled, solid green = done."""

    def __init__(self, per_row=12):
        super().__init__()
        self.per_row = per_row
        self._grid = QGridLayout(self)
        self._grid.setSpacing(4)
        self._boxes = []
        self._active = None
        self._on = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._blink)

    def setup(self, comp_numbers):
        for b in self._boxes:
            b.setParent(None)
        self._boxes = []
        self._active = None
        self._timer.stop()
        for idx, comp in enumerate(comp_numbers):
            lbl = QLabel(str(comp))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedSize(44, 38)
            lbl.setStyleSheet(_CP_EMPTY)
            self._grid.addWidget(lbl, idx // self.per_row, idx % self.per_row)
            self._boxes.append(lbl)

    def set_active(self, i):
        if not (0 <= i < len(self._boxes)):
            return
        self._active = i
        self._on = True
        self._boxes[i].setStyleSheet(_CP_ON)
        self._timer.start(450)

    def set_done(self, i):
        if self._active == i:
            self._timer.stop()
            self._active = None
        if 0 <= i < len(self._boxes):
            self._boxes[i].setStyleSheet(_CP_DONE)

    def reset(self):
        self._timer.stop()
        self._active = None
        for b in self._boxes:
            b.setStyleSheet(_CP_EMPTY)

    def _blink(self):
        if self._active is None:
            return
        self._on = not self._on
        self._boxes[self._active].setStyleSheet(_CP_ON if self._on else _CP_OFF)


class AutomationTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        self.worker = None
        self._done_count = 0
        self._run_repeat = 1
        self._run_mode = "assembly"
        v = QVBoxLayout(self)
        v.addWidget(self._box())
        self.progress = CellProgressWidget()
        pgbox = QGroupBox("Progress (square = cell · number = composition · blinking = assembling · green = done)")
        pgl = QVBoxLayout(pgbox)
        pgl.addWidget(self.progress)
        v.addWidget(pgbox)
        # Three bottom panels, equal size: prodtracker (placeholder) | camera (live) | future addition (placeholder)
        panels = QHBoxLayout()
        pt_dir = str(self.main.cfg.get("vision", {}).get("prodtracker_dir", "") or "")
        self.prodtracker_view = LatestImageView(self.main, "prodtracker", pt_dir)
        self.camera_view = CameraView(self.main, "Camera")
        self.future_view = big_panel("To be added later")   # slot for a second camera
        panels.addWidget(self.prodtracker_view, 1)
        panels.addWidget(self.camera_view, 1)
        panels.addWidget(self.future_view, 1)
        v.addLayout(panels, 1)
        # Controls under each column: prodtracker = Live toggle only; camera = live-only (no
        # controls); future addition = empty
        ctrl = QHBoxLayout()
        pt_wrap = QHBoxLayout()
        pt_wrap.addStretch(1)
        pt_wrap.addWidget(self.prodtracker_view.btn_prev)
        pt_wrap.addWidget(self.prodtracker_view.lbl_counter)
        pt_wrap.addWidget(self.prodtracker_view.btn_next)
        pt_wrap.addSpacing(12)
        pt_wrap.addWidget(self.prodtracker_view.btn_live)
        pt_wrap.addStretch(1)
        ctrl.addLayout(pt_wrap, 1)                 # prodtracker column: ◀ position ▶ · Live toggle
        ctrl.addStretch(1)                         # under the camera column (empty — live only)
        ctrl.addStretch(1)                         # under the future-addition column (empty)
        v.addLayout(ctrl)

    def _box(self):
        box = QGroupBox("Cell Assembly Automation")
        v = QVBoxLayout(box)

        # Mode selection
        rm = QHBoxLayout()
        rm.addWidget(QLabel("Mode"))
        self.mode_asm = QRadioButton("Assembly only")
        self.mode_cyc = QRadioButton("Assembly + cycling")
        self.mode_asm.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.mode_asm); grp.addButton(self.mode_cyc)
        self.mode_asm.toggled.connect(self._sync_mode)
        rm.addWidget(self.mode_asm); rm.addWidget(self.mode_cyc); rm.addStretch(1)
        v.addLayout(rm)

        # Shared inputs (assembly is common to both modes). The source plate is fixed to
        # wellplate (defined when OT2 connects).
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Cell count n"))
        self.n = QSpinBox(); self.n.setRange(1, 96); self.n.setValue(1)
        r1.addWidget(self.n)
        r1.addWidget(QLabel("Dosing start dosing_num"))
        self.dosing_num = QSpinBox(); self.dosing_num.setRange(0, 95)
        r1.addWidget(self.dosing_num)
        r1.addWidget(QLabel("Repeats per composition repeat_num"))
        self.repeat_num = QSpinBox(); self.repeat_num.setRange(1, 96); self.repeat_num.setValue(1)
        r1.addWidget(self.repeat_num)
        self.b_apply = QPushButton("Apply"); self.b_apply.clicked.connect(self._apply_preview)
        r1.addWidget(self.b_apply)
        r1.addStretch(1)
        v.addLayout(r1)

        rd = QHBoxLayout()
        rd.addWidget(QLabel("dosing_list ="))
        self.dosing_preview = QLabel("(computed when you press Apply)")
        self.dosing_preview.setStyleSheet("color:#FFFFFF;")
        self.dosing_preview.setWordWrap(True)
        rd.addWidget(self.dosing_preview, 1)
        v.addLayout(rd)

        # Mode B only inputs
        self.cyc_box = QGroupBox("Cycling Options (Mode B)")
        cv = QVBoxLayout(self.cyc_box)
        c1 = QHBoxLayout()
        c1.addWidget(QLabel("Jig start number jig_num"))
        self.jig_num = QSpinBox(); self.jig_num.setRange(0, 47)
        c1.addWidget(self.jig_num)
        c1.addWidget(QLabel("-> jig_pos ="))
        self.jig_preview = QLabel("(computed when you press Apply)")
        self.jig_preview.setStyleSheet("color:#FFFFFF; font-weight:bold;")
        c1.addWidget(self.jig_preview)
        c1.addStretch(1)
        cv.addLayout(c1)
        c2 = QHBoxLayout()
        c2.addWidget(QLabel("Protocol"))
        self.protocol = QLineEdit("C:/NewareData/251121_MTI_NCM811_1C50cycEIS.xml")
        c2.addWidget(self.protocol)
        b_proto = QPushButton("Browse"); b_proto.clicked.connect(self._browse_protocol)
        c2.addWidget(b_proto)
        cv.addLayout(c2)
        c3 = QHBoxLayout()
        c3.addWidget(QLabel("Save Folder"))
        self.savedir = QLineEdit()
        c3.addWidget(self.savedir)
        b_browse = QPushButton("Browse"); b_browse.clicked.connect(self._browse)
        c3.addWidget(b_browse)
        cv.addLayout(c3)
        v.addWidget(self.cyc_box)

        # Start / stop
        r3 = QHBoxLayout()
        self.btn_start = QPushButton("Start Automation"); self.btn_start.clicked.connect(self._start)
        self.btn_stop = QPushButton("Code Interrupt"); self.btn_stop.clicked.connect(self.stop_automation)
        self.btn_stop.setEnabled(False)
        r3.addWidget(self.btn_start); r3.addWidget(self.btn_stop); r3.addStretch(1)
        v.addLayout(r3)

        self._sync_mode()
        return box

    def _sync_mode(self):
        self.cyc_box.setEnabled(self.mode_cyc.isChecked())

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select Save Folder")
        if path:
            self.savedir.setText(path)

    def _browse_protocol(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Charge/Discharge Protocol", "",
                                              "Neware protocol (*.xml);;All files (*.*)")
        if path:
            self.protocol.setText(path)

    def _apply_preview(self):
        """Apply — build the progress squares from the inputs (n, dosing_num, repeat_num) and,
        in Mode B, precompute and show jig_pos."""
        from albatross.operations import assembly_ops
        repeat = self.repeat_num.value()
        dosing = assembly_ops.build_dosing_list(self.dosing_num.value(), repeat, self.n.value())
        n = len(dosing)
        if n <= 0:
            self.main.log("[Warning] Cell count is smaller than the repeat count (cannot preview).")
            return
        comp_numbers = [self.dosing_num.value() + i // repeat for i in range(n)]
        self.progress.setup(comp_numbers)
        self.dosing_preview.setText(str(dosing))
        msg = (f"Preview: {n} cell(s) (from composition {self.dosing_num.value()}, "
               f"repeat {repeat}) · dosing_list {dosing}")
        if self.mode_cyc.isChecked():
            acfg = self.main.cfg.get("assembly", {})
            exclude = set(acfg.get("jig_exclude", []))
            jig_list = [i for i in range(acfg.get("jig_count", 48)) if i not in exclude]
            jig_pos = assembly_ops.build_jig_pos(self.jig_num.value(), n, jig_list)
            self.jig_preview.setText(str(jig_pos))
            msg += f" · jig_pos {jig_pos}"
            if len(jig_pos) < n:
                self.main.log(f"[Warning] Not enough jigs: {n} needed, {len(jig_pos)} available")
        self.main.log(msg)

    def _start(self):
        if self.worker or not self.main.writable():   # read-only: block starting automation
            return
        mode = "cycle" if self.mode_cyc.isChecked() else "assembly"
        need = [(self.main.plc, "PLC"), (self.main.robot, "Robot"), (self.main.ot2, "OT2")]
        if mode == "cycle":
            need.append((self.main.neware, "Neware"))
        for c, name in need:
            if not c.connected:
                self.main.log(f"[Warning] {name} is not connected.")
                return
        from albatross.operations import assembly_ops
        n = self.n.value()
        dosing = assembly_ops.build_dosing_list(self.dosing_num.value(),
                                                self.repeat_num.value(), n)
        if not dosing:
            self.main.log("[Warning] The dosing list is empty (check n / repeat_num)")
            return
        if len(dosing) != n:
            self.main.log(f"[Info] n({n}) is not a multiple of repeat_num, adjusting to {len(dosing)} cell(s).")
            n = len(dosing)
        params = dict(mode=mode, n=n, dosing_list=dosing, plate_info="wellplate")
        if mode == "cycle":
            acfg = self.main.cfg.get("assembly", {})
            exclude = set(acfg.get("jig_exclude", []))
            jig_list = [i for i in range(acfg.get("jig_count", 48)) if i not in exclude]
            jig_pos = assembly_ops.build_jig_pos(self.jig_num.value(), n, jig_list)
            if len(jig_pos) < n:
                self.main.log(f"[Warning] Not enough jigs from jig_num({self.jig_num.value()}) to hold {n} cell(s) (exceeds the jig_list range).")
                return
            params.update(jig_pos=jig_pos, protocol=self.protocol.text().strip(),
                          savedir=self.savedir.text().strip() or None)

        comp_numbers = [self.dosing_num.value() + i // self.repeat_num.value()
                        for i in range(n)]
        self.progress.setup(comp_numbers)
        self._done_count = 0
        self._run_repeat = self.repeat_num.value()
        self._run_mode = mode
        self.worker = AssemblyWorker(self.main.ctrl, params)
        self.worker.log.connect(self.main.log)
        self.worker.failed.connect(lambda m: self.main.log("[Error] " + m))
        self.worker.step_failed.connect(self._on_step_fail)
        self.worker.cell_started.connect(self.progress.set_active)
        self.worker.cell_done.connect(self._on_cell_done)
        self.worker.finished.connect(self._on_finished)
        self.main._workers.add(self.worker)
        self.worker.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._set_inputs_enabled(False)          # lock inputs/Apply while running

    def stop_automation(self):
        if self.worker:
            self.main.log("Automation stop requested...")
            self.worker.stop()

    def _on_step_fail(self, part, comp_id, cell_id):
        """Part mismatch -> pause assembly. The user picks [Continue] / [Stop]."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Part Mismatch — Assembly Paused")
        box.setText(f"Cell {cell_id} · part '{part}' mismatched or missing.\n"
                    f"Please check the assembly stage. (See the Slack / ProdTracker image.)")
        cont = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Stop", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is cont:
            self.main.log(f"Assembly resumed (cell {cell_id}, part {part})")
            if self.worker:
                self.worker.resume()
        else:
            self.main.log("Assembly stop requested")
            if self.worker:
                self.worker.stop()

    def _on_cell_done(self, i):
        self._done_count += 1
        self.progress.set_done(i)

    def _set_inputs_enabled(self, en):
        """Lock the inputs/Apply/mode while running (False when automation starts, True when it ends)."""
        for w in (self.n, self.dosing_num, self.repeat_num, self.b_apply,
                  self.mode_asm, self.mode_cyc, self.cyc_box):
            w.setEnabled(en)

    def _on_finished(self):
        self.main._workers.discard(self.worker)
        self.worker = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._set_inputs_enabled(True)
        self._sync_mode()                         # restore the Mode B box enabled state
        # Advance dosing_num to the next start point by the number of completed compositions
        # (notebook: dosing_num += n//repeat)
        done_comps = self._done_count // max(1, self._run_repeat)
        if done_comps > 0:
            self.dosing_num.setValue(self.dosing_num.value() + done_comps)
            self.main.log(f"Next start composition dosing_num = {self.dosing_num.value()} (advanced by {done_comps} completed composition(s))")
        if self._run_mode == "cycle" and self._done_count > 0:
            self.jig_num.setValue(self.jig_num.value() + self._done_count)
            self.main.log(f"Next jig start jig_num = {self.jig_num.value()} (advanced by {self._done_count} completed cell(s))")
